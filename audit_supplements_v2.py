"""
Audit + safe cleanup of supplement misresolutions.

Stage 1: audit (as before) — fetch IK doc for each tid, compare to expected name.
Stage 2 (--remove): delete ONLY aliases derived from the BAD case names.
                    Tids that are correctly bound to OTHER cases are preserved.

Why this matters: a single bad tid may be shared with a correctly-resolved case.
Example: tid 172105947 is Arjun Panditrao (correct, manually fixed),
but the supplement script tagged Sonu @ Amar aliases to that same tid.
Removing aliases-by-tid would kill Arjun. Removing aliases-by-name kills only
Sonu's aliases.

Usage:
  python audit_supplements_v2.py            # audit only
  python audit_supplements_v2.py --remove   # remove bad alias names
"""
import argparse
import json
import re
import shutil
import sys
from difflib import SequenceMatcher
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE if (HERE / "authority_index.py").exists() else HERE.parent
INDEX_PATH = ROOT / "authority_index.py"
SUPP_STATE = ROOT / "authority_build" / "supplement_state.json"
AUDIT_OUT = ROOT / "authority_build" / "supplement_audit_v2.json"
BACKUP_PATH = INDEX_PATH.with_suffix(".py.pre_audit_v2.bak")

sys.path.insert(0, str(ROOT / "authority_build"))
from scraper.ik_client import IKClient
from scraper.extractors import parse_doc_page
from scraper.alias_utils import derive_aliases, _filter


def normalize_for_compare(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\s+on\s+\d+\s+\w+\s+\d{4}.*$", "", s)
    return s


def name_overlap(expected: str, actual: str) -> float:
    exp = set(normalize_for_compare(expected).split())
    act = set(normalize_for_compare(actual).split())
    stop = {"v", "vs", "and", "the", "of", "in", "ltd", "anr", "ors", "by", "lrs"}
    exp = exp - stop
    act = act - stop
    if not exp:
        return 1.0
    return len(exp & act) / len(exp)


def audit():
    if not SUPP_STATE.exists():
        print(f"ERROR: {SUPP_STATE} not found")
        return None

    supplement = json.loads(SUPP_STATE.read_text(encoding="utf-8"))
    resolved = supplement.get("resolved", {})
    print(f"Auditing {len(resolved)} entries\n")

    results = []
    client = IKClient()
    try:
        for i, (expected_name, info) in enumerate(resolved.items(), 1):
            tid = info.get("tid")
            if not tid:
                continue
            try:
                doc_html = client.doc(tid)
                doc = parse_doc_page(doc_html or "")
                actual_title = doc.get("title", "")
            except Exception as e:
                actual_title = f"<error: {e}>"
            overlap = name_overlap(expected_name, actual_title)
            seq_ratio = SequenceMatcher(None,
                                         normalize_for_compare(expected_name),
                                         normalize_for_compare(actual_title)).ratio()
            if overlap >= 0.5 or seq_ratio >= 0.5:
                verdict = "OK"
            elif overlap >= 0.3 or seq_ratio >= 0.3:
                verdict = "CHECK"
            else:
                verdict = "BAD"
            results.append({
                "expected_name": expected_name,
                "tid": tid,
                "actual_title": actual_title,
                "overlap": round(overlap, 2),
                "seq_ratio": round(seq_ratio, 2),
                "verdict": verdict,
            })
            mark = {"OK": "✓", "CHECK": "?", "BAD": "✗"}[verdict]
            print(f"[{i:>2}/{len(resolved)}] {mark} tid={tid}  overlap={overlap:.2f}")
            print(f"       expected: {expected_name[:70]}")
            print(f"       got:      {actual_title[:70]}\n")
    finally:
        client.close()

    AUDIT_OUT.write_text(json.dumps(results, indent=2, ensure_ascii=False),
                          encoding="utf-8")

    from collections import Counter
    verdicts = Counter(r["verdict"] for r in results)
    print(f"{'─'*60}")
    print(f"OK: {verdicts['OK']}  CHECK: {verdicts['CHECK']}  BAD: {verdicts['BAD']}")
    print(f"Audit saved: {AUDIT_OUT}")
    return results


def remove_bad_alias_lines(results):
    """
    For each BAD entry, derive the aliases that WOULD have been generated
    for its expected_name, and delete those alias lines from authority_index.py.
    Does NOT delete the tid itself or other correctly-bound aliases.
    """
    bad = [r for r in results if r["verdict"] == "BAD"]
    if not bad:
        print("No BAD entries — nothing to remove.")
        return

    # Build the set of aliases to delete
    aliases_to_delete = set()
    for r in bad:
        derived = derive_aliases(r["expected_name"])
        derived = _filter(set(derived))
        aliases_to_delete.update(derived)

    print(f"\n{'─'*60}")
    print(f"BAD entries: {len(bad)}")
    print(f"Total aliases derived from BAD names: {len(aliases_to_delete)}")
    print(f"\nSample aliases to delete (first 12):")
    for a in sorted(aliases_to_delete)[:12]:
        print(f"  {a!r}")

    # Read index, find lines matching those aliases
    text = INDEX_PATH.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    new_lines = []
    n_removed = 0
    removed_examples = []
    for line in lines:
        m = re.match(r'\s*"([^"]+)":\s*"(\d+)"', line)
        if m and m.group(1) in aliases_to_delete:
            n_removed += 1
            if len(removed_examples) < 5:
                removed_examples.append(f"  {m.group(1)!r}: {m.group(2)!r}")
            continue
        new_lines.append(line)

    if n_removed == 0:
        print("\nNothing to remove from index (aliases not found).")
        return

    new_text = "".join(new_lines)
    before_count = len(re.findall(r'"([^"]+)":\s*"\d+"', text))
    after_count = len(re.findall(r'"([^"]+)":\s*"\d+"', new_text))

    print(f"\nWill remove {n_removed} alias lines.")
    print(f"  Aliases before: {before_count}")
    print(f"  Aliases after:  {after_count}")
    print(f"\nFirst removals:")
    for e in removed_examples:
        print(e)

    confirm = input("\nProceed? (yes/no): ").strip().lower()
    if confirm != "yes":
        print("Aborted.")
        return

    shutil.copy2(INDEX_PATH, BACKUP_PATH)
    print(f"Backup: {BACKUP_PATH.name}")
    INDEX_PATH.write_text(new_text, encoding="utf-8")
    print(f"Done. Removed {n_removed} bad-alias lines.")
    print(f"Tids preserved for any correctly-bound aliases that point to them.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--remove", action="store_true")
    ap.add_argument("--audit-from-file", action="store_true",
                    help="Skip IK fetches, load previous audit from supplement_audit_v2.json")
    args = ap.parse_args()

    if args.audit_from_file and AUDIT_OUT.exists():
        results = json.loads(AUDIT_OUT.read_text(encoding="utf-8"))
        print(f"Loaded previous audit: {len(results)} entries")
    else:
        results = audit()
        if results is None:
            return 1

    if args.remove:
        remove_bad_alias_lines(results)


if __name__ == "__main__":
    raise SystemExit(main())
