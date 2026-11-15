"""
Apply single_word_audit.csv decisions to authority_index.py.

Reads the CSV's 'keep' column:
  Y = keep alias (no change)
  N = drop alias (line removed from authority_index.py)
  blank or other = treated as KEEP (safe default — never silently drop)

Writes:
  authority_index.py.bak   — backup before modification
  authority_index.py       — updated, with rejected aliases removed
"""
import csv
import re
import shutil
from pathlib import Path

HERE = Path(__file__).parent
INDEX_PATH = HERE.parent / "authority_index.py"
AUDIT_CSV  = HERE / "single_word_audit.csv"
BACKUP_PATH = HERE.parent / "authority_index.py.bak"


def main():
    if not AUDIT_CSV.exists():
        print(f"ERROR: {AUDIT_CSV} not found. Run audit_single_word_aliases.py first.")
        return 1
    if not INDEX_PATH.exists():
        print(f"ERROR: {INDEX_PATH} not found.")
        return 1

    # Read audit decisions
    drops = set()
    keeps = 0
    with AUDIT_CSV.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            decision = (row.get("keep") or "").strip().upper()
            if decision == "N":
                drops.add(row["alias"])
            else:
                keeps += 1

    if not drops:
        print("No aliases marked for drop. Nothing to do.")
        return 0

    print(f"Aliases to drop: {len(drops)}")
    print(f"Aliases to keep: {keeps}")
    print()
    print("Sample drops:", sorted(drops)[:10])
    print()
    confirm = input("Proceed? (yes/no): ").strip().lower()
    if confirm != "yes":
        print("Aborted.")
        return 0

    # Backup
    shutil.copy2(INDEX_PATH, BACKUP_PATH)
    print(f"Backup: {BACKUP_PATH}")

    # Process line by line
    lines = INDEX_PATH.read_text(encoding="utf-8").splitlines(keepends=True)
    out_lines = []
    n_removed = 0
    entry_re = re.compile(r'^\s*"([^"]+)":\s*"(\d+)"')
    for line in lines:
        m = entry_re.match(line)
        if m and m.group(1) in drops:
            n_removed += 1
            continue
        out_lines.append(line)

    INDEX_PATH.write_text("".join(out_lines), encoding="utf-8")

    # Update the header counts (rough — total only)
    text = INDEX_PATH.read_text(encoding="utf-8")
    new_total = len(re.findall(r'^\s*"[^"]+":\s*"\d+"', text, re.MULTILINE))
    text = re.sub(
        r"Total aliases:\s*\d+",
        f"Total aliases: {new_total}",
        text,
        count=1,
    )
    text = re.sub(
        r"HIGH:\s+\d+",
        f"HIGH:   {new_total}",
        text,
        count=1,
    )
    INDEX_PATH.write_text(text, encoding="utf-8")

    print(f"Done. Removed {n_removed} alias lines.")
    print(f"New total aliases: {new_total}")
    print(f"If something went wrong: copy {BACKUP_PATH.name} back over authority_index.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
