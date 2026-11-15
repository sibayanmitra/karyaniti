"""
Overnight expansion: run Phase 1 (citedby) on the 47 supplement cases.

Reuses authority_build/scraper/ machinery. Writes to a NEW state file
(supplement_phase1_state.json) — does NOT touch your existing phase0/phase1
state files. Safe to interrupt with Ctrl+C: resumes from last save point.

Cost: ₹0. Free IK public scraping. ~2-4 hours for ~47 seeds × ~20 citers each.

Usage:
  python supplement_phase1.py             # full run
  python supplement_phase1.py --limit 5   # try 5 seeds first (smoke test)
  python supplement_phase1.py --merge     # merge results into authority_index.py
                                          # (run AFTER the scrape completes)
"""
import argparse
import json
import re
import shutil
import sys
import time
from pathlib import Path

# Paths
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent if HERE.name == "authority_build" else HERE
INDEX_PATH = ROOT / "authority_index.py"
SUPP_STATE = ROOT / "authority_build" / "supplement_state.json"
OUT_STATE = ROOT / "authority_build" / "supplement_phase1_state.json"
BACKUP_PATH = INDEX_PATH.with_suffix(".py.pre_phase1_supp.bak")

# Import scraper machinery
sys.path.insert(0, str(ROOT / "authority_build"))
from scraper.ik_client import IKClient
from scraper.extractors import parse_search_results, is_supreme_court, parse_doc_page, body_contains_citation
from scraper.alias_utils import derive_aliases, _filter

TOP_CITERS_PER_SEED = 25       # slightly conservative — ~25 citers × 47 seeds = ~1200 fetches
SAVE_EVERY = 5                 # save every 5 seeds processed
MAX_VERIFY_PER_SEED = 25       # ceiling — never more than this


# ── State management ────────────────────────────────────────────────────────

def load_state() -> dict:
    if OUT_STATE.exists():
        return json.loads(OUT_STATE.read_text(encoding="utf-8"))
    return {"processed_seed_tids": [], "new_resolved": {}, "failed": []}


def save_state(state: dict):
    OUT_STATE.write_text(json.dumps(state, indent=2, ensure_ascii=False),
                          encoding="utf-8")


# ── Verify a citer is a real SC case with body-verifiable citation ──────────

def verify_citer(client: IKClient, tid: str, hint_title: str) -> dict | None:
    doc_html = client.doc(tid)
    doc = parse_doc_page(doc_html or "")
    if not doc.get("source"):
        return None
    if "supreme court of india" not in doc["source"].lower():
        return None
    if not doc.get("citations"):
        return None
    body = doc.get("body_text", "")
    for c in doc["citations"]:
        if body_contains_citation(body, c):
            return {
                "tid": tid,
                "title": doc["title"] or hint_title,
                "citations": doc["citations"],
                "reason": "citation-verified-via-supplement-phase1",
            }
    return None


# ── Main scrape loop ────────────────────────────────────────────────────────

def run_scrape(limit: int | None = None):
    if not SUPP_STATE.exists():
        print(f"ERROR: {SUPP_STATE} not found. Run resolve_supplement.py first.")
        return 1

    supplement = json.loads(SUPP_STATE.read_text(encoding="utf-8"))
    resolved = supplement.get("resolved", {})
    if not resolved:
        print("ERROR: supplement_state.json has no resolved cases.")
        return 1

    # Seeds: (tid, display_title)
    seeds = []
    seen_tid = set()
    for case_name, info in resolved.items():
        tid = info.get("tid")
        if tid and tid not in seen_tid:
            seen_tid.add(tid)
            seeds.append((tid, info.get("title", case_name)))

    state = load_state()
    processed = set(state["processed_seed_tids"])
    pending = [s for s in seeds if s[0] not in processed]

    if limit is not None:
        pending = pending[:limit]

    print(f"Total seeds:  {len(seeds)}")
    print(f"Already done: {len(processed)}")
    print(f"Pending:      {len(pending)}")
    print(f"Top citers per seed: {TOP_CITERS_PER_SEED}")
    print(f"Est wall time: {len(pending) * (TOP_CITERS_PER_SEED + 1) * 3.5 / 60:.0f} min")
    print(f"Output state: {OUT_STATE}")
    print()

    if not pending:
        print("Nothing to do.")
        return 0

    client = IKClient()
    t0 = time.time()
    n_new_this_run = 0

    try:
        for i, (seed_tid, seed_title) in enumerate(pending, 1):
            try:
                html = client.search(f"citedby:{seed_tid}")
                if not html:
                    state["processed_seed_tids"].append(seed_tid)
                    continue
                results = parse_search_results(html, limit=TOP_CITERS_PER_SEED)
                sc_results = [r for r in results if is_supreme_court(r)]
                local_new = 0
                for cand in sc_results[:MAX_VERIFY_PER_SEED]:
                    cand_tid = cand.get("tid")
                    if not cand_tid:
                        continue
                    if cand_tid in state["new_resolved"]:
                        continue
                    if cand_tid == seed_tid:
                        continue
                    info = verify_citer(client, cand_tid, cand.get("title", ""))
                    if info:
                        state["new_resolved"][cand_tid] = info
                        local_new += 1
                        n_new_this_run += 1
                state["processed_seed_tids"].append(seed_tid)
                rate = i / (time.time() - t0) if time.time() > t0 else 0
                eta = (len(pending) - i) / rate / 60 if rate else 0
                print(f"[{i:>3}/{len(pending)}] {seed_title[:55]:<55} +{local_new:>2} new "
                      f"| total={len(state['new_resolved']):>3} | ETA {eta:.0f}min")
            except Exception as e:
                print(f"[{i:>3}] ERR seed {seed_tid}: {e}")
                state["failed"].append({"seed_tid": seed_tid, "error": str(e)})
                state["processed_seed_tids"].append(seed_tid)

            if i % SAVE_EVERY == 0:
                save_state(state)
                print(f"   saved | new this run: {n_new_this_run}")
    except KeyboardInterrupt:
        print("\nInterrupted. Saving...")
    finally:
        save_state(state)
        client.close()

    print(f"\n{'─'*60}")
    print(f"Done. New cases this run: {n_new_this_run}.")
    print(f"Total resolved in supplement_phase1: {len(state['new_resolved'])}")
    print(f"Failed seeds: {len(state['failed'])}")
    print(f"\nNext: run with --merge to add aliases to authority_index.py")
    return 0


# ── Merge into authority_index.py ───────────────────────────────────────────

def merge():
    if not OUT_STATE.exists():
        print(f"ERROR: {OUT_STATE} not found. Run without --merge first.")
        return 1

    state = json.loads(OUT_STATE.read_text(encoding="utf-8"))
    resolved = state.get("new_resolved", {})
    if not resolved:
        print("No resolved cases in supplement_phase1 state.")
        return 0

    print(f"Resolved cases to consider: {len(resolved)}")

    text = INDEX_PATH.read_text(encoding="utf-8")
    existing_aliases = set(re.findall(r'"([^"]+)":\s*"\d+"', text))
    print(f"Existing aliases in index: {len(existing_aliases)}")

    new_entries = []
    skipped = 0
    for tid, info in resolved.items():
        title = info.get("title", "Unknown")
        citations = info.get("citations", [])
        aliases = derive_aliases(title, citations=citations) if citations else derive_aliases(title)
        aliases = _filter(set(aliases))
        for alias in sorted(aliases):
            if alias in existing_aliases:
                skipped += 1
                continue
            new_entries.append((alias, tid, title.replace('"', "'")[:90]))
            existing_aliases.add(alias)

    if not new_entries:
        print("Nothing new to add.")
        return 0

    print(f"\nNew aliases to add:     {len(new_entries)}")
    print(f"Aliases already present: {skipped}")
    print(f"\nSample new entries (first 5):")
    for a, t, _ in new_entries[:5]:
        print(f"  {a!r}: {t!r}")

    # Find closing brace robustly
    norm_pos = text.find("def _normalize")
    if norm_pos < 0:
        print("ERROR: def _normalize not found")
        return 1
    before_text = text[:norm_pos]
    brace_match = None
    for m in re.finditer(r"^\}\s*$", before_text, re.MULTILINE):
        brace_match = m
    if brace_match is None:
        print("ERROR: closing brace not found")
        return 1
    brace_pos = brace_match.start()

    insert_lines = ["    # ── PHASE 1 CITEDBY SUPPLEMENT (auto-added) ──"]
    for alias, tid, title in new_entries:
        insert_lines.append(f'    "{alias}": "{tid}",  # {title}')
    insert_block = "\n".join(insert_lines) + "\n"

    new_text = text[:brace_pos] + insert_block + text[brace_pos:]

    confirm = input(f"\nProceed with merge of {len(new_entries)} new aliases? (yes/no): ").strip().lower()
    if confirm != "yes":
        print("Aborted.")
        return 0

    shutil.copy2(INDEX_PATH, BACKUP_PATH)
    print(f"Backup: {BACKUP_PATH.name}")
    INDEX_PATH.write_text(new_text, encoding="utf-8")

    # Verify
    final_text = INDEX_PATH.read_text(encoding="utf-8")
    final_aliases = set(re.findall(r'"([^"]+)":\s*"\d+"', final_text))
    print(f"Done. Aliases: {len(existing_aliases) - len(new_entries)} → {len(final_aliases)}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None,
                    help="Process only N seeds (smoke test). Omit for full run.")
    ap.add_argument("--merge", action="store_true",
                    help="Merge results into authority_index.py (run AFTER scrape).")
    args = ap.parse_args()

    if args.merge:
        sys.exit(merge())
    else:
        sys.exit(run_scrape(limit=args.limit))
