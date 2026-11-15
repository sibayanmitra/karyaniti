"""One-off helper: print top IK results for a case name so you can pick the right doc_id."""
import httpx, os, re, sys
from dotenv import load_dotenv
load_dotenv()
TOKEN = os.getenv("INDIAN_KANOON_API_TOKEN")

CANONICAL_CASES = [
    # Section 65B
    "Anvar P.V. Basheer",
    "Arjun Panditrao Khotkar",
    "Shafhi Mohammad",
    # Section 438
    "Gurbaksh Singh Sibbia",
    "Sushila Aggarwal",
    "Siddharam Mhetre",
    # Section 482
    "State of Haryana Bhajan Lal",
    "R.P. Kapur State of Punjab",
    # Article 226 private body
    "Andi Mukta Sadguru",
    "Binny Ltd",
    "Ramesh Ahluwalia State of Punjab",
    # Tenth Schedule
    "Kihoto Hollohan Zachillhu",
    "Ravi Naik Union of India",
    "Shrimanth Balasaheb Patil",
    # Section 11 Arbitration
    "SBP Co Patel Engineering",
    "National Insurance Boghara Polyfab",
    "Vidya Drolia Durga Trading",
    # Section 138 NI
    "Dashrath Rupsingh Rathod",
    "Bridgestone India Inderpal Singh",
    # Section 498A
    "Arnesh Kumar State of Bihar",
    "Rajesh Sharma State of UP",
    "Preeti Gupta State of Jharkhand",
    # Section 9 IBC
    "Mobilox Innovations Kirusa Software",
    "Innoventive Industries ICICI Bank",
    # Specific performance
    "Saradamani Kandappan Rajalakshmi",
    "Katta Sujatha Reddy Siddamsetty Infra",
]

def search(q):
    r = httpx.post("https://api.indiankanoon.org/search/",
        headers={"Authorization": f"Token {TOKEN}"},
        data={"formInput": q, "pagenum": 0, "doctypes": "supremecourt"}, timeout=30)
    return r.json().get("docs", [])

def strip(t): return re.sub(r"<[^>]+>", "", t)

for name in CANONICAL_CASES:
    print(f"\n=== {name} ===")
    docs = search(name)
    for d in docs[:3]:
        tid = d.get("tid", "")
        title = strip(d.get("title", ""))[:90]
        src = d.get("docsource", "")[:25]
        print(f"  {tid:>10} | {src:<25} | {title}")