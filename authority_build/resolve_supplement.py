"""
Resolve landmark supplement cases via IK public-website citation phrase search.

Workflow:
1. Read LANDMARK_SUPPLEMENT
2. For each entry: search IK for citation phrase, filter to SC results,
   verify citation appears in body
3. On success: derive aliases (name variants, citation variants)
4. Merge into authority_index.py

Cost: free (uses authority_build/scraper/, the same scraper that built
the existing index).
"""
import json
import re
import sys
import time
from pathlib import Path

# Reuse the same scraper module that built the existing index
HERE = Path(__file__).parent
ROOT = HERE.parent  # vakeel_beta/
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

from scraper.ik_client import IKClient
from scraper.extractors import (
    parse_search_results, parse_doc_page,
    is_supreme_court, body_contains_citation
)
from scraper.alias_utils import derive_aliases, _filter

from landmark_supplement import LANDMARK_SUPPLEMENT


OUT_STATE = HERE / "supplement_state.json"
AUTH_INDEX_PATH = ROOT.parent / "vakeel_beta" / "authority_index.py"
# Backup path in case the merge goes wrong
BACKUP_PATH = AUTH_INDEX_PATH.with_suffix(".py.pre_supplement.bak")


# ── Resolver per case ────────────────────────────────────────────────────────

def _citation_variants(c: str) -> list[str]:
    """Generate IK-friendly variants of a citation string."""
    c = c.strip()
    variants = {c}
    # Remove parentheses on year, e.g. "(2014) 10 SCC 473" -> "2014 10 SCC 473"
    variants.add(re.sub(r"[()]", "", c))
    # "AIR 1962 SC 199" works as-is
    return list(variants)


def resolve_one(client: IKClient, name: str, citation: str) -> dict | None:
    """Returns dict with tid, title, court if resolved; None otherwise."""
    for variant in _citation_variants(citation):
        try:
            html = client.search(variant)
            if not html:
                continue
            results = parse_search_results(html, limit=8)
            sc_results = [r for r in results if is_supreme_court(r)]
            if not sc_results:
                continue
            # Try each SC result in ranked order
            for r in sc_results:
                tid = r.get("tid")
                if not tid:
                    continue
                doc_html = client.doc(tid)
                if not doc_html:
                    continue
                parsed = parse_doc_page(doc_html)
                body_text = parsed.get("body_text", "")
                if body_contains_citation(body_text, citation):
                    return {
                        "tid": tid,
                        "title": r.get("title", parsed.get("title", "")),
                        "court": "Supreme Court of India",
                        "matched_via": variant,
                    }
        except Exception as e:
            print(f"  ! search error for {variant!r}: {e}")
            continue
    return None


# ── Load / save state ────────────────────────────────────────────────────────

def load_state():
    if OUT_STATE.exists():
        return json.loads(OUT_STATE.read_text(encoding="utf-8"))
    return {"resolved": {}, "failed": []}


def save_state(state):
    OUT_STATE.write_text(json.dumps(state, indent=2, ensure_ascii=False),
                          encoding="utf-8")


# ── Merge into authority_index.py ────────────────────────────────────────────

def merge_into_authority_index(state: dict) -> int:
    """
    Append new alias→tid mappings to authority_index.py.
    Skips aliases that already exist (no overwrites — preserves existing data).
    Returns number of new aliases added.
    """
    import shutil
    shutil.copy2(AUTH_INDEX_PATH, BACKUP_PATH)
    print(f"\nBackup written: {BACKUP_PATH}")

    # Parse existing index — get current aliases
    text = AUTH_INDEX_PATH.read_text(encoding="utf-8")
    existing_aliases = set(re.findall(r'"([^"]+)":\s*"\d+"', text))

    # Build list of (alias, tid, comment) to insert
    new_entries = []
    skipped_existing = 0
    for case_name, info in state["resolved"].items():
        tid = info["tid"]
        title = info.get("title", case_name).replace('"', "'")[:90]
        aliases = derive_aliases(case_name)
        aliases = _filter(set(aliases))
        for alias in sorted(aliases):
            if alias in existing_aliases:
                skipped_existing += 1
                continue
            new_entries.append((alias, tid, title))
            existing_aliases.add(alias)

    if not new_entries:
        print("Nothing new to add.")
        return 0

    # Find the closing brace of AUTHORITY_INDEX
    # Pattern: }\n followed by the resolve function definitions
    insert_marker = re.search(r"\n}\n\n\ndef _normalize", text)
    if not insert_marker:
        # Older format — try simpler pattern
        insert_marker = re.search(r"\n\}\s*\n+def _normalize", text)
    if not insert_marker:
        print("ERROR: Could not find AUTHORITY_INDEX closing brace.")
        print("       Check authority_index.py manually.")
        return -1

    # Insert before the closing brace
    insert_lines = ["\n    # ── LANDMARK SUPPLEMENT (auto-added) ──"]
    for alias, tid, title in new_entries:
        insert_lines.append(f'    "{alias}": "{tid}",  # {title}')
    insert_block = "\n".join(insert_lines) + "\n"

    # Find the closing brace position and inject before it
    close_brace_pos = insert_marker.start()
    new_text = text[:close_brace_pos] + insert_block + text[close_brace_pos:]

    AUTH_INDEX_PATH.write_text(new_text, encoding="utf-8")

    print(f"Added {len(new_entries)} new aliases.")
    print(f"Skipped {skipped_existing} aliases already present in index.")
    return len(new_entries)


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    state = load_state()
    print(f"Loaded state: {len(state['resolved'])} resolved, "
          f"{len(state['failed'])} failed")

    pending = [
        c for c in LANDMARK_SUPPLEMENT
        if c["name"] not in state["resolved"]
        and c["name"] not in {f["name"] for f in state["failed"]}
    ]
    print(f"Pending: {len(pending)} of {len(LANDMARK_SUPPLEMENT)} total")

    if not pending:
        print("All cases already processed.")
    else:
        client = IKClient()
        try:
            t_start = time.time()
            for i, c in enumerate(pending, 1):
                print(f"\n[{i:>2}/{len(pending)}] {c['name'][:60]}  ({c['citation']})")
                result = resolve_one(client, c["name"], c["citation"])
                if result:
                    state["resolved"][c["name"]] = {
                        **result,
                        "citation": c["citation"],
                        "category": c["category"],
                    }
                    print(f"        ✓ tid={result['tid']}  via {result['matched_via'][:50]}")
                else:
                    state["failed"].append({"name": c["name"],
                                            "citation": c["citation"],
                                            "category": c["category"]})
                    print(f"        ✗ not resolved")
                if i % 5 == 0:
                    save_state(state)
            save_state(state)
            print(f"\nDone. Elapsed: {time.time() - t_start:.1f}s")
        finally:
            client.close()

    # Stats
    print(f"\n{'─'*50}")
    print(f"Resolved: {len(state['resolved'])}/{len(LANDMARK_SUPPLEMENT)}")
    print(f"Failed:   {len(state['failed'])}")
    if state["failed"]:
        print("\nFailures (worth manual review):")
        for f in state["failed"]:
            print(f"  - {f['name']}  ({f['citation']})")

    # Auto-merge if user confirms
    if state["resolved"]:
        print(f"\n{'─'*50}")
        confirm = input(f"Merge {len(state['resolved'])} resolved cases into authority_index.py? (yes/no): ").strip().lower()
        if confirm == "yes":
            n_added = merge_into_authority_index(state)
            if n_added > 0:
                print(f"\nDone. {n_added} new aliases added to {AUTH_INDEX_PATH.name}")
                print(f"If anything is wrong: copy {BACKUP_PATH.name} back over authority_index.py")
        else:
            print("Skipped merge. State preserved in supplement_state.json — rerun anytime.")


if __name__ == "__main__":
    main()
