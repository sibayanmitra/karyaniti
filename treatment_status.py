"""
Treatment status lookup for Karyaniti.

Reads data/treatment_status.json and provides:
  - get_treatment(tid: str) -> dict | None
  - filter_overruled(candidates: list) -> tuple[list, list]  # (kept, dropped)
  - annotate_candidates(candidates: list) -> list  # adds treatment field in-place
  - build_synthesis_warning(holdings: list) -> str  # warning block for synth prompt

Status values:
  confirmed             — explicitly confirmed by later benches. Safe.
  overruled             — overruled by larger bench. Filter out.
  partially_overruled   — overruled on one point. Flag prominently.
  modified              — position refined by later judgments. Flag.
  superseded_by_statute — legislation changed the law. Flag.
"""
import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
DB_PATH = HERE / "data" / "treatment_status.json"

# Hot-loaded once at module import. Reloadable via reload().
_DB: dict[str, dict[str, Any]] = {}


def reload() -> int:
    """Reload the JSON. Returns number of real entries loaded."""
    global _DB
    if not DB_PATH.exists():
        print(f"WARNING: {DB_PATH} not found — treatment status disabled")
        _DB = {}
        return 0
    raw = json.loads(DB_PATH.read_text(encoding="utf-8"))
    _DB = {k: v for k, v in raw.items() if not k.startswith("_")}
    return len(_DB)


def get_treatment(tid: str | int | None) -> dict[str, Any] | None:
    """Return treatment dict for tid, or None if not in DB."""
    if not tid:
        return None
    return _DB.get(str(tid))


# Default exclusion rule: only fully overruled cases get filtered out.
# Everything else passes through but is flagged.
DROP_STATUSES = {"overruled"}

FLAG_STATUSES = {"partially_overruled", "modified", "superseded_by_statute"}


def filter_overruled(candidates: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    Split candidates into kept and dropped.
    Drops candidates whose tid is marked 'overruled' in the DB.
    Logs dropped cases.
    """
    kept, dropped = [], []
    for c in candidates:
        tid = str(c.get("tid", ""))
        t = get_treatment(tid)
        if t and t.get("status") in DROP_STATUSES:
            dropped.append({
                **c,
                "_drop_reason": "overruled",
                "_overruled_by": t.get("overruled_by_name", ""),
                "_treatment": t,
            })
        else:
            kept.append(c)
    return kept, dropped


def annotate_candidates(candidates: list[dict]) -> list[dict]:
    """
    Adds 'treatment_status' and 'treatment_note' fields to each candidate.
    Returns the same list (mutated in place).
    """
    for c in candidates:
        tid = str(c.get("tid", ""))
        t = get_treatment(tid)
        if not t:
            c["treatment_status"] = "unverified"
            c["treatment_note"] = ""
            continue
        c["treatment_status"] = t.get("status", "unverified")
        # Build a one-line note
        parts = []
        if t.get("status") == "partially_overruled":
            parts.append(f"Partially overruled by {t.get('overruled_by_name', 'a later judgment')} on: {t.get('on_point', '')}")
        elif t.get("status") == "modified":
            parts.append(f"Position modified: {t.get('note', '')}")
        elif t.get("status") == "superseded_by_statute":
            parts.append(f"Superseded by statute: {t.get('note', '')}")
        elif t.get("status") == "confirmed":
            parts.append(f"Confirmed good law. {t.get('note', '')}")
        if t.get("warning"):
            parts.append(f"WARNING: {t['warning']}")
        c["treatment_note"] = " | ".join(parts)
    return candidates


def build_synthesis_warning(holdings: list[dict]) -> str:
    """
    Build a warning block for the synthesis prompt.
    Lists any holding whose treatment status requires lawyer attention.
    Returns empty string if no warnings needed.
    """
    warnings = []
    seen_tids = set()
    for h in holdings:
        tid = str(h.get("ik_doc_id", ""))
        if tid in seen_tids:
            continue
        seen_tids.add(tid)
        status = h.get("treatment_status", "unverified")
        if status in FLAG_STATUSES:
            t = get_treatment(tid) or {}
            warnings.append({
                "case": h.get("case_name", ""),
                "status": status,
                "detail": t.get("note", "") or t.get("on_point", ""),
                "overruled_by": t.get("overruled_by_name", ""),
            })

    if not warnings:
        return ""

    lines = ["IMPORTANT TREATMENT-STATUS WARNINGS:"]
    for w in warnings:
        line = f"- {w['case']}: status = {w['status']}."
        if w["overruled_by"]:
            line += f" Compare with {w['overruled_by']}."
        if w["detail"]:
            line += f" {w['detail']}"
        lines.append(line)
    lines.append("")
    lines.append(
        "When citing any case marked partially_overruled, modified, or superseded_by_statute, "
        "the research note MUST explicitly state the limitation and direct the reader to the "
        "controlling later authority. Do NOT present the holding as currently controlling without "
        "this qualification."
    )
    return "\n".join(lines)


def stats() -> dict[str, int]:
    """Counts by status — useful for sanity checks."""
    from collections import Counter
    return dict(Counter(v["status"] for v in _DB.values()))


# Auto-load on import
reload()
