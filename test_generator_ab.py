"""
A/B test: V4 Pro vs Gemini 3.1 Pro for landmark case generation.
Verifier is V4 Pro for both arms. Only the GENERATOR varies.
Now logs why each candidate gets rejected so we can debug the verifier.
"""
import asyncio, httpx, json, os, re, time
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
IK_TOKEN = os.getenv("INDIAN_KANOON_API_TOKEN", "")
OR_KEY   = os.getenv("OPENROUTER_API_KEY", "")

V4_PRO  = "deepseek/deepseek-v4-pro"
GEMINI  = "google/gemini-3-flash-preview"
VERIFIER = V4_PRO

TEST_DOCTRINES = [
    "Section 482 CrPC quashing of FIR",
    "Section 11 Arbitration Act scope of court inquiry",
    "Section 9 IBC operational creditor pre-existing dispute",
    "Article 226 writ against private body",
    "Section 14A Income Tax disallowance",
]


async def llm(model: str, prompt: str, max_tokens: int = 6000) -> tuple[str, dict]:
    async with httpx.AsyncClient(timeout=180) as c:
        r = await c.post("https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {OR_KEY}",
                     "Content-Type": "application/json",
                     "HTTP-Referer": "https://karyaniti.in",
                     "X-Title": "Karyaniti"},
            json={"model": model,
                  "messages": [{"role": "user", "content": prompt}],
                  "temperature": 0.0,
                  "max_tokens": max_tokens})
    r.raise_for_status()
    data = r.json()
    content = data["choices"][0]["message"].get("content") or ""
    return content, data.get("usage", {})


def parse_json(raw: str) -> dict:
    c = re.sub(r"```json\s*|```\s*", "", raw).strip()
    s, e = c.find("{"), c.rfind("}") + 1
    if s < 0:
        return {}
    try:
        return json.loads(c[s:e])
    except json.JSONDecodeError:
        fixed = re.sub(r",(\s*[}\]])", r"\1", c[s:e])
        try:
            return json.loads(fixed)
        except json.JSONDecodeError:
            return {}


async def ik_search(query: str) -> list:
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post("https://api.indiankanoon.org/search/",
            headers={"Authorization": f"Token {IK_TOKEN}"},
            data={"formInput": query, "pagenum": 0, "doctypes": "supremecourt"})
        return r.json().get("docs", []) if r.status_code == 200 else []


GEN_PROMPT = """You are an expert in Indian law. List the most-cited Supreme Court of India landmark judgments on this doctrine.

DOCTRINE: {doctrine}

Output 6-10 cases. Real, verifiable cases only — if unsure, omit. Include the SCC/AIR citation.

Output ONLY this JSON:
{{"cases":[
  {{"name":"<short form>", "citation":"<SCC/AIR cite>", "year":<int>, "bench":"<Constitution Bench|3-judge|2-judge>"}}
]}}"""


VERIFY_PROMPT = """You verify whether a retrieved Indian SC judgment is the same case as a target landmark.

TARGET CASE:    {name}
KNOWN CITATION: {citation}
DOCTRINE:       {doctrine}

RETRIEVED CANDIDATE:
  Title:  {title}
  Source: {source}

Indian Kanoon's case titles often use different formatting than common citation form.
TREAT THESE AS THE SAME CASE:
- "CIT v. X"  ≡  "C.I.T.,Mumbai vs M/S.X" (abbreviations expanded, location appended, M/S prefix)
- "Andi Mukta v. V.R. Rudani"  ≡  "Andi Mukta Sadguru Shree Muktajee Vandas Swami Suvarna Trust vs V.R. Rudani" (long-form vs short-form party name)
- "SBP & Co. v. Patel Engineering"  ≡  "S.B.P. & Co. vs Patel Engineering Ltd. & Anr." (punctuation, suffixes)
- "Mobilox v. Kirusa"  ≡  "Mobilox Innovations Private Limited vs Kirusa Software Private Limited" (Pvt Ltd. expanded)
- Different date suffixes after the title ("on 21 September, 2017") are not different cases

REJECT (different cases):
- Completely different parties (e.g. target "Mobilox v. Kirusa" vs candidate "Hindustan Construction v. Union of India")
- Source NOT "Supreme Court of India" — reject Daily Orders, High Courts, NCLAT, ITAT, etc.
- Earlier or later proceeding between same parties (review petition, daily order, HC stage)

Decision rule: if the core distinctive party tokens match (e.g. "Walfort", "Andi Mukta", "Mobilox", "Bhajan Lal"), MATCH. Be lenient on formatting, strict on identity.

Output ONLY JSON: {{"match": true/false, "reason": "<≤15 words>"}}"""


_PUNCT = re.compile(r"[^\w\s]")


def strip_html(s): return re.sub(r"<[^>]+>", "", s or "")


def overlap(target: str, candidate: str) -> float:
    stop = {"versus","vs","v","state","union","india","the","of","and","anr","ors","ltd","limited","co",
            "pvt","private","corp","corporation","mfg","manufacturing","mumbai","delhi","p"}
    tt = {t for t in _PUNCT.sub(" ", target.lower()).split() if len(t) >= 3} - stop
    ct = {t for t in _PUNCT.sub(" ", candidate.lower()).split() if len(t) >= 3} - stop
    if not tt:
        return 0.0
    # Bonus for "distinctive" tokens (rare in legal corpus)
    distinctive = tt - {"cit","commissioner","income","tax","appellate","court","supreme"}
    if distinctive and any(d in ct for d in distinctive):
        return max(0.5, len(tt & ct) / len(tt))
    return len(tt & ct) / len(tt)


async def verify(case: dict, doctrine: str, candidate: dict) -> tuple[bool, str]:
    title  = strip_html(candidate.get("title", ""))
    source = candidate.get("docsource", "")
    if "Supreme Court of India" not in source:
        return False, f"source filter ({source[:30]})"
    ov = overlap(case.get("name", ""), title)
    if ov < 0.25:
        return False, f"low overlap ({ov:.2f})"
    try:
        raw, _ = await llm(VERIFIER, VERIFY_PROMPT.format(
            name=case.get("name", ""), citation=case.get("citation", ""),
            doctrine=doctrine, title=title, source=source), max_tokens=1500)
        obj = parse_json(raw)
        if obj.get("match") is True:
            return True, obj.get("reason", "")
        # Fallback: detect truncated true responses
        if re.search(r'"match"\s*:\s*true', raw):
            return True, "(truncated response, regex-detected match)"
        return False, obj.get("reason", raw[:120])
    except Exception as e:
        return False, f"err: {e}"


async def resolve(case: dict, doctrine: str) -> tuple[str | None, str, list]:
    name = case.get("name", "")
    if not name:
        return None, "", []
    queries = [f"{name} {case.get('citation','')}".strip(), name, f"{name} {doctrine}"]
    rejections = []
    for q in queries:
        docs = await ik_search(q)
        for cand in docs[:10]:
            ok, reason = await verify(case, doctrine, cand)
            tid = str(cand.get("tid", ""))
            src = cand.get("docsource", "")[:25]
            title = strip_html(cand.get("title", ""))[:50]
            if ok:
                return tid, strip_html(cand.get("title", "")), rejections
            rejections.append(f"    tid={tid:>10}  src={src:<25}  title={title:<50}  →  {reason}")
    return None, "", rejections


async def run_arm(generator_model: str, doctrine: str) -> dict:
    t0 = time.time()
    try:
        raw, usage = await llm(generator_model, GEN_PROMPT.format(doctrine=doctrine))
        obj = parse_json(raw)
        cases = obj.get("cases", []) if isinstance(obj.get("cases"), list) else []
    except Exception as e:
        return {"model": generator_model, "doctrine": doctrine, "error": str(e),
                "cases_generated": 0, "cases_resolved": [], "elapsed": 0,
                "tokens_in": 0, "tokens_out": 0}

    resolved = []
    for c in cases:
        doc_id, title, rejections = await resolve(c, doctrine)
        resolved.append({
            "name": c.get("name", ""),
            "citation": c.get("citation", ""),
            "bench": c.get("bench", ""),
            "doc_id": doc_id,
            "matched_title": title,
            "resolved": doc_id is not None,
            "rejections": rejections,
        })
        if doc_id:
            print(f"   ✓  {c.get('name','')[:55]:<55}  →  {doc_id}")
        else:
            print(f"   ✗  {c.get('name','')[:55]:<55}  (tried {len(rejections)})")
            for r in rejections[:3]:
                print(r)

    return {
        "model": generator_model,
        "doctrine": doctrine,
        "cases_generated": len(cases),
        "cases_resolved": resolved,
        "elapsed": round(time.time() - t0, 1),
        "tokens_in": int(usage.get("prompt_tokens", 0)),
        "tokens_out": int(usage.get("completion_tokens", 0)),
    }


def compare(v4: dict, gem: dict) -> dict:
    v4_ids  = {r["doc_id"] for r in v4["cases_resolved"]  if r["resolved"]}
    gem_ids = {r["doc_id"] for r in gem["cases_resolved"] if r["resolved"]}
    return {
        "doctrine": v4["doctrine"],
        "v4_generated":  v4["cases_generated"],
        "v4_resolved":   len(v4_ids),
        "gem_generated": gem["cases_generated"],
        "gem_resolved":  len(gem_ids),
        "only_in_v4":  list(v4_ids - gem_ids),
        "only_in_gem": list(gem_ids - v4_ids),
        "in_both":     list(v4_ids & gem_ids),
    }


PRICE = {
    V4_PRO: (0.435e-6, 0.87e-6),
    GEMINI: (2e-6, 12e-6),
}


def cost(result: dict) -> float:
    p_in, p_out = PRICE.get(result["model"], (0, 0))
    return result["tokens_in"] * p_in + result["tokens_out"] * p_out


async def main():
    if not IK_TOKEN or not OR_KEY:
        print("ERROR: INDIAN_KANOON_API_TOKEN or OPENROUTER_API_KEY missing")
        return

    print(f"A/B test: {V4_PRO} vs {GEMINI}")
    print(f"Verifier (constant): {VERIFIER}\n")

    all_results = []
    total_cost_v4 = total_cost_gem = 0.0

    for i, doctrine in enumerate(TEST_DOCTRINES, 1):
        print(f"\n[{i}/{len(TEST_DOCTRINES)}]  {doctrine}")
        print("  V4 Pro arm:")
        v4_result  = await run_arm(V4_PRO,  doctrine)
        print("  Gemini arm:")
        gem_result = await run_arm(GEMINI,  doctrine)
        comp = compare(v4_result, gem_result)
        all_results.append({"v4": v4_result, "gem": gem_result, "comparison": comp})
        c_v4 = cost(v4_result); c_gem = cost(gem_result)
        total_cost_v4 += c_v4; total_cost_gem += c_gem
        print(f"  Summary: V4 {v4_result['cases_generated']}→{comp['v4_resolved']}  "
              f"Gem {gem_result['cases_generated']}→{comp['gem_resolved']}  "
              f"V4 ${c_v4:.4f}  Gem ${c_gem:.4f}")

    Path("ab_test_results.json").write_text(
        json.dumps(all_results, indent=2, ensure_ascii=False), encoding="utf-8")

    total_v4_resolved  = sum(c["comparison"]["v4_resolved"]  for c in all_results)
    total_gem_resolved = sum(c["comparison"]["gem_resolved"] for c in all_results)
    unique_to_v4  = sum(len(c["comparison"]["only_in_v4"])  for c in all_results)
    unique_to_gem = sum(len(c["comparison"]["only_in_gem"]) for c in all_results)
    overlap_cases = sum(len(c["comparison"]["in_both"])     for c in all_results)
    total_v4_generated  = sum(c["comparison"]["v4_generated"]  for c in all_results)
    total_gem_generated = sum(c["comparison"]["gem_generated"] for c in all_results)

    print("\n" + "═" * 70)
    print(f"V4 Pro  : gen {total_v4_generated:>3}  res {total_v4_resolved:>3}  (${total_cost_v4:.4f})")
    print(f"Gemini  : gen {total_gem_generated:>3}  res {total_gem_resolved:>3}  (${total_cost_gem:.4f})")
    print(f"Overlap : {overlap_cases} | V4 only: {unique_to_v4} | Gem only: {unique_to_gem}")
    print()

    gem_advantage = unique_to_gem - unique_to_v4
    cost_multiple = total_cost_gem / max(total_cost_v4, 0.001)
    print(f"Gemini advantage: +{gem_advantage} unique | cost: {cost_multiple:.1f}×")

    if gem_advantage >= 5 and cost_multiple <= 25:
        print("VERDICT: Gemini worth the cost.")
    elif gem_advantage <= 2:
        print("VERDICT: No meaningful difference. Use V4 Pro.")
    else:
        print("VERDICT: Marginal Gemini advantage — inspect JSON.")
    print("\nFull detail in ab_test_results.json")


if __name__ == "__main__":
    asyncio.run(main())