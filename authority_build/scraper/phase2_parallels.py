"""Phase 2: fetch doc page for each resolved tid, extract parallel citations as extra aliases."""
import time
from .ik_client import IKClient
from .extractors import parse_doc_page
from .state import load_state, save_state, write_authority_index

SAVE_EVERY = 25


def run(fresh: bool = False) -> int:
    p0 = load_state("phase0")
    p1 = load_state("phase1")
    all_tids = set()
    for e in p0["resolved"].values():
        if e.get("tid"):
            all_tids.add(e["tid"])
    for tid in p1.get("new_resolved", {}):
        all_tids.add(tid)

    state = load_state("phase2", fresh)
    processed = set(state["processed_tids"])
    pending = [t for t in sorted(all_tids) if t not in processed]

    print(f"Phase 2: parallel cites | total tids {len(all_tids)} | done {len(processed)} | pending {len(pending)}")
    print(f"Est wall time: {len(pending) * 3.5 / 60:.1f} min")

    client = IKClient()
    n_added_total = 0
    t0 = time.time()

    try:
        for i, tid in enumerate(pending, 1):
            try:
                html = client.doc(tid)
                doc = parse_doc_page(html or "")
                cites = doc.get("citations", [])
                if cites:
                    state["citations_by_tid"][tid] = cites
                    n_added_total += len(cites)
                state["processed_tids"].append(tid)
                if i % 10 == 0 or cites:
                    title = doc.get("title", "")[:50]
                    print(f"[{i:>4}/{len(pending)}] {title:<50} +{len(cites)} cites")
            except Exception as e:
                print(f"[{i:>4}] ERR {tid}: {e}")
                state["processed_tids"].append(tid)

            if i % SAVE_EVERY == 0:
                save_state("phase2", state)
                _flush_index()
                rate = i / (time.time() - t0) if time.time() > t0 else 0
                eta = (len(pending) - i) / rate / 60 if rate else 0
                print(f"   saved | +{n_added_total} citations total | {rate*60:.1f}/min | ETA {eta:.0f}min")
    except KeyboardInterrupt:
        print("\nInterrupted. Saving...")
    finally:
        save_state("phase2", state)
        _flush_index()
        client.close()

    print(f"\nPhase 2 done. Citations harvested this run: {n_added_total}")
    return 0


def _flush_index():
    """Same as phase1._flush_index — rebuilds from all 3 phases."""
    from .phase1_citedby import _flush_index as flush
    flush()
