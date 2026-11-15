"""
Diagnose why supplement_phase1 returned 0 verifications.

For Anvar P.V. (tid 187283766) — the most heavily-cited case in your supplement
— fetch its citedby list, take 3 top SC results, and dump exactly what
parse_doc_page sees for each. We'll find out whether the issue is:
  - empty docsource (filter A)
  - empty citations list (filter B)
  - body doesn't contain own citation (filter C)
  - something else
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent if HERE.name == "authority_build" else HERE
sys.path.insert(0, str(ROOT / "authority_build"))

from scraper.ik_client import IKClient
from scraper.extractors import parse_search_results, is_supreme_court, parse_doc_page, body_contains_citation

ANVAR_TID = "187283766"

def main():
    client = IKClient()
    try:
        print(f"Fetching citedby:{ANVAR_TID}...")
        html = client.search(f"citedby:{ANVAR_TID}")
        if not html:
            print("ERROR: No search results")
            return 1

        # Parse search results
        results = parse_search_results(html, limit=10)
        print(f"Got {len(results)} search results")
        if not results:
            print("ERROR: parse_search_results returned nothing")
            print(f"\nFirst 1000 chars of HTML:\n{html[:1000]}")
            return 1

        sc_results = [r for r in results if is_supreme_court(r)]
        print(f"After SC filter: {len(sc_results)}")
        if not sc_results:
            print("WARNING: No SC cases in citedby — that's the bug")
            print(f"\nFirst 3 raw results (sample):")
            for r in results[:3]:
                print(f"  tid={r.get('tid')}  title={r.get('title','')[:80]}  src_hint={r.get('court_or_source','')}")
            return 1

        # Examine first 3 SC citers in detail
        for i, cand in enumerate(sc_results[:3], 1):
            print(f"\n{'='*60}")
            print(f"[{i}] tid={cand['tid']}  title={cand.get('title','')[:70]}")
            print(f"{'='*60}")

            doc_html = client.doc(cand["tid"])
            if not doc_html:
                print("  client.doc returned empty")
                continue
            print(f"  HTML length: {len(doc_html)} chars")

            doc = parse_doc_page(doc_html)
            print(f"  parse_doc_page returned keys: {list(doc.keys())}")
            print(f"  source: {doc.get('source', 'MISSING')!r}")
            print(f"  citations count: {len(doc.get('citations', []))}")
            if doc.get('citations'):
                print(f"  first citations: {doc['citations'][:3]}")
            print(f"  body_text length: {len(doc.get('body_text', ''))}")
            print(f"  body_text first 300 chars: {doc.get('body_text','')[:300]!r}")

            # Walk each filter
            if not doc.get("source"):
                print("  → FAILED at: empty source")
                continue
            if "supreme court of india" not in doc["source"].lower():
                print(f"  → FAILED at: source != 'supreme court of india' (source={doc['source']!r})")
                continue
            if not doc.get("citations"):
                print("  → FAILED at: empty citations list")
                continue
            body = doc.get("body_text", "")
            found_any = False
            for c in doc["citations"]:
                if body_contains_citation(body, c):
                    print(f"  ✓ body contains citation: {c}")
                    found_any = True
                    break
            if not found_any:
                print(f"  → FAILED at: body_contains_citation — none of {len(doc['citations'])} citations found in body")
                # Show what we're looking for vs what's in body
                print(f"     Sample citation to search for: {doc['citations'][0]!r}")
                print(f"     Body sample (chars 100-400): {body[100:400]!r}")
            else:
                print(f"  ✓ Would have passed verify_citer")
    finally:
        client.close()
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
