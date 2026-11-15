"""
IK scraper CLI.

Usage from inside authority_build/:
    python scrape_ik.py                  # Phase 0: resolve unresolved cases from progress
    python scrape_ik.py --limit 10       # canary 10
    python scrape_ik.py --citedby        # Phase 1: mine cited-by graph from resolved
    python scrape_ik.py --parallel-cites # Phase 2: extract parallel citations
    python scrape_ik.py --fresh ...      # discard state for that phase
"""
import argparse
from scraper import phase0_resolve, phase1_citedby, phase2_parallels


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, help="Canary: process only first N (phase 0 only)")
    ap.add_argument("--fresh", action="store_true", help="Discard state for the selected phase")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--citedby", action="store_true", help="Phase 1: mine cited-by graph")
    g.add_argument("--parallel-cites", action="store_true", help="Phase 2: extract parallel citations")
    args = ap.parse_args()

    if args.citedby:
        return phase1_citedby.run(fresh=args.fresh)
    if args.parallel_cites:
        return phase2_parallels.run(fresh=args.fresh)
    return phase0_resolve.run(limit=args.limit, fresh=args.fresh)


if __name__ == "__main__":
    raise SystemExit(main())
