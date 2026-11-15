"""Phase 1: for each resolved case, fetch its 'cited by' list and verify each citer."""
import time
from .ik_client import IKClient
from .extractors import parse_search_results, is_supreme_court, parse_doc_page, body_contains_citation
from .alias_utils import derive_aliases, merge_alias_map
from .state import load_state, save_state, write_authority_index

TOP_CITERS_PER_SEED = 30
SAVE_EVERY = 10           # seed cases between saves


def _verify_citer(client: IKClient, tid: str, hint_title: str) -> dict | None:
    """Fetch the doc page, return doc info if it's a verifiable SC case."""
    doc_html = client.doc(tid)
    doc = parse_doc_page(doc_html or "")
    if not doc.get("source"):
        return None
    if "supreme court of india" not in doc["source"].lower():
        return None
    if not doc.get("citations"):
        return None
    # Body must contain at least one of its own listed citations
    body = doc.get("body_text", "")
    for c in doc["citations"]:
        if body_contains_citation(body, c):
            return {
                "tid": tid,
                "title": doc["title"] or hint_title,
                "citations": doc["citations"],
                "reason": "citation-verified",
            }
    return None


def run(fresh: bool = False) -> int:
    phase0 = load_state("phase0")
    seeds = [(e["tid"], e["name"], e["title"])
             for e in phase0["resolved"].values()
             if e.get("tid")]
    # Dedup by tid
    seen_tid = set()
    uniq_seeds = []
    for tid, name, title in seeds:
        if tid in seen_tid:
            continue
        seen_tid.add(tid)
        uniq_seeds.append((tid, name, title))
    seeds = uniq_seeds

    state = load_state("phase1", fresh)
    processed = set(state["processed_seed_tids"])
    pending = [s for s in seeds if s[0] not in processed]

    print(f"Phase 1: citedby | seeds {len(seeds)} | done {len(processed)} | pending {len(pending)}")
    print(f"Top citers per seed: {TOP_CITERS_PER_SEED}")
    print(f"Est wall time: {len(pending) * (TOP_CITERS_PER_SEED + 1) * 3.5 / 60:.0f} min")

    client = IKClient()
    n_new = 0
    t0 = time.time()

    try:
        for i, (seed_tid, seed_name, seed_title) in enumerate(pending, 1):
            try:
                html = client.search(f"citedby:{seed_tid}")
                if not html:
                    state["processed_seed_tids"].append(seed_tid)
                    continue
                results = parse_search_results(html, limit=TOP_CITERS_PER_SEED)
                sc_results = [r for r in results if is_supreme_court(r)]
                local_new = 0
                for cand in sc_results:
                    cand_tid = cand["tid"]
                    if cand_tid in state["new_resolved"]:
                        continue
                    if cand_tid == seed_tid:
                        continue
                    info = _verify_citer(client, cand_tid, cand["title"])
                    if info:
                        state["new_resolved"][cand_tid] = info
                        local_new += 1
                        n_new += 1
                state["processed_seed_tids"].append(seed_tid)
                print(f"[{i:>4}/{len(pending)}] {seed_title[:55]:<55} +{local_new:>2} new")
            except Exception as e:
                print(f"[{i:>4}] ERR seed {seed_tid}: {e}")
                state["failed"].append({"seed_tid": seed_tid, "error": str(e)})
                state["processed_seed_tids"].append(seed_tid)

            if i % SAVE_EVERY == 0:
                save_state("phase1", state)
                _flush_index()
                rate = i / (time.time() - t0) if time.time() > t0 else 0
                eta = (len(pending) - i) / rate / 60 if rate else 0
                print(f"   saved | new={n_new} | {rate*60:.1f}/min | ETA {eta:.0f}min")
    except KeyboardInterrupt:
        print("\nInterrupted. Saving...")
    finally:
        save_state("phase1", state)
        _flush_index()
        client.close()

    print(f"\nPhase 1 done. New cases this run: {n_new}. Total phase1: {len(state['new_resolved'])}")
    return 0


def _flush_index():
    """Rebuild authority_index from BOTH phase0 and phase1 resolved."""
    p0 = load_state("phase0")
    p1 = load_state("phase1")
    p2 = load_state("phase2")  # may not exist yet, returns empty

    alias_map: dict = {}
    by_tid_info: dict = {}

    # Phase 0 — original V4-named + IK-resolved cases
    for entry in p0["resolved"].values():
        tid = entry["tid"]
        by_tid_info[tid] = {"title": entry["title"], "reason": entry["reason"]}
        cites = [entry["citation"]] + p2.get("citations_by_tid", {}).get(tid, [])
        aliases = derive_aliases(entry["name"], citations=cites)
        merge_alias_map(alias_map, aliases, tid, entry)

    # Phase 1 — citedby-discovered cases
    for tid, info in p1["new_resolved"].items():
        existing = by_tid_info.get(tid)
        if not existing:
            by_tid_info[tid] = {"title": info["title"], "reason": info["reason"]}
        cites = info.get("citations", []) + p2.get("citations_by_tid", {}).get(tid, [])
        aliases = derive_aliases(info["title"], citations=cites)
        merge_alias_map(alias_map, aliases, tid, info)

    write_authority_index(alias_map, by_tid_info)
