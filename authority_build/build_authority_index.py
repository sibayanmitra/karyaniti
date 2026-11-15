"""
Build authority_index.py and treatment_status.py from doctrine_seed.

Concurrent generation + resolution, resumable mid-run, cost tracking.

Run from inside authority_build/:
    python build_authority_index.py
Resume:
    python build_authority_index.py
Fresh start (discard progress):
    python build_authority_index.py --fresh
"""
import argparse, asyncio, json, re, time
from pathlib import Path
from doctrine_seed import DOCTRINES
from llm_client import llm, parse_json, IK_TOKEN, OR_KEY
from prompts import GEN_PROMPT
from resolver import resolve_case

GENERATOR_MODEL = "deepseek/deepseek-v4-pro"

GEN_CONCURRENCY     = 10   # parallel doctrine generations
RESOLVE_CONCURRENCY = 8    # parallel case resolutions within a doctrine

# Output files write to parent directory (where main.py lives)
PARENT = Path(__file__).parent.parent
OUTPUT_INDEX     = PARENT / "authority_index.py"
OUTPUT_TREATMENT = PARENT / "treatment_status.py"
PROGRESS_PATH    = Path(__file__).parent / "authority_build_progress.json"

PRICE_IN  = 0.435 / 1_000_000   # V4 Pro pricing
PRICE_OUT = 0.87  / 1_000_000

_token_in = _token_out = _call_count = 0


# ── Generation ─────────────────────────────────────────────────────────────

async def list_landmark_cases(doctrine: str) -> list[dict]:
    global _token_in, _token_out, _call_count
    try:
        raw, usage = await llm(GENERATOR_MODEL, GEN_PROMPT.format(doctrine=doctrine), max_tokens=2200)
        _token_in  += int(usage.get("prompt_tokens", 0))
        _token_out += int(usage.get("completion_tokens", 0))
        _call_count += 1
        obj = parse_json(raw)
        cases = obj.get("cases", []) if isinstance(obj.get("cases"), list) else []
        return [c for c in cases if isinstance(c, dict) and c.get("name")]
    except Exception as e:
        print(f"   GEN FAIL [{doctrine[:50]}]: {e}")
        return []


# ── Aliases ────────────────────────────────────────────────────────────────

_HONORIFICS = {"shri", "smt", "mr", "mrs", "ms", "dr", "prof", "the", "state", "union"}


def _normalize(s: str) -> str:
    s = (s or "").lower().replace(".", " ")
    return re.sub(r"\s+", " ", s).strip()


def derive_aliases(name: str) -> list[str]:
    """Generate surname/short-form aliases from full case name."""
    out = set()
    out.add(_normalize(name))
    parts = re.split(r"\bv\.?s?\.?\b", name, flags=re.I)
    for party in (p.strip() for p in parts if p.strip()):
        norm = _normalize(party)
        toks = [t for t in norm.split() if t not in _HONORIFICS and len(t) >= 2]
        if not toks:
            continue
        out.add(" ".join(toks))
        if len(toks[-1]) >= 4 and not toks[-1].isdigit():
            out.add(toks[-1])
        if len(toks) >= 2:
            out.add(" ".join(toks[:2]))
    return sorted({a for a in out if a and len(a) >= 3 and a not in _HONORIFICS})


# ── Progress + output ──────────────────────────────────────────────────────

def load_progress(fresh: bool) -> dict:
    if fresh and PROGRESS_PATH.exists():
        PROGRESS_PATH.unlink()
    if PROGRESS_PATH.exists():
        try:
            return json.loads(PROGRESS_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print("Progress file corrupt — starting fresh")
    return {"completed_doctrines": [], "resolved": {}, "treatment": {}, "unresolved": []}


def save_progress(state: dict):
    tmp = PROGRESS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(PROGRESS_PATH)


RESOLVER_CODE = '''
import re

def _normalize(s: str) -> str:
    s = (s or "").lower().replace(".", " ")
    return re.sub(r"\\s+", " ", s).strip()


def resolve_case_name(variant: str):
    """Extract leading capitalized case-name tokens and look up doc_id."""
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


def write_outputs(state: dict):
    resolved: dict[str, dict] = state["resolved"]
    high, medium = [], []
    for alias, info in sorted(resolved.items()):
        if (info or {}).get("confidence") == "HIGH":
            high.append((alias, info))
        else:
            medium.append((alias, info))

    lines = [
        '"""',
        'Auto-generated by authority_build/build_authority_index.py',
        'Do not edit by hand. Re-run the builder to regenerate.',
        '',
        f'Aliases:  {len(resolved)}',
        f'  HIGH:   {len(high)} (verifier + citation match)',
        f'  MEDIUM: {len(medium)} (verifier match only)',
        '"""',
        "",
        "AUTHORITY_INDEX: dict[str, str] = {",
    ]

    def _emit(label, items):
        if not items:
            return
        lines.append(f"    # ── {label} confidence ──")
        for alias, info in items:
            doc_id = (info or {}).get("doc_id", "")
            title  = (info or {}).get("matched_title", "")[:70]
            comment = f"  # {title}" if title else ""
            lines.append(f'    "{alias}": "{doc_id}",{comment}')

    _emit("HIGH", high)
    _emit("MEDIUM", medium)
    lines.append("}")
    lines.append("")
    lines.append(RESOLVER_CODE)
    OUTPUT_INDEX.write_text("\n".join(lines), encoding="utf-8")

    treatment = state.get("treatment", {})
    if treatment:
        t_lines = ['"""Auto-generated. Treatment status per doc_id."""', "",
                   "TREATMENT_STATUS: dict[str, str] = {"]
        for did, status in sorted(treatment.items()):
            t_lines.append(f'    "{did}": "{status}",')
        t_lines.append("}")
        OUTPUT_TREATMENT.write_text("\n".join(t_lines), encoding="utf-8")


# ── Orchestration ─────────────────────────────────────────────────────────

async def process_doctrine(doctrine: str, state: dict, sem_resolve: asyncio.Semaphore):
    cases = await list_landmark_cases(doctrine)
    if not cases:
        return 0, 0

    async def _resolve_one(case):
        async with sem_resolve:
            return case, await resolve_case(case, doctrine)

    results = await asyncio.gather(*[_resolve_one(c) for c in cases])
    n_ok = n_fail = 0
    for case, info in results:
        if not info or not info.get("doc_id"):
            state["unresolved"].append({"name": case.get("name", ""),
                                        "doctrine": doctrine,
                                        "citation": case.get("citation", "")})
            n_fail += 1
            continue
        doc_id = info["doc_id"]
        if info.get("treatment_status") and info["treatment_status"] != "good_law":
            state["treatment"][doc_id] = info["treatment_status"]
        all_aliases = set(info.get("aliases", []) or []) | set(derive_aliases(info["name"]))
        rank_map = {"HIGH": 0, "MEDIUM": 1}
        for a in all_aliases:
            norm = _normalize(a)
            if not norm or len(norm) < 3:
                continue
            existing = state["resolved"].get(norm)
            if existing and rank_map.get(existing.get("confidence", "MEDIUM"), 1) <= rank_map.get(info["confidence"], 1):
                continue
            state["resolved"][norm] = info
        n_ok += 1
    return n_ok, n_fail


async def main(args):
    if not IK_TOKEN or not OR_KEY:
        print("ERROR: INDIAN_KANOON_API_TOKEN or OPENROUTER_API_KEY missing in .env")
        return 1

    state = load_progress(args.fresh)
    completed = set(state["completed_doctrines"])
    pending = [d for d in DOCTRINES if d not in completed]

    print(f"Total: {len(DOCTRINES)}  done: {len(completed)}  pending: {len(pending)}")
    print(f"Generator: {GENERATOR_MODEL}  |  concurrency gen={GEN_CONCURRENCY} resolve={RESOLVE_CONCURRENCY}")
    print()

    sem_gen = asyncio.Semaphore(GEN_CONCURRENCY)
    sem_resolve = asyncio.Semaphore(RESOLVE_CONCURRENCY)
    t0 = time.time()
    total_ok = total_fail = 0

    async def _one(idx: int, doctrine: str):
        nonlocal total_ok, total_fail
        async with sem_gen:
            t_start = time.time()
            try:
                ok, fail = await process_doctrine(doctrine, state, sem_resolve)
            except Exception as e:
                print(f"[{idx:>3}] {doctrine[:55]:<55} CRASHED: {e}")
                return
        total_ok += ok
        total_fail += fail
        completed.add(doctrine)
        state["completed_doctrines"] = sorted(completed)
        save_progress(state)
        write_outputs(state)
        cost = _token_in * PRICE_IN + _token_out * PRICE_OUT
        print(f"[{idx:>3}/{len(pending)}] {doctrine[:55]:<55} +{ok:>2}✓/{fail:>2}✗  "
              f"{time.time()-t_start:5.1f}s  ${cost:.3f}  aliases={len(state['resolved'])}")

    await asyncio.gather(*[_one(i+1, d) for i, d in enumerate(pending)])

    elapsed = time.time() - t0
    final_cost = _token_in * PRICE_IN + _token_out * PRICE_OUT
    print()
    print("═" * 70)
    print(f"Done in {elapsed:.1f}s ({elapsed/60:.1f} min)")
    print(f"LLM calls: {_call_count}  in: {_token_in:,}  out: {_token_out:,}  ${final_cost:.3f}")
    print(f"Resolved aliases: {len(state['resolved'])}")
    print(f"Unresolved cases: {len(state['unresolved'])}")
    print(f"Treatment flags:  {len(state['treatment'])}")
    print(f"Output:  {OUTPUT_INDEX}")
    if state["treatment"]:
        print(f"Output:  {OUTPUT_TREATMENT}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fresh", action="store_true", help="Discard progress, start over")
    raise SystemExit(asyncio.run(main(ap.parse_args())))
