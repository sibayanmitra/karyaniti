"""Inspect HTML structure for citedby search and doc pages."""
import httpx, re

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
TID = "1033637"  # Bhajan Lal — we know this resolved


def show(label, url):
    print(f"\n{'═'*70}\n{label}\n{url}\n{'═'*70}")
    r = httpx.get(url, headers=HEADERS, timeout=30, follow_redirects=True)
    html = r.text
    print(f"Status: {r.status_code}  Length: {len(html)}")

    idx = html.find("/doc/")
    if idx < 0:
        idx = html.find("/docfragment/")
    print(f"\nFirst doc-link at offset {idx}:")
    if idx > 0:
        print(html[max(0, idx - 200):idx + 400])

    classes = set(re.findall(r'class=["\']([^"\']+)["\']', html))
    relevant = sorted(c for c in classes if any(k in c.lower() for k in ["cit", "result", "doc", "head", "title"]))
    print("\nRelevant class names:")
    for c in relevant:
        print(f"  {c}")


show("Method 1: citedby search results", f"https://indiankanoon.org/search/?formInput=citedby:{TID}")
show("Method 2: doc page header (parallel citations)", f"https://indiankanoon.org/doc/{TID}/")
