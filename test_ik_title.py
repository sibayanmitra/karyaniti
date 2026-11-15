import httpx, os
from dotenv import load_dotenv
load_dotenv()

TOKEN = os.getenv("INDIAN_KANOON_API_TOKEN")

def search(form_input, title="", doctypes="judgments"):
    data = {"formInput": form_input, "doctypes": doctypes, "pagenum": 0}
    if title:
        data["title"] = title
    r = httpx.post("https://api.indiankanoon.org/search/",
                   headers={"Authorization": f"Token {TOKEN}"},
                   data=data, timeout=30)
    return r.json().get("docs", [])

import re
def strip(t): return re.sub(r"<[^>]+>", "", t)

# Test 1: title=Anvar as separate param
docs = search("Section 65B certificate mandatory", title="Anvar")
print(f"\nTest 1 — formInput='Section 65B certificate mandatory' title='Anvar' → {len(docs)} docs")
for d in docs[:5]:
    print(f"  - {strip(d.get('title',''))[:80]}  ({d.get('docsource','')[:25]})")

# Test 2: title=Panditrao
docs = search("Section 65B condition precedent", title="Panditrao")
print(f"\nTest 2 — formInput='Section 65B condition precedent' title='Panditrao' → {len(docs)} docs")
for d in docs[:5]:
    print(f"  - {strip(d.get('title',''))[:80]}  ({d.get('docsource','')[:25]})")

# Test 3: title=Sibbia (sanity check from a working doctrine)
docs = search("Section 438 anticipatory bail", title="Sibbia")
print(f"\nTest 3 — formInput='Section 438 anticipatory bail' title='Sibbia' → {len(docs)} docs")
for d in docs[:5]:
    print(f"  - {strip(d.get('title',''))[:80]}  ({d.get('docsource','')[:25]})")