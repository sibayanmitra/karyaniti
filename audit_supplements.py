"""
Audit supplement_state.json: for each resolved case, fetch IK's doc title
and compare against what we expected. Flag mismatches.

A "mismatch" is when the recorded tid points to a DIFFERENT case than the
one we asked the resolver to find. This catches the body-citation
matching bug where case A's tid was returned because A's body cites B.

Cost: ₹0. ~5-10 min for 47 cases.

Usage:
  python audit_supplements.py            # report only
  python audit_supplements.py --remove   # remove confirmed bad entries from index
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
AUDIT_OUT = ROOT / "authority_build" / "supplement_audit.json"
BACKUP_PATH = INDEX_PATH.with_suffix(".py.pre_audit_clean.bak")

sys.path.insert(0, str(ROOT / "authority_build"))
from scraper.ik_client import IKClient
from scraper.extractors import parse_doc_page


def normalize_for_compare(s: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    s = (s or "").lower()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    # Drop date-suffix "on 14 july 2020" patterns
    s = re.sub(r"\s+on\s+\d+\s+\w+\s+\d{4}.*$", "", s)
    return s


def name_overlap(expected: str, actual: str) -> float:
    """Token-overlap ratio. Higher = more likely same case."""
    exp = set(normalize_for_compare(expected).split())
    act = set(normalize_for_compare(actual).split())
    # Drop short connector words that match anything
    stop = {"v", "vs", "and", "the", "of", "in", "ltd", "anr", "ors", "by", "lrs"}
    exp = exp - stop
    act = act - stop
    if not exp:
        return 1.0
    return len(exp & act) / len(exp)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--remove", action="store_true",
                    help="After audit, remove confirmed-bad entries from authority_index.py")
    args = ap.parse_args()

    if not SUPP_STATE.exists():
        print(f"ERROR: {SUPP_STATE} not found")
        return 1

    supplement = json.loads(SUPP_STATE.read_text(encoding="utf-8"))
    resolved = supplement.get("resolved", {})
    print(f"Auditing {len(resolved)} supplement entries\n")

    audit_results = []
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
                actual_source = doc.get("source", "")
            except Exception as e:
                actual_title = f"<error: {e}>"
                actual_source = ""

            overlap = name_overlap(expected_name, actual_title)
            # SequenceMatcher as a second signal
            seq_ratio = SequenceMatcher(None,
                                         normalize_for_compare(expected_name),
                                         normalize_for_compare(actual_title)).ratio()

            # Verdict
            if overlap >= 0.5 or seq_ratio >= 0.5:
                verdict = "OK"
            elif overlap >= 0.3 or seq_ratio >= 0.3:
                verdict = "CHECK"
            else:
                verdict = "BAD"

            audit_results.append({
                "expected_name": expected_name,
                "tid": tid,
                "actual_title": actual_title,
                "actual_source": actual_source,
                "overlap": round(overlap, 2),
                "seq_ratio": round(seq_ratio, 2),
                "verdict": verdict,
            })

            mark = {"OK": "✓", "CHECK": "?", "BAD": "✗"}[verdict]
            print(f"[{i:>2}/{len(resolved)}] {mark} tid={tid}  "
                  f"overlap={overlap:.2f}  seq={seq_ratio:.2f}")
            print(f"       expected: {expected_name[:70]}")
            print(f"       got:      {actual_title[:70]}")
            if actual_source:
                print(f"       source:   {actual_source}")
            print()
    finally:
        client.close()

    # Save audit
    AUDIT_OUT.write_text(json.dumps(audit_results, indent=2, ensure_ascii=False),
                          encoding="utf-8")

    from collections import Counter
    verdicts = Counter(r["verdict"] for r in audit_results)
    print(f"{'─'*60}")
    print(f"OK:    {verdicts['OK']}")
    print(f"CHECK: {verdicts['CHECK']}  (manual review)")
    print(f"BAD:   {verdicts['BAD']}  (likely misresolutions)")
    print(f"\nFull audit: {AUDIT_OUT}")

    bad = [r for r in audit_results if r["verdict"] == "BAD"]
    if bad:
        print(f"\n{'─'*60}")
        print("BAD entries (need removal from index):")
        for r in bad:
            print(f"  tid={r['tid']}")
            print(f"    expected: {r['expected_name']}")
            print(f"    actually: {r['actual_title']}")

    if args.remove and bad:
        print(f"\n{'─'*60}")
        bad_tids = {r["tid"] for r in bad}
        text = INDEX_PATH.read_text(encoding="utf-8")
        before_count = len(re.findall(r'"([^"]+)":\s*"\d+"', text))

        lines = text.splitlines(keepends=True)
        new_lines = []
        n_removed = 0
        for line in lines:
            m = re.match(r'\s*"([^"]+)":\s*"(\d+)"', line)
            if m and m.group(2) in bad_tids:
                n_removed += 1
                continue
            new_lines.append(line)

        new_text = "".join(new_lines)
        after_count = len(re.findall(r'"([^"]+)":\s*"\d+"', new_text))

        print(f"Will remove {n_removed} alias lines from index")
        print(f"  Aliases before: {before_count}")
        print(f"  Aliases after:  {after_count}")
        confirm = input("\nProceed? (yes/no): ").strip().lower()
        if confirm == "yes":
            shutil.copy2(INDEX_PATH, BACKUP_PATH)
            print(f"Backup: {BACKUP_PATH.name}")
            INDEX_PATH.write_text(new_text, encoding="utf-8")
            print(f"Done. Removed {n_removed} bad-tid aliases.")
        else:
            print("Aborted.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
