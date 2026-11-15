"""
Overnight test runner for Karyaniti — 10 queries across doctrinal areas.

Requires: server already running at http://localhost:8765 (python main.py)
in another terminal.

Output: results/overnight_TIMESTAMP/qXX_<slug>.json + summary.txt

Usage:
  python overnight_runner.py            # full 10-query run
  python overnight_runner.py --resume   # skip queries already saved
  python overnight_runner.py --start 5  # start from query 5

Safe to Ctrl+C — partial results preserved.
"""
import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

SERVER_URL = "http://localhost:8765"
RESULTS_ROOT = Path(__file__).resolve().parent / "results"

QUERIES = [
    # Doctrinal queries (7)
    ("anticipatory_bail",
     "What are the grounds for anticipatory bail under section 438 CrPC and when can it be denied?"),
    ("part_performance",
     "What is the doctrine of part performance under section 53A of the Transfer of Property Act?"),
    ("specific_performance",
     "When can a court grant specific performance of a contract for sale of immovable property?"),
    ("limitation_appeal",
     "What is the limitation period for filing an appeal under article 116 of the Limitation Act?"),
    ("ni_138_cognizance",
     "Can a Magistrate take cognizance of an offence under section 138 of the Negotiable Instruments Act without a complaint?"),
    ("interim_maintenance",
     "What are the principles for granting interim maintenance under section 125 CrPC?"),
    ("dowry_death_304b",
     "What is the standard of proof required for a conviction under section 304B IPC for dowry death?"),
    # Case-name queries (3) — test authority resolver
    ("vishaka",
     "What did Vishaka v State of Rajasthan hold about sexual harassment at workplace?"),
    ("kesavananda",
     "What principles did Kesavananda Bharati lay down regarding basic structure of the Constitution?"),
    ("joseph_shine",
     "What did Joseph Shine decide about section 497 IPC adultery?"),
]


def health_check() -> bool:
    """Verify server is up before starting."""
    try:
        r = httpx.get(f"{SERVER_URL}/api/health", timeout=5.0)
        return r.status_code == 200
    except Exception as e:
        print(f"Health check failed: {e}")
        return False


def parse_sse_stream(response) -> list[dict]:
    """Collect all SSE events from streaming response."""
    events = []
    buffer = ""
    for chunk in response.iter_text():
        buffer += chunk
        while "\n\n" in buffer:
            block, buffer = buffer.split("\n\n", 1)
            for line in block.split("\n"):
                if line.startswith("data: "):
                    try:
                        events.append(json.loads(line[6:]))
                    except json.JSONDecodeError:
                        pass
    # Flush trailing buffer — the last event (usually 'done') has no
    # trailing \n\n before the connection closes
    if buffer.strip():
        for line in buffer.split("\n"):
            if line.startswith("data: "):
                try:
                    events.append(json.loads(line[6:]))
                except json.JSONDecodeError:
                    pass
    return events


def run_query(query: str, slug: str, out_dir: Path) -> dict:
    """Run a single query, save full event log + final result."""
    out_path = out_dir / f"{slug}.json"
    print(f"\n{'═'*72}")
    print(f"  Query: {query[:64]}")
    print(f"  Slug:  {slug}")
    print(f"{'═'*72}")

    t0 = time.time()
    try:
        with httpx.stream(
            "POST",
            f"{SERVER_URL}/api/research",
            json={"query": query, "doctypes": "supremecourt"},
            timeout=1800.0,  # 30 min ceiling per query
        ) as response:
            if response.status_code != 200:
                print(f"  HTTP {response.status_code}")
                return {"slug": slug, "query": query, "status": "http_error",
                        "code": response.status_code}
            events = parse_sse_stream(response)
    except Exception as e:
        elapsed = time.time() - t0
        print(f"  Error after {elapsed:.0f}s: {e}")
        result = {"slug": slug, "query": query, "status": "error",
                  "error": str(e)[:200], "elapsed_sec": elapsed}
        out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False),
                            encoding="utf-8")
        return result

    elapsed = time.time() - t0

    # Find the 'complete' event with final stats + holdings
    complete_event = None
    for e in events:
        if e.get("type") == "complete":
            complete_event = e
            break

    if complete_event:
        holdings = complete_event.get("holdings", [])
        stats = complete_event.get("stats", {})
        passed = stats.get("passed", sum(1 for h in holdings if h.get("pass")))
        total = stats.get("total", len(holdings))
        note = complete_event.get("note", "")
        print(f"  Done: {passed}/{total} verified, {elapsed:.0f}s")
    else:
        holdings = []
        passed = total = 0
        note = ""
        print(f"  No 'complete' event received, {elapsed:.0f}s")

    result = {
        "slug": slug,
        "query": query,
        "status": "completed" if complete_event else "incomplete",
        "elapsed_sec": round(elapsed, 1),
        "passed": passed,
        "total": total,
        "note": note,
        "holdings": holdings,
        "n_events": len(events),
    }
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False),
                        encoding="utf-8")
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--resume", action="store_true",
                    help="Skip queries already saved in latest results dir")
    ap.add_argument("--start", type=int, default=1,
                    help="Start from query number N (1-indexed)")
    ap.add_argument("--limit", type=int, default=None,
                    help="Run only N queries (smoke test)")
    args = ap.parse_args()

    if not health_check():
        print("Server not reachable at http://localhost:8765")
        print("Start server in another terminal: python main.py")
        return 1

    print(f"Server OK at {SERVER_URL}")

    # Choose output dir: reuse latest if --resume, else fresh timestamp
    RESULTS_ROOT.mkdir(exist_ok=True)
    if args.resume:
        dirs = sorted([d for d in RESULTS_ROOT.iterdir()
                        if d.is_dir() and d.name.startswith("overnight_")])
        out_dir = dirs[-1] if dirs else RESULTS_ROOT / f"overnight_{datetime.now():%Y%m%d_%H%M%S}"
    else:
        out_dir = RESULTS_ROOT / f"overnight_{datetime.now():%Y%m%d_%H%M%S}"
    out_dir.mkdir(exist_ok=True)
    print(f"Output: {out_dir}\n")

    queries_to_run = QUERIES[args.start - 1:]
    if args.limit:
        queries_to_run = queries_to_run[:args.limit]

    summary = []
    t_start = time.time()
    for i, (slug, query) in enumerate(queries_to_run, start=args.start):
        out_path = out_dir / f"q{i:02d}_{slug}.json"
        if args.resume and out_path.exists():
            existing = json.loads(out_path.read_text(encoding="utf-8"))
            print(f"\n[{i:>2}/{len(QUERIES)}] SKIPPED (already done): {slug} — "
                  f"{existing.get('passed','?')}/{existing.get('total','?')}")
            summary.append(existing)
            continue

        result = run_query(query, f"q{i:02d}_{slug}", out_dir)
        summary.append(result)

        # Brief pause between queries — let server breathe
        if i < len(QUERIES):
            time.sleep(3)

    # Write summary
    total_elapsed = time.time() - t_start
    print(f"\n{'═'*72}")
    print(f"All queries done. Total wall time: {total_elapsed/60:.1f} min")
    print(f"{'═'*72}")

    summary_lines = [
        f"Overnight run summary",
        f"Started: {datetime.now():%Y-%m-%d %H:%M:%S}",
        f"Total wall time: {total_elapsed/60:.1f} min",
        f"",
        f"{'#':<3} {'slug':<25} {'status':<12} {'passed/total':<14} {'elapsed':<10}",
        "-" * 72,
    ]
    n_completed = 0
    n_total_passed = 0
    n_total_holdings = 0
    for i, r in enumerate(summary, start=args.start):
        if r["status"] == "completed":
            n_completed += 1
            n_total_passed += r["passed"]
            n_total_holdings += r["total"]
        summary_lines.append(
            f"{i:<3} {r['slug'][:25]:<25} {r['status']:<12} "
            f"{r.get('passed','?')}/{r.get('total','?'):<10} "
            f"{r.get('elapsed_sec','?')}s"
        )
    summary_lines.extend([
        "",
        f"Completed: {n_completed}/{len(summary)}",
        f"Total verified holdings: {n_total_passed}/{n_total_holdings}",
    ])

    summary_text = "\n".join(summary_lines)
    print("\n" + summary_text)
    (out_dir / "summary.txt").write_text(summary_text, encoding="utf-8")
    print(f"\nResults saved in: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
