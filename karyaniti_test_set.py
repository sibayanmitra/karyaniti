"""
Karyaniti — Adversarial Query Set v1
Hardness-graded queries with pre-specified must-find and must-reject lists.
Protocol locked BEFORE results to prevent confirmation bias.

PROTOCOL:
- PASS    = 0 must-reject present in verified results AND >=50% must-find coverage
- PARTIAL = 0 must-reject present in verified results AND <50% must-find coverage
- FAIL    = ANY must-reject appears in verified results (single attribution/scope
            failure that reaches a lawyer = trust destruction = FAIL)

Aggregate:
- System PASS:    0 FAIL and >=80% PASS
- System NEEDS WORK: 0 FAIL and <80% PASS (coverage problem, fixable)
- System BLOCKED: any FAIL (correctness problem, do not ship)

Evaluation rigor levels:
- RIGOROUS  = source PDFs read; must-find/must-reject lists are confirmed
- DOCTRINAL = general legal knowledge; must-find at doctrinal level, not citation
- DIRECTIONAL = predicted failure modes; treat results as signal not verdict

Reading discipline: score against the lists, not impressions. For unlisted
holdings, open the source paragraph and form an independent judgment that goes
in notes — NOT into PASS/FAIL.
"""

QUERY_SET = [
    # ═════════════════════════════════════════════════════════════════════════
    # REGRESSION TESTS — already-known failures, rigorously specified
    # ═════════════════════════════════════════════════════════════════════════

    {
        "id": "Q01_anticipatory_bail_section_438",
        "query": "anticipatory bail section 438 CrPC scope conditions duration",
        "doctrinal_area": "CrPC anticipatory bail",
        "target_failure_mode": "counsel-as-court attribution",
        "evaluation_rigor": "RIGOROUS",
        "context": (
            "Regression test for Priya Indoria failure. The original system extracted "
            "Dr. Manish Singhvi's submission (counsel for State of Rajasthan, sub-para "
            "7.3.iii) as a Supreme Court holding. The Court actually held the OPPOSITE "
            "in paragraphs 36, 38, and 44 — territorial jurisdiction is NOT a strict bar."
        ),
        "must_find": [
            {
                "case": "Priya Indoria vs The State of Karnataka",
                "substance": (
                    "The Court of Session or High Court CAN grant limited anticipatory bail / "
                    "interim protection even when the FIR is registered outside its territorial "
                    "jurisdiction. Para 36 / 44 / 46 area."
                ),
            },
            {
                "case": "Sushila Aggarwal vs State (NCT of Delhi)",
                "substance": (
                    "Section 438 does not prescribe a fixed duration limit for anticipatory bail; "
                    "it may continue till end of trial. Conditions under Section 437(3) / 438(2) "
                    "may be imposed."
                ),
            },
            {
                "case": "Gurbaksh Singh Sibbia vs State of Punjab",
                "substance": (
                    "Section 438 jurisdiction to be exercised by wise and careful use of "
                    "discretion; no inflexible rules; FIR not a condition precedent."
                ),
            },
        ],
        "must_reject": [
            {
                "case": "Priya Indoria",
                "paragraph": 22,
                "deceptive_proposition": (
                    "The High Court or Court of Session having territorial jurisdiction over "
                    "the offence is the court competent to grant anticipatory bail under "
                    "Section 438 CrPC, and the word 'the' prefixed to both High Court and "
                    "Sessions Court in Section 438 cannot be construed so liberally as to "
                    "become indistinguishable from 'any'."
                ),
                "why_bad": (
                    "This is Dr. Manish Singhvi's submission for Rajasthan, sub-paragraph iii "
                    "of section 7.3 ('Submissions of Counsel'). The Supreme Court EXPLICITLY "
                    "REJECTED this view in paragraphs 36, 38, and 44. It also set aside the "
                    "Patna and Calcutta HC judgments that supported this view. A lawyer citing "
                    "this would be destroyed by opposing counsel pulling the same judgment."
                ),
                "failure_mode": "counsel-as-court attribution",
            },
        ],
    },

    {
        "id": "Q02_writ_226_private_body",
        "query": "writ petition maintainability against private body under Article 226",
        "doctrinal_area": "Constitutional / writ jurisdiction",
        "target_failure_mode": "scope drift + qualifier drop",
        "evaluation_rigor": "RIGOROUS",
        "context": (
            "Regression test for AWHO Society scope drift. Anchor in Smt. Saroj Devi para 43 "
            "specifically discusses 'AWHO Society' (Army Welfare Housing Organisation) as the "
            "subject. The previous system widened this to 'private body or society' generally "
            "and added 'regardless of its private character' (not in anchor). Strict "
            "faithfulness gate must now catch this."
        ),
        "must_find": [
            {
                "case": "Any cited source",
                "substance": (
                    "Writ lies against a private body when it discharges a public function or "
                    "public duty; not every private dispute is amenable to writ jurisdiction."
                ),
            },
            {
                "case": "Any cited source (Binny Ltd, Andi Mukta, St Mary's, Ramakrishna Mission lineage)",
                "substance": (
                    "Public law element / public character is required; mere discharge of public "
                    "function is not enough; State control or substantial funding may be relevant."
                ),
            },
        ],
        "must_reject": [
            {
                "case": "Smt. Saroj Devi vs Union of India",
                "paragraph": 43,
                "deceptive_proposition": (
                    "A writ petition under Article 226 is maintainable against a private body "
                    "or society registered under the Societies Registration Act if it is "
                    "performing a public function having a public character, regardless of its "
                    "private character."
                ),
                "why_bad": (
                    "Anchor is specifically about AWHO Society. Proposition widens subject to "
                    "'private body or society' (Axis 1: subject preservation). Adds 'regardless "
                    "of its private character' which is not in the anchor (Axis 5: no additions)."
                ),
                "failure_mode": "scope drift + addition",
            },
        ],
    },

    # ═════════════════════════════════════════════════════════════════════════
    # DOCTRINAL STRESS TESTS — general legal knowledge, doctrinal must-find
    # ═════════════════════════════════════════════════════════════════════════

    {
        "id": "Q03_section_482_quashing",
        "query": "quashing of FIR under Section 482 CrPC when allegations do not constitute offence",
        "doctrinal_area": "CrPC inherent powers",
        "target_failure_mode": "qualifier preservation (rarest of rare / sparingly)",
        "evaluation_rigor": "DOCTRINAL",
        "context": (
            "Section 482 quashing is a well-trodden area dominated by State of Haryana vs "
            "Bhajan Lal (1992) — the seven categories for quashing. The faithfulness gate "
            "must preserve the strict qualifiers: 'rarest of rare', 'sparingly', 'in exceptional "
            "cases'. Dropping these qualifiers changes the rule fundamentally."
        ),
        "must_find": [
            {
                "case": "State of Haryana vs Bhajan Lal (or HC cases applying Bhajan Lal)",
                "substance": (
                    "Seven-category framework for quashing FIRs under Section 482 / Article 226. "
                    "Typically: where allegations don't make out an offence on their face; "
                    "where allegations are inherently improbable; where there's bar by law; etc."
                ),
            },
            {
                "case": "Any source on the 'sparingly' standard",
                "substance": (
                    "Section 482 power is to be exercised sparingly / in rarest of rare cases / "
                    "not as a matter of routine."
                ),
            },
        ],
        "must_reject": [
            {
                "case": "any case",
                "deceptive_proposition": (
                    "Hypothetical drift: an extracted proposition saying 'the High Court may "
                    "quash an FIR under Section 482 if allegations do not constitute an "
                    "offence' WITHOUT preserving the 'rarest of rare' / 'sparingly' / "
                    "'exceptional cases' qualifier."
                ),
                "why_bad": (
                    "Without the strict qualifier, the rule sounds routine. Bhajan Lal "
                    "specifically frames this as exceptional. Modal/qualifier drop changes "
                    "the rule's force."
                ),
                "failure_mode": "Axis 2 qualifier drop / Axis 3 modal weakening",
            },
        ],
    },

    {
        "id": "Q04_section_65B_electronic_evidence",
        "query": "Section 65B Indian Evidence Act certificate requirement electronic record",
        "doctrinal_area": "Evidence — electronic records",
        "target_failure_mode": "modal preservation (condition precedent vs mandatory)",
        "evaluation_rigor": "DOCTRINAL",
        "context": (
            "Anvar P.V. vs P.K. Basheer (2014) and Arjun Panditrao Khotkar vs Kailash Kushanrao "
            "Gorantyal (2020) established the Section 65B(4) certificate requirement. The exact "
            "phrase used is 'condition precedent' — a specific legal term of art. The "
            "faithfulness gate must not let this drift to 'mandatory' or 'required' (weaker "
            "modal forms with different doctrinal force)."
        ),
        "must_find": [
            {
                "case": "Anvar P.V. or Arjun Panditrao or HC application",
                "substance": (
                    "Section 65B(4) certificate is required for admissibility of electronic "
                    "records as secondary evidence. The standard is 'condition precedent'."
                ),
            },
            {
                "case": "Shafhi Mohammad (or its overruling)",
                "substance": (
                    "Shafhi Mohammad (2018) — which had relaxed the certificate requirement — "
                    "stands overruled by Arjun Panditrao (2020). Treatment status matters here."
                ),
            },
        ],
        "must_reject": [
            {
                "case": "any case",
                "deceptive_proposition": (
                    "Hypothetical drift: 'A Section 65B(4) certificate is mandatory for "
                    "admitting electronic evidence' when the anchor specifically says 'condition "
                    "precedent'."
                ),
                "why_bad": (
                    "'Condition precedent' is a stronger and more specific legal concept than "
                    "'mandatory' — it means the requirement must be satisfied BEFORE the action "
                    "can proceed at all. Substituting weakens the rule."
                ),
                "failure_mode": "Axis 3 modal substitution of legal-term-of-art",
            },
            {
                "case": "Shafhi Mohammad",
                "deceptive_proposition": (
                    "Any proposition presenting Shafhi Mohammad's relaxed view as current law."
                ),
                "why_bad": (
                    "Shafhi Mohammad is overruled by Arjun Panditrao. Citing it as good law "
                    "would be devastating. (Note: treatment-status gate not yet built — this "
                    "is a known weakness we're monitoring.)"
                ),
                "failure_mode": "overruled-case-as-good-law",
            },
        ],
    },

    {
        "id": "Q05_section_138_NI_Act_dishonour",
        "query": "Section 138 Negotiable Instruments Act dishonour of cheque presumption",
        "doctrinal_area": "Commercial / NI Act",
        "target_failure_mode": "coverage + synthesis quality",
        "evaluation_rigor": "DOCTRINAL",
        "context": (
            "High-volume doctrine with extensive HC and SC case law. Section 139 presumption "
            "(legally enforceable debt) is the central interpretive question. This query tests "
            "whether the system maintains coverage and synthesis quality on a saturated doctrine "
            "without producing attribution failures."
        ),
        "must_find": [
            {
                "case": "Rangappa vs Sri Mohan (SC) or HC applications",
                "substance": (
                    "Section 139 raises a presumption of legally enforceable debt; presumption "
                    "is rebuttable; standard of proof for rebuttal is 'preponderance of "
                    "probabilities' not 'beyond reasonable doubt'."
                ),
            },
            {
                "case": "Any source on the standard of presumption rebuttal",
                "substance": (
                    "The accused need not enter the witness box but must raise probable defence."
                ),
            },
        ],
        "must_reject": [
            {
                "case": "any",
                "deceptive_proposition": (
                    "Hypothetical: a proposition that strengthens the standard of rebuttal "
                    "from 'preponderance of probabilities' to 'beyond reasonable doubt'."
                ),
                "why_bad": "Modal/standard shift — different evidentiary standard.",
                "failure_mode": "Axis 3 modal substitution",
            },
        ],
    },

    {
        "id": "Q06_anti_defection_tenth_schedule",
        "query": "anti-defection law Tenth Schedule Constitution disqualification grounds",
        "doctrinal_area": "Constitutional — Tenth Schedule",
        "target_failure_mode": "dicta-as-ratio confusion",
        "evaluation_rigor": "DOCTRINAL",
        "context": (
            "Kihoto Hollohan vs Zachillhu (1992) is the foundational Constitution Bench case. "
            "Recent activity around Speaker's role, time limits for disposal. Constitution "
            "Bench judgments often have extensive obiter — risk of presenting dicta as binding "
            "ratio."
        ),
        "must_find": [
            {
                "case": "Kihoto Hollohan vs Zachillhu",
                "substance": (
                    "Tenth Schedule disqualification provisions are constitutionally valid; "
                    "Speaker acts as tribunal subject to judicial review on grounds of mala "
                    "fides, perversity etc; paragraph 7 finality clause read down."
                ),
            },
        ],
        "must_reject": [
            {
                "case": "any",
                "deceptive_proposition": (
                    "Hypothetical: an obiter dictum from Kihoto Hollohan presented as a binding "
                    "rule."
                ),
                "why_bad": "Dicta should be marked as dicta; ratio should be marked as ratio.",
                "failure_mode": "dicta-as-ratio (current system marks both as 'Dicta' — known weakness)",
            },
        ],
    },

    # ═════════════════════════════════════════════════════════════════════════
    # DIRECTIONAL TESTS — predicted failure modes, signal not verdict
    # ═════════════════════════════════════════════════════════════════════════

    {
        "id": "Q07_section_11_arbitration_appointment",
        "query": "Section 11 Arbitration Act appointment of arbitrator scope of court inquiry",
        "doctrinal_area": "Arbitration",
        "target_failure_mode": "doctrine evolution (pre-2015 vs post-2015 vs post-2019)",
        "evaluation_rigor": "DIRECTIONAL",
        "context": (
            "Section 11 jurisprudence has evolved significantly across the 2015 and 2019 "
            "amendments. SBP & Co vs Patel Engineering, Boghara Polyfab, Duro Felguera, "
            "Vidya Drolia, NN Global — each shifted the scope of Section 11 inquiry. Old "
            "cases may no longer be good law. Tests whether the system handles doctrinal "
            "evolution gracefully."
        ),
        "must_find": [
            {
                "case": "Vidya Drolia or NN Global or recent SC",
                "substance": (
                    "Post-amendment scope of Section 11 inquiry is narrow — limited to "
                    "existence of arbitration agreement; merits/arbitrability go to the "
                    "arbitral tribunal under Section 16."
                ),
            },
        ],
        "must_reject": [
            {
                "case": "SBP & Co vs Patel Engineering or pre-amendment cases",
                "deceptive_proposition": (
                    "Hypothetical: a proposition from SBP & Co presented as current law on "
                    "scope of Section 11 inquiry."
                ),
                "why_bad": (
                    "SBP & Co's broader inquiry standard has been substantially narrowed by "
                    "subsequent law. Citing it as current would mislead."
                ),
                "failure_mode": "doctrine evolution / overruled-or-narrowed-case-as-good-law",
            },
        ],
    },

    {
        "id": "Q08_section_498A_jurisdiction",
        "query": "section 498A IPC jurisdiction wife's parental home cruelty",
        "doctrinal_area": "Criminal — matrimonial",
        "target_failure_mode": "evolving jurisdiction doctrine",
        "evaluation_rigor": "DIRECTIONAL",
        "context": (
            "Y. Abraham Ajith / Sujata Mukherjee era held jurisdiction lies only where offence "
            "ingredients occurred. Rupali Devi (2019) clarified that consequences of cruelty "
            "felt at parental home can constitute jurisdiction. Tests handling of clarifying "
            "vs overruling precedent."
        ),
        "must_find": [
            {
                "case": "Rupali Devi vs State of UP",
                "substance": (
                    "Adverse effects on mental health of wife at parental home from acts in "
                    "matrimonial home constitute cruelty at parental home; jurisdiction extends "
                    "to courts where wife takes shelter."
                ),
            },
        ],
        "must_reject": [
            {
                "case": "Y. Abraham Ajith / Manish Ratan",
                "deceptive_proposition": (
                    "Hypothetical: a proposition presenting the older view (no jurisdiction at "
                    "parental home) as current law."
                ),
                "why_bad": "Rupali Devi clarified/modified the earlier position.",
                "failure_mode": "earlier-position-presented-as-current",
            },
        ],
    },

    {
        "id": "Q09_section_9_IBC_operational_creditor",
        "query": "Section 9 IBC operational creditor pre-existing dispute insolvency",
        "doctrinal_area": "Insolvency — IBC",
        "target_failure_mode": "recent doctrine, narrower corpus",
        "evaluation_rigor": "DIRECTIONAL",
        "context": (
            "Mobilox Innovations vs Kirusa Software (2017) and Innoventive Industries established "
            "the pre-existing dispute test. Active area of NCLT/NCLAT jurisprudence. Tests system "
            "on younger doctrines where corpus is thinner."
        ),
        "must_find": [
            {
                "case": "Mobilox Innovations vs Kirusa Software",
                "substance": (
                    "Pre-existing dispute is a defence to Section 9 IBC application; dispute "
                    "need not be definitive; bona fide dispute suffices; not spurious / "
                    "moonshine / illusory."
                ),
            },
        ],
        "must_reject": [
            {
                "case": "any",
                "deceptive_proposition": (
                    "Hypothetical: drift from 'bona fide dispute' to 'any dispute' or 'mere "
                    "denial' — weakens the threshold."
                ),
                "why_bad": "Bona fide qualifier matters; drift weakens debtor's standard.",
                "failure_mode": "Axis 2 qualifier drop",
            },
        ],
    },

    # ═════════════════════════════════════════════════════════════════════════
    # CONTROL QUERY — easy, settled doctrine, should pass cleanly
    # ═════════════════════════════════════════════════════════════════════════

    {
        "id": "Q10_control_specific_performance",
        "query": "specific performance contract Section 10 readiness and willingness",
        "doctrinal_area": "Contract — specific performance",
        "target_failure_mode": "(control) settled doctrine, post-2018 amendment",
        "evaluation_rigor": "DOCTRINAL",
        "context": (
            "Control query. Section 10 amended in 2018 to make specific performance "
            "(generally) enforceable, removing the old discretionary standard. Settled "
            "doctrine, clean precedent. System should surface this without producing "
            "attribution or scope failures."
        ),
        "must_find": [
            {
                "case": "Any post-2018 case interpreting Section 10",
                "substance": (
                    "Readiness and willingness must be pleaded and proved; Section 16(c) "
                    "framework; post-2018 amendment changed discretionary standard."
                ),
            },
        ],
        "must_reject": [
            # Control — no specific expected failure. If anything fails here, it's a
            # signal the system is over-rejecting on settled doctrine.
        ],
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# Helper functions for evaluation
# ─────────────────────────────────────────────────────────────────────────────

def get_query_ids():
    return [q["id"] for q in QUERY_SET]


def get_query_by_id(qid: str):
    for q in QUERY_SET:
        if q["id"] == qid:
            return q
    return None


def evaluation_template(qid: str) -> str:
    """Generate a blank evaluation template for a query."""
    q = get_query_by_id(qid)
    if not q:
        return f"Unknown query: {qid}"
    out = []
    out.append(f"# Evaluation: {qid}")
    out.append(f"Query: {q['query']}")
    out.append(f"Doctrinal area: {q['doctrinal_area']}")
    out.append(f"Target failure mode: {q['target_failure_mode']}")
    out.append(f"Rigor: {q['evaluation_rigor']}")
    out.append("")
    out.append("## Must-find coverage")
    for i, mf in enumerate(q["must_find"], 1):
        out.append(f"  [{i}] {mf['case']}")
        out.append(f"      Substance: {mf['substance']}")
        out.append(f"      Found?      [ ] yes  [ ] no  [ ] partial")
        out.append(f"      Notes:")
    out.append("")
    out.append("## Must-reject check")
    if not q["must_reject"]:
        out.append("  (none specified — control query)")
    for i, mr in enumerate(q["must_reject"], 1):
        out.append(f"  [{i}] {mr['case']}")
        if mr.get("paragraph"):
            out.append(f"      Paragraph: {mr['paragraph']}")
        out.append(f"      Failure mode: {mr['failure_mode']}")
        out.append(f"      Deceptive proposition (do NOT verify):")
        out.append(f"        {mr['deceptive_proposition']}")
        out.append(f"      Appeared in verified results?  [ ] YES (FAIL)  [ ] no")
        out.append(f"      Notes:")
    out.append("")
    out.append("## Other holdings in verified set (not on lists)")
    out.append("  Source-read needed: [ ] yes  [ ] no")
    out.append("  Independent judgement notes:")
    out.append("")
    out.append("## Verdict")
    out.append("  [ ] PASS    — 0 must-reject + >=50% must-find")
    out.append("  [ ] PARTIAL — 0 must-reject + <50% must-find")
    out.append("  [ ] FAIL    — any must-reject present (catastrophic)")
    out.append("")
    return "\n".join(out)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        # Print template for one query
        print(evaluation_template(sys.argv[1]))
    else:
        # List all
        print(f"Query set v1 — {len(QUERY_SET)} queries")
        for q in QUERY_SET:
            print(f"  {q['id']:<40}  [{q['evaluation_rigor']:<11}]  {q['target_failure_mode']}")
