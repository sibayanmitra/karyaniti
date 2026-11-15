"""Inspect IK search HTML to find correct CSS selectors."""
import httpx, re

url = "https://indiankanoon.org/search/?formInput=1992+Supp+1+SCC+335"
r = httpx.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30, follow_redirects=True)
html = r.text

print(f"Status: {r.status_code}")
print(f"Length: {len(html)}")
print()

idx = html.find("/doc/")
print(f"First '/doc/' at offset: {idx}")
if idx > 0:
    print("--- 600 chars around first /doc/ ---")
    print(html[max(0, idx - 300):idx + 300])
print()

print("--- pattern counts ---")
for pat in ["result_title", "<div class=\"result", "docsource", "docfragment",
            "cite_tid", "class='result", "result-title", "/doc/"]:
    print(f"  {pat!r}: {html.count(pat)}")
print()

print("--- all class names referenced ---")
classes = set(re.findall(r'class=["\']([^"\']+)["\']', html))
result_like = [c for c in classes if "result" in c.lower() or "doc" in c.lower() or "cite" in c.lower()]
for c in sorted(result_like):
    print(f"  {c}")
