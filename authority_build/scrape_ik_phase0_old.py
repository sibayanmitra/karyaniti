"""
Deterministic resolver: scrapes IK public website using citation phrase search.

Uses no LLM, no API, no money. Just IK's free web interface with polite delays.

For each unresolved case in authority_build_progress.json:
  1. Search IK for the citation as a phrase query
  2. Find the first "Supreme Court of India" result
  3. Fetch the doc page, verify the citation appears in the body
  4. If verified -> extract tid -> add to authority_index.py

Run from inside authority_build/:
    python scrape_ik.py            # full run, resumable
    python scrape_ik.py --limit 20 # canary on 20 cases first
    python scrape_ik.py --fresh    # discard scraper progress, start over
"""
import argparse, json, re, time
from pathlib import Path
from urllib.parse import quote_plus
import httpx
from bs4 import BeautifulSoup

HERE = Path(__file__).parent
PARENT = HERE.parent

PROGRESS_PATH      = HERE / "authority_build_progress.json"        # input
SCRAPE_STATE_PATH  = HERE / "ik_scrape_state.json"                 # our own state
OUTPUT_INDEX       = PARENT / "authority_index.py"

REQUEST_DELAY_SECONDS = 3.0          # polite — IK has anti-scraping
SAVE_EVERY_N          = 25
USER_AGENT            = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

session = httpx.Client(
    headers={"User-Agent": USER_AGENT,
             "Accept": "text/html,application/xhtml+xml",
             "Accept-Language": "en-US,en;q=0.9"},
    timeout=30,
    follow_redirects=True,
)


# ── Citation normalization ─────────────────────────────────────────────────

def normalize_citation_for_search(cite: str) -> list[str]:
    """Produce search variants for a citation."""
    if not cite:
        return []
    variants = [cite.strip()]
    # Without parens: "1992 Supp (1) SCC 335" -> "1992 Supp 1 SCC 335"
    no_parens = re.sub(r"[()]", "", cite).strip()
    no_parens = re.sub(r"\s+", " ", no_parens)
    if no_parens != cite:
        variants.append(no_parens)
    return variants


def citation_token_signature(cite: str) -> set[str]:
    """Tokens that must appear in body to confirm match."""
    if not cite:
        return set()
    tokens = set()
    # Year
    for y in re.findall(r"\b(19|20)\d{2}\b", cite):
        tokens.add(y)
    # Reporter name (SCC, AIR, SC etc)
    for r in re.findall(r"\b(SCC|AIR|SCR|JT|SC|SCALE)\b", cite, re.I):
        tokens.add(r.upper())
    # Volume and page numbers
    for n in re.findall(r"\d+", cite):
        if len(n) >= 1 and len(n) <= 4:
            tokens.add(n)
    return tokens


# ── HTTP layer ─────────────────────────────────────────────────────────────

def fetch(url: str, retries: int = 3) -> str | None:
    last_err = None
    for attempt in range(retries):
        try:
            r = session.get(url)
            if r.status_code == 200:
                return r.text
            if r.status_code in (429, 503):
                wait = 30 * (attempt + 1)
                print(f"   rate-limited ({r.status_code}), sleeping {wait}s")
                time.sleep(wait)
                continue
            return None
        except Exception as e:
            last_err = e
            time.sleep(5 * (attempt + 1))
    return None


# ── IK search + extract ────────────────────────────────────────────────────

def search_ik(query: str) -> list[dict]:
    """Return list of {tid, title, source} for results on first page."""
    url = f"https://indiankanoon.org/search/?formInput={quote_plus(query)}"
    html = fetch(url)
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for div in soup.select("article.result")[:15]:
        title_tag = div.select_one("h4.result_title a") or div.select_one("a")
        if not title_tag:
            continue
        href = title_tag.get("href", "")
        m = re.search(r"/(?:doc|docfragment)/(\d+)/", href)
        if not m:
            continue
        title = title_tag.get_text(strip=True)
        meta = div.select_one(".docsource")
        source = meta.get_text(strip=True) if meta else ""
        # Fallback: source sometimes lives in the title cite line
        if not source:
            cite_line = div.select_one(".citation")
            source = cite_line.get_text(strip=True) if cite_line else ""
        out.append({"tid": m.group(1), "title": title, "source": source, "raw_div": div.get_text(" ", strip=True)})
    return out


def fetch_doc_text(tid: str) -> str | None:
    return fetch(f"https://indiankanoon.org/doc/{tid}/")


def is_supreme_court(result: dict) -> bool:
    """Check if a search result hit is from the Supreme Court."""
    blob = (result.get("source", "") + " " + result.get("raw_div", "")).lower()
    if "supreme court of india" in blob:
        # Reject daily orders, review petitions
        if "daily order" in blob:
            return False
        return True
    return False


def verify_citation_in_doc(doc_html: str, citation: str) -> bool:
    """Confirm the case's citation appears in the doc body."""
    if not doc_html:
        return False
    soup = BeautifulSoup(doc_html, "html.parser")
    text = soup.get_text(" ", strip=True)
    required = citation_token_signature(citation)
    if not required:
        return False
    text_upper = text.upper()
    matched = sum(1 for tok in required if tok.upper() in text_upper)
    # Need at least 3 of {year, reporter, vol, page} to confirm
    return matched >= min(3, len(required))


# ── Resolution per case ────────────────────────────────────────────────────

def resolve_one(case: dict) -> tuple[str | None, str, str]:
    """Returns (tid, title, reason). tid=None if unresolved."""
    name = case.get("name", "")
    citation = case.get("citation", "")
    if not citation:
        return None, "", "no citation"

    # Try citation-phrase search
    for q in normalize_citation_for_search(citation):
        time.sleep(REQUEST_DELAY_SECONDS)
        results = search_ik(q)
        if not results:
            continue
        sc_results = [r for r in results if is_supreme_court(r)]
        if not sc_results:
            continue
        # Take the top SC result, verify by fetching doc
        for cand in sc_results[:3]:
            time.sleep(REQUEST_DELAY_SECONDS)
            doc_html = fetch_doc_text(cand["tid"])
            if doc_html and verify_citation_in_doc(doc_html, citation):
                return cand["tid"], cand["title"], "citation-verified"
        # Citation search returned SC results but none verified — accept top SC anyway as MEDIUM
        return sc_results[0]["tid"], sc_results[0]["title"], "top-SC-result (unverified body)"

    return None, "", "no SC results found"


# ── State + output ─────────────────────────────────────────────────────────

def load_scrape_state(fresh: bool) -> dict:
    if fresh and SCRAPE_STATE_PATH.exists():
        SCRAPE_STATE_PATH.unlink()
    if SCRAPE_STATE_PATH.exists():
        return json.loads(SCRAPE_STATE_PATH.read_text(encoding="utf-8"))
    return {"resolved": {}, "failed": []}


def save_scrape_state(state: dict):
    SCRAPE_STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False),
                                  encoding="utf-8")


# ── Alias derivation (clean, no pollution) ─────────────────────────────────

_HONORIFICS = {"shri", "smt", "mr", "mrs", "ms", "dr", "prof"}
_GENERIC = {
    "state", "union", "india", "of", "the", "and", "anr", "ors",
    "ltd", "limited", "co", "pvt", "private", "corp", "corporation",
    "singh", "kumar", "patel", "sharma", "rao", "devi", "lal", "das",
}


def _normalize(s: str) -> str:
    s = (s or "").lower().replace(".", " ")
    return re.sub(r"\s+", " ", s).strip()


def derive_aliases(name: str) -> list[str]:
    """Surname/short-form aliases — no single-word generic tokens allowed."""
    out = set()
    norm = _normalize(name)
    out.add(norm)
    parts = re.split(r"\bv\.?s?\.?\b", name, flags=re.I)
    parties = [_normalize(p) for p in parts if p.strip()]
    for party in parties:
        toks = [t for t in party.split() if t not in _HONORIFICS and len(t) >= 2]
        if not toks:
            continue
        full_party = " ".join(toks)
        if full_party and full_party not in _GENERIC:
            out.add(full_party)
        # 2-3 token short form (avoid 1-word generic surnames)
        if len(toks) >= 2:
            two = " ".join(toks[:2])
            if two not in _GENERIC:
                out.add(two)
    # Filter: must be 2+ words OR a distinctive single word (not in _GENERIC)
    final = set()
    for a in out:
        if len(a) < 4:
            continue
        if " " in a:
            final.add(a)
        elif a not in _GENERIC and len(a) >= 5:
            final.add(a)
    return sorted(final)


# ── Writer ─────────────────────────────────────────────────────────────────

RESOLVER_CODE = '''
import re

def _normalize(s: str) -> str:
    s = (s or "").lower().replace(".", " ")
    return re.sub(r"\\s+", " ", s).strip()


def resolve_case_name(variant: str):
    LEGAL_STARTERS = {
        "Section", "Article", "Under", "Whether", "When", "What",
        "How", "Where", "Which", "Can", "Is", "Are", "Does", "Order",
    }
    parts = variant.split()
    name_tokens = []
    for tok in parts:
        clean = tok.rstrip(".,")
        if clean in LEGAL_STARTERS or (clean and clean[0].isdigit()):
            break
        if clean and clean[0].isupper() and len(clean) >= 2:
            name_tokens.append(tok)
        else:
            break
    if not name_tokens:
        return None
    name = _normalize(" ".join(name_tokens))
    if name in AUTHORITY_INDEX:
        return AUTHORITY_INDEX[name]
    tokens = name.split()
    for i in range(len(tokens) - 1, 0, -1):
        prefix = " ".join(tokens[:i])
        if prefix in AUTHORITY_INDEX:
            return AUTHORITY_INDEX[prefix]
    return None
'''


def write_index(resolved: dict):
    """Build alias map from resolved cases."""
    alias_map = {}  # alias -> (tid, reason, title)
    for entry in resolved.values():
        tid = entry["tid"]
        for alias in derive_aliases(entry["name"]):
            if alias not in alias_map:
                alias_map[alias] = (tid, entry["reason"], entry["title"])

    high = [(a, t, r, ti) for a, (t, r, ti) in alias_map.items() if r == "citation-verified"]
    medium = [(a, t, r, ti) for a, (t, r, ti) in alias_map.items() if r != "citation-verified"]
    high.sort(); medium.sort()

    lines = [
        '"""',
        'Auto-generated by authority_build/scrape_ik.py',
        'Cases verified by IK public-website citation search + body match.',
        '',
        f'Aliases:  {len(alias_map)}',
        f'  HIGH:   {len(high)} (citation found in document body)',
        f'  MEDIUM: {len(medium)} (top SC result for citation phrase, body not verified)',
        '"""',
        "",
        "AUTHORITY_INDEX: dict[str, str] = {",
    ]

    def emit(label, items):
        if not items:
            return
        lines.append(f"    # ── {label} ──")
        for a, t, _, ti in items:
            lines.append(f'    "{a}": "{t}",  # {ti[:70]}')

    emit("HIGH (citation-verified)", high)
    emit("MEDIUM (top SC result, unverified)", medium)
    lines.append("}")
    lines.append(RESOLVER_CODE)
    OUTPUT_INDEX.write_text("\n".join(lines), encoding="utf-8")


# ── Main ───────────────────────────────────────────────────────────────────

def main(args):
    if not PROGRESS_PATH.exists():
        print(f"ERROR: {PROGRESS_PATH} not found.")
        print("Place authority_build_progress.json in this folder.")
        return 1

    progress = json.loads(PROGRESS_PATH.read_text(encoding="utf-8"))
    cases = progress.get("unresolved", [])
    # Dedup by (name, citation)
    seen = set()
    uniq = []
    for c in cases:
        key = (c.get("name", ""), c.get("citation", ""))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(c)
    cases = uniq

    if args.limit:
        cases = cases[: args.limit]
        print(f"CANARY: limiting to first {len(cases)} cases")

    state = load_scrape_state(args.fresh)
    already = {(r["name"], r["citation"]) for r in state["resolved"].values()}
    pending = [c for c in cases if (c["name"], c["citation"]) not in already]

    print(f"Total: {len(cases)} | already resolved: {len(already)} | pending: {len(pending)}")
    print(f"Delay: {REQUEST_DELAY_SECONDS}s/request | save every {SAVE_EVERY_N}")
    print(f"Estimated wall time: {len(pending) * REQUEST_DELAY_SECONDS * 2 / 60:.0f} min (best case)")
    print()

    t0 = time.time()
    n_ok = n_fail = 0

    for i, case in enumerate(pending, 1):
        try:
            tid, title, reason = resolve_one(case)
        except KeyboardInterrupt:
            print("\nInterrupted. Saving state...")
            save_scrape_state(state)
            write_index(state["resolved"])
            return 0
        except Exception as e:
            print(f"[{i:>4}] ERR {case.get('name','')[:50]}: {e}")
            state["failed"].append({**case, "error": str(e)})
            continue

        if tid:
            key = f"{case['name']}|{case['citation']}"
            state["resolved"][key] = {
                "tid": tid, "title": title, "name": case["name"],
                "citation": case["citation"], "doctrine": case.get("doctrine", ""),
                "reason": reason,
            }
            n_ok += 1
            print(f"[{i:>4}/{len(pending)}] OK  {case['name'][:50]:<50} -> {tid}  ({reason})")
        else:
            state["failed"].append({**case, "error": reason})
            n_fail += 1
            if i % 10 == 0 or n_fail <= 5:
                print(f"[{i:>4}/{len(pending)}] no  {case['name'][:50]:<50} ({reason})")

        if i % SAVE_EVERY_N == 0:
            save_scrape_state(state)
            write_index(state["resolved"])
            elapsed = time.time() - t0
            rate = i / elapsed if elapsed else 0
            eta = (len(pending) - i) / rate / 60 if rate else 0
            print(f"   ── saved | ok={n_ok} fail={n_fail} | {rate*60:.1f}/min | ETA {eta:.0f}min ──")

    save_scrape_state(state)
    write_index(state["resolved"])
    elapsed = time.time() - t0
    print()
    print("═" * 70)
    print(f"Done in {elapsed/60:.1f} min")
    print(f"Resolved this run: {n_ok}  failed: {n_fail}")
    print(f"Total resolved: {len(state['resolved'])}")
    print(f"Output: {OUTPUT_INDEX}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, help="Canary: process only first N cases")
    ap.add_argument("--fresh", action="store_true", help="Discard scrape progress")
    raise SystemExit(main(ap.parse_args()))
