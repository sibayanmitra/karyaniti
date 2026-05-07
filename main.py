"""
Vakeel AI — Local Research Server
Run: python main.py
Open: http://localhost:8765

Calls Indian Kanoon API server-side (no CORS issues).
Streams pipeline progress to the browser via SSE.
"""

import os, json, re, asyncio, time, logging
from pathlib import Path
from typing import AsyncGenerator
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
log = logging.getLogger(__name__)

IK_TOKEN   = os.getenv("INDIAN_KANOON_API_TOKEN", "")
OR_KEY     = os.getenv("OPENROUTER_API_KEY", "")
IK_BASE    = "https://api.indiankanoon.org"

# ── Model catalogue ────────────────────────────────────────────────────────────
# Known SOTA models — shown first in their group even if not in live list
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
]

PINNED_PAID = [
    # xAI Grok
    {"id": "x-ai/grok-4.20",                           "label": "Grok 4.20 (xAI)"},
    {"id": "x-ai/grok-4.1-fast",                       "label": "Grok 4.1 Fast (xAI)"},
    {"id": "x-ai/grok-4.20-multi-agent",               "label": "Grok 4.20 Multi-Agent (xAI)"},
    # OpenAI
    {"id": "openai/gpt-5.5",                           "label": "GPT-5.5 (OpenAI)"},
    {"id": "openai/gpt-5.4",                           "label": "GPT-5.4 (OpenAI)"},
    {"id": "openai/gpt-4.1",                           "label": "GPT-4.1 (OpenAI)"},
    {"id": "openai/gpt-4.1-mini",                      "label": "GPT-4.1 Mini (OpenAI)"},
    # Anthropic
    {"id": "anthropic/claude-opus-4.7",                "label": "Claude Opus 4.7 (Anthropic)"},
    {"id": "anthropic/claude-sonnet-4.6",              "label": "Claude Sonnet 4.6 (Anthropic)"},
    {"id": "anthropic/claude-sonnet-4-5",              "label": "Claude Sonnet 4.5 (Anthropic)"},
    # Google
    {"id": "google/gemini-3.1-pro-preview",            "label": "Gemini 3.1 Pro (Google)"},
    {"id": "google/gemini-3-pro-preview",              "label": "Gemini 3 Pro (Google)"},
    {"id": "google/gemini-3-flash-preview",            "label": "Gemini 3 Flash (Google)"},
    {"id": "google/gemini-2.5-flash-lite",             "label": "Gemini 2.5 Flash Lite (Google)"},
    # Moonshot
    {"id": "moonshotai/kimi-k2.6",                     "label": "Kimi K2.6 (Moonshot)"},
    # DeepSeek
    {"id": "deepseek/deepseek-v4-pro",                 "label": "DeepSeek V4 Pro"},
    {"id": "deepseek/deepseek-v4-flash",               "label": "DeepSeek V4 Flash"},
    {"id": "deepseek/deepseek-r1",                     "label": "DeepSeek R1"},
    # Xiaomi
    {"id": "xiaomi/mimodel-ultra",                     "label": "MiMo Ultra (Xiaomi)"},
    # ByteDance Seed
    {"id": "bytedance-seed/seed-2.0-mini",             "label": "Seed 2.0 Mini (ByteDance)"},
    # MiniMax
    {"id": "minimax/minimax-m2.7",                     "label": "MiniMax M2.7"},
    # Z.AI GLM
    {"id": "z-ai/glm-5.1",                             "label": "GLM-5.1 (Z.AI)"},
]

_model_cache: dict | None = None
_model_cache_ts: float = 0

async def fetch_or_models() -> dict:
    """Fetch live model list from OpenRouter, cache for 10 min. Falls back to PINNED."""
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

    # Sort live models: pinned first, then by token usage (popularity)
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
                continue  # will be added from PINNED_PAID with better labels
            cost_str = f"~${prompt_cost*1e6:.2f}/M"
            label = f"{name}  {cost_str}"
            paid_list.append({"id": mid, "label": label})

    # Prepend PINNED_PAID in order
    paid_list = PINNED_PAID + [p for p in paid_list if p["id"] not in pinned_paid_ids]

    # Deduplicate free list preserving order
    seen = set()
    free_dedup = []
    for m in free_list:
        if m["id"] not in seen:
            seen.add(m["id"]); free_dedup.append(m)

    # If live fetch returned nothing, fall back to known good list
    if not free_dedup:
        free_dedup = [{"id": i, "label": i.split("/")[-1].replace(":free","")} for i in PINNED_FREE]

    _model_cache = {"free": free_dedup, "paid": paid_list}
    _model_cache_ts = now
    return _model_cache

# Default model slots — all free. Override via .env or UI
M_EXTRACTOR  = os.getenv("COUNCIL_EXTRACTOR_MODEL",  "nvidia/nemotron-3-super-120b-a12b:free")
M_SKEPTIC    = os.getenv("COUNCIL_SKEPTIC_MODEL",     "tencent/hy3-preview:free")
M_ADVERSARY  = os.getenv("COUNCIL_ADVERSARY_MODEL",   "deepseek/deepseek-chat-v3.1:free")
M_OUTSIDER   = os.getenv("COUNCIL_OUTSIDER_MODEL",    "inclusionai/ling-2.6-1t:free")
M_JUDGE      = os.getenv("COUNCIL_JUDGE_MODEL",       "nvidia/nemotron-3-super-120b-a12b:free")
M_SYNTHESIS  = os.getenv("SYNTHESIS_MODEL",           "inclusionai/ling-2.6-1t:free")

# Fallback chain for dead free models
FALLBACKS = [
    "nvidia/nemotron-3-super-120b-a12b:free",
    "tencent/hy3-preview:free",
    "inclusionai/ling-2.6-1t:free",
    "deepseek/deepseek-chat-v3.1:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "google/gemma-4-31b-it:free",
]

app = FastAPI(title="Vakeel AI Local")

# ── IK API helpers ─────────────────────────────────────────────────────────────

async def ik_search(query: str, doctypes: str = "supremecourt", page: int = 0) -> list:
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(f"{IK_BASE}/search/",
            headers={"Authorization": f"Token {IK_TOKEN}"},
            data={"formInput": query, "pagenum": page, "doctypes": doctypes})
        if r.status_code != 200:
            log.warning(f"IK search {r.status_code}: {r.text[:200]}")
            return []
        return r.json().get("docs", [])


async def ik_doc(doc_id: str) -> dict:
    async with httpx.AsyncClient(timeout=45) as c:
        r = await c.post(f"{IK_BASE}/doc/{doc_id}/",
            headers={"Authorization": f"Token {IK_TOKEN}"},
            data={"maxcites": 15, "maxcitedby": 5})
        if r.status_code != 200:
            log.warning(f"IK doc {r.status_code}: doc_id={doc_id}")
            return {}
        return r.json()


def parse_ik_doc(doc_id: str, data: dict) -> dict:
    from bs4 import BeautifulSoup
    raw_html = data.get("doc", "")
    soup = BeautifulSoup(raw_html, "lxml") if raw_html else None
    paragraphs = []
    holding_paras = []
    if soup:
        para_num = 0
        for el in soup.find_all(["p", "div"]):
            if el.parent and el.parent.name in ["p"]:
                continue
            text = el.get_text(" ", strip=True)
            text = re.sub(r"\s+", " ", text).strip()
            if len(text) < 25:
                continue
            para_num += 1
            ptype = _para_type(el)
            p = {"number": para_num, "text": text, "type": ptype}
            paragraphs.append(p)
            if ptype in {"analysis_of_law", "conclusion", "courts_discourse"}:
                holding_paras.append(p)
    if not paragraphs:
        plain = re.sub(r"<[^>]+>", " ", raw_html)
        plain = re.sub(r"\s+", " ", plain).strip()
        chunks = [c.strip() for c in plain.split("  ") if len(c.strip()) > 25]
        for i, c in enumerate(chunks[:80], 1):
            paragraphs.append({"number": i, "text": c, "type": "general"})
        holding_paras = paragraphs[-15:]
    title = re.sub(r"<[^>]+>", "", data.get("title", "Unknown Case")).strip()
    citation = _extract_citation(title)
    court = data.get("docsource", "Supreme Court of India")
    treatment_map = {}
    for cite in data.get("citeList", []):
        ctype = cite.get("catgeory", cite.get("category", "neutral")).lower()
        treatment_map[str(cite.get("tid", ""))] = ctype
    holding_text = "\n\n".join(
        f"[Para {p['number']} — {p['type'].replace('_',' ').title()}]\n{p['text']}"
        for p in holding_paras
    ) or "\n\n".join(p["text"] for p in paragraphs[:20])
    return {
        "doc_id": doc_id, "title": title, "citation": citation or title,
        "court": court, "date": data.get("publishdate", ""),
        "paragraphs": paragraphs, "holding_text": holding_text[:6000],
        "treatment_map": treatment_map,
        "ik_url": f"https://indiankanoon.org/doc/{doc_id}/",
    }


def _para_type(el) -> str:
    classes = " ".join(el.get("class", [])).lower()
    attr    = el.get("data-paratype", "").lower()
    combined = classes + " " + attr
    if any(k in combined for k in ["conclusion", "final", "order", "result"]): return "conclusion"
    if any(k in combined for k in ["analysis", "held", "holding", "view", "reasoning"]): return "analysis_of_law"
    if any(k in combined for k in ["discourse", "discussion"]): return "courts_discourse"
    if any(k in combined for k in ["fact", "background"]): return "facts"
    if any(k in combined for k in ["issue", "question"]): return "issues"
    return "general"


def _extract_citation(title: str) -> str:
    for pat in [r'\(\d{4}\)\s+\d+\s+SCC\s+\d+', r'AIR\s+\d{4}\s+SC\s+\d+']:
        m = re.search(pat, title)
        if m: return m.group(0)
    return ""


# ── LLM helpers ────────────────────────────────────────────────────────────────

async def llm(model: str, prompt: str) -> str:
    is_free = model.endswith(":free")
    chain = [model] + ([m for m in FALLBACKS if m != model] if is_free else [])
    for m in chain:
        try:
            async with httpx.AsyncClient(timeout=90) as c:
                r = await c.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={"Authorization": f"Bearer {OR_KEY}",
                             "Content-Type": "application/json",
                             "HTTP-Referer": "https://vakeel.ai",
                             "X-Title": "Vakeel AI"},
                    json={"model": m, "messages": [{"role": "user", "content": prompt}],
                          "temperature": 0.0, "max_tokens": 2500})
            if r.status_code in (404, 503):
                log.warning(f"Model {m} unavailable ({r.status_code}), trying fallback")
                continue
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
        except Exception as e:
            log.warning(f"LLM error [{m}]: {e}")
            if not is_free: raise
            continue
    raise RuntimeError("All models in fallback chain unavailable")


def pj(raw, key=""):
    if not raw: return [] if key else {}
    try:
        c = re.sub(r"```json\s*|```\s*", "", raw).strip()
        s, e = c.find("{"), c.rfind("}") + 1
        if s < 0: return [] if key else {}
        obj = json.loads(c[s:e])
        return obj.get(key, []) if key else obj
    except: return [] if key else {}


# ── Zero-cost checks ───────────────────────────────────────────────────────────

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


# ── Council prompts ────────────────────────────────────────────────────────────

def p_premise(q): return f"""Does this legal query contain a false factual premise?
Query: "{q}"
Return ONLY JSON: {{"has_false_premise":false,"assumed_fact":"what it assumes","confidence":0.0,"explanation":"one sentence"}}"""

def p_extract(q, name, text): return f"""Extract legal holdings from this Indian Supreme Court judgment.
Query context: "{q}"
Case: {name}
Source text (IK-classified holding paragraphs):
{text}
RULES: Extract ONLY rules explicitly stated above. Provide verbatim_anchor: exact phrase that MUST appear verbatim. Never invent.
Return ONLY JSON: {{"holdings":[{{"proposition":"one-sentence rule","verbatim_anchor":"exact phrase","paragraph_number":1,"is_ratio":true,"confidence":0.85}}]}}"""

def p_skeptic(q, name, text): return f"""You are a legal skeptic. Query: "{q}" | Case: {name}
Source: {text}
What propositions are ABSENT, HEDGED, or OBITER?
Return ONLY JSON: {{"absent_propositions":[{{"description":"wrongly claimed","reason_absent":"why","paragraph_number":1}}],"ambiguous_paragraphs":[{{"paragraph_number":1,"ambiguity":"why"}}]}}"""

def p_adversary(q, name, text, props): return f"""Defense lawyer. Default NO unless unambiguous.
Query: "{q}" | Case: {name}
Source: {text}
Evaluate: {props}
Return ONLY JSON: {{"verdicts":[{{"holding_index":0,"verdict":"SUPPORTED","evidence_quote":"verbatim","reasoning":"one sentence"}}]}}"""

def p_outsider(para): return f"""Read with fresh eyes. No case name. No context.
{para}
Does this text state a specific legal rule?
Return ONLY JSON: {{"found_rule":true,"rule_statement":"rule","verbatim_evidence":"exact words","confidence":0.8,"reasoning":"one sentence"}}"""

def p_judge(q, name, pnum, ptext, prop, anchor, d): return f"""FINAL JUDGE. Nothing reaches a lawyer without your PASS. Be conservative.
Query: "{q}" | Case: {name} | Para {pnum}:
{ptext[:1000]}
Proposed: {prop}
Anchor: {anchor}
Council — L1={d['l1']} L3={d['l3']} L4ok={d['l4ok']} adversary={d['adv']} skeptic_flagged={d['sf']} outsider_found={d['of']} outsider_conf={d['oc']}
PASS=genuinely supported by real text. FAIL=uncertain/hallucinated.
Return ONLY JSON: {{"verdict":"PASS","confidence":0.0,"reasoning":"one sentence","final_verbatim":"best quote or empty if FAIL"}}"""

def p_synth(q, holdings):
    items = "\n\n".join(
        f"{i+1}. {h['case_name']} ({h['citation']}) Para {h['para_num']}:\n"
        f"   \"{h['verbatim']}\"\n   {h['prop']}\n   Source: {h['ik_url']}"
        for i, h in enumerate(holdings))
    return f"""Research note for Indian lawyer. Query: "{q}"
Verified authorities (from real Indian Kanoon corpus):
{items}
Write: 1. Restated legal question  2. Each authority with case name, citation, paragraph, exact holding  3. Note treatment=unverified — verify via SCC before court  4. 2-sentence legal summary
Max 400 words. Precise legal language."""


# ── Main research pipeline ─────────────────────────────────────────────────────

class ResearchRequest(BaseModel):
    query: str
    doctypes: str = "supremecourt"
    mode: str = "quick"
    # Per-request model overrides (sent by UI)
    extractor_model: str = ""
    adversary_model: str = ""
    judge_model: str = ""
    synthesis_model: str = ""


def sse(type: str, **kwargs) -> str:
    return f"data: {json.dumps({'type': type, 'ts': time.time(), **kwargs})}\n\n"


async def pipeline(req: ResearchRequest) -> AsyncGenerator[str, None]:
    if not IK_TOKEN:
        yield sse("error", message="INDIAN_KANOON_API_TOKEN not set in .env"); return
    if not OR_KEY:
        yield sse("error", message="OPENROUTER_API_KEY not set in .env"); return

    m_ext = req.extractor_model or M_EXTRACTOR
    m_adv = req.adversary_model or M_ADVERSARY
    m_jdg = req.judge_model     or M_JUDGE
    m_syn = req.synthesis_model or M_SYNTHESIS

    q = req.query.strip()
    t0 = time.time()

    yield sse("models", message=f"Extractor: {m_ext.split('/')[-1]} · Judge: {m_jdg.split('/')[-1]} · Synthesis: {m_syn.split('/')[-1]}")

    # Premise check
    yield sse("thinking", message="Checking query for false premises…")
    premise_warn = None
    try:
        pr = await llm(m_ext, p_premise(q))
        po = pj(pr)
        if po and po.get("has_false_premise") and po.get("confidence", 0) > 0.6:
            premise_warn = po
            yield sse("premise_warn", message=f"False premise: {po['assumed_fact']}", detail=po.get("explanation",""))
        else:
            yield sse("premise_ok", message="No false premise detected")
    except Exception as e:
        yield sse("warning", message=f"Premise check failed: {e}")

    # IK Search
    yield sse("searching", message=f"Searching Indian Kanoon ({req.doctypes})…")
    try:
        results = await ik_search(q, doctypes=req.doctypes)
    except Exception as e:
        yield sse("error", message=f"Indian Kanoon search failed: {e}"); return

    if not results:
        yield sse("error", message="No results from Indian Kanoon. Try different keywords."); return

    yield sse("found", message=f"Found {len(results)} candidates from IK corpus", count=len(results))

    all_holdings = []
    docs_processed = 0

    for res in results[:4]:
        doc_id = str(res.get("tid", ""))
        title  = re.sub(r"<[^>]+>", "", res.get("title", "Unknown")).strip()
        size   = res.get("docsize", 0)
        if not doc_id or size < 1500: continue

        yield sse("fetching", message=f"Fetching: {title[:55]}…")
        try:
            raw = await ik_doc(doc_id)
        except Exception as e:
            yield sse("warning", message=f"Fetch failed for {doc_id}: {e}"); continue
        if not raw: continue

        doc = parse_ik_doc(doc_id, raw)
        docs_processed += 1
        hc = len([p for p in doc['paragraphs'] if p['type'] in {'analysis_of_law','conclusion','courts_discourse'}])
        yield sse("processing", message=f"Extracted {len(doc['paragraphs'])} paragraphs · {hc} holding-type")
        yield sse("council_start", message=f"Council: extracting holdings from {doc['title'][:45]}…")

        try:
            ext_raw = await llm(m_ext, p_extract(q, doc["title"], doc["holding_text"]))
            holdings = pj(ext_raw, "holdings") or []
        except Exception as e:
            yield sse("warning", message=f"Extractor failed: {e}"); continue

        if not holdings:
            yield sse("no_holdings", message=f"No holdings found in {doc['title'][:40]}"); continue
        yield sse("extracted", message=f"{len(holdings)} raw holdings extracted")

        absent_kw, ambig_paras = set(), set()
        if req.mode == "full":
            try:
                sk_raw = await llm(M_SKEPTIC, p_skeptic(q, doc["title"], doc["holding_text"]))
                for ap in pj(sk_raw, "absent_propositions"): absent_kw |= set(ap.get("description","").lower().split())
                for ap in pj(sk_raw, "ambiguous_paragraphs"): ambig_paras.add(ap.get("paragraph_number",-1))
                yield sse("skeptic_done", message="Skeptic pass complete")
            except Exception as e:
                yield sse("warning", message=f"Skeptic failed: {e}")

        para_map = {p["number"]: p["text"] for p in doc["paragraphs"]}
        cands = []
        for h in holdings:
            pn = h.get("paragraph_number", 1)
            pt = para_map.get(pn, doc["holding_text"][:500])
            anchor = h.get("verbatim_anchor", "")
            prop = h.get("proposition", "")
            L1 = l1(anchor, pt); L3 = l3(pt); L4ok, L4f = l4(prop, pt)
            pw = set(prop.lower().split())
            sf = (len(pw & absent_kw) / max(len(pw), 1) > 0.35 or pn in ambig_paras)
            cands.append({**h, "para_text": pt, "para_num": pn,
                          "L1": L1, "L3": L3, "L4ok": L4ok, "L4f": L4f, "sf": sf, "doc": doc})

        yield sse("l1_done", message=f"L1 verified: {sum(1 for c in cands if c['L1'])}/{len(cands)}")

        str_verified = [c for c in cands if c["L1"]]
        adv_verdicts = {}
        if str_verified:
            try:
                props = json.dumps([{"index": i, "proposition": c["proposition"], "paragraph_number": c["para_num"]} for i, c in enumerate(str_verified)])
                adv_raw = await llm(m_adv, p_adversary(q, doc["title"], doc["holding_text"], props))
                for v in pj(adv_raw, "verdicts"): adv_verdicts[v["holding_index"]] = v
                yield sse("adversary_done", message="Adversary verdicts received")
            except Exception as e:
                yield sse("warning", message=f"Adversary failed: {e}")

        outsiders = {}
        if req.mode == "full":
            for i, c in enumerate(cands):
                try:
                    o_raw = await llm(M_OUTSIDER, p_outsider(c["para_text"]))
                    oo = pj(o_raw)
                    outsiders[i] = {"found": oo.get("found_rule", False), "stmt": oo.get("rule_statement",""), "conf": float(oo.get("confidence", 0))}
                except: outsiders[i] = {"found": False, "stmt": "", "conf": 0}
            yield sse("outsider_done", message="Outsider cold reads complete")

        yield sse("judging", message="Judge: final PASS/FAIL…")
        for i, c in enumerate(cands):
            adv = adv_verdicts.get(i, {"verdict": "skipped", "evidence_quote": ""})
            out = outsiders.get(i, {"found": False, "stmt": "", "conf": 0})
            try:
                j_raw = await llm(m_jdg, p_judge(q, doc["title"], c["para_num"], c["para_text"],
                    c["proposition"], c.get("verbatim_anchor",""),
                    {"l1": c["L1"], "l3": c["L3"], "l4ok": c["L4ok"],
                     "adv": adv.get("verdict","skipped"), "sf": c["sf"],
                     "of": out["found"], "oc": f"{out['conf']:.2f}"}))
                jobj = pj(j_raw)
            except Exception as e:
                jobj = {"verdict": "FAIL", "confidence": 0, "reasoning": str(e), "final_verbatim": ""}

            passed = jobj.get("verdict") == "PASS"
            yield sse("judge_verdict",
                      message=f"{'✓ PASS' if passed else '✗ FAIL'}: {c['proposition'][:60]}",
                      passed=passed, reasoning=jobj.get("reasoning",""))

            all_holdings.append({
                "case_name": doc["title"], "citation": doc["citation"], "court": doc["court"],
                "date": doc["date"], "para_num": c["para_num"], "para_text": c["para_text"],
                "prop": c["proposition"], "verbatim": jobj.get("final_verbatim") or c.get("verbatim_anchor",""),
                "is_ratio": c.get("is_ratio", True), "pass": passed,
                "judge_conf": float(jobj.get("confidence", 0)), "judge_reason": jobj.get("reasoning",""),
                "L1": c["L1"], "L3": c["L3"], "L4ok": c["L4ok"], "L4f": c["L4f"],
                "adv_verdict": adv.get("verdict","skipped"), "sf": c["sf"],
                "ik_url": doc["ik_url"], "ik_doc_id": doc["doc_id"],
                "treatment_status": "unverified",
                "models_used": {"extractor": m_ext, "adversary": m_adv, "judge": m_jdg},
            })

    passed_h = [h for h in all_holdings if h["pass"]]
    yield sse("synthesising", message=f"Synthesising research note from {len(passed_h)} verified holdings…")

    note = ""
    if passed_h:
        try: note = await llm(m_syn, p_synth(q, passed_h))
        except Exception as e: note = f"Synthesis failed: {e}"
    else:
        note = ("No holdings passed council verification for this query.\n"
                + (f"Note: {premise_warn['explanation']}" if premise_warn else
                   "Try different keywords or broaden the search."))

    elapsed = round(time.time() - t0, 1)
    yield sse("complete",
              message=f"Done in {elapsed}s · {len(passed_h)}/{len(all_holdings)} passed",
              note=note, holdings=all_holdings, premise_warn=premise_warn,
              stats={"elapsed": elapsed, "passed": len(passed_h),
                     "total": len(all_holdings), "docs": docs_processed})


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.post("/api/research")
async def research(req: ResearchRequest):
    return StreamingResponse(pipeline(req), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

@app.get("/api/models")
async def get_models():
    return JSONResponse(await fetch_or_models())

@app.get("/api/health")
async def health():
    return {"ik_token": "set" if IK_TOKEN else "MISSING",
            "or_key": "set" if OR_KEY else "MISSING",
            "extractor": M_EXTRACTOR, "judge": M_JUDGE, "synthesis": M_SYNTHESIS}

@app.get("/", response_class=HTMLResponse)
async def index():
    return Path("index.html").read_text()

if __name__ == "__main__":
    import uvicorn
    print("\n── Vakeel AI Local Server ──────────────────────")
    print(f"  IK Token : {'✓ SET' if IK_TOKEN else '✗ MISSING — add to .env'}")
    print(f"  OR Key   : {'✓ SET' if OR_KEY   else '✗ MISSING — add to .env'}")
    print(f"  Extractor: {M_EXTRACTOR}")
    print(f"  Judge    : {M_JUDGE}")
    print("  Open     : http://localhost:8765")
    print("────────────────────────────────────────────────\n")
    uvicorn.run("main:app", host="0.0.0.0", port=8765, reload=True)
