"""
Remove aliases derived from the 7 CHECK-verdict misresolutions.

All 7 are confirmed wrong — the supplement script returned tids of cases
that CITE the expected case, not the case itself. Same body-citation bug.

This deletes ONLY aliases derived from the bad case names, preserving any
correctly-bound aliases on those tids (e.g. Arjun Panditrao stays on
tid 172105947; Sonu @ Amar aliases get removed).
"""
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE if (HERE / "authority_index.py").exists() else HERE.parent
INDEX_PATH = ROOT / "authority_index.py"
BACKUP_PATH = INDEX_PATH.with_suffix(".py.pre_check_cleanup.bak")

sys.path.insert(0, str(ROOT / "authority_build"))
from scraper.alias_utils import derive_aliases, _filter

# The 7 CHECK entries — same body-citation bug as the 10 BAD ones
BAD_NAMES = [
    "Cox and Kings Ltd v SAP India Pvt Ltd",
    "Sonu @ Amar v State of Haryana",
    "In Re Interplay between Arbitration Agreements and Stamp Act",
    "Centrotrade Minerals and Metal Inc v Hindustan Copper Ltd",
    "PASL Wind Solutions v GE Power Conversion",
    "Hiralal Patni v Sri Kali Nath",
    "State (Delhi Administration) v Pali Ram",
]

aliases_to_delete = set()
for name in BAD_NAMES:
    derived = derive_aliases(name)
    derived = _filter(set(derived))
    aliases_to_delete.update(derived)

print(f"Aliases derived from {len(BAD_NAMES)} bad names: {len(aliases_to_delete)}")
print(f"\nSample (first 15):")
for a in sorted(aliases_to_delete)[:15]:
    print(f"  {a!r}")

text = INDEX_PATH.read_text(encoding="utf-8")
lines = text.splitlines(keepends=True)
new_lines = []
n_removed = 0
removed_examples = []
for line in lines:
    m = re.match(r'\s*"([^"]+)":\s*"(\d+)"', line)
    if m and m.group(1) in aliases_to_delete:
        n_removed += 1
        if len(removed_examples) < 8:
            removed_examples.append(f"  {m.group(1)!r}: {m.group(2)!r}")
        continue
    new_lines.append(line)

before = len(re.findall(r'"([^"]+)":\s*"\d+"', text))
after = before - n_removed

print(f"\nWill remove {n_removed} alias lines.")
print(f"  Before: {before}")
print(f"  After:  {after}")
print(f"\nFirst removals:")
for e in removed_examples:
    print(e)

confirm = input("\nProceed? (yes/no): ").strip().lower()
if confirm != "yes":
    print("Aborted.")
    sys.exit(0)

shutil.copy2(INDEX_PATH, BACKUP_PATH)
print(f"Backup: {BACKUP_PATH.name}")
INDEX_PATH.write_text("".join(new_lines), encoding="utf-8")
print(f"Done. Removed {n_removed} alias lines.")
