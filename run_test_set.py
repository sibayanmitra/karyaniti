"""
Karyaniti — Test Set Runner
Runs all 18 queries from the locked test set against the local server.
Saves structured results to a markdown document for review.

Usage:
    1. Make sure main.py server is running on localhost:8765
    2. python run_test_set.py
    3. Open test_results_<timestamp>.md

Cost estimate: ~$2-3 in OpenRouter spend (18 queries × ~$0.10-0.15 each)
Runtime: ~60-90 minutes (sequential, ~3-4 min per query)
"""

import httpx
import json
import asyncio
import time
from datetime import datetime
from pathlib import Path

# ── The locked test set ──────────────────────────────────────────────────────

TEST_QUERIES = [
    # Tier 1 — Standard queries (well-established authority)
    {
        "id": 1,
        "tier": 1,
        "topic": "Electronic evidence under Section 65B",
        "query": "electronic evidence admissibility section 65B evidence act",
    },
    {
        "id": 2,
        "tier": 1,
        "topic": "Article 226 alternative remedy",
        "query": "writ petition maintainability under Article 226 when alternative remedies exist",
    },
    {
        "id": 3,
        "tier": 1,
        "topic": "Partnership firm legal status on partner death",
        "query": "legal status of partnership firm when partner dies under partnership act",
    },
    {
        "id": 4,
        "tier": 1,
        "topic": "Writ against private body",
        "query": "writ petition maintainability against private body under Article 226",
    },
    {
        "id": 5,
        "tier": 1,
        "topic": "Anticipatory bail under Section 438",
        "query": "anticipatory bail section 438 CrPC scope conditions duration",
    },
    {
        "id": 6,
        "tier": 1,
        "topic": "Natural justice and urgency exception",
        "query": "natural justice audi alteram partem exception urgency administrative action",
    },
    {
        "id": 7,
        "tier": 1,
        "topic": "Section 482 CrPC quashing of FIR",
        "query": "section 482 CrPC inherent power high court quashing FIR",
    },
    {
        "id": 8,
        "tier": 1,
        "topic": "Specific performance — discretionary relief",
        "query": "specific performance contract immovable property discretionary relief",
    },
    {
        "id": 9,
        "tier": 1,
        "topic": "Doctrine of pith and substance",
        "query": "doctrine pith and substance legislative competence seventh schedule",
    },
    {
        "id": 10,
        "tier": 1,
        "topic": "Promissory estoppel against state",
        "query": "promissory estoppel against state government policy change",
    },

    # Tier 2 — Natural language phrasing
    {
        "id": 11,
        "tier": 2,
        "topic": "Partner death (natural language)",
        "query": "what happens to a partnership firm when one of the partners dies",
    },
    {
        "id": 12,
        "tier": 2,
        "topic": "Tape recording as evidence",
        "query": "is a tape recording admissible as evidence in court",
    },
    {
        "id": 13,
        "tier": 2,
        "topic": "Wife's stridhan ownership",
        "query": "does husband have any right over wife's stridhan property",
    },

    # Tier 3 — Stress tests
    {
        "id": 14,
        "tier": 3,
        "topic": "Empty result test (no relevant authority)",
        "query": "liability of artificial general intelligence under indian penal code",
        "stress_type": "empty_result",
        "expected_behavior": "Honest 'no relevant authorities' output. No confabulation.",
    },
    {
        "id": 15,
        "tier": 3,
        "topic": "False premise — non-existent section",
        "query": "section 99 indian partnership act dissolution remedies",
        "stress_type": "false_premise",
        "expected_behavior": "Either premise check catches it OR retrieval returns nothing AND synthesis says no relevant authority. No fabrication of Section 99 content.",
    },
    {
        "id": 16,
        "tier": 3,
        "topic": "Recently overruled doctrine (Kharak Singh privacy)",
        "query": "right to privacy not a fundamental right kharak singh",
        "stress_type": "overruled_doctrine",
        "expected_behavior": "Either synthesis flags Puttaswamy 2017 overruling OR honest gap analysis acknowledges treatment unverified. Should NOT cite Kharak Singh as current good law on this point.",
    },
    {
        "id": 17,
        "tier": 3,
        "topic": "New law (post-2024 BNS transition)",
        "query": "BNS section 103 murder punishment 2024",
        "stress_type": "new_law_thin_corpus",
        "expected_behavior": "Honest 'no case law yet' OR transitional cases acknowledging IPC-to-BNS shift. Should NOT pretend BNS Section 103 has settled jurisprudence.",
    },
    {
        "id": 18,
        "tier": 3,
        "topic": "Cross-statute disambiguation — Section 138",
        "query": "section 138 negotiable instruments act dishonour cheque",
        "stress_type": "cross_statute_collision",
        "expected_behavior": "≥2 holdings PASS, all from NI Act context. No CrPC Section 138 or IT Act Section 138 contamination.",
    },
]

# ── Configuration ────────────────────────────────────────────────────────────

SERVER_URL = "http://localhost:8765/api/research"
DOCTYPES = "supremecourt"  # will get auto-broadened to 'judgments' by the pipeline
MODE = "quick"
TIMEOUT = 600  # 10 min per query, generous
DELAY_BETWEEN_QUERIES = 5  # seconds, let server breathe


# ── SSE parsing helpers ──────────────────────────────────────────────────────

async def run_query(client: httpx.AsyncClient, query: str) -> dict:
    """
    Hit the local API for one query.
    Returns dict with: trace_events (list), final_data (complete event), elapsed (float).
    """
    payload = {
        "query": query,
        "doctypes": DOCTYPES,
        "mode": MODE,
        "enable_premise_check": False,
    }

    trace_events = []
    final_data = None
    start = time.time()

    try:
        async with client.stream(
            "POST",
            SERVER_URL,
            json=payload,
            timeout=TIMEOUT,
            headers={"Accept": "text/event-stream"},
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                try:
                    event = json.loads(line[6:])
                except json.JSONDecodeError:
                    continue

                trace_events.append(event)

                if event.get("type") == "complete":
                    final_data = event
                    break
                elif event.get("type") == "error":
                    final_data = {"type": "error", "message": event.get("message", "")}
                    break

    except httpx.TimeoutException:
        return {"error": "timeout", "trace_events": trace_events, "elapsed": time.time() - start}
    except httpx.HTTPError as e:
        return {"error": f"HTTP error: {e}", "trace_events": trace_events, "elapsed": time.time() - start}
    except Exception as e:
        return {"error": f"Unexpected: {e}", "trace_events": trace_events, "elapsed": time.time() - start}

    return {
        "trace_events": trace_events,
        "final_data": final_data,
        "elapsed": round(time.time() - start, 1),
    }


# ── Markdown formatting ──────────────────────────────────────────────────────

def format_trace(events: list) -> str:
    """Render the trace events as a readable list."""
    lines = []
    for ev in events:
        t = ev.get("type", "")
        msg = ev.get("message", "")
        if t in {"complete", "error"}:
            continue
        # Skip noise
        if t == "judge_verdict":
            mark = "✓" if ev.get("passed") else "✗"
            lines.append(f"- {mark} {msg}")
        else:
            lines.append(f"- {msg}")
    return "\n".join(lines)


def format_holdings(holdings: list) -> str:
    """Render PASSed and FAILed holdings in a compact form."""
    if not holdings:
        return "_No holdings returned._"

    passed = [h for h in holdings if h.get("pass")]
    failed = [h for h in holdings if not h.get("pass")]

    out = []

    if passed:
        out.append(f"\n**Verified ({len(passed)}):**\n")
        for i, h in enumerate(passed, 1):
            case = h.get("case_name", "Unknown")[:80]
            citation = h.get("citation", "")
            para = h.get("para_num", "?")
            court = h.get("court", "")
            prop = h.get("prop", "")
            verbatim = h.get("verbatim", "")
            ik_url = h.get("ik_url", "")
            adv = h.get("adv_verdict", "skipped")
            conf = round(h.get("judge_conf", 0) * 100)

            out.append(f"#### {i}. {case}")
            out.append(f"- **Citation:** {citation}")
            out.append(f"- **Court:** {court} · Para {para}")
            out.append(f"- **Proposition:** {prop}")
            out.append(f"- **Verbatim:** \"{verbatim}\"")
            out.append(f"- **Adversary:** {adv} · **Judge confidence:** {conf}%")
            out.append(f"- **IK link:** {ik_url}")
            out.append("")

    if failed:
        out.append(f"\n**Did not clear ({len(failed)}):**\n")
        for i, h in enumerate(failed, 1):
            case = h.get("case_name", "Unknown")[:80]
            para = h.get("para_num", "?")
            prop = h.get("prop", "")
            judge_reason = h.get("judge_reason", "")
            gate = h.get("gate_failed", "")

            out.append(f"#### {i}. {case} · Para {para}")
            out.append(f"- **Proposition:** {prop}")
            out.append(f"- **Reason:** {judge_reason}")
            if gate:
                out.append(f"- **Gate failed:** {gate}")
            out.append("")

    return "\n".join(out)


def format_result(test: dict, result: dict) -> str:
    """Format one query's full result block."""
    out = []
    out.append(f"## Query {test['id']} (Tier {test['tier']}) — {test['topic']}")
    out.append("")
    out.append(f"**Query text:** `{test['query']}`")
    out.append("")

    if test.get("stress_type"):
        out.append(f"**Stress test type:** {test['stress_type']}")
        out.append(f"**Expected behavior:** {test['expected_behavior']}")
        out.append("")

    if "error" in result:
        out.append(f"### ❌ ERROR: {result['error']}")
        out.append(f"Elapsed before failure: {result.get('elapsed', 0)}s")
        out.append("")
        return "\n".join(out)

    final = result.get("final_data") or {}

    if final.get("type") == "error":
        out.append(f"### ❌ Pipeline returned error: {final.get('message', '')}")
        out.append("")
        return "\n".join(out)

    stats = final.get("stats", {})
    holdings = final.get("holdings", [])
    passed = stats.get("passed", 0)
    total = stats.get("total", 0)
    docs = stats.get("docs", 0)
    elapsed = stats.get("elapsed", 0)

    out.append(f"### Result: {passed}/{total} verified · {docs} docs read · {elapsed}s")
    out.append("")

    # Synthesis note
    note = final.get("note", "")
    if note:
        out.append("### Research note")
        out.append("")
        out.append(note)
        out.append("")

    # Holdings
    out.append("### Holdings")
    out.append(format_holdings(holdings))
    out.append("")

    # Trace
    out.append("<details><summary>Pipeline trace</summary>")
    out.append("")
    out.append(format_trace(result.get("trace_events", [])))
    out.append("")
    out.append("</details>")
    out.append("")
    out.append("---")
    out.append("")

    return "\n".join(out)


# ── Main runner ──────────────────────────────────────────────────────────────

async def main():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = Path(f"test_results_{timestamp}.md")

    # Header
    header_lines = [
        f"# Karyaniti Test Set Results — {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        f"**Server:** `{SERVER_URL}`",
        f"**Mode:** `{MODE}` · **Doctypes:** `{DOCTYPES}`",
        f"**Total queries:** {len(TEST_QUERIES)}",
        "",
        "---",
        "",
    ]

    # Open file and write header immediately so partial results are saved
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(header_lines))
        f.flush()

    # Track aggregate stats
    aggregate = {
        "total_run": 0,
        "errored": 0,
        "tier1": {"passed_holdings": 0, "total_holdings": 0, "queries": 0},
        "tier2": {"passed_holdings": 0, "total_holdings": 0, "queries": 0},
        "tier3": {"queries": 0},
        "total_elapsed": 0.0,
    }

    print(f"\n=== Karyaniti Test Run · {len(TEST_QUERIES)} queries ===")
    print(f"Output: {output_path.absolute()}\n")

    async with httpx.AsyncClient() as client:
        for i, test in enumerate(TEST_QUERIES, 1):
            print(f"[{i}/{len(TEST_QUERIES)}] Tier {test['tier']} · {test['topic']}")
            print(f"    Query: {test['query']}")

            t_start = time.time()
            result = await run_query(client, test["query"])
            elapsed = time.time() - t_start
            aggregate["total_elapsed"] += elapsed
            aggregate["total_run"] += 1

            if "error" in result:
                print(f"    ❌ ERROR: {result['error']} ({round(elapsed,1)}s)")
                aggregate["errored"] += 1
            else:
                final = result.get("final_data") or {}
                stats = final.get("stats", {})
                passed = stats.get("passed", 0)
                total = stats.get("total", 0)
                docs = stats.get("docs", 0)
                print(f"    ✓ {passed}/{total} verified · {docs} docs · {round(elapsed,1)}s")

                tier_key = f"tier{test['tier']}"
                if tier_key in aggregate:
                    aggregate[tier_key]["queries"] += 1
                    if test["tier"] in (1, 2):
                        aggregate[tier_key]["passed_holdings"] += passed
                        aggregate[tier_key]["total_holdings"] += total

            # Write this query's result block immediately (incremental save)
            with open(output_path, "a", encoding="utf-8") as f:
                f.write(format_result(test, result))
                f.flush()

            # Pause between queries
            if i < len(TEST_QUERIES):
                await asyncio.sleep(DELAY_BETWEEN_QUERIES)

    # Aggregate summary at the bottom
    summary_lines = [
        "",
        "## Aggregate Summary",
        "",
        f"- Queries attempted: {aggregate['total_run']}",
        f"- Errored: {aggregate['errored']}",
        f"- Total runtime: {round(aggregate['total_elapsed']/60, 1)} minutes",
        "",
        "### Tier 1 (standard queries)",
        f"- Queries: {aggregate['tier1']['queries']}",
        f"- Holdings verified: {aggregate['tier1']['passed_holdings']}/{aggregate['tier1']['total_holdings']}",
        "",
        "### Tier 2 (natural language)",
        f"- Queries: {aggregate['tier2']['queries']}",
        f"- Holdings verified: {aggregate['tier2']['passed_holdings']}/{aggregate['tier2']['total_holdings']}",
        "",
        "### Tier 3 (stress tests)",
        f"- Queries: {aggregate['tier3']['queries']}",
        "- Pass criteria are behavior-based — review each manually against `expected_behavior` above.",
        "",
        "---",
        "",
        "## How to read this document",
        "",
        "Tier 1 and 2 pass rate is a quantitative signal — aim for ≥12/18 holdings-verified rate across queries.",
        "",
        "Tier 3 requires manual inspection: did the system fail in the *expected* way (good) or in an *unexpected* way (finding)?",
        "",
        "For each query, check:",
        "1. Did real cases get retrieved? (look at holdings list)",
        "2. Did the synthesis honestly state gaps? (look at research note)",
        "3. Did any FAILed holding actually look correct? (judge being too conservative)",
        "4. Did any PASSed holding actually look wrong? (judge too lenient — most damaging case)",
        "",
    ]
    with open(output_path, "a", encoding="utf-8") as f:
        f.write("\n".join(summary_lines))

    print(f"\n=== Done. Output: {output_path.absolute()} ===\n")


if __name__ == "__main__":
    asyncio.run(main())
