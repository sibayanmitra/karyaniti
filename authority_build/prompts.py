"""Prompts for case generation and IK candidate verification."""

GEN_PROMPT = """You are an expert in Indian law. List the most-cited Supreme Court of India landmark judgments on this doctrine.

DOCTRINE: {doctrine}

Output 6-12 cases. Real, verifiable Indian SC cases ONLY — if unsure, omit.

Rules:
- Use commonly-cited short form (e.g. "Anvar P.V. v. P.K. Basheer" not full party-string)
- Include SCC/AIR citation
- Include bench strength if known (Constitution Bench / 3-judge / 2-judge)
- Include overruled-but-historically-important cases — mark treatment_status accordingly
- aliases = how lawyers refer to it: surname-only, common short, party-only
- treatment_status: "good_law" (default), "overruled_by:<short name>", "doubted_by:<short>", "distinguished"

Output ONLY this JSON, no commentary:
{{"cases":[
  {{
    "name": "Anvar P.V. v. P.K. Basheer",
    "citation": "(2014) 10 SCC 473",
    "year": 2014,
    "bench": "3-judge",
    "treatment_status": "good_law",
    "aliases": ["anvar", "anvar pv", "anvar basheer"]
  }}
]}}"""


VERIFY_PROMPT = """You verify whether a retrieved Indian SC judgment is the same case as a target landmark.

TARGET CASE:    {name}
KNOWN CITATION: {citation}
DOCTRINE:       {doctrine}

RETRIEVED CANDIDATE:
  Title:  {title}
  Source: {source}

Indian Kanoon titles often use different formatting than common citation form.
TREAT AS SAME CASE:
- "CIT v. X" ≡ "C.I.T.,Mumbai vs M/S.X" (abbreviation, location, M/S prefix)
- "Andi Mukta v. Rudani" ≡ "Andi Mukta Sadguru Shree Muktajee Vandas Swami Suvarna Trust vs V.R. Rudani"
- "SBP & Co. v. Patel Engineering" ≡ "S.B.P. & Co. vs Patel Engineering Ltd. & Anr."
- "Mobilox v. Kirusa" ≡ "Mobilox Innovations Private Limited vs Kirusa Software Private Limited"
- Date suffix ("on 21 September, 2017") does not make it a different case

REJECT (different cases):
- Source NOT "Supreme Court of India" (no HC, Daily Order, NCLAT, ITAT, tribunal)
- Completely different parties (different distinctive names)
- Daily order or interim order rather than the main judgment

Decision rule: if the core distinctive party tokens match (e.g. "Walfort", "Andi Mukta", "Mobilox", "Bhajan Lal"), MATCH. Be lenient on formatting; strict on identity.

Output ONLY JSON: {{"match": true/false, "reason": "<≤15 words>"}}"""
