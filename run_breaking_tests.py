"""
Karyaniti — Adversarial Test Runner

Runs the query set against the local Karyaniti server and saves verbose results
for evaluation. Saves both raw events and an evaluation template per query.

USAGE:
  python run_breaking_tests.py                     # run all queries
  python run_breaking_tests.py Q01_anticipatory_bail_section_438
  python run_breaking_tests.py Q01 Q02              # run a few by id-prefix
  python run_breaking_tests.py --server http://localhost:8765
  python run_breaking_tests.py --pause              # pause between queries

OUTPUT:
  results/run_<timestamp>/
    Q01_anticipatory_bail_section_438.events.jsonl   # raw SSE stream
    Q01_anticipatory_bail_section_438.summary.md     # readable summary
    Q01_anticipatory_bail_section_438.eval.md        # evaluation template
    aggregate.md                                      # cross-query summary
"""
import sys
import os
import json
import time
import argparse
import pathlib
import datetime
import httpx

# Local import
HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE))
from karyaniti_test_set import QUERY_SET, get_query_by_id, evaluation_template


# ─────────────────────────────────────────────────────────────────────────────
# SSE streaming
# ─────────────────────────────────────────────────────────────────────────────

def stream_sse(client: httpx.Client, server: str, query: str):
    """Stream SSE events from /api/research. Yield decoded events."""
    url = f"{server.rstrip('/')}/api/research"
    with client.stream(
        "POST", url,
        json={"query": query},
        headers={"Accept": "text/event-stream"},
        timeout=httpx.Timeout(connect=30, read=900, write=60, pool=30),
    ) as r:
        r.raise_for_status()
        buf = ""
        current_event = None
        current_data_lines = []
        for chunk in r.iter_bytes(chunk_size=None):
            if not chunk:
                continue
            buf += chunk.decode("utf-8", errors="replace")
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                line = line.rstrip("\r")
                if not line:
                    # Event boundary
                    if current_event is not None or current_data_lines:
                        data = "\n".join(current_data_lines)
                        try:
                            payload = json.loads(data) if data else {}
                        except json.JSONDecodeError:
                            payload = {"_raw": data}
                        yield {"event": current_event or "message", "data": payload}
                        current_event = None
                        current_data_lines = []
                elif line.startswith("event:"):
                    current_event = line[6:].strip()
                elif line.startswith("data:"):
                    current_data_lines.append(line[5:].lstrip())
                # comment lines (":") ignored


# ─────────────────────────────────────────────────────────────────────────────
# Run one query
# ─────────────────────────────────────────────────────────────────────────────

def run_one(query_spec: dict, server: str, outdir: pathlib.Path) -> dict:
    qid = query_spec["id"]
    print(f"\n{'='*70}")
    print(f"  {qid}")
    print(f"  Query: {query_spec['query']}")
    print(f"  Target failure mode: {query_spec['target_failure_mode']}")
    print(f"  Rigor: {query_spec['evaluation_rigor']}")
    print(f"{'='*70}")

    events_path = outdir / f"{qid}.events.jsonl"
    summary_path = outdir / f"{qid}.summary.md"
    eval_path    = outdir / f"{qid}.eval.md"

    started = time.time()
    events = []
    final_event = None
    last_progress = started

    try:
        with httpx.Client() as client:
            for ev in stream_sse(client, server, query_spec["query"]):
                events.append(ev)
                etype = ev.get("event")
                data = ev.get("data") or {}
                msg = data.get("message", "")

                # Progress print — keep it light, don't spam
                now = time.time()
                if etype == "complete" or (ev.get("data") or {}).get("type") == "complete":
                     final_event = ev
                elif etype in ("warning", "judge_verdict") or (now - last_progress) > 8:
                    short_msg = (msg[:80] + "…") if len(msg) > 82 else msg
                    print(f"    [{etype:<14}] {short_msg}")
                    last_progress = now
    except Exception as e:
        print(f"  ERROR during stream: {e}")
        final_event = {"event": "error", "data": {"error": str(e)}}

    elapsed = round(time.time() - started, 1)
    print(f"  Done in {elapsed}s — {len(events)} events")

    # Save raw events
    with events_path.open("w", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")

    # Build summary
    summary = build_summary(query_spec, events, final_event, elapsed)
    summary_path.write_text(summary, encoding="utf-8")

    # Evaluation template
    eval_path.write_text(evaluation_template(qid), encoding="utf-8")

    return {
        "qid": qid,
        "elapsed": elapsed,
        "final_event": final_event,
        "n_events": len(events),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Summary builder
# ─────────────────────────────────────────────────────────────────────────────

def build_summary(query_spec: dict, events: list, final_event: dict, elapsed: float) -> str:
    lines = []
    lines.append(f"# Run summary — {query_spec['id']}")
    lines.append(f"Query: {query_spec['query']}")
    lines.append(f"Elapsed: {elapsed}s")
    lines.append(f"Events: {len(events)}")
    lines.append("")

    # Stage-by-stage trace
    lines.append("## Pipeline trace (timing-ordered)")
    for ev in events:
        etype = ev.get("event")
        msg = (ev.get("data") or {}).get("message", "")
        if etype in ("judge_verdict",):
            passed = (ev.get("data") or {}).get("passed", False)
            tag = "✓" if passed else "✗"
            lines.append(f"  {tag} {msg}")
        elif etype in (
            "council_start", "fetching", "processing", "l1_done",
            "adversary_done", "warning", "no_holdings", "judging",
            "synthesising", "complete", "stage2_filtered", "stage4_filtered",
        ):
            lines.append(f"  · {etype}: {msg}")
    lines.append("")

    # Final results
    if not final_event:
        lines.append("## No final event received")
        return "\n".join(lines)

    final_data = final_event.get("data", {})
    note = final_data.get("note", "")
    holdings = final_data.get("holdings", [])
    stats = final_data.get("stats", {})

    lines.append("## Stats")
    lines.append(f"- passed: {stats.get('passed', '?')}")
    lines.append(f"- total : {stats.get('total', '?')}")
    lines.append(f"- docs  : {stats.get('docs', '?')}")
    lines.append(f"- elapsed pipeline : {stats.get('elapsed', '?')}s")
    lines.append("")

    # Verified holdings
    passed_holdings = [h for h in holdings if h.get("pass")]
    failed_holdings = [h for h in holdings if not h.get("pass")]

    lines.append(f"## Verified holdings ({len(passed_holdings)})")
    for i, h in enumerate(passed_holdings, 1):
        lines.append(f"### V{i:02d} — {h.get('case_name','?')}, para {h.get('para_num','?')}")
        lines.append(f"**Proposition:** {h.get('prop','')}")
        lines.append("")
        lines.append(f"**Anchor:** {h.get('verbatim','')}")
        lines.append("")
        lines.append(f"- court: {h.get('court','?')}")
        lines.append(f"- faithful: {h.get('faithful','?')}")
        lines.append(f"- attribution: {h.get('attribution','?')} ({h.get('attribution_reason','')})")
        lines.append(f"- adv_verdict: {h.get('adv_verdict','?')}")
        lines.append(f"- judge_conf: {h.get('judge_conf','?')}")
        lines.append(f"- judge_reason: {h.get('judge_reason','')}")
        lines.append(f"- ik_url: {h.get('ik_url','')}")
        lines.append("")
        lines.append(f"<details><summary>Source paragraph</summary>\n\n{h.get('para_text','')}\n\n</details>")
        lines.append("")

    # Failed holdings — which gate caught them
    lines.append(f"## Rejected holdings ({len(failed_holdings)})")
    by_gate = {}
    for h in failed_holdings:
        gate = h.get("gate_failed", "?")
        by_gate.setdefault(gate, []).append(h)
    for gate, hs in sorted(by_gate.items()):
        lines.append(f"### Gate `{gate}` caught {len(hs)}")
        for h in hs:
            lines.append(f"- {h.get('case_name','?')[:50]}, para {h.get('para_num','?')}")
            lines.append(f"  prop: {h.get('prop','')[:150]}")
            lines.append(f"  reason: {h.get('judge_reason','')[:150]}")
            lines.append(f"  attribution: {h.get('attribution','?')} ({h.get('attribution_reason','')})")
            lines.append(f"  faithful: {h.get('faithful','?')} ({h.get('judge_reason','')[:60]})")
            lines.append("")
    lines.append("")

    # Synthesis note (if any)
    if note:
        lines.append("## Synthesis note")
        lines.append("")
        lines.append(note)
        lines.append("")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Aggregate
# ─────────────────────────────────────────────────────────────────────────────

def build_aggregate(results: list, outdir: pathlib.Path):
    lines = []
    lines.append("# Aggregate run report")
    lines.append(f"Timestamp: {datetime.datetime.now().isoformat()}")
    lines.append(f"Queries run: {len(results)}")
    total_elapsed = sum(r["elapsed"] for r in results)
    lines.append(f"Total wall time: {round(total_elapsed,1)}s ({round(total_elapsed/60,1)} min)")
    lines.append("")
    lines.append("## Per-query summary")
    lines.append("")
    lines.append("| Query | Elapsed | Passed/Total | Final |")
    lines.append("|-------|---------|--------------|-------|")
    for r in results:
        fd = (r.get("final_event") or {}).get("data") or {}
        stats = fd.get("stats", {})
        passed = stats.get("passed", "?")
        total = stats.get("total", "?")
        final_msg = (r.get("final_event") or {}).get("event", "?")
        lines.append(f"| {r['qid']} | {r['elapsed']}s | {passed}/{total} | {final_msg} |")
    lines.append("")
    lines.append("## Evaluation step")
    lines.append("")
    lines.append("For each query, open `<qid>.summary.md` to see verified holdings.")
    lines.append("Then open `<qid>.eval.md` and fill it in against the must-find / must-reject lists.")
    lines.append("Verdict reminder:")
    lines.append("  - PASS    = 0 must-reject + >=50% must-find")
    lines.append("  - PARTIAL = 0 must-reject + <50% must-find")
    lines.append("  - FAIL    = ANY must-reject present (catastrophic)")
    lines.append("")
    (outdir / "aggregate.md").write_text("\n".join(lines), encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query_ids", nargs="*", help="Query IDs or prefixes to run (default: all)")
    ap.add_argument("--server", default="http://localhost:8765", help="Karyaniti server URL")
    ap.add_argument("--outdir", default="results", help="Output directory base")
    ap.add_argument("--pause", action="store_true", help="Pause between queries for inspection")
    args = ap.parse_args()

    # Filter queries
    if args.query_ids:
        selected = []
        for q in QUERY_SET:
            for prefix in args.query_ids:
                if q["id"] == prefix or q["id"].startswith(prefix):
                    selected.append(q)
                    break
    else:
        selected = QUERY_SET

    if not selected:
        print(f"No queries match: {args.query_ids}")
        print("Available query IDs:")
        for q in QUERY_SET:
            print(f"  {q['id']}")
        return 1

    # Health check
    print(f"Server: {args.server}")
    try:
        with httpx.Client(timeout=10) as c:
            r = c.get(f"{args.server.rstrip('/')}/api/health")
            r.raise_for_status()
            health = r.json()
            print(f"Health: extractor={health.get('extractor')}  judge={health.get('judge')}  "
                  f"faithful={health.get('faithful')}  attribution={health.get('attribution')}")
            for k in ("ik_token", "or_key"):
                if health.get(k) != "set":
                    print(f"  WARNING: {k} not set in server env")
    except Exception as e:
        print(f"Server health check failed: {e}")
        print("Is the server running on the URL given?")
        return 2

    # Output directory
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    outdir = pathlib.Path(args.outdir) / f"run_{ts}"
    outdir.mkdir(parents=True, exist_ok=True)
    print(f"Output: {outdir}")
    print(f"Running {len(selected)} query(ies)")

    results = []
    for q in selected:
        r = run_one(q, args.server, outdir)
        results.append(r)
        if args.pause and q is not selected[-1]:
            input("\n  [Press Enter for next query, or Ctrl-C to stop] ")

    build_aggregate(results, outdir)
    print(f"\n{'='*70}")
    print(f"Done. Results in: {outdir}")
    print(f"Open aggregate.md, then each <qid>.summary.md and <qid>.eval.md")
    print(f"{'='*70}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
