"""Alias generation from case names + parallel citations. Pollution-aware."""
import re

_HONORIFICS = {"shri", "smt", "mr", "mrs", "ms", "dr", "prof"}

_GENERIC = {
    "state", "union", "india", "of", "the", "and", "anr", "ors",
    "ltd", "limited", "co", "pvt", "private", "corp", "corporation",
    "singh", "kumar", "patel", "sharma", "rao", "devi", "lal", "das",
    "khan", "ram", "shah", "yadav", "verma", "gupta", "agarwal",
    "company", "association", "society", "trust", "board", "council",
    "ministry", "department", "government", "ch", "sri",
}


def normalize(s: str) -> str:
    s = (s or "").lower().replace(".", " ")
    return re.sub(r"\s+", " ", s).strip()


def derive_aliases(name: str, citations: list[str] | None = None) -> list[str]:
    """Multi-token aliases from name, plus citations themselves. No solo generic words."""
    out = set()
    norm = normalize(name)
    if norm and norm not in _GENERIC:
        out.add(norm)
    parts = re.split(r"\bv\.?s?\.?\b", name, flags=re.I)
    for party in (normalize(p) for p in parts if p.strip()):
        toks = [t for t in party.split() if t not in _HONORIFICS and len(t) >= 2]
        if not toks:
            continue
        if len(toks) >= 2:
            for j in (2, 3):
                if len(toks) >= j:
                    candidate = " ".join(toks[:j])
                    if candidate not in _GENERIC:
                        out.add(candidate)
        full_party = " ".join(toks)
        if full_party and full_party not in _GENERIC:
            out.add(full_party)
    # Add citations directly — "(2018) 1 SCC 353" should resolve to the case
    if citations:
        for c in citations:
            c_norm = normalize(c)
            if c_norm and len(c_norm) >= 8:
                out.add(c_norm)
    return sorted(_filter(out))


def _filter(aliases: set[str]) -> set[str]:
    final = set()
    for a in aliases:
        if len(a) < 4:
            continue
        if " " in a:
            final.add(a)
        elif a not in _GENERIC and len(a) >= 5:
            final.add(a)
    return final


def merge_alias_map(target: dict, new_aliases: list[str], tid: str, info: dict) -> int:
    """
    Add new_aliases -> tid in target. If an alias already maps to a DIFFERENT tid,
    mark it ambiguous (set to None) so future lookups skip it. Returns count added.
    """
    n = 0
    for a in new_aliases:
        if a in target:
            existing = target[a]
            if existing is None or existing["tid"] == tid:
                continue
            # Collision with different tid — kill the alias
            target[a] = None
        else:
            target[a] = {"tid": tid, "info": info}
            n += 1
    return n
