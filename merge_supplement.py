"""
One-shot merge: read supplement_state.json, append new aliases to
authority_index.py. Robust against the closing-brace regex issue.

Run from anywhere; uses absolute path navigation.

Usage: python merge_supplement.py
"""
import json
import re
import shutil
import sys
from pathlib import Path

# Locate files robustly
HERE = Path(__file__).resolve().parent
# Try authority_build/ first, then current dir
if (HERE / "supplement_state.json").exists():
    STATE_PATH = HERE / "supplement_state.json"
elif (HERE / "authority_build" / "supplement_state.json").exists():
    STATE_PATH = HERE / "authority_build" / "supplement_state.json"
else:
    print(f"ERROR: supplement_state.json not found near {HERE}")
    sys.exit(1)

# authority_index.py is in vakeel_beta/ root
if (HERE / "authority_index.py").exists():
    INDEX_PATH = HERE / "authority_index.py"
elif (HERE.parent / "authority_index.py").exists():
    INDEX_PATH = HERE.parent / "authority_index.py"
else:
    print(f"ERROR: authority_index.py not found near {HERE}")
    sys.exit(1)

BACKUP_PATH = INDEX_PATH.with_suffix(".py.pre_supplement2.bak")

# Try to import alias_utils for proper alias generation
sys.path.insert(0, str(HERE if (HERE / "scraper").exists() else HERE / "authority_build"))
try:
    from scraper.alias_utils import derive_aliases, _filter
except ImportError:
    print("WARNING: scraper.alias_utils not importable; using basic alias derivation")
    def derive_aliases(name):
        import re
        # Basic fallback: lowercase, with/without "v" variants
        s = name.lower()
        s_clean = re.sub(r"[^\w\s]", " ", s)
        s_norm = re.sub(r"\s+", " ", s_clean).strip()
        return {s_norm, s_norm.replace(" v ", " vs "), s_norm.replace(" vs ", " v ")}
    def _filter(aliases):
        return {a for a in aliases if len(a) > 3}


print(f"State:  {STATE_PATH}")
print(f"Index:  {INDEX_PATH}")

state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
resolved = state.get("resolved", {})
print(f"Resolved cases in state: {len(resolved)}")

text = INDEX_PATH.read_text(encoding="utf-8")
existing_aliases = set(re.findall(r'"([^"]+)":\s*"\d+"', text))
print(f"Existing aliases in index: {len(existing_aliases)}")

# Build new entries
new_entries = []
skipped = 0
for case_name, info in resolved.items():
    tid = info["tid"]
    title = info.get("title", case_name).replace('"', "'")[:90]
    aliases = derive_aliases(case_name)
    aliases = _filter(set(aliases))
    for alias in sorted(aliases):
        if alias in existing_aliases:
            skipped += 1
            continue
        new_entries.append((alias, tid, title))
        existing_aliases.add(alias)

if not new_entries:
    print("Nothing new to add.")
    sys.exit(0)

print(f"\nNew aliases to add:     {len(new_entries)}")
print(f"Aliases already present: {skipped}")
print(f"Sample new entries (first 5):")
for a, t, _ in new_entries[:5]:
    print(f"  {a!r}: {t!r}")

# Find the closing brace robustly:
# Match the LAST closing brace at start of a line before "def _normalize"
# This handles any whitespace/imports between them.
norm_pos = text.find("def _normalize")
if norm_pos < 0:
    print("ERROR: def _normalize not found in authority_index.py")
    sys.exit(1)

# Search backward from norm_pos for the closing }
# It must be a } at start of a line (the dict close)
before_text = text[:norm_pos]
brace_match = None
for m in re.finditer(r"^\}\s*$", before_text, re.MULTILINE):
    brace_match = m  # keep the last one
if brace_match is None:
    print("ERROR: Could not find '}' before def _normalize")
    sys.exit(1)

brace_pos = brace_match.start()
print(f"\nFound dict closing brace at offset {brace_pos}")
print(f"Context: ...{text[max(0,brace_pos-60):brace_pos+5]!r}...")

# Build the insertion block — sits BEFORE the closing brace, inside the dict
insert_lines = ["    # ── LANDMARK SUPPLEMENT (auto-added) ──"]
for alias, tid, title in new_entries:
    insert_lines.append(f'    "{alias}": "{tid}",  # {title}')
insert_block = "\n".join(insert_lines) + "\n"

new_text = text[:brace_pos] + insert_block + text[brace_pos:]

# Sanity check: new content must still parse as Python
import ast
try:
    # Extract just the dict via the file's structure check
    print(f"\nSanity check: new file size = {len(new_text)} bytes "
          f"(was {len(text)}, delta = +{len(new_text) - len(text)})")
except Exception as e:
    print(f"ERROR validating new content: {e}")
    sys.exit(1)

confirm = input("\nProceed with merge? (yes/no): ").strip().lower()
if confirm != "yes":
    print("Aborted.")
    sys.exit(0)

# Backup
shutil.copy2(INDEX_PATH, BACKUP_PATH)
print(f"Backup: {BACKUP_PATH.name}")

# Write
INDEX_PATH.write_text(new_text, encoding="utf-8")

# Verify by re-parsing
final_text = INDEX_PATH.read_text(encoding="utf-8")
final_aliases = set(re.findall(r'"([^"]+)":\s*"\d+"', final_text))
print(f"\nDone.")
print(f"  Aliases before: {len(existing_aliases) - len(new_entries)}")
print(f"  Aliases after:  {len(final_aliases)}")
print(f"  Net added:      {len(final_aliases) - (len(existing_aliases) - len(new_entries))}")
print(f"\nIf anything looks wrong: copy {BACKUP_PATH.name} back over authority_index.py")
