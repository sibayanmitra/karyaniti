"""Show actual citation block contents on a doc page."""
import httpx, re

html = httpx.get("https://indiankanoon.org/doc/1033637/",
                 headers={"User-Agent": "Mozilla/5.0"},
                 timeout=30, follow_redirects=True).text

for cls in ["doc_citations", "citetop", "citetext", "docsource_main", "doc_title", "doc_bench"]:
    # Capture the whole tag and ~400 chars after
    pattern = rf'<[^>]+class=["\'][^"\']*\b{cls}\b[^"\']*["\'][^>]*>(.{{0,600}}?)</'
    m = re.search(pattern, html, re.DOTALL)
    print(f"\n── {cls} ──")
    if m:
        # strip nested tags for readability
        text = re.sub(r"<[^>]+>", " | ", m.group(1))
        text = re.sub(r"\s+", " ", text).strip()
        print(text[:500])
    else:
        print("  not found")
