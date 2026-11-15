"""
Sequential test runner for 5 doctrinal queries matched to a law intern's
High Court research topics.

Run before a demo to know what works and what does not.

Usage:
  1. Start your server in another terminal: python main.py
  2. Run: python test_intern_queries.py
  3. Walk away ~15 min
  4. Read test_results/<timestamp>/summary.txt
"""
import json
import re
import time
from datetime import datetime
from pathlib import Path

import httpx

SERVER_URL = "http://localhost:8765/api/research"
TIMEOUT_SECONDS = 600   # 10 min per query ceiling — none should hit this

# ── Queries ──────────────────────────────────────────────────────────────────
# Phrased the way a 4th-year intern would actually type them.
# Mix of (a) topics he's worked on, (b) different doctrinal areas to surface
# different failure modes.

QUERIES = [
    {
        "id": "q1_arbitration_termination",
        "topic": "Termination of arbitrator's mandate",
        "query": "On what grounds can an arbitrator's mandate be terminated under section 14 of the Arbitration and Conciliation Act 1996?",
        "expected_landmarks": [
            "HRD Corporation",          # tid 35443395 — in your index
            "Voestalpine Schienen",     # tid 28100587 — in your index
            "Bharat Broadband",         # tid 88491207 — in your index
        ],
        "difficulty": "EASY",
        "why": "All three canonical SC cases confirmed present in authority_index. If this fails, retrieval path itself is broken.",
    },
    {
        "id": "q2_res_judicata",
        "topic": "Res judicata",
        "query": "What is the scope of res judicata under section 11 CPC and how does it differ from issue estoppel?",
        "expected_landmarks": [
            "Sulochana Amma",           # tid 1047975 — in your index
            "Satyadhyan Ghosal",        # — may or may not be in index
            "State of UP v Nawab Hussain",
        ],
        "difficulty": "MEDIUM",
        "why": "Sulochana Amma confirmed in index. Tests whether retrieval surfaces it when query is doctrinal not name-based.",
    },
    {
        "id": "q3_execution_jurisdiction",
        "topic": "Execution proceedings and jurisdiction",
        "query": "Can the executing court go behind the decree to challenge jurisdiction of the court that passed it?",
        "expected_landmarks": [
            "Brahmdeo Choudhary",       # tid 1203615 — in your index
            "Hiralal Patni",
            "Vasudev Dhanjibhai Modi",
        ],
        "difficulty": "MEDIUM-HARD",
        "why": "Classic Calcutta HC research topic. Tests whether index handles 'executing court' + 'going behind decree' phrasing.",
    },
    {
        "id": "q4_partition_commissioner",
        "topic": "Partition Commissioner duties",
        "query": "What are the duties of a Partition Commissioner appointed under Order XX Rule 18 CPC in a partition suit?",
        "expected_landmarks": [
            "Phoolchand v Gopal Lal",
            "R Ramamurthi Iyer",
        ],
        "difficulty": "HARD",
        "why": "Niche area. Probably NOT in your authority index. Tests pure BM25+rerank fallback. Honest failure here is fine — tells us breadth limit.",
    },
    {
        "id": "q5_handwriting_expert",
        "topic": "Handwriting expert appointment",
        "query": "When can a court appoint a handwriting expert under section 45 of the Evidence Act and what is the evidentiary value of their opinion?",
        "expected_landmarks": [
            "Murari Lal",
            "State (Delhi Admn) v Pali Ram",
            "Magan Bihari Lal",
        ],
        "difficulty": "MEDIUM",
        "why": "Section number in query (§45) is strong signal. Tests if extractor + judge handle expert-evidence holdings.",
    },
]


# ── Output paths ─────────────────────────────────────────────────────────────

RUN_DIR = Path("test_results") / datetime.now().strftime("%Y%m%d_%H%M%S")
RUN_DIR.mkdir(parents=True, exist_ok=True)


# ── SSE parsing ──────────────────────────────────────────────────────────────

def parse_sse_line(line: str) -> tuple[str, dict] | None:
    """SSE format: 'event: <type>\\ndata: <json>\\n\\n'. We see one line at a time."""
    line = line.strip()
    if not line:
        return None
    if line.startswith("event:"):
        return ("EVENT_TYPE", {"_event_type": line[6:].strip()})
    if line.startswith("data:"):
        try:
            return ("DATA", json.loads(line[5:].strip()))
        except json.JSONDecodeError:
            return ("DATA", {"_raw": line[5:].strip()})
    return None


# ── One query, one full trace ────────────────────────────────────────────────

def run_one_query(qmeta: dict) -> dict:
    """Fire one query at server, stream SSE, capture everything."""
    print(f"\n{'═'*70}")
    print(f"[{qmeta['id']}] {qmeta['topic']}  ({qmeta['difficulty']})")
    print(f"Query: {qmeta['query']}")
    print(f"{'═'*70}")

    t_start = time.time()
    events = []
    current_event_type = None
    final_data = None
    error = None

    try:
        with httpx.stream(
            "POST", SERVER_URL,
            json={"query": qmeta["query"], "doctypes": "supremecourt"},
            timeout=TIMEOUT_SECONDS,
        ) as resp:
            if resp.status_code != 200:
                error = f"HTTP {resp.status_code}: {resp.read()[:300]}"
                return {
                    "meta": qmeta,
                    "elapsed": time.time() - t_start,
                    "events": [],
                    "final": None,
                    "error": error,
                }
            for raw_line in resp.iter_lines():
                if not raw_line:
                    continue
                parsed = parse_sse_line(raw_line)
                if not parsed:
                    continue
                kind, payload = parsed
                if kind == "EVENT_TYPE":
                    current_event_type = payload["_event_type"]
                elif kind == "DATA":
                    ev = {
                        "t": round(time.time() - t_start, 2),
                        "type": current_event_type,
                        **payload,
                    }
                    events.append(ev)
                    # Print short live status
                    msg = payload.get("message", "")[:70]
                    print(f"  [{ev['t']:>6.1f}s] {current_event_type:<20} {msg}")
                    if current_event_type == "complete":
                        final_data = payload
    except Exception as e:
        error = f"{type(e).__name__}: {e}"

    return {
        "meta": qmeta,
        "elapsed": round(time.time() - t_start, 2),
        "events": events,
        "final": final_data,
        "error": error,
    }


# ── Diagnostic analysis ──────────────────────────────────────────────────────

def diagnose(result: dict) -> dict:
    """Boil down the trace into a verdict + failure mode."""
    events = result.get("events", [])
    final = result.get("final")

    if result.get("error"):
        return {
            "verdict": "ERROR",
            "failure_mode": "TRANSPORT_ERROR",
            "detail": result["error"],
            "elapsed_sec": result.get("elapsed", 0),
            "candidates_retrieved": [],
            "landmarks_seen": [],
            "landmarks_missed": result["meta"].get("expected_landmarks", []),
            "holdings_pass": 0,
            "holdings_fail": 0,
            "event_counts": {},
            "treatment_drops": [],
            "final_note_preview": "",
        }

    # Count event types
    event_counts = {}
    for e in events:
        event_counts[e.get("type", "?")] = event_counts.get(e.get("type", "?"), 0) + 1

    # Extract candidate titles (from "fetching" events)
    candidates = []
    for e in events:
        if e.get("type") == "fetching" and "Fetching:" in e.get("message", ""):
            title = e["message"].replace("Fetching:", "").strip().rstrip("…").strip()
            candidates.append(title)

    # Check expected landmarks
    expected = result["meta"].get("expected_landmarks", [])
    landmarks_seen = []
    for landmark in expected:
        for c in candidates:
            if landmark.lower() in c.lower():
                landmarks_seen.append(landmark)
                break
    landmarks_missed = [l for l in expected if l not in landmarks_seen]

    # Pass/fail counts (from "judge_verdict" events)
    passes = sum(1 for e in events if e.get("type") == "judge_verdict" and e.get("passed"))
    fails  = sum(1 for e in events if e.get("type") == "judge_verdict" and not e.get("passed"))

    # Treatment status drops?
    treatment_drops = [
        e for e in events
        if "overruled" in str(e.get("message", "")).lower()
    ]

    # Final synthesis stats
    final_stats = (final or {}).get("stats", {})
    final_note = (final or {}).get("note", "")

    # Failure-mode decision tree
    if not candidates:
        failure_mode = "RETRIEVAL_MISS"
        detail = "Zero candidates retrieved. Search/rerank returned nothing."
    elif landmarks_missed and not landmarks_seen:
        failure_mode = "RETRIEVAL_WRONG_CASES"
        detail = f"None of expected landmarks retrieved. Got: {candidates[:3]}"
    elif passes == 0 and fails > 0:
        failure_mode = "ALL_GATES_FAILED"
        detail = f"{fails} candidates evaluated, 0 passed the council."
    elif passes == 0 and fails == 0:
        failure_mode = "EXTRACTION_EMPTY"
        detail = "Cases retrieved but extractor produced no holdings to evaluate."
    elif passes > 0:
        failure_mode = "SUCCESS"
        detail = f"{passes} verified holdings produced."
    else:
        failure_mode = "UNKNOWN"
        detail = "Did not fit known patterns."

    return {
        "verdict": "PASS" if passes > 0 else "FAIL",
        "failure_mode": failure_mode,
        "detail": detail,
        "elapsed_sec": result["elapsed"],
        "candidates_retrieved": candidates,
        "landmarks_seen": landmarks_seen,
        "landmarks_missed": landmarks_missed,
        "holdings_pass": passes,
        "holdings_fail": fails,
        "event_counts": event_counts,
        "treatment_drops": [e.get("message") for e in treatment_drops][:5],
        "final_note_preview": (final_note or "")[:600],
    }


# ── Write human-readable report ──────────────────────────────────────────────

def write_query_report(result: dict, diag: dict):
    qid = result["meta"]["id"]

    # Full JSON trace
    (RUN_DIR / f"{qid}.json").write_text(
        json.dumps({"meta": result["meta"], "diagnosis": diag, "events": result["events"], "final": result["final"]}, indent=2, default=str),
        encoding="utf-8",
    )

    # Human-readable text
    lines = [
        "═" * 72,
        f"  {result['meta']['topic']}",
        "═" * 72,
        f"Query:       {result['meta']['query']}",
        f"Difficulty:  {result['meta']['difficulty']}",
        f"Rationale:   {result['meta']['why']}",
        "",
        f"Elapsed:     {diag['elapsed_sec']}s",
        f"Verdict:     {diag['verdict']}",
        f"Failure mode: {diag['failure_mode']}",
        f"Detail:      {diag['detail']}",
        "",
        "─ Expected canonical landmarks ─",
    ]
    for lm in result["meta"].get("expected_landmarks", []):
        mark = "✓" if lm in diag["landmarks_seen"] else "✗"
        lines.append(f"  {mark} {lm}")
    lines.append("")

    lines.append("─ Candidates retrieved ─")
    if diag["candidates_retrieved"]:
        for c in diag["candidates_retrieved"]:
            lines.append(f"  - {c}")
    else:
        lines.append("  (none)")
    lines.append("")

    lines.append(f"Holdings: {diag['holdings_pass']} PASS / {diag['holdings_fail']} FAIL")
    lines.append("")

    if diag["treatment_drops"]:
        lines.append("─ Treatment status drops ─")
        for d in diag["treatment_drops"]:
            lines.append(f"  - {d}")
        lines.append("")

    lines.append("─ Event counts ─")
    for k, v in sorted(diag["event_counts"].items(), key=lambda x: -x[1]):
        lines.append(f"  {k}: {v}")
    lines.append("")

    lines.append("─ Final research note ─")
    lines.append(diag["final_note_preview"] or "(empty)")
    lines.append("")

    (RUN_DIR / f"{qid}.txt").write_text("\n".join(lines), encoding="utf-8")


# ── Cross-query summary ──────────────────────────────────────────────────────

def write_summary(all_diagnoses: list):
    lines = [
        "═" * 72,
        f"  KARYANITI PIPELINE TEST — {datetime.now():%Y-%m-%d %H:%M}",
        "═" * 72,
        f"Queries run: {len(all_diagnoses)}",
        f"Passed: {sum(1 for d in all_diagnoses if d['verdict'] == 'PASS')}",
        f"Failed: {sum(1 for d in all_diagnoses if d['verdict'] == 'FAIL')}",
        f"Errors: {sum(1 for d in all_diagnoses if d['verdict'] == 'ERROR')}",
        "",
        "─ Per query verdict ─",
    ]
    for d in all_diagnoses:
        meta = d.get("_meta", {})
        lines.append(
            f"  [{d['verdict']:<5}] {meta.get('id','?'):<35} "
            f"{d['failure_mode']:<25} "
            f"{d['elapsed_sec']:>6.1f}s  "
            f"({d['holdings_pass']}P/{d['holdings_fail']}F)"
        )
    lines.append("")
    lines.append("─ Failure mode distribution ─")
    from collections import Counter
    modes = Counter(d["failure_mode"] for d in all_diagnoses)
    for m, c in modes.most_common():
        lines.append(f"  {c}× {m}")
    lines.append("")
    lines.append("─ Total wall time ─")
    total = sum(d["elapsed_sec"] for d in all_diagnoses)
    lines.append(f"  {total:.1f}s ({total/60:.1f} min)")
    lines.append("")
    lines.append("─ Per-query reports ─")
    for d in all_diagnoses:
        meta = d.get("_meta", {})
        lines.append(f"  test_results/{RUN_DIR.name}/{meta.get('id','?')}.txt")
    (RUN_DIR / "summary.txt").write_text("\n".join(lines), encoding="utf-8")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print(f"Output dir: {RUN_DIR}\n")

    # Sanity check server
    try:
        r = httpx.get("http://localhost:8765/api/health", timeout=5)
        if r.status_code != 200:
            print(f"Server health check failed: {r.status_code}")
            return 1
        print(f"Server reachable: {r.json()}\n")
    except Exception as e:
        print(f"Cannot reach server at {SERVER_URL}. Is python main.py running?")
        print(f"Error: {e}")
        return 1

    all_diagnoses = []
    for qmeta in QUERIES:
        result = run_one_query(qmeta)
        diag = diagnose(result)
        diag["_meta"] = qmeta  # for the summary
        write_query_report(result, diag)
        all_diagnoses.append(diag)
        print(f"\n  → {diag['verdict']} | {diag['failure_mode']} | "
              f"{diag['elapsed_sec']}s | {diag['holdings_pass']}P/{diag['holdings_fail']}F")

    write_summary(all_diagnoses)
    print(f"\n{'═'*70}")
    print(f"Summary: {RUN_DIR / 'summary.txt'}")
    print(f"Per-query reports: {RUN_DIR}/*.txt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
