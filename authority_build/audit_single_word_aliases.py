"""
Audit single-word aliases in authority_index.py for collision risk.

Outputs `single_word_audit.csv` with columns:
  alias | tid | case_title | risk | suggestion | keep (Y/N — fill manually)

After review, run apply_audit.py to drop rejected aliases.
"""
import csv
import re
from pathlib import Path

HERE = Path(__file__).parent
INDEX_PATH = HERE.parent / "authority_index.py"   # vakeel_beta/authority_index.py
OUTPUT_CSV = HERE / "single_word_audit.csv"

# Common English / Indian-language words that should NEVER be aliases —
# they will trigger false positives on any query containing them.
DEFINITE_DROP = {
    "collector", "customs", "commissioner", "secretary", "director",
    "company", "board", "council", "ministry", "department", "government",
    "managing", "registrar", "principal", "chairman", "officer",
    "the", "state", "union", "india", "national", "central", "regional",
    "ramesh", "rajesh", "suresh", "ramesh", "satish", "vijay", "ajay", "anil", "amit",
    "george", "thomas", "joseph", "abraham", "alexander", "lewis", "kapoor", "kapur",
    "karim", "khan", "ali", "abdul", "salim", "ashfaq", "haroon", "rafiq",
    "ram", "krishna", "shanti", "lakshmi", "radha", "sita", "gita", "kamla",
    "patel", "sharma", "rao", "singh", "kumar", "lal", "das", "shah", "verma",
    "chowdhary", "chowdhuri", "mukherjee", "bhattacharjee", "banerjee", "agarwal",
    "agrawal", "gupta", "yadav", "mishra", "tiwari", "pandey", "joshi",
    "deepa", "meena", "anita", "rekha", "sunita", "rashmi", "neeta", "rita",
}

# These are case names that ARE legitimate single-word references in legal usage.
# Audit will pre-suggest KEEP.
DEFINITE_KEEP = {
    "bhajan lal",  # multi-word, here as marker
    "antulay", "puttaswamy", "selvi", "nakara", "khatri",
    "balchand", "bhagirath", "bachan singh",
    "shayara bano",
    "ayyasamy", "mhetre",
    "machhi singh", "gurmit singh",
    "bhatia", "balco",  # arbitration
    "anvar", "rangarajan",
    "bhagat", "dastane",  # divorce
    "khujji",
}

VARIANTS_OK = {"-", "@", "(", ")"}  # aliases with hyphens, like "andi-mukta" — typically real


def is_single_word(alias: str) -> bool:
    """Treat as single-word if it has no space AND no digit (citations excluded)."""
    if any(c.isdigit() for c in alias):
        return False
    if " " in alias:
        return False
    return True


def classify(alias: str) -> tuple[str, str]:
    """Return (risk_level, suggestion)."""
    a = alias.lower().strip()
    if a in DEFINITE_DROP:
        return ("HIGH", "DROP")
    if a in DEFINITE_KEEP:
        return ("LOW", "KEEP")
    if len(a) <= 4:
        return ("HIGH", "DROP — too short")
    if len(a) >= 9:
        return ("LOW", "KEEP — distinctive")
    # 5-8 chars: medium risk, manual review
    if a.endswith("nath") or a.endswith("singh") or a.endswith("kumar"):
        return ("HIGH", "DROP — common surname pattern")
    return ("MEDIUM", "REVIEW")


def main():
    if not INDEX_PATH.exists():
        print(f"ERROR: {INDEX_PATH} not found.")
        print("Run this from inside authority_build/.")
        return 1

    text = INDEX_PATH.read_text(encoding="utf-8")

    # Parse alias -> (tid, comment) — comment has the case title
    entry_re = re.compile(r'"([^"]+)":\s*"(\d+)"\s*,\s*#\s*(.+?)$', re.MULTILINE)
    rows = []
    for m in entry_re.finditer(text):
        alias = m.group(1)
        tid   = m.group(2)
        title = m.group(3).strip()
        if not is_single_word(alias):
            continue
        risk, suggestion = classify(alias)
        rows.append({
            "alias": alias,
            "tid": tid,
            "case_title": title[:80],
            "risk": risk,
            "suggestion": suggestion,
            "keep": "Y" if suggestion.startswith("KEEP") else ("N" if "DROP" in suggestion else ""),
        })

    # Sort: HIGH first (most dangerous), then MEDIUM, then LOW
    risk_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    rows.sort(key=lambda r: (risk_order[r["risk"]], r["alias"]))

    with OUTPUT_CSV.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["alias", "tid", "case_title", "risk", "suggestion", "keep"])
        writer.writeheader()
        writer.writerows(rows)

    high   = sum(1 for r in rows if r["risk"] == "HIGH")
    medium = sum(1 for r in rows if r["risk"] == "MEDIUM")
    low    = sum(1 for r in rows if r["risk"] == "LOW")

    print(f"Single-word alias audit complete.")
    print(f"Total: {len(rows)}")
    print(f"  HIGH risk    (pre-marked DROP): {high}")
    print(f"  MEDIUM risk  (need review):     {medium}")
    print(f"  LOW risk     (pre-marked KEEP): {low}")
    print()
    print(f"Output: {OUTPUT_CSV}")
    print()
    print("Next steps:")
    print(f"  1. Open {OUTPUT_CSV.name} in Excel/LibreOffice")
    print(f"  2. Review the 'keep' column. Y = keep alias, N = drop it")
    print(f"  3. Focus attention on MEDIUM rows (pre-filled blank)")
    print(f"  4. HIGH rows are pre-marked N — only change if you know better")
    print(f"  5. Save, then run: python apply_audit.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
