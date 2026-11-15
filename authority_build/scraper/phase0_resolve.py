"""Phase 0: resolve cases from authority_build_progress.json via citation phrase search."""
import json, re, time
from pathlib import Path
from .ik_client import IKClient
from .extractors import parse_search_results, is_supreme_court, parse_doc_page, body_contains_citation
from .alias_utils import derive_aliases, merge_alias_map
from .state import load_state, save_state, write_authority_index, HERE

PROGRESS_PATH = HERE / "authority_build_progress.json"

SAVE_EVERY = 25


def _citation_variants(c: str) -> list[str]:
    if not c:
        return []
    out = [c.strip()]
    cleaned = re.sub(r"[()]", "", c)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if cleaned != c:
        out.append(cleaned)
    return out


def _resolve_one(client: IKClient, name: str, citation: str) -> tuple[str | None, str, str]:
    for q in _citation_variants(citation):
        html = client.search(q)
        if not html:
            continue
        results = parse_search_results(html)
        sc = [r for r in results if is_supreme_court(r)]
        if not sc:
            continue
        # Verify by fetching doc, looking for citation in body
        for cand in sc[:3]:
            doc_html = client.doc(cand["tid"])
            doc = parse_doc_page(doc_html or "")
            if body_contains_citation(doc.get("body_text", ""), citation):
                return cand["tid"], doc.get("title") or cand["title"], "citation-verified"
        return sc[0]["tid"], sc[0]["title"], "top-SC-result (unverified)"
    return None, "", "no SC results found"


def run(limit: int | None = None, fresh: bool = False) -> int:
    if not PROGRESS_PATH.exists():
        print(f"ERROR: {PROGRESS_PATH} not found")
        return 1
    progress = json.loads(PROGRESS_PATH.read_text(encoding="utf-8"))
    cases = progress.get("unresolved", [])

    seen = set()
    uniq = []
    for c in cases:
        key = (c.get("name", ""), c.get("citation", ""))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(c)

    if limit:
        uniq = uniq[:limit]
        print(f"CANARY: limiting to first {len(uniq)} cases")

    state = load_state("phase0", fresh)
    already = {k for k in state["resolved"]}
    pending = [c for c in uniq if f"{c['name']}|{c['citation']}" not in already]

    print(f"Phase 0: resolve | total {len(uniq)} | done {len(already)} | pending {len(pending)}")
    print(f"Est wall time: {len(pending) * 6 / 60:.0f} min")

    client = IKClient()
    n_ok = n_fail = 0
    t0 = time.time()

    try:
        for i, case in enumerate(pending, 1):
            try:
                tid, title, reason = _resolve_one(client, case["name"], case["citation"])
            except Exception as e:
                print(f"[{i:>4}] ERR {case['name'][:50]}: {e}")
                continue
            key = f"{case['name']}|{case['citation']}"
            if tid:
                state["resolved"][key] = {
                    "tid": tid, "title": title, "name": case["name"],
                    "citation": case["citation"], "doctrine": case.get("doctrine", ""),
                    "reason": reason,
                }
                n_ok += 1
                print(f"[{i:>4}/{len(pending)}] OK  {case['name'][:50]:<50} -> {tid} ({reason})")
            else:
                state["failed"].append({**case, "error": reason})
                n_fail += 1
            if i % SAVE_EVERY == 0:
                save_state("phase0", state)
                _flush_index(state)
                rate = i / (time.time() - t0) if time.time() > t0 else 0
                eta = (len(pending) - i) / rate / 60 if rate else 0
                print(f"   saved | ok={n_ok} fail={n_fail} | {rate*60:.1f}/min | ETA {eta:.0f}min")
    except KeyboardInterrupt:
        print("\nInterrupted. Saving...")
    finally:
        save_state("phase0", state)
        _flush_index(state)
        client.close()

    print(f"\nPhase 0 done. Resolved this run: {n_ok}. Total resolved: {len(state['resolved'])}")
    return 0


def _flush_index(phase0_state: dict):
    """Build alias map from phase0 resolved + write authority_index.py."""
    alias_map: dict = {}
    by_tid_info: dict = {}
    for entry in phase0_state["resolved"].values():
        tid = entry["tid"]
        by_tid_info[tid] = {"title": entry["title"], "reason": entry["reason"]}
        aliases = derive_aliases(entry["name"], citations=[entry["citation"]])
        merge_alias_map(alias_map, aliases, tid, entry)
    write_authority_index(alias_map, by_tid_info)
