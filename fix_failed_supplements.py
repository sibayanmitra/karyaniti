"""
Interactive resolver for the 14 cases that failed citation-phrase search.

For each case:
  - Searches IK by case NAME (not citation — more forgiving)
  - Shows top 5 SC results with tid + title
  - You pick: number (1-5), or paste a tid/URL, or skip

Then merges accepted picks into authority_index.py.

Cost: ₹0. Free IK public scraping. ~15-25 min for all 14.

Usage:
  python fix_failed_supplements.py
"""
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE if (HERE / "authority_index.py").exists() else HERE.parent
INDEX_PATH = ROOT / "authority_index.py"
BACKUP_PATH = INDEX_PATH.with_suffix(".py.pre_fix_failed.bak")

sys.path.insert(0, str(ROOT / "authority_build"))
from scraper.ik_client import IKClient
from scraper.extractors import parse_search_results, is_supreme_court, parse_doc_page
from scraper.alias_utils import derive_aliases, _filter

# The 14 failures, with search queries optimized for name-based search
FAILED_CASES = [
    {"name": "Arjun Panditrao Khotkar v Kailash Kushanrao Gorantyal",
     "citation": "(2020) 7 SCC 1",
     "search": "Arjun Panditrao Khotkar Kailash Kushanrao Gorantyal"},
    {"name": "Vijay Madanlal Choudhary v Union of India",
     "citation": "(2022) SCC OnLine SC 929",
     "search": "Vijay Madanlal Choudhary Union of India PMLA"},
    {"name": "Ravinder Singh Kaku v State of Punjab",
     "citation": "(2022) 7 SCC 581",
     "search": "Ravinder Singh Kaku State of Punjab"},
    {"name": "Voestalpine Schienen v Delhi Metro Rail Corporation",
     "citation": "(2017) 4 SCC 665",
     "search": "Voestalpine Schienen Delhi Metro Rail"},
    {"name": "Perkins Eastman Architects v HSCC India",
     "citation": "(2020) 20 SCC 760",
     "search": "Perkins Eastman Architects HSCC India"},
    {"name": "NN Global Mercantile v Indo Unique Flame",
     "citation": "(2023) 7 SCC 1",
     "search": "NN Global Mercantile Indo Unique Flame arbitration stamp"},
    {"name": "Chloro Controls India v Severn Trent Water Purification",
     "citation": "(2013) 1 SCC 641",
     "search": "Chloro Controls India Severn Trent Water Purification"},
    {"name": "Pankaj Bansal v Union of India",
     "citation": "(2024) 7 SCC 576",
     "search": "Pankaj Bansal Union of India arrest PMLA"},
    {"name": "Prabir Purkayastha v State NCT of Delhi",
     "citation": "(2024) 8 SCC 254",
     "search": "Prabir Purkayastha State NCT Delhi UAPA"},
    {"name": "Phoolchand v Gopal Lal",
     "citation": "AIR 1967 SC 1470",
     "search": "Phoolchand Gopal Lal partition preliminary decree"},
    {"name": "Murari Lal v State of Madhya Pradesh",
     "citation": "(1980) 1 SCC 704",
     "search": "Murari Lal State Madhya Pradesh handwriting expert"},
    {"name": "Essar Steel India Committee of Creditors v Satish Kumar Gupta",
     "citation": "(2020) 8 SCC 531",
     "search": "Essar Steel Committee of Creditors Satish Kumar Gupta"},
    {"name": "Vidarbha Industries Power v Axis Bank",
     "citation": "(2022) 8 SCC 352",
     "search": "Vidarbha Industries Power Axis Bank IBC"},
    {"name": "Rajnesh v Neha",
     "citation": "(2021) 2 SCC 324",
     "search": "Rajnesh Neha maintenance interim guidelines"},
]


def search_and_pick(client, case):
    """Run search, show top SC results, get user pick."""
    print(f"\n{'═'*72}")
    print(f"  {case['name']}")
    print(f"  Citation: {case['citation']}")
    print(f"{'═'*72}")
    print(f"Searching IK: {case['search']!r}")

    try:
        html = client.search(case["search"])
    except Exception as e:
        print(f"  Search error: {e}")
        return None

    if not html:
        print("  No HTML returned")
        return None

    results = parse_search_results(html, limit=15)
    sc_results = [r for r in results if is_supreme_court(r)]
    if not sc_results:
        print("  No SC results in top 15")
        print(f"  Top 3 non-SC: ")
        for r in results[:3]:
            print(f"    tid={r.get('tid')}  source={r.get('source','')[:30]}  title={r.get('title','')[:60]}")
        # Allow manual override anyway
    else:
        print(f"\nTop SC results:")
        for i, r in enumerate(sc_results[:5], 1):
            title = r.get("title", "")[:80]
            tid = r.get("tid")
            print(f"  [{i}] tid={tid}  {title}")
            print(f"      url: https://indiankanoon.org/doc/{tid}/")

    print(f"\nOptions:")
    print(f"  1-5  : accept that numbered result")
    print(f"  t<tid> : paste a specific tid (e.g. 't131202146')")
    print(f"  s    : skip this case")
    print(f"  q    : quit (save what's done so far)")
    choice = input("Your choice: ").strip().lower()

    if choice == "q":
        return "QUIT"
    if choice == "s" or choice == "":
        return None
    if choice.startswith("t"):
        tid_str = choice[1:].strip()
        # Could be tid or full URL
        m = re.search(r"(\d{4,})", tid_str)
        if not m:
            print("  Invalid tid")
            return None
        tid = m.group(1)
    elif choice in {"1","2","3","4","5"}:
        idx = int(choice) - 1
        if idx >= len(sc_results):
            print("  No such result")
            return None
        tid = sc_results[idx].get("tid")
    else:
        print("  Invalid choice")
        return None

    # Verify the picked tid is actually SC
    print(f"  Verifying tid {tid}...")
    try:
        doc_html = client.doc(tid)
        doc = parse_doc_page(doc_html or "")
        source = doc.get("source", "").lower()
        if "supreme court of india" not in source:
            print(f"  ! Warning: source = {doc.get('source')!r}")
            confirm = input("  Add anyway? (yes/no): ").strip().lower()
            if confirm != "yes":
                return None
        return {
            "tid": tid,
            "title": doc.get("title", case["name"]),
            "citations": doc.get("citations", []),
            "case_name": case["name"],
        }
    except Exception as e:
        print(f"  Verify error: {e}")
        return None


def merge_picks(picks):
    """Add picks as new aliases to authority_index.py."""
    if not picks:
        print("Nothing to merge.")
        return

    text = INDEX_PATH.read_text(encoding="utf-8")
    existing_aliases = set(re.findall(r'"([^"]+)":\s*"\d+"', text))
    existing_tids = set(re.findall(r':\s*"(\d+)"', text))

    new_entries = []
    skipped_aliases = 0
    skipped_existing_tid = 0

    for pick in picks:
        tid = pick["tid"]
        if tid in existing_tids:
            print(f"  ! tid {tid} ({pick['case_name'][:40]}) already in index — skipping duplicate")
            skipped_existing_tid += 1
            continue
        title = pick.get("title", pick["case_name"]).replace('"', "'")[:90]
        citations = pick.get("citations", [])
        aliases = derive_aliases(pick["case_name"], citations=citations) if citations else derive_aliases(pick["case_name"])
        aliases = _filter(set(aliases))
        for alias in sorted(aliases):
            if alias in existing_aliases:
                skipped_aliases += 1
                continue
            new_entries.append((alias, tid, title))
            existing_aliases.add(alias)

    print(f"\n{'─'*60}")
    print(f"New aliases to add:       {len(new_entries)}")
    print(f"Aliases already present:  {skipped_aliases}")
    print(f"Tids skipped (duplicate): {skipped_existing_tid}")

    if not new_entries:
        return

    print(f"\nSample (first 6):")
    for a, t, _ in new_entries[:6]:
        print(f"  {a!r}: {t!r}")

    confirm = input("\nMerge into authority_index.py? (yes/no): ").strip().lower()
    if confirm != "yes":
        print("Skipped merge.")
        return

    # Find closing brace robustly
    norm_pos = text.find("def _normalize")
    before = text[:norm_pos]
    brace_match = None
    for m in re.finditer(r"^\}\s*$", before, re.MULTILINE):
        brace_match = m
    if brace_match is None:
        print("ERROR: closing brace not found.")
        return
    brace_pos = brace_match.start()

    insert_lines = ["    # ── FIX-FAILED SUPPLEMENT (auto-added) ──"]
    for alias, tid, title in new_entries:
        insert_lines.append(f'    "{alias}": "{tid}",  # {title}')
    insert_block = "\n".join(insert_lines) + "\n"
    new_text = text[:brace_pos] + insert_block + text[brace_pos:]

    shutil.copy2(INDEX_PATH, BACKUP_PATH)
    print(f"Backup: {BACKUP_PATH.name}")
    INDEX_PATH.write_text(new_text, encoding="utf-8")

    final_aliases = set(re.findall(r'"([^"]+)":\s*"\d+"', INDEX_PATH.read_text(encoding="utf-8")))
    print(f"Done. Total aliases: {len(final_aliases)}")


def main():
    print(f"Index path:  {INDEX_PATH}")
    print(f"Cases to process: {len(FAILED_CASES)}")
    print()
    print("For each case, you'll see top SC search results.")
    print("Pick a number (1-5), paste a tid (t12345), skip (s), or quit (q).")
    print()
    input("Press Enter to start... ")

    client = IKClient()
    picks = []
    try:
        for case in FAILED_CASES:
            result = search_and_pick(client, case)
            if result == "QUIT":
                print("\nStopping at user request.")
                break
            if result:
                picks.append(result)
                print(f"  ✓ Added tid {result['tid']}")
            else:
                print(f"  - Skipped")
    finally:
        client.close()

    print(f"\n{'═'*72}")
    print(f"Picks collected: {len(picks)} of {len(FAILED_CASES)}")
    if picks:
        merge_picks(picks)


if __name__ == "__main__":
    main()
