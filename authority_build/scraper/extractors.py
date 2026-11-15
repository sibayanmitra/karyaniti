"""Pure HTML parsing — no I/O. Functions take HTML strings, return structured data."""
import re
from bs4 import BeautifulSoup

_DOC_LINK_RE = re.compile(r"/(?:doc|docfragment)/(\d+)/")
_YEAR_RE     = re.compile(r"\b(19|20)\d{2}\b")
_REPORTER_RE = re.compile(r"\b(SCC|AIR|SCR|JT|SCALE|SC)\b", re.I)


# ── Search result list ─────────────────────────────────────────────────────

def parse_search_results(html: str, limit: int = 15) -> list[dict]:
    """Parse IK search page. Returns [{tid, title, source, raw_snippet}, ...]."""
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for art in soup.select("article.result")[:limit]:
        title_tag = art.select_one("h4.result_title a") or art.select_one("a")
        if not title_tag:
            continue
        href = title_tag.get("href", "")
        m = _DOC_LINK_RE.search(href)
        if not m:
            continue
        title = title_tag.get_text(strip=True)
        src = art.select_one(".docsource")
        source = src.get_text(strip=True) if src else ""
        if not source:
            blob = art.get_text(" ", strip=True).lower()
            if "supreme court of india" in blob and "daily order" not in blob:
                source = "Supreme Court of India"
        out.append({
            "tid": m.group(1),
            "title": title,
            "source": source,
            "raw_snippet": art.get_text(" ", strip=True)[:500],
        })
    return out


def is_supreme_court(result: dict) -> bool:
    source = (result.get("source", "") or "").lower().strip()
    return source == "supreme court of india"


# ── Doc page metadata ──────────────────────────────────────────────────────

def parse_doc_page(html: str) -> dict:
    """Returns {title, source, citations: [str], body_text}."""
    if not html:
        return {"title": "", "source": "", "citations": [], "body_text": ""}
    soup = BeautifulSoup(html, "html.parser")

    def _text(sel):
        el = soup.select_one(sel)
        return el.get_text(" ", strip=True) if el else ""

    title  = _text(".doc_title")
    source = _text(".docsource_main")

    citations_raw = ""
    el = soup.select_one(".doc_citations")
    if el:
        citations_raw = el.get_text(" ", strip=True)
        # Strip "Equivalent citations:" prefix
        citations_raw = re.sub(r"^[Ee]quivalent\s+citations?\s*:\s*", "", citations_raw)

    citations = _split_citations(citations_raw)

    # Body text — doc body is in <pre> or .judgments
    body_el = (soup.select_one(".judgments")
               or soup.select_one("pre")
               or soup.select_one(".maindoc"))
    body_text = body_el.get_text(" ", strip=True) if body_el else soup.get_text(" ", strip=True)

    return {
        "title": title,
        "source": source,
        "citations": citations,
        "body_text": body_text,
    }


def _split_citations(raw: str) -> list[str]:
    """Split a comma-joined citation string into individual citations."""
    if not raw:
        return []
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    cites = []
    buf = []
    for p in parts:
        buf.append(p)
        joined = ", ".join(buf)
        # A complete citation has a year AND a reporter token
        if _YEAR_RE.search(joined) and _REPORTER_RE.search(joined):
            cites.append(joined)
            buf = []
    if buf:
        cites.append(", ".join(buf))
    # Dedup, drop very short fragments
    seen = set()
    out = []
    for c in cites:
        c = re.sub(r"\s+", " ", c).strip()
        if len(c) < 8 or c.lower() in seen:
            continue
        seen.add(c.lower())
        out.append(c)
    return out


def citation_signature(cite: str) -> set[str]:
    """Tokens that, if found in doc body, confirm the citation."""
    if not cite:
        return set()
    sig = set()
    sig.update(m.group(0) for m in _YEAR_RE.finditer(cite))
    sig.update(m.group(0).upper() for m in _REPORTER_RE.finditer(cite))
    for n in re.findall(r"\b\d+\b", cite):
        if 1 <= len(n) <= 4:
            sig.add(n)
    return sig


def body_contains_citation(body_text: str, cite: str) -> bool:
    if not body_text or not cite:
        return False
    sig = citation_signature(cite)
    if not sig:
        return False
    upper = body_text.upper()
    matched = sum(1 for tok in sig if tok.upper() in upper)
    return matched >= min(3, len(sig))
