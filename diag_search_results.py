"""Show what parse_search_results returns for citedby:Anvar."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "authority_build"))

from scraper.ik_client import IKClient
from scraper.extractors import parse_search_results, is_supreme_court

ANVAR_TID = "187283766"

c = IKClient()
try:
    html = c.search(f"citedby:{ANVAR_TID}")
    print(f"HTML length: {len(html or '')}")
    results = parse_search_results(html, limit=10)
    print(f"Parsed {len(results)} results\n")
    for i, r in enumerate(results, 1):
        print(f"[{i}] tid={r.get('tid')}")
        print(f"    is_sc:   {is_supreme_court(r)}")
        print(f"    source:  {r.get('source','')!r}")
        print(f"    title:   {r.get('title','')[:70]!r}")
        print(f"    snippet: {r.get('raw_snippet','')[:120]!r}")
        print()
finally:
    c.close()
