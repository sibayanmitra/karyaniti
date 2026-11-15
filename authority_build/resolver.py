"""Resolve a generated case to an Indian Kanoon doc_id via search + LLM verification."""
import re
from llm_client import llm, ik_search, parse_json, strip_html
from prompts import VERIFY_PROMPT

VERIFIER_MODEL = "deepseek/deepseek-v4-pro"

_PUNCT = re.compile(r"[^\w\s]")
_STOPWORDS = {
    "versus", "vs", "v", "state", "union", "india", "the", "of", "and",
    "anr", "ors", "ltd", "limited", "co", "pvt", "private", "corp",
    "corporation", "mfg", "manufacturing", "mumbai", "delhi", "p",
}


def _overlap(target: str, candidate: str) -> float:
    """Token overlap with a bonus for distinctive (non-generic-legal) tokens."""
    tt = {t for t in _PUNCT.sub(" ", target.lower()).split() if len(t) >= 3} - _STOPWORDS
    ct = {t for t in _PUNCT.sub(" ", candidate.lower()).split() if len(t) >= 3} - _STOPWORDS
    if not tt:
        return 0.0
    distinctive = tt - {"cit", "commissioner", "income", "tax", "appellate", "court", "supreme"}
    if distinctive and any(d in ct for d in distinctive):
        return max(0.5, len(tt & ct) / len(tt))
    return len(tt & ct) / len(tt)


async def _verify(case: dict, doctrine: str, candidate: dict) -> tuple[bool, str]:
    """LLM-verify a candidate is the same case. Pre-filter cheap signals first."""
    title  = strip_html(candidate.get("title", ""))
    source = candidate.get("docsource", "")
    if "Supreme Court of India" not in source:
        return False, f"source filter ({source[:30]})"
    ov = _overlap(case.get("name", ""), title)
    if ov < 0.25:
        return False, f"low overlap ({ov:.2f})"
    try:
        raw, _ = await llm(VERIFIER_MODEL, VERIFY_PROMPT.format(
            name=case.get("name", ""), citation=case.get("citation", ""),
            doctrine=doctrine, title=title, source=source), max_tokens=1500)
        obj = parse_json(raw)
        if obj.get("match") is True:
            return True, obj.get("reason", "")
        # Truncation-tolerant fallback
        if re.search(r'"match"\s*:\s*true', raw):
            return True, "truncated response, regex-detected match"
        return False, obj.get("reason", raw[:120])
    except Exception as e:
        return False, f"verify err: {e}"


def _citation_match(citation: str, text: str) -> bool:
    if not citation:
        return False
    cit_tokens = set(re.findall(r"\d{4}|SCC|AIR|SC|\(\d+\)|\d+", citation))
    txt_tokens = set(re.findall(r"\d{4}|SCC|AIR|SC|\(\d+\)|\d+", text))
    return len(cit_tokens & txt_tokens) >= 3


async def resolve_case(case: dict, doctrine: str) -> dict | None:
    """
    Returns:
      {
        "doc_id": "...", "name": "...", "citation": "...", "aliases": [...],
        "confidence": "HIGH"|"MEDIUM", "treatment_status": "...",
        "matched_title": "...",
      }
    or None if unresolvable.
    """
    name = case.get("name", "")
    citation = case.get("citation", "")
    if not name:
        return None

    queries = [f"{name} {citation}".strip(), name, f"{name} {doctrine}"]
    best = None  # (confidence_rank, info)

    for q in queries:
        docs = await ik_search(q)
        for cand in docs[:10]:
            ok, _ = await _verify(case, doctrine, cand)
            if not ok:
                continue
            title = strip_html(cand.get("title", ""))
            confidence = "HIGH" if _citation_match(citation, title) else "MEDIUM"
            info = {
                "doc_id": str(cand.get("tid", "")),
                "name": name,
                "citation": citation,
                "aliases": case.get("aliases", []) or [],
                "confidence": confidence,
                "treatment_status": case.get("treatment_status", "good_law"),
                "matched_title": title,
            }
            rank = {"HIGH": 0, "MEDIUM": 1}[confidence]
            if best is None or rank < best[0]:
                best = (rank, info)
            if confidence == "HIGH":
                return info  # short-circuit on best
        if best:
            return best[1]
    return None
