"""
Karyaniti — Local Research Server
Run: python main.py
Open: http://localhost:8765
"""

import os, json, re, asyncio, time, logging, sqlite3
import treatment_status
from pathlib import Path
from typing import AsyncGenerator
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv
from authority_index import resolve_case_name

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
log = logging.getLogger(__name__)

IK_TOKEN   = os.getenv("INDIAN_KANOON_API_TOKEN", "")
OR_KEY     = os.getenv("OPENROUTER_API_KEY", "")
IK_BASE    = "https://api.indiankanoon.org"

# ── Local cache for parsed IK documents ─────────────────────────────────────
# Sits at <main.py dir>/data/ik_doc_cache.db. Path is anchored to this file so
# the cache works regardless of which directory we launch Python from.
DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)
CACHE_DB = DATA_DIR / "ik_doc_cache.db"

PINNED_FREE = [
    "qwen/qwen3-coder-480b-a35b-instruct:free",
    "deepseek/deepseek-r1:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "tencent/hy3-preview:free",
    "deepseek/deepseek-chat-v3.1:free",
    "microsoft/mai-ds-r1:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "inclusionai/ling-2.6-1t:free",
    "google/gemma-4-31b-it:free",
    "mistralai/mistral-small-3.1-24b-instruct:free",
    "nousresearch/hermes-3-llama-3.1-405b:free",
]

PINNED_PAID = [
    {"id": "x-ai/grok-4.20",                           "label": "Grok 4.20 (xAI)"},
    {"id": "x-ai/grok-4.1-fast",                       "label": "Grok 4.1 Fast (xAI)"},
    {"id": "x-ai/grok-4.20-multi-agent",               "label": "Grok 4.20 Multi-Agent (xAI)"},
    {"id": "openai/gpt-5.5",                           "label": "GPT-5.5 (OpenAI)"},
    {"id": "openai/gpt-5.4",                           "label": "GPT-5.4 (OpenAI)"},
    {"id": "openai/gpt-4.1",                           "label": "GPT-4.1 (OpenAI)"},
    {"id": "openai/gpt-4.1-mini",                      "label": "GPT-4.1 Mini (OpenAI)"},
    {"id": "anthropic/claude-opus-4.7",                "label": "Claude Opus 4.7 (Anthropic)"},
    {"id": "anthropic/claude-sonnet-4.6",              "label": "Claude Sonnet 4.6 (Anthropic)"},
    {"id": "anthropic/claude-sonnet-4-5",              "label": "Claude Sonnet 4.5 (Anthropic)"},
    {"id": "google/gemini-3.1-pro-preview",            "label": "Gemini 3.1 Pro (Google)"},
    {"id": "google/gemini-3-pro-preview",              "label": "Gemini 3 Pro (Google)"},
    {"id": "google/gemini-3-flash-preview",            "label": "Gemini 3 Flash (Google)"},
    {"id": "google/gemini-2.5-flash-lite",             "label": "Gemini 2.5 Flash Lite (Google)"},
    {"id": "moonshotai/kimi-k2.6",                     "label": "Kimi K2.6 (Moonshot)"},
    {"id": "deepseek/deepseek-v4-pro",                 "label": "DeepSeek V4 Pro"},
    {"id": "deepseek/deepseek-v4-flash",               "label": "DeepSeek V4 Flash"},
    {"id": "deepseek/deepseek-r1",                     "label": "DeepSeek R1"},
    {"id": "xiaomi/mimodel-ultra",                     "label": "MiMo Ultra (Xiaomi)"},
    {"id": "bytedance-seed/seed-2.0-mini",             "label": "Seed 2.0 Mini (ByteDance)"},
    {"id": "minimax/minimax-m2.7",                     "label": "MiniMax M2.7"},
    {"id": "z-ai/glm-5.1",                             "label": "GLM-5.1 (Z.AI)"},
]

_model_cache: dict | None = None
_model_cache_ts: float = 0

async def fetch_or_models() -> dict:
    global _model_cache, _model_cache_ts
    now = time.time()
    if _model_cache and now - _model_cache_ts < 600:
        return _model_cache
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get("https://openrouter.ai/api/v1/models",
                headers={"Authorization": f"Bearer {OR_KEY}"})
        models = r.json().get("data", [])
    except Exception as e:
        log.warning(f"OR model list fetch failed: {e}")
        models = []
    free_list, paid_list = [], []
    pinned_free_ids = set(PINNED_FREE)
    pinned_paid_ids = {m["id"] for m in PINNED_PAID}
    for m in models:
        mid = m.get("id", "")
        name = m.get("name", mid.split("/")[-1])
        pricing = m.get("pricing", {})
        prompt_cost = float(pricing.get("prompt", 0) or 0)
        if mid.endswith(":free") or prompt_cost == 0:
            label = f"{name} (free)"
            entry = {"id": mid, "label": label}
            if mid in pinned_free_ids:
                free_list.insert(0, entry)
            else:
                free_list.append(entry)
        else:
            if mid in pinned_paid_ids:
                continue
            cost_str = f"~${prompt_cost*1e6:.2f}/M"
            label = f"{name}  {cost_str}"
            paid_list.append({"id": mid, "label": label})
    paid_list = PINNED_PAID + [p for p in paid_list if p["id"] not in pinned_paid_ids]
    seen = set()
    free_dedup = []
    for m in free_list:
        if m["id"] not in seen:
            seen.add(m["id"]); free_dedup.append(m)
    if not free_dedup:
        free_dedup = [{"id": i, "label": i.split("/")[-1].replace(":free","")} for i in PINNED_FREE]
    _model_cache = {"free": free_dedup, "paid": paid_list}
    _model_cache_ts = now
    return _model_cache

# Model constants — all must be set in .env. Empty default = loud failure if not configured.
M_EXTRACTOR  = os.getenv("COUNCIL_EXTRACTOR_MODEL",  "")
M_ADVERSARY  = os.getenv("COUNCIL_ADVERSARY_MODEL",  "")
M_JUDGE      = os.getenv("COUNCIL_JUDGE_MODEL",      "")
M_SYNTHESIS  = os.getenv("SYNTHESIS_MODEL",          "")
M_RERANK     = os.getenv("RERANK_MODEL",             "")
M_FAITHFUL    = os.getenv("COUNCIL_FAITHFUL_MODEL",    "deepseek/deepseek-v4-pro")
M_ATTRIBUTION = os.getenv("COUNCIL_ATTRIBUTION_MODEL", "deepseek/deepseek-v4-pro")
M_EXPANSION = os.getenv("COUNCIL_EXPANSION_MODEL", "anthropic/claude-opus-4.7")

app = FastAPI(title="Karyaniti Local")

# === Minimal access control ===
import collections as _collections, datetime as _datetime
from fastapi import HTTPException as _HTTPException

ACCESS_KEY = os.getenv("KARYANITI_ACCESS_KEY", "change-me-before-sharing")
DAILY_CAP = int(os.getenv("KARYANITI_DAILY_CAP", "25"))
_query_log = _collections.defaultdict(list)

def _gate(request: Request):
    today = _datetime.date.today().isoformat()
    if len(_query_log[today]) >= DAILY_CAP:
        raise _HTTPException(429, f"Daily cap of {DAILY_CAP} queries reached. Try tomorrow.")
    _query_log[today].append(1)


# ── IK API helpers ────────────────────────────────────────────────────────────

async def ik_search(query: str, doctypes: str = "supremecourt", page: int = 0) -> list:
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(f"{IK_BASE}/search/",
            headers={"Authorization": f"Token {IK_TOKEN}"},
            data={"formInput": query, "pagenum": page, "doctypes": doctypes})
        if r.status_code != 200:
            log.warning(f"IK search {r.status_code}: {r.text[:200]}")
            return []
        return r.json().get("docs", [])


async def ik_doc(doc_id: str, maxcitedby: int = 5) -> dict:
    async with httpx.AsyncClient(timeout=45) as c:
        r = await c.post(f"{IK_BASE}/doc/{doc_id}/",
            headers={"Authorization": f"Token {IK_TOKEN}"},
            data={"maxcites": 15, "maxcitedby": maxcitedby})
        if r.status_code != 200:
            log.warning(f"IK doc {r.status_code}: doc_id={doc_id}")
            return {}
        return r.json()


async def ik_docmeta(doc_id: str) -> dict:
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(f"{IK_BASE}/docmeta/{doc_id}/",
            headers={"Authorization": f"Token {IK_TOKEN}"})
        if r.status_code != 200:
            log.warning(f"IK docmeta {r.status_code}: doc_id={doc_id}")
            return {}
        return r.json()


async def ik_docfragment(doc_id: str, query: str) -> dict:
    async with httpx.AsyncClient(timeout=45) as c:
        r = await c.post(f"{IK_BASE}/docfragment/{doc_id}/",
            headers={"Authorization": f"Token {IK_TOKEN}"},
            data={"formInput": query})
        if r.status_code != 200:
            log.warning(f"IK docfragment {r.status_code}: doc_id={doc_id}")
            return {}
        return r.json()


def _is_section_introducer(text: str) -> bool:
    """Detect paragraphs that introduce a new section (submission, discussion, etc.).
    Stage 1 of attribution defense — heuristic only; Stage 2 makes the verdict."""
    if len(text) > 350:
        return False
    tl = text.lower()
    if text.rstrip().endswith(":"):
        return True
    return any(p in tl for p in [
        "submitted as under", "submitted as follows",
        "contended as under", "argued as follows",
        "submissions of", "contentions of",
    ])


def _has_strong_court_voice(text: str) -> bool:
    """Markers strong enough to override a stale submission section_header.
    Conservative list — false negatives are handled by Stage 2 with full context."""
    head = text.lower()[:300]
    return any(k in head for k in [
        "we hold", "we are of the view", "we are of the opinion",
        "in our opinion", "it is held", "we conclude", "we therefore",
        "this court holds", "we find that", "having heard",
        "having considered", "we have heard", "for our consideration",
    ])


def _walk_paragraphs(soup, max_paras=None):
    """Yield paragraph dicts with section_header tracking.
    The section_header is a HINT for downstream stages, not a verdict."""
    current_section_header = ""
    section_age = 0
    para_num = 0
    for el in soup.find_all(["p", "div", "h1", "h2", "h3", "h4", "h5", "h6"]):
        if el.parent and el.parent.name in ["p"]:
            continue
        text = el.get_text(" ", strip=True)
        text = re.sub(r"\s+", " ", text).strip()
        is_html_heading = el.name in ("h1", "h2", "h3", "h4", "h5", "h6")
        if is_html_heading and 3 <= len(text) <= 300:
            current_section_header = text[:250]
            section_age = 0
            continue
        if len(text) < 25:
            continue
        para_num += 1
        if max_paras is not None and para_num > max_paras:
            break
        ptype = _para_type(el)
        if ptype == "submission":
            if _is_section_introducer(text) or not current_section_header:
                current_section_header = text[:250]
                section_age = 0
            else:
                section_age += 1
        elif _is_section_introducer(text) and current_section_header and section_age >= 2:
            current_section_header = ""
            section_age = 0
        elif current_section_header:
            if _has_strong_court_voice(text):
                current_section_header = ""
                section_age = 0
            elif section_age > 20:
                current_section_header = ""
                section_age = 0
            else:
                section_age += 1
        yield {
            "number": para_num,
            "text": text,
            "type": ptype,
            "section_header": current_section_header,
        }


def _format_para_for_extractor(p: dict) -> str:
    """Format a paragraph with section context for the extractor LLM."""
    header_line = f"[Section context: {p['section_header']}]\n" if p.get("section_header") else ""
    return f"[Para {p['number']} — {p['type'].replace('_',' ').title()}]\n{header_line}{p['text']}"


def parse_ik_doc(doc_id: str, data: dict) -> dict:
    from bs4 import BeautifulSoup
    raw_html = data.get("doc", "")
    soup = BeautifulSoup(raw_html, "lxml") if raw_html else None
    paragraphs = []
    holding_paras = []
    if soup:
        for p in _walk_paragraphs(soup):
            paragraphs.append(p)
            if p["type"] in {"analysis_of_law", "conclusion", "courts_discourse"}:
                holding_paras.append(p)
    if not paragraphs:
        plain = re.sub(r"<[^>]+>", " ", raw_html)
        plain = re.sub(r"\s+", " ", plain).strip()
        chunks = [c.strip() for c in plain.split("  ") if len(c.strip()) > 25]
        for i, c in enumerate(chunks[:80], 1):
            paragraphs.append({"number": i, "text": c, "type": "general", "section_header": ""})
        holding_paras = paragraphs[-15:]
    title = re.sub(r"<[^>]+>", "", data.get("title", "Unknown Case")).strip()
    citation = _extract_citation(title)
    court = data.get("docsource", "Supreme Court of India")
    treatment_map = {}
    for cite in data.get("citeList", []):
        ctype = cite.get("catgeory", cite.get("category", "neutral")).lower()
        treatment_map[str(cite.get("tid", ""))] = ctype
    # Fallback: if no holding-type paragraphs detected, use second-half paragraphs
    # WITH proper [Para N] formatting so extractor anchors to real paragraph numbers.
    if not holding_paras and paragraphs:
        holding_paras = paragraphs[max(0, len(paragraphs)//2):]
        log.info(f"parse_ik_doc {doc_id}: no holding-type paras detected, "
                 f"falling back to {len(holding_paras)} paragraphs from doc body")
    holding_text = "\n\n".join(_format_para_for_extractor(p) for p in holding_paras)
    return {
        "doc_id": doc_id, "title": title, "citation": citation or title,
        "court": court, "date": data.get("publishdate", ""),
        "paragraphs": paragraphs, "holding_text": holding_text[:6000],
        "treatment_map": treatment_map,
        "ik_url": f"https://indiankanoon.org/doc/{doc_id}/",
    }


def parse_ik_fragment(doc_id: str, data: dict, fallback_meta: dict | None = None) -> dict:
    from bs4 import BeautifulSoup
    raw_html = data.get("doc", "") or data.get("fragment", "")
    soup = BeautifulSoup(raw_html, "lxml") if raw_html else None
    paragraphs = []
    holding_paras = []
    if soup:
        for p in _walk_paragraphs(soup):
            paragraphs.append(p)
            if p["type"] in {"analysis_of_law", "conclusion", "courts_discourse"}:
                holding_paras.append(p)
    if not paragraphs:
        plain = re.sub(r"<[^>]+>", " ", raw_html)
        plain = re.sub(r"\s+", " ", plain).strip()
        chunks = [c.strip() for c in plain.split("  ") if len(c.strip()) > 25]
        for i, c in enumerate(chunks[:40], 1):
            paragraphs.append({"number": i, "text": c, "type": "general", "section_header": ""})

    if not holding_paras and paragraphs:
        holding_paras = paragraphs[:20]

    title = re.sub(r"<[^>]+>", "",
                   data.get("title", "") or (fallback_meta or {}).get("title", "Unknown Case")).strip()
    citation = _extract_citation(title)
    court = data.get("docsource", "") or (fallback_meta or {}).get("docsource", "Supreme Court of India")

    treatment_map = {}
    for cite in (data.get("citeList") or (fallback_meta or {}).get("citeList") or []):
        ctype = cite.get("catgeory", cite.get("category", "neutral")).lower()
        treatment_map[str(cite.get("tid", ""))] = ctype

    # holding_paras already includes the paragraphs[:20] fallback above, but
    # guard against edge case where neither branch ran.
    if not holding_paras and paragraphs:
        holding_paras = paragraphs[:20]
    holding_text = "\n\n".join(_format_para_for_extractor(p) for p in holding_paras)

    return {
        "doc_id": doc_id, "title": title, "citation": citation or title,
        "court": court, "date": data.get("publishdate", "") or (fallback_meta or {}).get("publishdate", ""),
        "paragraphs": paragraphs, "holding_text": holding_text[:6000],
        "treatment_map": treatment_map,
        "ik_url": f"https://indiankanoon.org/doc/{doc_id}/",
        "_from_fragment": True,
    }


# ─── Doc cache helpers ──────────────────────────────────────────────────────
# Layer 2 caching: stores parsed IK document results by doc_id. On cache hit,
# the fragment + full doc fetches AND the BeautifulSoup parsing are all skipped.

def init_cache() -> None:
    """Create the cache DB and table if they don't exist. Call once at startup."""
    with sqlite3.connect(CACHE_DB) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS doc_cache (
                doc_id        TEXT PRIMARY KEY,
                parsed_json   TEXT NOT NULL,
                cached_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_accessed TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                access_count  INTEGER DEFAULT 1
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_doc_cache_accessed "
            "ON doc_cache(last_accessed)"
        )
    log.info(f"Doc cache initialised at {CACHE_DB}")


def get_cached_doc(doc_id: str) -> dict | None:
    """Return cached parsed doc for doc_id, or None if not cached.
    Updates access stats on hit."""
    try:
        with sqlite3.connect(CACHE_DB) as conn:
            row = conn.execute(
                "SELECT parsed_json FROM doc_cache WHERE doc_id = ?",
                (doc_id,)
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                "UPDATE doc_cache "
                "SET last_accessed = CURRENT_TIMESTAMP, "
                "    access_count = access_count + 1 "
                "WHERE doc_id = ?",
                (doc_id,)
            )
            return json.loads(row[0])
    except Exception as e:
        log.warning(f"Cache read failed for {doc_id}: {e}")
        return None


def cache_doc(doc_id: str, parsed: dict) -> None:
    """Store a parsed doc result. Silently no-ops on error."""
    try:
        with sqlite3.connect(CACHE_DB) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO doc_cache "
                "(doc_id, parsed_json, cached_at, last_accessed, access_count) "
                "VALUES (?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, "
                "        COALESCE((SELECT access_count FROM doc_cache WHERE doc_id = ?), 0) + 1)",
                (doc_id, json.dumps(parsed), doc_id)
            )
    except Exception as e:
        log.warning(f"Cache write failed for {doc_id}: {e}")


def cache_stats() -> dict:
    """Return cache stats — useful for /api/health and debugging."""
    try:
        with sqlite3.connect(CACHE_DB) as conn:
            total = conn.execute("SELECT COUNT(*) FROM doc_cache").fetchone()[0]
            hits = conn.execute(
                "SELECT COALESCE(SUM(access_count), 0) FROM doc_cache"
            ).fetchone()[0]
            top = conn.execute(
                "SELECT doc_id, access_count FROM doc_cache "
                "ORDER BY access_count DESC LIMIT 5"
            ).fetchall()
        # Each cache hit saves the docfragment (₹0.05) + doc (₹0.20) = ₹0.25 pre-GST.
        # With 18% GST that's ₹0.295 per hit.
        return {
            "total_docs_cached": total,
            "total_accesses": hits,
            "hit_savings_estimate_inr": round(max(0, hits - total) * 0.295, 2),
            "top_accessed": [{"doc_id": d, "count": c} for d, c in top],
        }
    except Exception as e:
        return {"error": str(e)}


def _para_type(el) -> str:
    attr = el.get("data-type", "").lower()
    classes = " ".join(el.get("class", [])).lower()
    text_short = el.get_text(" ", strip=True).lower()[:120]
    text_full = el.get_text(" ", strip=True).lower()
    combined = attr + " " + classes

    # Stage 1 — Conservative attribution filter.
    # Catches the obvious counsel/party voice cases cheaply.
    # Ambiguous cases (sub-paragraphs without in-text markers, mixed paragraphs)
    # are left for Stage 2 (paragraph attribution gate) to judge with full context.
    submission_markers = [
        "learned counsel submitted", "learned senior counsel submitted",
        "learned senior counsel for", "learned counsel for",
        "it was contended", "it was further contended", "it was submitted",
        "it was further submitted", "it was urged", "it was argued",
        "the petitioner submitted", "the petitioner urged", "the petitioner argued",
        "the petitioner contended", "the appellant submitted", "the appellant urged",
        "the appellant argued", "the appellant contended",
        "the respondent submitted", "the respondent urged", "the respondent argued",
        "the respondent contended", "amicus submitted", "the amicus submitted",
        "learned amicus submitted", "asg submitted", "the asg submitted",
        "learned asg submitted", "the additional solicitor general submitted",
        "the solicitor general submitted",
        "learned counsel apprised", "learned senior counsel apprised",
        "learned counsel further submitted", "learned senior counsel further submitted",
    ]
    if any(m in text_full for m in submission_markers):
        return "submission"

    if any(k in combined for k in ["conclusion", "final", "order", "result"]):
        return "conclusion"
    if any(k in combined for k in ["analysis", "held", "holding", "view", "reasoning"]):
        return "analysis_of_law"
    if any(k in combined for k in ["discourse", "discussion"]):
        return "courts_discourse"
    if any(k in text_short for k in ["we hold", "held that", "it is held", "we are of the view",
                                 "in our opinion", "we conclude", "ratio", "therefore"]):
        return "analysis_of_law"
    if any(k in text_short for k in ["accordingly", "appeal is dismissed", "appeal is allowed",
                                 "writ petition", "order accordingly"]):
        return "conclusion"
    return "general"


def _extract_citation(title: str) -> str:
    for pat in [r'\(\d{4}\)\s+\d+\s+SCC\s+\d+', r'AIR\s+\d{4}\s+SC\s+\d+']:
        m = re.search(pat, title)
        if m: return m.group(0)
    return ""


# ── LLM ───────────────────────────────────────────────────────────────────────

async def llm(model: str, prompt: str) -> str:
    if not model:
        raise RuntimeError("No model configured — check .env")
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {OR_KEY}",
                     "Content-Type": "application/json",
                     "HTTP-Referer": "https://karyaniti.in",
                     "X-Title": "Karyaniti"},
            json={"model": model, "messages": [{"role": "user", "content": prompt}],
                  "temperature": 0.0, "max_tokens": 2500})
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def pj(raw, key=""):
    if not raw: return [] if key else {}
    try:
        c = re.sub(r"```json\s*|```\s*", "", raw).strip()
        s, e = c.find("{"), c.rfind("}") + 1
        if s < 0: return [] if key else {}
        obj = json.loads(c[s:e])
        return obj.get(key, []) if key else obj
    except: return [] if key else {}


def l1(anchor, para):
    if not anchor or not para: return False
    a = re.sub(r"\s+", " ", anchor.lower().strip())
    p = re.sub(r"\s+", " ", para.lower())
    if a in p: return True
    aw, pw = set(a.split()), set(p.split())
    return len(aw & pw) / max(len(aw), 1) >= 0.72

def l3(para):
    neg = ["we do not agree", "we are unable to agree", "we overrule",
           "stands overruled", "per incuriam", "we doubt", "cannot be accepted",
           "we reject", "is not the law"]
    return not any(n in para.lower() for n in neg)

def l4(prop, para):
    stops = {"the","a","an","is","are","was","of","in","to","for","on","by","that","this","it","as","with","or","not","and"}
    atoms = re.split(r"\band\b|\balso\b|\bfurther\b|\bmoreover\b", prop, flags=re.I)
    atoms = [s.strip() for s in atoms if len(s.strip()) > 15]
    if len(atoms) <= 1: return True, []
    pw = set(re.sub(r"[^\w\s]","",para.lower()).split()) - stops
    failed = []
    for atom in atoms:
        aw = set(re.sub(r"[^\w\s]","",atom.lower()).split()) - stops
        aw = {w for w in aw if len(w) > 2}
        if aw and len(aw & pw) / len(aw) < 0.5: failed.append(atom[:50])
    return (len(failed) == 0), failed


def topical_overlap(query: str, text: str) -> float:
    """Cheap word-overlap score between query and text. 0.0-1.0."""
    stops = {"the","a","an","is","are","was","of","in","to","for","on","by","that",
             "this","it","as","with","or","not","and","what","when","where","under",
             "from","be","been","do","does","how","why","which","who"}
    q_words = set(re.sub(r"[^\w\s]"," ",query.lower()).split()) - stops
    q_words = {w for w in q_words if len(w) > 2}
    t_words = set(re.sub(r"[^\w\s]"," ",text.lower()).split()) - stops
    if not q_words: return 0.0
    return len(q_words & t_words) / len(q_words)

    # ── Title-field boost for named-case search variants ─────────────────────────
_LEGAL_STARTERS = {
    "Section", "Article", "Under", "Whether", "When", "What",
    "How", "Where", "Which", "Can", "Is", "Are", "Does",
}

def _title_boost(variant: str) -> str:
    """
    If a search variant begins with a proper-noun case name (variants 2-3 from
    expand_query), rewrite as:  title:CaseName <doctrinal keywords>

    This pins the IK BM25 title index to the named case while the remaining
    doctrinal terms do full-text body matching.

    Safe to apply to all variants: variants starting with "Section" / digit
    are skipped by the LEGAL_STARTERS guard and returned unchanged.
    """
    parts = variant.split()
    if not parts:
        return variant

    name_tokens = []
    for tok in parts:
        clean = tok.rstrip(".,")
        if clean in _LEGAL_STARTERS or (clean and clean[0].isdigit()):
            break
        if clean and clean[0].isupper() and len(clean) >= 2:
            name_tokens.append(tok)
        else:
            break

    # 1-4 leading capitalized tokens = plausible case name
    if not name_tokens or len(name_tokens) > 4:
        return variant

    title_anchor = name_tokens[0].rstrip(".,")
    doctrinal_rest = " ".join(parts[len(name_tokens):])
    if not doctrinal_rest:
        return variant  # degenerate: entire variant is a name, no doctrinal terms

    boosted = f"title:{title_anchor} {doctrinal_rest}"
    log.info(f"_title_boost: '{variant}' → '{boosted}'")
    return boosted


# ── Query expansion ──────────────────────────────────────────────────────────

async def expand_query(q: str, model: str) -> list[str]:
    user_section = re.search(r'(?:section|sec\.?|s\.?)\s*(\d+(?:\([a-z]\))?)', q, re.I)
    section_lock = ""
    if user_section:
        section_str = f"Section {user_section.group(1)}"
        section_lock = (f"\n\nCRITICAL CONSTRAINT: The user explicitly referenced '{section_str}'. "
                        f"EVERY variant MUST contain '{section_str}' verbatim. "
                        f"DO NOT change it to a different section number. "
                        f"DO NOT substitute related sections. "
                        f"The user knows the exact section they want.")

    prompt = f"""You are a legal research assistant for Indian law. The lawyer's query will be searched on Indian Kanoon (BM25 keyword matching).

LAWYER'S QUERY: "{q}"

Generate 4 search queries. Indian Kanoon uses BM25 — each query should be 3-7 keywords, no full sentences, no quotes.

Variant 1 — DOCTRINAL: Section numbers, act names, legal terms (close to user's wording).
Variant 2 — NAMED CANONICAL CASE: A leading Indian SC/HC case you are CONFIDENT exists on this doctrine, by case name. Format: "[Case shortname] [doctrine keywords]". E.g., "Anvar P.V. Section 65B condition precedent" or "Sibbia Section 438 anticipatory bail".
Variant 3 — NAMED CANONICAL CASE: A different leading case on this doctrine, same format.
Variant 4 — FACTUAL/ALTERNATIVE PHRASING: A reformulation a lawyer might type.

Rules for named cases (variants 2-3):
- Only include case names you are CONFIDENT are real Indian SC/HC judgments on this exact doctrine
- The system independently verifies retrieved cases. Hallucinated names will fail verification and be discarded — but they waste a search slot, so prioritize accuracy over guessing
- Prefer Supreme Court cases over High Court when both exist
- Use the parties' surnames or commonly-cited short form (e.g., "Anvar P.V." not full citation)
- If you cannot confidently name 2 canonical cases for this doctrine, leave variants 2-3 as doctrinal/factual variants instead

If the doctrine has known overruled-but-historically-important cases (e.g., Shafhi Mohammad on 65B), you may include them — the system will flag treatment status separately.{section_lock}

Output ONLY this JSON, no explanation:
{{"queries":["variant1","variant2","variant3","variant4"]}}"""

    try:
        raw = await llm(model, prompt)
        log.info(f"expand_query raw response: {raw[:300]}")

        variants = pj(raw, "queries")
        if isinstance(variants, list) and len(variants) >= 2:
            cleaned = [str(v).strip() for v in variants[:5] if v and len(str(v).strip()) > 3]
            if user_section and cleaned:
                section_digit = user_section.group(1)
                fixed = []
                for v in cleaned:
                    if section_digit not in v:
                        v = f"Section {section_digit} {v}"
                    fixed.append(v)
                cleaned = fixed
            if cleaned:
                return cleaned

        import re as _re
        quoted = _re.findall(r'"([^"]{8,80})"', raw)
        if len(quoted) >= 2:
            cleaned = [q for q in quoted if q.lower() not in ("queries", "variant1", "variant2", "variant3", "variant4")]
            if user_section and cleaned:
                section_digit = user_section.group(1)
                fixed = []
                for v in cleaned:
                    if section_digit not in v:
                        v = f"Section {section_digit} {v}"
                    fixed.append(v)
                cleaned = fixed
            if cleaned:
                return cleaned[:5]

    except Exception as e:
        log.warning(f"Query expansion failed entirely: {e}")

    words = q.lower().replace("?", "").split()
    legal_terms = [w for w in words if len(w) > 3 and w not in {"when", "what", "where", "under", "from", "with", "that", "this", "have", "been"}]
    if len(legal_terms) >= 4:
        return [q, " ".join(legal_terms[:5]), " ".join(legal_terms[-5:])]
    return [q]


# ── Statute-anchored retrieval ────────────────────────────────────────────────

def detect_statute_query(q: str) -> tuple:
    sec_match = re.search(r'(?:section|sec\.?|s\.?)\s*(\d+(?:\([a-z]\))?)', q, re.I)
    if not sec_match:
        return None, None
    section_num = sec_match.group(1)

    act_patterns = [
        r'(?:partnership\s+act|indian\s+partnership)',
        r'(?:contract\s+act|indian\s+contract)',
        r'(?:evidence\s+act|indian\s+evidence)',
        r'(?:penal\s+code|ipc)',
        r'(?:crpc|criminal\s+procedure)',
        r'(?:cpc|civil\s+procedure)',
        r'(?:companies\s+act)',
        r'(?:income[\s-]tax\s+act)',
        r'(?:transfer\s+of\s+property)',
        r'(?:specific\s+relief)',
        r'(?:limitation\s+act)',
        r'(?:constitution|article)',
    ]
    for pat in act_patterns:
        m = re.search(pat, q, re.I)
        if m:
            return section_num, m.group(0)

    bare_acts = {
        "partnership": "partnership act",
        "contract": "contract act",
        "evidence": "evidence act",
        "penal": "penal code",
    }
    for word, full in bare_acts.items():
        if word in q.lower():
            return section_num, full

    return section_num, None


async def fetch_statute_citing_cases(section: str, act_kw, top_k: int = 15) -> list:
    if not section:
        return []

    statute_query = f"Section {section}"
    if act_kw:
        statute_query += f" {act_kw}"

    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(f"{IK_BASE}/search/",
                headers={"Authorization": f"Token {IK_TOKEN}"},
                data={"formInput": statute_query, "pagenum": 0, "doctypes": "laws"})
        if r.status_code != 200:
            log.warning(f"Statute search HTTP {r.status_code}")
            return []
        statute_results = r.json().get("docs", [])
    except Exception as e:
        log.warning(f"Statute search failed: {e}")
        return []

    log.info(f"STATUTE SEARCH: query='{statute_query}' results={len(statute_results)}")

    if not statute_results:
        return []

    statute_doc_id = str(statute_results[0].get("tid", ""))
    statute_title = statute_results[0].get("title", "?")
    if not statute_doc_id:
        return []

    log.info(f"STATUTE TOP HIT: id={statute_doc_id} title={statute_title[:80]}")

    try:
        statute_data = await ik_docmeta(statute_doc_id)
        log.info(f"STATUTE DOCMETA KEYS: {list(statute_data.keys())}")
    except Exception as e:
        log.warning(f"Statute docmeta fetch failed: {e}")
        statute_data = {}

    citing = (statute_data.get("citedbyList") or
              statute_data.get("citedbylist") or
              statute_data.get("cited_by") or
              statute_data.get("citedby") or [])

    log.info(f"STATUTE CITEDBY count (from docmeta): {len(citing)}")

    if not citing:
        try:
            log.info("Falling back to full /doc/ for citedby list")
            full = await ik_doc(statute_doc_id, maxcitedby=top_k)
            log.info(f"STATUTE FULL DOC KEYS: {list(full.keys())}")
            citing = (full.get("citedbyList") or
                      full.get("citedbylist") or
                      full.get("cited_by") or
                      full.get("citedby") or [])
            log.info(f"STATUTE CITEDBY (from /doc/) count: {len(citing)}")
        except Exception as e:
            log.warning(f"Fallback /doc/ fetch failed: {e}")

    candidates = []
    for c in citing[:top_k]:
        candidates.append({
            "tid": c.get("tid", ""),
            "title": c.get("title", "Unknown"),
            "headline": c.get("headline", ""),
            "docsource": c.get("docsource", ""),
            "_source": "statute_citedby",
        })
    return candidates


async def cohere_rerank(query: str, candidates: list, top_k: int = 8, model: str = "cohere/rerank-v3.5") -> list:
    """
    Cohere rerank via OpenRouter's /rerank endpoint.
    Cross-encoder built for relevance ranking — better and cheaper than LLM rerank.
    Uses OR_KEY. Returns [] on failure so caller falls back to LLM rerank.
    """
    if not OR_KEY or not candidates:
        return []

    docs = []
    for c in candidates:
        title = re.sub(r"<[^>]+>", "", c.get("title", "")).strip()
        headline = re.sub(r"<[^>]+>", "", c.get("headline", "") or "").strip()[:300]
        src_tag = " [STATUTE-CITED]" if c.get("_source") == "statute_citedby" else ""
        docs.append(f"{title}{src_tag}\n{headline}")

    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(
                "https://openrouter.ai/api/v1/rerank",
                headers={"Authorization": f"Bearer {OR_KEY}",
                         "Content-Type": "application/json"},
                json={
                    "model": model,
                    "query": query,
                    "documents": docs,
                    "top_n": min(top_k, len(docs)),
                })
        if r.status_code != 200:
            log.warning(f"Rerank HTTP {r.status_code}: {r.text[:200]}")
            return []
        result = r.json()
        log.info(f"COHERE RERANK ({model}): {len(result.get('results', []))} results")

        ranked = []
        sc_boosted = 0
        for item in result.get("results", []):
            idx = item.get("index")
            score = item.get("relevance_score", 0)
            if isinstance(idx, int) and 0 <= idx < len(candidates):
                cand = dict(candidates[idx])
                # ── SC authority boost ───────────────────────────────────────
                # Landmark SC precedents tend to lose to longer-titled HC cases
                # in BM25+Cohere because their titles are short (surname vs
                # surname format). A modest post-hoc multiplier corrects this
                # without overriding Cohere's semantic judgment.
                # Check both docsource AND title — IK candidates sometimes
                # have empty docsource but "Supreme Court" appears in title.
                docsource = (cand.get("docsource", "") or "").lower()
                title = re.sub(r"<[^>]+>", "", cand.get("title", "")).lower()
                is_sc = ("supreme court" in docsource) or ("supremecourt" in docsource) or (
                    "supreme court of india" in title)
                if is_sc:
                    score = score * 2.5
                    sc_boosted += 1
                # High Court is the second tier — give a modest boost too,
                # so HC outranks District/Tribunal but doesn't beat SC.
                elif "high court" in docsource or "high court" in title:
                    score = score * 1.3
                
                cand["_rerank_score"] = score
                ranked.append(cand)

        # Re-sort by modified score (SC boost may have changed order)
        ranked.sort(key=lambda x: x["_rerank_score"], reverse=True)
        if sc_boosted:
            log.info(f"SC boost applied to {sc_boosted} candidates")
        return ranked[:top_k]
    except Exception as e:
        log.warning(f"Cohere rerank failed: {e}")
        return []


# ── LLM rerank ───────────────────────────────────────────────────────────────

async def llm_rerank(query: str, candidates: list, model: str, top_k: int = 8) -> list:
    if not candidates:
        return []
    cand_lines = []
    for i, c in enumerate(candidates):
        title = re.sub(r"<[^>]+>", "", c.get("title", "")).strip()
        headline = re.sub(r"<[^>]+>", "", c.get("headline", "") or "").strip()[:200]
        src_tag = " [STATUTE-CITED]" if c.get("_source") == "statute_citedby" else ""
        cand_lines.append(f"{i}.{src_tag} {title}\n   {headline}")
    cand_text = "\n\n".join(cand_lines)
    prompt = f"""You are a legal research assistant. A lawyer asked this question:
"{query}"

Below are {len(candidates)} candidate Indian court judgments retrieved by keyword search and statute citation graph.
Cases tagged [STATUTE-CITED] cite the relevant statute directly — usually highly relevant.
Many BM25 results will be IRRELEVANT (wrong area of law, wrong context).
Your job: identify the indices of the {top_k} MOST RELEVANT candidates to the lawyer's actual legal question.

Candidates:
{cand_text}

Be ruthless. EXCLUDE candidates that are:
- State tax acts (GST, VAT, sales tax) when query is not about tax
- Court fee schedules / High Court Rules when query is about substantive law
- Co-operative society regulations when query is about partnership
- Mining or environmental rules when query is unrelated
- Criminal procedure when query is civil (and vice versa)

A title that merely contains keywords from the query is NOT relevant if the underlying area of law is different.

Prefer [STATUTE-CITED] cases when relevant.
Return ONLY JSON with the indices ranked by relevance:
{{"top_indices": [3, 7, 1, ...]}}"""
    try:
        raw = await llm(model, prompt)
        obj = pj(raw)
        indices = obj.get("top_indices", []) if obj else []
        if isinstance(indices, list) and indices:
            seen = set()
            ranked = []
            for idx in indices:
                try:
                    i = int(idx)
                    if 0 <= i < len(candidates) and i not in seen:
                        seen.add(i)
                        ranked.append(candidates[i])
                except (ValueError, TypeError):
                    continue
            if ranked:
                return ranked[:top_k]
    except Exception as e:
        log.warning(f"LLM rerank failed: {e}")
    return candidates[:top_k]


# ── Council prompts ──────────────────────────────────────────────────────────

NEG_TOKENS = re.compile(
    r"\b(no|not|cannot|can't|cannot be|never|neither|nor|without|"
    r"shall not|may not|must not|need not|does not|do not|did not|"
    r"is not|are not|was not|were not|none|nothing|nowhere)\b",
    re.IGNORECASE
)

def polarity_mismatch(anchor: str, prop: str) -> bool:
    """Cheap pre-check: does anchor have negation tokens that the proposition lacks
    (or vice versa)? Returns True if polarities likely don't match.
    Heuristic only — the LLM faithfulness_check is the authoritative gate."""
    a_neg = len(NEG_TOKENS.findall(anchor or ""))
    p_neg = len(NEG_TOKENS.findall(prop or ""))
    return (a_neg > 0) != (p_neg > 0)


def p_faithful(anchor: str, prop: str, paragraph_context: str = "") -> str:
    """Strict faithfulness gate. Sees the anchor, proposition, and optionally
    the surrounding paragraph context (for attribution disambiguation).
    Checks 5 axes: subject, qualifiers, modals, polarity, additions.
    Default to DRIFTED when uncertain — false DRIFTED loses one citation;
    false FAITHFUL costs the lawyer's reputation.

    paragraph_context is used ONLY to verify whether an attribution clause
    in the proposition is grounded in the source paragraph. It is NOT a
    source for substantive content."""
    ctx_block = ""
    if paragraph_context:
        ctx_block = f"""

PARAGRAPH CONTEXT (the source paragraph the anchor was extracted from):
"{paragraph_context[:1200]}"

The paragraph context is provided ONLY for attribution-clause verification
(see "ATTRIBUTION-WRAPPED PROPOSITIONS" below). It is NOT a substitute for
the anchor. All substantive content in the proposition must still be in
the anchor — content present in the paragraph but absent from the anchor
CANNOT be used to justify a FAITHFUL verdict on substantive matter."""
    return f"""You are a strict legal citation faithfulness checker for an Indian legal
research tool. A lawyer will cite this proposition to this anchor in a court
brief. If opposing counsel could attack the citation, the proposition is
unfaithful — regardless of whether it is "broadly correct" or "a defensible
inference".

You check ONLY whether the proposition is SUPPORTED BY THE SPECIFIC WORDS of
the anchor. Not by general law. Not by what the court "really meant". Not by
what other lawyers would agree to. Only by the anchor's specific words.

VERBATIM ANCHOR: "{anchor}"

PROPOSITION: "{prop}"{ctx_block}

The anchor is your only source for SUBSTANTIVE CONTENT.

Check each axis. The proposition must pass ALL.

AXIS 1 — Subject preservation
The legal subject named in the anchor must appear in the proposition with the
same scope. Specific-to-general abstraction is DRIFT, even if the general claim
follows logically.

- "AWHO Society performing public function" cannot become "private body".
- "Society registered under Societies Registration Act" cannot become
  "any entity".
- "ICRISAT" cannot become "research institutions".

EXCEPTION — established legal-terminology synonyms within the same doctrine
are allowed:
- "public function" ↔ "public duty" (Article 226)
- "amenable to writ jurisdiction" ↔ "maintainable under Article 226"
- "discharging" ↔ "performing" (when modifying public function/duty)

When in doubt whether two terms are synonyms or different categories, treat as
different categories and flag DRIFTED.

AXIS 2 — Qualifier preservation
Every qualifying word, clause, and condition in the anchor must appear in the
proposition. Silent dropping of qualifiers is the most common drift.

- Conditional clauses ("if", "provided", "only when", "subject to", "where",
  "so long as") must be preserved with their full content.
- Qualifying adjectives (primary, substantial, exclusive, sole, mere,
  voluntary, statutory, purely, otherwise) must NOT be silently dropped.
  Examples:
  • "primary function of the State" cannot become "function of the State"
  • "substantial State funding" cannot become "State funding"
  • "purely private body" cannot become "private body"
  • "mere discharge of public function" cannot become "discharge of public function"
- Scope qualifiers ("section thereof", "in some cases", "generally",
  "ordinarily") must be preserved.

AXIS 3 — Modal preservation
Modal verbs and strength markers encode the binding force of the holding.
They cannot shift.

- "May" cannot become "must"/"shall"/"will".
- "Can" cannot become "is"/"must be".
- "Generally" cannot become "always" or unconditional.
- "Condition precedent" is STRONGER than "mandatory"/"required" — these are
  not synonymous in legal usage. Do not substitute.
- "In some cases" cannot become unconditional.
- "Apparent on the face of record" cannot become "established" — these are
  different evidentiary standards.

AXIS 4 — Polarity preservation
Negation cannot flip. If the anchor says X is NOT Y, the proposition cannot
say X IS Y (or vice versa). The contrapositive form is acceptable
("if not P, then not Q" can become "only if P, then Q") but the polarity of
the underlying legal claim must match.

AXIS 5 — No additions that change legal scope or force

The proposition must not introduce phrases, qualifiers, rationales, or 
claims that change what the rule MEANS or to whom/when it applies.

DRIFT (flag as DRIFTED):
- Adding "regardless of its private character" when the anchor doesn't 
  say "regardless" — adds an unconditional sweep.
- Adding "and analogous bodies" when the anchor names only specific bodies 
  — widens scope.
- Adding "in all cases" or "at all times" — strengthens to unconditional.
- Adding "only" / "exclusively" / "always" / "never" when not in anchor 
  — adds a restrictor or absolute.
- Adding a different statutory section than the one the anchor discusses 
  (e.g., anchor cites Section 16, proposition adds Section 11) — links the 
  rule to a different provision.
- Adding rationale ("because X") or a justification not stated in anchor.
- Adding case names, doctrines, or qualifiers that NARROW or WIDEN the 
  rule beyond what the anchor establishes.

NOT DRIFT (acceptable disambiguation — keep as FAITHFUL):
- Specifying the statute when the anchor's section number is implicit 
  from being the subject of the entire judgment (e.g., anchor says 
  "Section 11" and proposition writes "Section 11 of the Arbitration 
  and Conciliation Act" — the case IS a Section 11 ACA case).
- Naming a doctrine the entire judgment is about (e.g., anchor about 
  "readiness" → proposition writes "readiness and willingness doctrine").
- Naming the subject the entire judgment is about (e.g., the judgment 
  is on specific performance, anchor says "the plaintiff's entitlement", 
  proposition writes "entitlement to specific performance").
- Spelling out an abbreviation or pronoun whose referent is unambiguous 
  in the paragraph ("the amount" → "the balance sale consideration" 
  when prior anchor sentence established this).

TEST: ask "does the addition change WHAT the rule does, WHEN it applies, 
or TO WHOM it applies?" If yes → DRIFTED. If the addition only names 
something already implicit and unambiguous in the source → FAITHFUL.

VERDICTS:

FAITHFUL — passes ALL FIVE axes. A clean restatement in the same scope, all
qualifiers preserved, modals preserved, polarity preserved, no additions.

DRIFTED — fails one or more of axes 1, 2, 3, 5. The proposition widens,
strengthens, drops qualifiers, or adds claims beyond the anchor.

INVERTED — fails axis 4. Polarity flipped.

DEFAULT BEHAVIOUR:
- Uncertain between FAITHFUL and DRIFTED → DRIFTED.
- Uncertain between DRIFTED and INVERTED → INVERTED (polarity flips are worse
  than scope drift).
- A false DRIFTED costs the system one good holding.
- A false FAITHFUL costs the lawyer their reputation.
- Strictness is correct.

═══════════════════════════════════════════════════════════════════════
ATTRIBUTION-WRAPPED PROPOSITIONS — SPECIAL HANDLING
═══════════════════════════════════════════════════════════════════════

The extractor (per its own instructions) attributes quoted-authority holdings
by writing the proposition as: "In [Earlier Case], it was held that [rule]..."
or "The Supreme Court in [Earlier Case] held that [rule]..."

When the proposition contains such an attribution clause naming an earlier
case, you must verify whether that attribution is GROUNDED in the source.
There are two cases:

CASE A — Attribution is grounded in the paragraph context:
The PARAGRAPH CONTEXT (if provided) contains the same case name being
attributed in the proposition (e.g. proposition says "In Hope Plantations
Ltd. v Taluk Land Board, it was held..." AND the paragraph context shows
"In Hope Plantations Ltd. v Taluk Land Board, Peermade and another [3], it
was held that...").

  → The attribution is structural. Apply Axes 1–5 to the SUBSTANTIVE CONTENT
    that follows the attribution wrapper in the proposition, comparing
    against the substantive content of the anchor (which is the quoted
    holding itself, typically without the wrapper).

  → Acceptable simplifications of the case name (NOT flagged as DRIFTED):
    • Drop reporter footnote markers: "[3]", "(N)" at end of name.
    • Drop generic suffixes: "& Ors", "and others", "and another", "Etc.",
      "(Dead) by LRs", "(Through LRs)", second-respondent place names like
      "Peermade and another".
    • Drop year/citation suffixes.
    Preserve all substantive party names (first appellant + first respondent).

CASE B — Attribution is NOT grounded:
Proposition names a case in its attribution clause, but that case does not
appear in the paragraph context (or no context was provided and the anchor
itself lacks any attribution).

  → DRIFTED. Proposition is claiming the rule belongs to a case the source
    doesn't connect it to. This is an addition that changes the legal
    authority — a lawyer citing this would be exposed in court.

CASE C — Wrong case attributed:
Proposition's attribution clause names case A, but the paragraph context
clearly attributes the quote to case B (different substantive parties).

  → INVERTED. Wrong authority is a polarity-class error.

CRITICAL: the carve-out for Case A only applies to the ATTRIBUTION WRAPPER
("In X v Y, it was held that..."). The substantive rule that follows the
wrapper must STILL pass Axes 1–5 against the anchor. If the proposition
adds, widens, drops qualifiers, or shifts modals in the substantive part,
still flag DRIFTED.

Return ONLY JSON:
{{"verdict":"FAITHFUL|DRIFTED|INVERTED","reason":"≤20 words, name the failed axis if not FAITHFUL"}}"""


async def faithfulness_check(anchor: str, prop: str, model: str,
                              paragraph_context: str = "") -> dict:
    """Run the faithfulness gate. Returns dict with verdict and reason.
    Defaults to DRIFTED on any error — conservative failure.

    paragraph_context (optional): the source paragraph the anchor was
    extracted from. Used by the gate to verify whether attribution clauses
    in the proposition are grounded in the source."""
    if not anchor or not prop:
        return {"verdict": "DRIFTED", "reason": "empty anchor or proposition"}
    try:
        raw = await llm(model, p_faithful(anchor, prop, paragraph_context))
        out = pj(raw)
        verdict = out.get("verdict", "DRIFTED")
        if verdict not in ("FAITHFUL", "DRIFTED", "INVERTED"):
            verdict = "DRIFTED"
        return {"verdict": verdict, "reason": out.get("reason", "")[:80]}
    except Exception as e:
        log.warning(f"Faithfulness check failed: {e}")
        return {"verdict": "DRIFTED", "reason": f"check error: {str(e)[:40]}"}


# ── Attribution gates (Stage 2 + Stage 4) ─────────────────────────────────────

def p_attribution_para(para_text: str, section_header: str) -> str:
    """Stage 2 prompt: paragraph-level attribution check."""
    sec_line = f'\nSECTION CONTEXT (header of the section this paragraph sits under):\n"{section_header}"' \
               if section_header else ""
    return f"""You are a strict attribution checker for an Indian legal research tool.
Determine whether this paragraph is the PRESENT COURT'S OWN VOICE, or whether it is
recording SOMEONE ELSE'S WORDS (counsel, party, earlier case, statute, foreign law).

A lawyer who cites counsel's submission as the court's holding will be destroyed
in court. Default to ATTRIBUTED_TO_OTHER or AMBIGUOUS when uncertain.{sec_line}

PARAGRAPH:
{para_text[:1500]}

VERDICTS:

COURT_VOICE — paragraph is the present court's own reasoning, holding, or observation.
Signs: "we hold", "we are of the view", "in our opinion", "we find", "it is held",
"this Court holds", "we therefore conclude". Section context names "Discussion",
"Analysis", "Held", "Reasoning", "Conclusion", or is absent.

ATTRIBUTED_TO_OTHER — paragraph records someone else's words. Signs:
• "learned counsel submitted", "it was contended", "[Name] submitted",
  "the petitioner urged", "the appellant argued", "the respondent contended",
  "amicus submitted", "it was further submitted".
• Section context names "Submissions", "Arguments", "Contentions", or names a
  specific counsel — even if the sub-paragraph itself sounds like legal reasoning.
• Sub-paragraph markers (i., ii., iii.) under a Submissions/Arguments section.
• Paragraph quotes an earlier case at length: "In [Case] this Court held...",
  "The Constitution Bench in [Case] held...". Rule belongs to the earlier case.
• Paragraph reproduces statutory text or foreign/international law.

AMBIGUOUS — cannot determine with confidence.

RULES:
1. Section context showing submission/argument → ATTRIBUTED_TO_OTHER for ALL
   sub-paragraphs, even those that sound like court reasoning.
2. "Therefore", "Thus", "Hence" do NOT establish court voice.
3. AMBIGUOUS counts the same as ATTRIBUTED_TO_OTHER — default to exclusion.

Return ONLY JSON:
{{"verdict":"COURT_VOICE|ATTRIBUTED_TO_OTHER|AMBIGUOUS","reason":"≤20 words"}}"""


def p_attribution_anchor(para_text: str, section_header: str, anchor: str,
                          proposition: str = "") -> str:
    """Stage 4 prompt: anchor-level attribution check.
    Catches embedded counsel quotations within mostly-court-voice paragraphs.
    Recognises CORRECTLY-ATTRIBUTED QUOTED AUTHORITY as a separate pass-verdict:
    when the present court quotes an earlier case AND the proposition explicitly
    attributes the rule to that earlier case, this is a valid citation pattern."""
    sec_line = f'\nSECTION CONTEXT: "{section_header}"' if section_header else ""
    prop_line = f'\n\nPROPOSED HOLDING (what the lawyer would cite, with its attribution):\n"{proposition}"' \
                 if proposition else ""
    return f"""You are a strict attribution checker for an Indian legal research tool.
A lawyer will cite this ANCHOR for the PROPOSED HOLDING above.
Determine the relationship between the anchor, the proposition, and the originating voice.

The paragraph may be mostly court voice but contain an embedded quotation from counsel
or an earlier case. The anchor may fall exactly in that embedded quotation.{sec_line}

FULL PARAGRAPH:
{para_text[:1500]}

EXTRACTED ANCHOR (the specific phrase to be cited):
"{anchor}"{prop_line}

VERDICTS:

COURT_VOICE — the anchor is the present court's own words in its own reasoning.
The lawyer cites this paragraph as authored by the present court.

QUOTED_AUTHORITY_ATTRIBUTED — the anchor is a verbatim quotation from an earlier
named case, AND the proposition correctly attributes the rule to that originating case.
The lawyer cites the ORIGINATING case (the SC/earlier authority), using the present
case as a locator for where to find the quoted text.

Triggers ONLY when ALL THREE conditions hold:
  1. The FULL PARAGRAPH contains an attribution clause naming an earlier case
     (e.g. "In X v Y, it was held that...", "The Supreme Court in X v Y held...",
     "Following X v Y...", "[Case] laid down that...", "The Constitution Bench
     in [Case] held..."), AND the anchor falls within the quoted material that
     follows that clause. Note: the anchor itself may not contain the wrapper —
     the extractor often pulls only the substantive quote. Look at the full
     paragraph to determine whether the anchor sits inside a quoted-authority
     passage.
  2. The proposition BEGINS with an attribution clause naming the SAME earlier case.
     Allow these simplifications of the case name (do NOT flag mismatch):
       • Drop reporter footnote markers: "[3]", "(N)" at end of name.
       • Drop generic suffixes: "& Ors", "and others", "and another", "Etc.",
         "(Dead) by LRs", "(Through LRs)".
       • Drop year/citation suffixes already shown elsewhere.
     Preserve all substantive party names. If the proposition names a different
     case than the anchor (e.g. proposition says "In A v B" but anchor says
     "In X v Y"), this is NOT QUOTED_AUTHORITY_ATTRIBUTED — flag as ATTRIBUTED_TO_OTHER.
  3. The substantive rule that follows the attribution wrapper in the proposition
     is genuinely supported by the substantive rule that follows the wrapper in
     the anchor (same scope, same modals, same polarity).

When verdict is QUOTED_AUTHORITY_ATTRIBUTED, name the originating case in the
reason field in this exact format: "quoted authority: [Case Name]"
(e.g. "quoted authority: Hope Plantations Ltd. v Taluk Land Board").

ATTRIBUTED_TO_OTHER — the anchor is one of:
• A quotation from counsel's submission embedded in the paragraph
  (signs: "learned counsel submitted", named senior counsel speaking).
• A quotation from an earlier case where the proposition does NOT attribute
  the rule to that earlier case (proposition silently restates the rule as if
  the present court originated it — a lawyer citing this would be exposed).
• Statutory text being reproduced.

AMBIGUOUS — cannot determine with confidence.

CRITICAL DISTINCTION between QUOTED_AUTHORITY_ATTRIBUTED and ATTRIBUTED_TO_OTHER:
Both involve a quotation from an earlier case. The difference is whether the
PROPOSITION explicitly names that earlier case. If it does → QUOTED_AUTHORITY_ATTRIBUTED
(pass, lawyer cites the originating case). If it does not → ATTRIBUTED_TO_OTHER
(fail, silent re-attribution risks the lawyer being exposed in court).

DEFAULT: AMBIGUOUS counts as ATTRIBUTED_TO_OTHER — exclusion is safer.

Return ONLY JSON:
{{"verdict":"COURT_VOICE|QUOTED_AUTHORITY_ATTRIBUTED|ATTRIBUTED_TO_OTHER|AMBIGUOUS","reason":"≤30 words, for QUOTED_AUTHORITY_ATTRIBUTED use format 'quoted authority: [Case Name]'"}}"""


async def attribution_check_paragraph(para_text: str, section_header: str, model: str) -> dict:
    """Stage 2: run paragraph attribution gate. Returns verdict dict."""
    try:
        r = await llm(model, p_attribution_para(para_text, section_header))
        obj = pj(r)
        if not isinstance(obj, dict):
            return {"verdict": "AMBIGUOUS", "reason": "parse error"}
        return {"verdict": obj.get("verdict", "AMBIGUOUS"), "reason": obj.get("reason", "")}
    except Exception as e:
        log.warning(f"Para attribution check failed: {e}")
        return {"verdict": "AMBIGUOUS", "reason": f"check error: {str(e)[:40]}"}


async def attribution_check_anchor(para_text: str, section_header: str,
                                   anchor: str, model: str,
                                   proposition: str = "") -> dict:
    """Stage 4: run anchor attribution gate. Returns verdict dict.
    When proposition is provided, the gate can recognise correctly-attributed
    quoted authority (rule explicitly attributed to originating case) and pass
    it with metadata identifying that case in the 'quoted_case' field."""
    try:
        r = await llm(model, p_attribution_anchor(para_text, section_header,
                                                   anchor, proposition))
        obj = pj(r)
        if not isinstance(obj, dict):
            return {"verdict": "AMBIGUOUS", "reason": "parse error", "quoted_case": ""}
        verdict = obj.get("verdict", "AMBIGUOUS")
        if verdict not in ("COURT_VOICE", "QUOTED_AUTHORITY_ATTRIBUTED",
                            "ATTRIBUTED_TO_OTHER", "AMBIGUOUS"):
            verdict = "AMBIGUOUS"
        reason = obj.get("reason", "")
        quoted_case = ""
        if verdict == "QUOTED_AUTHORITY_ATTRIBUTED":
            # Reason format expected: "quoted authority: [Case Name]"
            m = re.search(r"quoted authority:\s*(.+?)(?:$|[\.;]|\s*$)",
                          reason, re.IGNORECASE)
            if m:
                quoted_case = m.group(1).strip().rstrip(".")
            # Defensive: if model returns the verdict but reason is missing the
            # case-name marker, we still pass but with empty quoted_case (synthesis
            # will fall back to native rendering).
        return {"verdict": verdict, "reason": reason[:120],
                "quoted_case": quoted_case}
    except Exception as e:
        log.warning(f"Anchor attribution check failed: {e}")
        return {"verdict": "AMBIGUOUS", "reason": f"check error: {str(e)[:40]}",
                "quoted_case": ""}


def p_extract(q, name, text, court=""):
    """Attribution-aware extractor. Refuses to extract from counsel/party voice paragraphs.
    Sees section_header context per paragraph; uses it together with in-paragraph markers."""
    return f"""You are extracting LEGAL HOLDINGS (ratio decidendi) from an Indian court judgment.


LAWYER'S QUERY: "{q}"
CASE: {name}
COURT: {court or 'Indian Court'}

SOURCE TEXT (paragraphs from the judgment, some carry "[Section context: ...]" hints):
{text}

═══════════════════════════════════════════════════════════════
ATTRIBUTION CHECK — DO THIS BEFORE EXTRACTING ANYTHING
═══════════════════════════════════════════════════════════════

A LAWYER WILL CITE WHAT YOU EXTRACT. If you extract counsel's submission and
present it as the court's holding, the lawyer will be destroyed when opposing
counsel pulls up the original judgment. NEVER do this.

For each paragraph you consider, identify WHO is speaking:

(A) PRESENT COURT in its own voice — its reasoning, holding, observation, or
    conclusion. Signs:
    • Phrases like "we hold", "we are of the view", "it is held that",
      "in our opinion", "we find", "this Court holds", "we therefore
      conclude", "we agree", "we reject", "we are mindful that".
    • Court analyzing the law and arriving at a position in its own voice.
    • [Section context] is empty, or names "Discussion", "Analysis",
      "Held", "Conclusion", "Reasoning", "Order", "Directions", or absent.

(B) COUNSEL or PARTY voice — recording what was argued/contended. NEVER EXTRACT.
    • Phrases like "learned counsel submitted", "Dr./Mr./Ms./Sri/Smt. [Name]
      submitted", "it was contended", "the petitioner urged", "the appellant
      argued", "the respondent contended", "amicus submitted", "ASG submitted",
      "learned senior counsel for [Party] submitted", "it was further submitted".
    • Sub-paragraphs ("i.", "ii.", "iii.", "(a)", "(b)") under a [Section context]
      that mentions "Submissions", "Submitted as under", "Contended", "Arguments",
      "Contentions of [Party]" — even if the sub-paragraph LOOKS like court
      reasoning ("Therefore the Court has jurisdiction..."), the author is
      SUMMARISING what counsel argued. The sub-paragraph is counsel voice.
    • If [Section context] contains "submitted as under", "submitted as follows",
      "submissions of", or names a specific counsel, treat all sub-paragraphs
      as counsel voice unless the paragraph itself unmistakably re-enters
      court voice (with phrases from group A).

(C) EARLIER CASE being quoted by the present court:
    • Phrases like "In [Case Name] this Court held...", "It was 
      observed in [Case]...", "The Constitution Bench in [Case] held".
    • Block quotations from earlier judgments.
    
    EXTRACTION FROM (C): EXTRACT the holding, but the proposition MUST 
    name the originating case (e.g., "In Bhajan Lal, the Supreme Court 
    laid down seven categories for quashing FIRs under Section 482..."). 
    The lawyer cites the present case AS authority for the earlier 
    case's rule. DO NOT silently restate the earlier case's rule as if 
    the present court originated it.

(D) STATUTORY TEXT being reproduced — NEVER EXTRACT as a holding.
    • "Section X reads as follows" followed by block-quoted statute.

(E) FOREIGN or INTERNATIONAL LAW being quoted — NEVER EXTRACT.

EXTRACTION RULE:
- EXTRACT only from category (A).
- EXTRACT from (C) WITH explicit attribution to the originating case.
- DO NOT EXTRACT from (B), (D), (E).
- If a paragraph contains a MIX of court voice and other voice, extract ONLY
  from the court-voice portions, and the verbatim_anchor must be drawn from
  those portions.
- If you cannot confidently determine voice, REFUSE EXTRACTION.

CRITICAL TEST:
Before extracting, ask: "If a lawyer cited this proposition to this paragraph,
and opposing counsel pulled up the full judgment, would opposing counsel be
able to say 'My Lord, this is in fact the submission of counsel for [Party] —
the position the Court expressly rejected'?"
If yes — or if you cannot be sure the answer is no — DO NOT EXTRACT.

═══════════════════════════════════════════════════════════════
WHAT TO EXTRACT (after attribution check passes)
═══════════════════════════════════════════════════════════════

A "holding" is a STATEMENT OF LAW that the court used to decide the case.
Extract ONLY holdings RESPONSIVE to the lawyer's query above.

EXTRACT (positive examples):
- Statements interpreting a statute, section, doctrine, or rule of law
- Tests or principles laid down by the court (e.g., "the test for X is...")
- Court's view on how a legal provision should be applied
- Court explicitly holding/declaring/ruling on a legal question

DO NOT EXTRACT:
- Procedural orders ("the appeal is dismissed", "writ petition allowed")
- Factual findings about THIS case ("the defendant filed on X date")
- Fee schedules, court fees, retention periods, administrative rules
- Pure recitations of statutory text without interpretation
- Tax recovery procedure, attachment orders, certificate issuance — UNLESS
  the query is about tax law

RELEVANCE GATE:
If the document is about a wholly different area of law than the lawyer's
query, return:
{{"holdings": [], "off_topic_reason": "source is about [area] but query is about [area]"}}

VERBATIM ANCHOR:
For each holding, provide a `verbatim_anchor` — an exact phrase copied
WORD-FOR-WORD from the source text. Multi-sentence anchors are encouraged when
the holding spans multiple sentences. The anchor must come from the court-voice
portions only. It will be string-matched; any deviation causes rejection.

═══════════════════════════════════════════════════════════════
ANCHOR-PROPOSITION ALIGNMENT — HIGHEST PRIORITY
═══════════════════════════════════════════════════════════════

Every substantive word in `proposition` MUST appear in `verbatim_anchor`.
The anchor is your ONLY allowed source for proposition content. Do not pull
qualifiers, modals, or context from elsewhere in the paragraph without
including that text in the anchor.

If you want to claim X in the proposition, X must be in the anchor — verbatim.

CORRECT (single-sentence anchor):
  Anchor:      "X is a condition precedent under Section 65B(4)."
  Proposition: "X is a condition precedent under Section 65B(4)." ✓

CORRECT (multi-sentence anchor — preferred when holding spans sentences):
  Anchor:      "X is a condition precedent. It is a mandatory requirement of the law."
  Proposition: "X is a mandatory condition precedent." ✓

WRONG (proposition adds words not in anchor):
  Anchor:      "X is a condition precedent."
  Proposition: "X is a mandatory condition precedent for secondary evidence."
  Why wrong: 'mandatory' and 'secondary evidence' are not in the anchor.
  Fix: either extend the anchor to include those words from elsewhere in the
  paragraph, or drop them from the proposition.

If you cannot say something using only the anchor's words, EXTEND THE ANCHOR.

Be conservative. If unsure whether something is true ratio, do not extract it.

Return ONLY JSON:
{{"holdings":[{{"proposition":"the rule of law expressed in as many sentences as needed to faithfully preserve all qualifiers, conditions, and modifiers from the anchor. Do not compress for brevity. Do not paraphrase to fit a shorter form. If the anchor's qualifiers require three or four sentences to preserve, use three or four sentences.","verbatim_anchor":"exact phrase from source","paragraph_number":1}}]}}


If no holdings pass the attribution check AND are responsive to the query,
return: {{"holdings":[]}}"""


def p_adversary(q, name, text, props): return f"""Defense lawyer. Default NO unless unambiguous.
Query: "{q}" | Case: {name}
Source: {text}
Evaluate: {props}
Return ONLY JSON: {{"verdicts":[{{"holding_index":0,"verdict":"SUPPORTED","evidence_quote":"verbatim","reasoning":"one sentence"}}]}}"""

def p_judge(q, name, pnum, ptext, prop, anchor, d, topical_score):
    """Judge with two-gate model — fidelity + relevance."""
    return f"""You are the FINAL JUDGE. Nothing reaches a lawyer without your PASS.
Be conservative. A wrong PASS damages a lawyer's reputation in court.

LAWYER'S QUERY: "{q}"
CASE: {name}
PARAGRAPH {pnum}:
{ptext[:1200]}

PROPOSED HOLDING: {prop}
VERBATIM ANCHOR: {anchor}

COUNCIL DIAGNOSTICS:
- L1 (anchor in source): {d['l1']}
- L3 (no negation): {d['l3']}
- L4 (atoms grounded): {d['l4ok']}
- Adversary verdict: {d['adv']}
- Faithfulness: {d['faithful']}

DECISION FRAMEWORK — TWO INDEPENDENT GATES, BOTH MUST PASS:

GATE 1 — TEXTUAL FIDELITY:
Is the proposition genuinely supported by the verbatim source paragraph?
- L1=False → automatic FAIL (anchor not in source)
- Adversary says NOT_SUPPORTED or CONTRADICTED → likely FAIL

GATE 2 — RELEVANCE TO LAWYER'S QUERY:
Is this holding ON THE DOCTRINE the lawyer asked about?

The proposition may use legal vocabulary different from the query — that
alone is not a relevance failure. The case name in the query may not appear
in the proposition. Judge by substance: does the rule of law in the
proposition address the doctrine the lawyer is researching?

PASS Gate 2 if:
- The proposition addresses the same doctrine, section, or area of law as
  the query (even if it covers a different aspect of that doctrine).
- A working lawyer researching this query would cite or read this holding
  as part of understanding the doctrine.
- The query names a specific case and the proposition is a substantive
  holding from that case (the proposition need not repeat the query's words).

FAIL Gate 2 if:
- The proposition is about a wholly different area of law:
  • Query: "partner death dissolution" + Holding about court fee schedules → FAIL
  • Query: "Section 42 Partnership Act" + Holding about VAT tax recovery → FAIL
- The proposition is procedural-only with no substantive doctrine content:
  • "the appeal is dismissed with costs" → FAIL
  • "the writ petition is allowed" → FAIL

When in doubt between "same doctrine, different aspect" (PASS) and "different
doctrine entirely" (FAIL), prefer PASS — the lawyer assesses utility, you
filter only out-of-domain content.



Output:
- PASS only if BOTH gates pass
- FAIL if either fails
- reasoning: ≤15 words stating which gate result drove the decision
- verbatim_override: leave EMPTY ("") unless you must substitute a different phrase from the source; the existing verbatim anchor will be used by default

Return ONLY JSON:
{{"verdict":"PASS","confidence":0.0,"reasoning":"≤15 words","verbatim_override":"","gate_failed":"none|fidelity|relevance"}}"""


def p_synth(q, holdings, warning_block=""):
    def _fmt_auth(i, h):
        lines = [
            f"AUTHORITY {i+1}:",
            f"  Case: {h['case_name']}",
            f"  Citation: {h['citation'] or 'NO CITATION AVAILABLE'}",
            f"  Paragraph: {h['para_num']}",
            f"  Court: {h['court']}",
        ]
        if h.get("quoted_case"):
            lines.append(f"  Originating authority (quoted in this paragraph): {h['quoted_case']}")
        lines.append(f"  Exact verified language: \"{h['verbatim']}\"")
        lines.append(f"  Source: {h['ik_url']}")
        return "\n".join(lines)

    items = "\n\n".join(_fmt_auth(i, h) for i, h in enumerate(holdings))

    warning_section = f"\n{warning_block}\n" if warning_block else ""
    return f"""Research note for an Indian lawyer. Query: "{q}"
{warning_section}
VERIFIED AUTHORITIES (only these are real, only these are sourced from the corpus):
{items}

STRICT RULES — VIOLATING ANY OF THESE = SEVERE FAILURE:

1. DO NOT state any rule of law that is not directly contained in the verbatim verified language above.
2. DO NOT add doctrinal explanations from your training data — even if you "know" what the law is.
3. DO NOT reference case names, sections, or statutes that are not in the verified authorities above.
4. DO NOT use phrases like "ipso facto", "the firm continues unless", "Section X provides" UNLESS those exact phrases appear in the verified verbatim language above.
5. If the verified holdings do not actually answer the lawyer's question, SAY SO EXPLICITLY: "The retrieved authorities do not directly address [the question]. Try a more specific query."
6. NEVER invent or guess a citation. If a verified authority shows "NO CITATION AVAILABLE", report it as such — do not fill in question marks or guess at SCC citations.

ATTRIBUTION HANDLING (quoted authority):

Some verified holdings have an "Originating authority (quoted in this paragraph): [Case]" field. When this field is present, the rule was transmitted by the present case from an earlier case. In the research note:

• Cite such a holding as: "Per [Originating Case], as quoted in [Present Case] Para [N]: [verbatim or close paraphrase from the verified language]."
• Treat the originating case as the primary authority. The present case is the locator (where the quote lives, useful for verification).
• Do NOT silently re-attribute the rule to the present case when an originating case is named — the lawyer needs to know which court actually laid down the rule.

EXCERPT vs DOCTRINE — when an originating case is named, the quoted paragraph is an EXCERPT from that earlier judgment, not its complete doctrine. Include a one-line caveat in the gap analysis section: "Holdings cited from a quoted earlier case are excerpts as reproduced in the present judgment. The originating case may contain exceptions, qualifications, or context not shown here — verify against the full original before citation in court."

When no "Originating authority" field is present, the rule is the present court's own. Cite normally: "Per [Present Case] Para [N]: [content]."

Format the output as:

**Question restated:** (one sentence)

**What the verified authorities say:**
(For each verified authority: case name, the exact verbatim phrase, and one sentence describing what the court actually decided in plain language — staying strictly within what the verbatim text supports. Follow the attribution handling rules above.)

**Honest gap analysis:**
(Plain statement of what the verified authorities do NOT cover. If the lawyer asked about partnership dissolution on death and you only have a procedural order from a tax case, SAY THAT. If any holdings are excerpts from quoted earlier cases, include the one-line caveat described above.)

Maximum 280 words. No invented law. No filler."""


class ResearchRequest(BaseModel):
    query: str
    doctypes: str = "supremecourt"
    extractor_model: str = ""
    adversary_model: str = ""
    judge_model: str = ""
    synthesis_model: str = ""
    rerank_model: str = ""


def sse(type: str, **kwargs) -> str:
    return f"data: {json.dumps({'type': type, 'ts': time.time(), **kwargs})}\n\n"


# ── Main pipeline ────────────────────────────────────────────────────────────
# NOTE: Trace messages sent to the browser are intentionally generic.
# Internal architecture detail (model names, stage labels, candidate counts,
# expansion variants, gate names) lives only in `log.info()` for terminal-side
# debugging. Anything yielded via sse() is visible to the user and to anyone
# who can screenshot the trace.

async def pipeline(req: ResearchRequest) -> AsyncGenerator[str, None]:
    if not IK_TOKEN:
        yield sse("error", message="Service unavailable — please contact support."); return
    if not OR_KEY:
        yield sse("error", message="Service unavailable — please contact support."); return

    m_ext = req.extractor_model or M_EXTRACTOR
    m_adv = req.adversary_model or M_ADVERSARY
    m_jdg = req.judge_model     or M_JUDGE
    m_syn = req.synthesis_model or M_SYNTHESIS
    m_rerank = req.rerank_model or M_RERANK or m_ext

    q = req.query.strip()
    t0 = time.time()

    # Public banner — no model names exposed
    yield sse("models", message="Verification council ready")
    log.info(f"Run config — Ext:{m_ext} | Rerank:{m_rerank} | Adv:{m_adv} | Judge:{m_jdg} | Synth:{m_syn}")
    yield sse("thinking", message="Initialising research…")

    section_num, act_kw = detect_statute_query(q)
    statute_pool = []
    if section_num:
        yield sse("thinking", message="Statute identified — locating authorities…")
        log.info(f"Statute detected: Section {section_num} {act_kw or ''}")
        try:
            statute_pool = await fetch_statute_citing_cases(section_num, act_kw, top_k=15)
            if statute_pool:
                yield sse("thinking", message="Authority list retrieved")
                log.info(f"Statute citation graph: {len(statute_pool)} citing cases")
            else:
                yield sse("thinking", message="Proceeding with corpus search…")
        except Exception as e:
            log.warning(f"Statute lookup failed: {e}")

    yield sse("thinking", message="Translating query for the corpus…")
    expanded = await expand_query(q, M_EXPANSION)
    log.info(f"Generated {len(expanded)} variants: {expanded}")
    # Internal expansion variants are NOT surfaced to the trace.

    effective_doctypes = req.doctypes
    if req.doctypes == "supremecourt":
        effective_doctypes = "judgments"
        yield sse("thinking", message="Broadening scope across courts…")

    yield sse("searching", message="Searching corpus…")
    try:
        seen = set()
        raw_pool = []

        for sc in statute_pool:
            tid = str(sc.get("tid", ""))
            if tid and tid not in seen:
                seen.add(tid)
                raw_pool.append(sc)

       # ── Pass 1: resolve authority-named variants FIRST ─────────────────
        # Must run before BM25 search across all variants, otherwise a
        # canonical case returned by another variant's BM25 pre-claims the
        # `seen` slot and the resolver's synthesized entry gets dropped.
        unresolved_variants = []
        for variant in expanded:
            resolved_id = resolve_case_name(variant)
            if resolved_id:
                log.info(f"AUTHORITY RESOLVED: '{variant}' → doc_id {resolved_id}")
                if resolved_id not in seen:
                    seen.add(resolved_id)
                    raw_pool.append({
                        "tid": resolved_id,
                        "title": variant,
                        "headline": "",
                        "docsource": "Supreme Court of India",
                        "_source": "authority_resolved",
                    })
            else:
                unresolved_variants.append(variant)

        # ── Pass 2: BM25 search for remaining variants ─────────────────────
        # Any tid already claimed by Pass 1 is filtered by `seen`.
        for variant in unresolved_variants:
            variant_results = await ik_search(variant, doctypes=effective_doctypes)
            log.info(f"VARIANT '{variant}' → {len(variant_results)} docs")
            for r in variant_results:
                tid = str(r.get("tid", ""))
                if tid and tid not in seen:
                    seen.add(tid)
                    raw_pool.append(r)
    except Exception as e:
        log.error(f"Corpus search failed: {e}")
        yield sse("error", message="Corpus search failed — please try again")
        return

    if not raw_pool:
        yield sse("error", message="No matching authorities found. Try rephrasing.")
        return

    log.info(f"Pooled {len(raw_pool)} unique candidates")
    yield sse("thinking", message="Compiling candidate authorities…")

# Authority-resolved candidates bypass rerank — they're pre-verified canonical
    # cases with synthesized metadata (empty headline) that Cohere has no useful
    # signal to score against. Pin them at the top of results.
    authority_resolved = [c for c in raw_pool if c.get("_source") == "authority_resolved"]
    other_candidates   = [c for c in raw_pool if c.get("_source") != "authority_resolved"]
    log.info(f"Pool split — authority_resolved={len(authority_resolved)} other={len(other_candidates)}")

    if len(other_candidates) > 8:
        rerank_model_to_use = m_rerank if m_rerank.startswith("cohere/rerank") else "cohere/rerank-4-pro"
        yield sse("thinking", message="Ranking by legal relevance…")
        reranked = await cohere_rerank(q, other_candidates, top_k=8, model=rerank_model_to_use)
        if not reranked:
            log.warning(f"Cohere rerank empty — falling back to LLM rerank")
            yield sse("thinking", message="Re-ranking via fallback method…")
            reranked = await llm_rerank(q, other_candidates, m_rerank, top_k=8)
    else:
        reranked = other_candidates

    # Authority-resolved at top, then reranked others fill remaining slots
    results = (authority_resolved + reranked)[:8]
 
    # Treatment-status filter: drop fully overruled cases silently,
    # annotate the rest with their treatment status.
    results, dropped = treatment_status.filter_overruled(results)
    for d in dropped:
        log.warning(f"Dropping overruled case: {d.get('title','?')[:60]} "
                    f"(superseded by {d.get('_overruled_by','?')[:50]})")
    treatment_status.annotate_candidates(results)
 
    yield sse("found", message="Top authorities selected", count=len(results))

    all_holdings = []
    docs_processed = 0

    fragment_query = q

    for res in results[:4]:
        doc_id = str(res.get("tid", ""))
        title  = re.sub(r"<[^>]+>", "", res.get("title", "Unknown")).strip()
        size   = res.get("docsize", 0)
        if not doc_id: continue
        if size and size < 1500 and res.get("_source") != "statute_citedby":
            continue

        yield sse("fetching", message=f"Fetching: {title[:55]}…")

        doc = None

        # Cache check: if we already have this doc parsed, skip both API calls
        # AND the BeautifulSoup parsing. Single SQLite lookup, ~10ms.
        cached = get_cached_doc(doc_id)
        if cached is not None:
            log.info(f"Cache HIT for doc {doc_id} — {cached.get('title','?')[:50]}")
            doc = cached
        else:
            log.info(f"Cache MISS for doc {doc_id} — fetching from IK")

            # Try fragment first
            try:
                frag = await ik_docfragment(doc_id, fragment_query)
                if frag and (frag.get("doc") or frag.get("fragment")):
                    doc = parse_ik_fragment(doc_id, frag, fallback_meta=res)
                    if doc and not doc.get("paragraphs"):
                        doc = None
            except Exception as e:
                log.warning(f"Fragment fetch failed for {doc_id}: {e}")
                doc = None

            # Fall back to full doc fetch if fragment was insufficient
            if doc is None:
                yield sse("fetching", message=f"Fetching full judgment: {title[:45]}…")
                try:
                    raw = await ik_doc(doc_id)
                except Exception as e:
                    log.warning(f"Full fetch failed for {doc_id}: {e}")
                    continue
                if not raw:
                    continue
                doc = parse_ik_doc(doc_id, raw)

            # Cache the parsed result for future queries — only if useful
            if doc and doc.get("paragraphs"):
                cache_doc(doc_id, doc)

        docs_processed += 1
        log.info(f"Doc {doc['title'][:50]} — {len(doc['paragraphs'])} paragraphs, "
                 f"{len([p for p in doc['paragraphs'] if p['type'] in {'analysis_of_law','conclusion','courts_discourse'}])} holding-type, "
                 f"source={'fragment' if doc.get('_from_fragment') else 'full'}")
        yield sse("processing", message=f"Reading: {doc['title'][:55]}…")

        # ── Stage 2: Paragraph attribution gate ──────────────────────────────
        # Parallel check on holding-type paragraphs before extraction.
        # Filters out counsel/party voice paragraphs that slipped past the parser
        # (e.g. IK HTML misclassification). AMBIGUOUS is treated as ATTRIBUTED_TO_OTHER.
        holding_paras_candidates = [
            p for p in doc["paragraphs"]
            if p["type"] in {"analysis_of_law", "conclusion", "courts_discourse"}
        ]
        if holding_paras_candidates:
            s2_tasks = [
                attribution_check_paragraph(
                    p["text"], p.get("section_header", ""), M_ATTRIBUTION
                )
                for p in holding_paras_candidates
            ]
            s2_results = await asyncio.gather(*s2_tasks, return_exceptions=True)
            holding_paras_clean = [
                p for p, r in zip(holding_paras_candidates, s2_results)
                if isinstance(r, dict) and r.get("verdict") == "COURT_VOICE"
            ]
            n_s2_filtered = len(holding_paras_candidates) - len(holding_paras_clean)
            if n_s2_filtered:
                log.info(f"Stage 2: filtered {n_s2_filtered}/{len(holding_paras_candidates)} "
                         f"paragraphs as non-court-voice in {doc['title'][:40]}")
            if holding_paras_clean:
                doc["holding_text"] = "\n\n".join(
                    _format_para_for_extractor(p) for p in holding_paras_clean
                )[:6000]

        try:
            ext_raw = await llm(m_ext, p_extract(q, doc["title"], doc["holding_text"], doc.get("court","")))
            holdings = pj(ext_raw, "holdings") or []
            ext_obj = pj(ext_raw)
            off_topic = ext_obj.get("off_topic_reason") if isinstance(ext_obj, dict) else None
        except Exception as e:
            log.warning(f"Extractor failed: {e}")
            continue

        if off_topic:
            log.info(f"Off-topic skipped: {off_topic}")
            yield sse("no_holdings", message="Authority not on-topic — skipping")
            continue

        if not holdings:
            yield sse("no_holdings", message=f"No verifiable holdings in {doc['title'][:40]}")
            continue
        log.info(f"Extracted {len(holdings)} raw holdings from {doc['title'][:40]}")

        para_map = {p["number"]: p["text"] for p in doc["paragraphs"]}
        para_sec_map = {p["number"]: p.get("section_header", "") for p in doc["paragraphs"]}
        cands = []
        for h in holdings:
            pn = h.get("paragraph_number", 1)
            pt = para_map.get(pn, doc["holding_text"][:500])
            anchor = h.get("verbatim_anchor", "")
            prop = h.get("proposition", "")
            L1 = l1(anchor, pt); L3 = l3(pt); L4ok, L4f = l4(prop, pt)
            topical = topical_overlap(q, prop)
            cands.append({**h, "para_text": pt, "para_num": pn,
                          "section_header": para_sec_map.get(pn, ""),
                          "L1": L1, "L3": L3, "L4ok": L4ok, "L4f": L4f,
                          "topical": topical, "doc": doc,
                          "faithful": "PENDING", "faithful_reason": "",
                          "attribution": "PENDING", "attribution_reason": ""})

        log.info(f"L1 verified: {sum(1 for c in cands if c['L1'])}/{len(cands)}")
        yield sse("l1_done", message="Source text verified")

        # ── Faithfulness gate ────────────────────────────────────────────────
        # Sees ONLY the verbatim anchor, never the full paragraph.
        # Catches polarity flips and scope drift that the judge misses because
        # the judge reads surrounding context that can wrongly justify a drifted claim.
        for c in cands:
            if not c["L1"]:
                c["faithful"] = "SKIPPED"
                c["faithful_reason"] = "L1 failed"
                continue
            polarity_flag = polarity_mismatch(c.get("verbatim_anchor", ""), c["proposition"])
            fc = await faithfulness_check(c.get("verbatim_anchor", ""), c["proposition"], M_FAITHFUL,
                                            paragraph_context=c.get("para_text", ""))
            c["faithful"] = fc["verdict"]
            c["faithful_reason"] = fc["reason"]
            if polarity_flag and fc["verdict"] == "FAITHFUL":
                log.warning(f"Polarity flag SET but faithfulness=FAITHFUL on para {c['para_num']}: "
                            f"anchor='{c.get('verbatim_anchor','')[:60]}' prop='{c['proposition'][:60]}'")
        n_faithful = sum(1 for c in cands if c.get("faithful") == "FAITHFUL")
        n_l1_passed = sum(1 for c in cands if c["L1"])
        log.info(f"Faithfulness verified: {n_faithful}/{n_l1_passed}")

        # ── Stage 4: Anchor attribution gate ─────────────────────────────────
        # Per-anchor parallel check on holdings that passed L1 + faithfulness.
        # Catches embedded counsel quotations inside mostly-court-voice paragraphs.
        s4_indices = [
            i for i, c in enumerate(cands)
            if c["L1"] and c.get("faithful") == "FAITHFUL"
        ]
        if s4_indices:
            s4_tasks = [
                attribution_check_anchor(
                    cands[i]["para_text"], cands[i].get("section_header", ""),
                    cands[i].get("verbatim_anchor", ""), M_ATTRIBUTION,
                    proposition=cands[i].get("proposition", "")
                )
                for i in s4_indices
            ]
            s4_results = await asyncio.gather(*s4_tasks, return_exceptions=True)
            for i, result in zip(s4_indices, s4_results):
                if isinstance(result, dict):
                    cands[i]["attribution"] = result.get("verdict", "AMBIGUOUS")
                    cands[i]["attribution_reason"] = result.get("reason", "")
                    cands[i]["quoted_case"] = result.get("quoted_case", "")
                else:
                    cands[i]["attribution"] = "AMBIGUOUS"
                    cands[i]["attribution_reason"] = "check error"
                    cands[i]["quoted_case"] = ""
            n_s4_failed = sum(
                1 for i in s4_indices
                if cands[i].get("attribution") not in ("COURT_VOICE", "QUOTED_AUTHORITY_ATTRIBUTED")
            )
            n_quoted_pass = sum(
                1 for i in s4_indices
                if cands[i].get("attribution") == "QUOTED_AUTHORITY_ATTRIBUTED"
            )
            if n_s4_failed:
                log.info(f"Stage 4: {n_s4_failed}/{len(s4_indices)} holdings failed anchor attribution")
            if n_quoted_pass:
                log.info(f"Stage 4: {n_quoted_pass}/{len(s4_indices)} holdings passed as quoted authority")

        # ── Adversary — batch call on L1-passing holdings ────────────────────
        str_verified_with_idx = [(i, c) for i, c in enumerate(cands) if c["L1"]]
        adv_verdicts = {}
        if str_verified_with_idx:
            try:
                props = json.dumps([
                    {"index": cand_idx, "proposition": c["proposition"], "paragraph_number": c["para_num"]}
                    for cand_idx, c in str_verified_with_idx
                ])
                adv_raw = await llm(m_adv, p_adversary(q, doc["title"], doc["holding_text"], props))
                for v in pj(adv_raw, "verdicts"):
                    hi = v.get("holding_index")
                    if isinstance(hi, int):
                        adv_verdicts[hi] = v
                log.info(f"Adversary returned {len(adv_verdicts)} verdicts for {len(str_verified_with_idx)} holdings")
                yield sse("adversary_done", message="Cross-validation received")
            except Exception as e:
                log.warning(f"Adversary failed: {e}")

        yield sse("judging", message="Final verification…")
        for i, c in enumerate(cands):
            adv = adv_verdicts.get(i, {"verdict": "missing", "evidence_quote": ""})

            # Short-circuit gates — skip judge LLM call when a hard gate has already failed.
            if not c["L1"]:
                jobj = {
                    "verdict": "FAIL", "confidence": 0.0,
                    "reasoning": "Anchor not found in source paragraph",
                    "verbatim_override": "", "gate_failed": "fidelity",
                }
                log.info(f"Auto-FAIL para {c['para_num']} — L1=False, skipping judge call")
            elif c.get("faithful") in ("DRIFTED", "INVERTED"):
                jobj = {
                    "verdict": "FAIL", "confidence": 0.0,
                    "reasoning": f"Proposition {c['faithful'].lower()}: {c.get('faithful_reason','')}",
                    "verbatim_override": "", "gate_failed": "faithfulness",
                }
                log.info(f"Auto-FAIL para {c['para_num']} — faithfulness={c['faithful']}, skipping judge call")
            elif c.get("attribution") in ("ATTRIBUTED_TO_OTHER", "AMBIGUOUS"):
                jobj = {
                    "verdict": "FAIL", "confidence": 0.0,
                    "reasoning": f"Attribution: {c.get('attribution_reason', 'not court voice')}",
                    "verbatim_override": "", "gate_failed": "attribution",
                }
                log.info(f"Auto-FAIL para {c['para_num']} — attribution={c.get('attribution')}, skipping judge call")
            else:
                if adv.get("verdict") == "missing":
                    log.warning(f"Adversary missed holding for para {c['para_num']}")
                    yield sse("warning", message=f"Cross-validation incomplete for para {c['para_num']}")
                try:
                    j_raw = await llm(m_jdg, p_judge(q, doc["title"], c["para_num"], c["para_text"],
                        c["proposition"], c.get("verbatim_anchor",""),
                        {"l1": c["L1"], "l3": c["L3"], "l4ok": c["L4ok"],
                         "adv": adv.get("verdict","skipped"),
                         "faithful": c.get("faithful","PENDING")},
                        c["topical"]))
                    jobj = pj(j_raw)
                except Exception as e:
                    jobj = {"verdict": "FAIL", "confidence": 0, "reasoning": str(e)[:80], "verbatim_override": "", "gate_failed": "error"}

            passed = jobj.get("verdict") == "PASS"
            yield sse("judge_verdict",
                      message=f"{'✓ Verified' if passed else '✗ Not verified'}: {c['proposition'][:60]}",
                      passed=passed, reasoning=jobj.get("reasoning",""))

            # Use the original anchor unless judge actively supplied a correction
            final_verbatim = jobj.get("verbatim_override", "").strip() or c.get("verbatim_anchor", "")

            all_holdings.append({
                "case_name": doc["title"], "citation": doc["citation"], "court": doc["court"],
                "date": doc["date"], "para_num": c["para_num"], "para_text": c["para_text"],
                "prop": c["proposition"], "verbatim": final_verbatim,
                "pass": passed,
                "judge_conf": float(jobj.get("confidence", 0)), "judge_reason": jobj.get("reasoning",""),
                "gate_failed": jobj.get("gate_failed",""),
                "L1": c["L1"], "L3": c["L3"], "L4ok": c["L4ok"], "L4f": c["L4f"],
                "topical_score": c["topical"],
                "adv_verdict": adv.get("verdict","skipped"),
                "faithful": c.get("faithful","PENDING"),
                "attribution": c.get("attribution","PENDING"),
                "attribution_reason": c.get("attribution_reason",""),
                "quoted_case": c.get("quoted_case",""),
                "ik_url": doc["ik_url"], "ik_doc_id": doc["doc_id"],
                "treatment_status": res.get("treatment_status", "unverified"),
                "treatment_note": res.get("treatment_note", ""),
                "models_used": {"extractor": m_ext, "rerank": m_rerank, "adversary": m_adv, "judge": m_jdg},
            })

    passed_h = [h for h in all_holdings if h["pass"]]
    yield sse("synthesising", message="Compiling research note…")

    note = ""
    if passed_h:
        warning_block = treatment_status.build_synthesis_warning(passed_h)
        try:
            note = await llm(m_syn, p_synth(q, passed_h, warning_block=warning_block))
        except Exception as e:
            note = f"Synthesis failed: {e}"
    else:
        note = "No verifiable authorities for this query.\nTry different keywords or broaden the search."

    elapsed = round(time.time() - t0, 1)
    yield sse("complete",
              message=f"Done · {len(passed_h)}/{len(all_holdings)} verified",
              note=note, holdings=all_holdings,
              stats={"elapsed": elapsed, "passed": len(passed_h),
                     "total": len(all_holdings), "docs": docs_processed})


@app.post("/api/research")
async def research(req: ResearchRequest, request: Request):
    _gate(request)
    return StreamingResponse(pipeline(req), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

@app.get("/api/models")
async def get_models():
    return JSONResponse(await fetch_or_models())

@app.get("/api/health")
async def health():
    return {"ik_token": "set" if IK_TOKEN else "MISSING",
            "or_key": "set" if OR_KEY else "MISSING",
            "extractor": M_EXTRACTOR, "judge": M_JUDGE, "synthesis": M_SYNTHESIS,
            "rerank": M_RERANK or "(falls back to extractor)",
            "faithful": M_FAITHFUL, "attribution": M_ATTRIBUTION}


@app.get("/api/cache-stats")
async def cache_stats_endpoint():
    """Doc cache statistics — total cached, total accesses, estimated INR saved."""
    return cache_stats()


# ── Static file serving for Karyaniti UI ────────────────────────────────────

app.mount("/assets", StaticFiles(directory="assets"), name="assets")
app.mount("/screenshots", StaticFiles(directory="screenshots"), name="screenshots")

@app.get("/", response_class=HTMLResponse)
async def index():
    """Serve the Karyaniti lawyer-facing UI by default."""
    return Path("Karyaniti.html").read_text(encoding="utf-8")

@app.get("/dev", response_class=HTMLResponse)
async def dev_ui():
    """Old dev UI with model selector dropdowns — kept for testing."""
    return Path("index-dev.html").read_text(encoding="utf-8")

# Serve root-level JS/CSS/JSX as files
@app.get("/styles.css")
async def styles_css():
    return FileResponse("styles.css", media_type="text/css")

@app.get("/app.js")
async def app_js():
    return FileResponse("app.js", media_type="application/javascript")

@app.get("/image-slot.js")
async def image_slot_js():
    return FileResponse("image-slot.js", media_type="application/javascript")

@app.get("/tweaks.jsx")
async def tweaks_jsx():
    return FileResponse("tweaks.jsx", media_type="application/javascript")

@app.get("/tweaks-panel.jsx")
async def tweaks_panel_jsx():
    return FileResponse("tweaks-panel.jsx", media_type="application/javascript")

if __name__ == "__main__":
    import uvicorn

    # Initialise the doc cache on startup (creates data/ik_doc_cache.db if missing)
    init_cache()
    _cs = cache_stats()

    print("\n── Karyaniti Local Server ──────────────────────")
    print(f"  IK Token : {'✓ SET' if IK_TOKEN else '✗ MISSING — add to .env'}")
    print(f"  OR Key   : {'✓ SET' if OR_KEY   else '✗ MISSING — add to .env'}")
    print(f"  Extractor: {M_EXTRACTOR or '⚠ NOT SET'}")
    print(f"  Rerank   : {M_RERANK or '(falls back to extractor)'}")
    print(f"  Judge    : {M_JUDGE or '⚠ NOT SET'}")
    print(f"  Faithful : {M_FAITHFUL}")
    print(f"  Attrib   : {M_ATTRIBUTION}")
    print(f"  Cache    : {_cs.get('total_docs_cached', 0)} docs · "
          f"{_cs.get('total_accesses', 0)} total accesses · "
          f"≈₹{_cs.get('hit_savings_estimate_inr', 0)} saved")
    print("  Open     : http://localhost:8765")
    print("────────────────────────────────────────────────\n")
    uvicorn.run("main:app", host="0.0.0.0", port=8765, reload=False)
