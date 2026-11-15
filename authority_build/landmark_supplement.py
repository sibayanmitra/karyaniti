"""
Landmark SC cases to supplement authority_index.py.

The base index has good coverage for pre-2019 doctrinal landmarks but uneven
coverage for (a) post-2019 cases, (b) evidence-law and arbitration sub-areas,
(c) cases referenced in treatment_status.json as overruled-by replacements.

Each entry: name + citation. The resolver script uses the citation phrase
to find the IK doc, verifies the citation appears in the body, then merges
into AUTHORITY_INDEX.

Categories are advisory only — drives priority if a partial run is needed.
"""

LANDMARK_SUPPLEMENT = [
    # ── treatment_chain — non-negotiable replacements for cases in treatment_status.json ──
    {"name": "Arjun Panditrao Khotkar v Kailash Kushanrao Gorantyal",
     "citation": "(2020) 7 SCC 1", "category": "treatment_chain"},
    {"name": "Bharat Aluminium Co v Kaiser Aluminium Technical Services",
     "citation": "(2012) 9 SCC 552", "category": "treatment_chain"},
    {"name": "Cox and Kings Ltd v SAP India Pvt Ltd",
     "citation": "(2023) 14 SCC 1", "category": "treatment_chain"},
    {"name": "Vijay Madanlal Choudhary v Union of India",
     "citation": "(2022) SCC OnLine SC 929", "category": "treatment_chain"},

    # ── evidence — §65B and electronic records ──
    {"name": "Anvar P.V. v P.K. Basheer",
     "citation": "(2014) 10 SCC 473", "category": "evidence"},
    {"name": "Tomaso Bruno v State of Uttar Pradesh",
     "citation": "(2015) 7 SCC 178", "category": "evidence"},
    {"name": "Sonu @ Amar v State of Haryana",
     "citation": "(2017) 8 SCC 570", "category": "evidence"},
    {"name": "State (NCT of Delhi) v Navjot Sandhu",
     "citation": "(2005) 11 SCC 600", "category": "evidence"},
    {"name": "Ravinder Singh @ Kaku v State of Punjab",
     "citation": "(2022) 7 SCC 581", "category": "evidence"},

    # ── arbitration — current law ──
    {"name": "HRD Corporation v GAIL (India) Ltd",
     "citation": "(2018) 12 SCC 471", "category": "arbitration"},
    {"name": "Voestalpine Schienen GmbH v Delhi Metro Rail Corporation",
     "citation": "(2017) 4 SCC 665", "category": "arbitration"},
    {"name": "Bharat Broadband Network Ltd v United Telecoms Ltd",
     "citation": "(2019) 5 SCC 755", "category": "arbitration"},
    {"name": "Perkins Eastman Architects DPC v HSCC (India) Ltd",
     "citation": "(2020) 20 SCC 760", "category": "arbitration"},
    {"name": "In Re Interplay between Arbitration Agreements and Stamp Act",
     "citation": "(2024) 6 SCC 1", "category": "arbitration"},
    {"name": "NN Global Mercantile Pvt Ltd v Indo Unique Flame Ltd",
     "citation": "(2023) 7 SCC 1", "category": "arbitration"},
    {"name": "Chloro Controls India v Severn Trent Water Purification",
     "citation": "(2013) 1 SCC 641", "category": "arbitration"},
    {"name": "Centrotrade Minerals and Metal Inc v Hindustan Copper Ltd",
     "citation": "(2017) 2 SCC 228", "category": "arbitration"},
    {"name": "PASL Wind Solutions v GE Power Conversion",
     "citation": "(2021) 7 SCC 1", "category": "arbitration"},

    # ── criminal procedure — recent and missing landmarks ──
    {"name": "Arnesh Kumar v State of Bihar",
     "citation": "(2014) 8 SCC 273", "category": "criminal_procedure"},
    {"name": "Joginder Kumar v State of UP",
     "citation": "(1994) 4 SCC 260", "category": "criminal_procedure"},
    {"name": "DK Basu v State of West Bengal",
     "citation": "(1997) 1 SCC 416", "category": "criminal_procedure"},
    {"name": "Lalita Kumari v Government of UP",
     "citation": "(2014) 2 SCC 1", "category": "criminal_procedure"},
    {"name": "Selvi v State of Karnataka",
     "citation": "(2010) 7 SCC 263", "category": "criminal_procedure"},
    {"name": "Pankaj Bansal v Union of India",
     "citation": "(2024) 7 SCC 576", "category": "criminal_procedure"},
    {"name": "Prabir Purkayastha v State (NCT of Delhi)",
     "citation": "(2024) 8 SCC 254", "category": "criminal_procedure"},

    # ── constitutional law — foundational and missing ──
    {"name": "Kesavananda Bharati v State of Kerala",
     "citation": "(1973) 4 SCC 225", "category": "constitutional"},
    {"name": "SR Bommai v Union of India",
     "citation": "(1994) 3 SCC 1", "category": "constitutional"},
    {"name": "Vishaka v State of Rajasthan",
     "citation": "(1997) 6 SCC 241", "category": "constitutional"},
    {"name": "Indra Sawhney v Union of India",
     "citation": "(1992) Supp (3) SCC 217", "category": "constitutional"},
    {"name": "Minerva Mills Ltd v Union of India",
     "citation": "(1980) 3 SCC 625", "category": "constitutional"},
    {"name": "Janhit Abhiyan v Union of India",
     "citation": "(2023) 5 SCC 1", "category": "constitutional"},
    {"name": "Supriyo @ Supriya Chakraborty v Union of India",
     "citation": "(2024) 5 SCC 313", "category": "constitutional"},
    {"name": "Anuradha Bhasin v Union of India",
     "citation": "(2020) 3 SCC 637", "category": "constitutional"},

    # ── res judicata, CPC — intern research topic ──
    {"name": "Satyadhyan Ghosal v Smt Deorajin Debi",
     "citation": "AIR 1960 SC 941", "category": "intern_research"},
    {"name": "State of UP v Nawab Hussain",
     "citation": "(1977) 2 SCC 806", "category": "intern_research"},
    {"name": "Sulochana Amma v Narayanan Nair",
     "citation": "(1994) 2 SCC 14", "category": "intern_research"},

    # ── execution + jurisdiction — intern research topic ──
    {"name": "Brahmdeo Choudhary v Rishikesh Prasad Jaiswal",
     "citation": "(1997) 3 SCC 694", "category": "intern_research"},
    {"name": "Hiralal Patni v Sri Kali Nath",
     "citation": "AIR 1962 SC 199", "category": "intern_research"},
    {"name": "Vasudev Dhanjibhai Modi v Rajabhai Abdul Rehman",
     "citation": "(1970) 1 SCC 670", "category": "intern_research"},

    # ── partition — intern research topic ──
    {"name": "Phoolchand v Gopal Lal",
     "citation": "AIR 1967 SC 1470", "category": "intern_research"},
    {"name": "R Ramamurthi Iyer v Raja V Rajeswara Rao",
     "citation": "AIR 1969 SC 1247", "category": "intern_research"},

    # ── handwriting expert §45 Evidence Act — intern research topic ──
    {"name": "Murari Lal v State of Madhya Pradesh",
     "citation": "(1980) 1 SCC 704", "category": "intern_research"},
    {"name": "State (Delhi Administration) v Pali Ram",
     "citation": "(1979) 2 SCC 158", "category": "intern_research"},
    {"name": "Magan Bihari Lal v State of Punjab",
     "citation": "(1977) 2 SCC 210", "category": "intern_research"},

    # ── IBC ──
    {"name": "Innoventive Industries Ltd v ICICI Bank",
     "citation": "(2018) 1 SCC 407", "category": "ibc"},
    {"name": "Essar Steel India Ltd Committee of Creditors v Satish Kumar Gupta",
     "citation": "(2020) 8 SCC 531", "category": "ibc"},
    {"name": "Pioneer Urban Land and Infrastructure v Union of India",
     "citation": "(2019) 8 SCC 416", "category": "ibc"},
    {"name": "Phoenix ARC Pvt Ltd v Spade Financial Services",
     "citation": "(2021) 3 SCC 475", "category": "ibc"},
    {"name": "Vidarbha Industries Power Ltd v Axis Bank Ltd",
     "citation": "(2022) 8 SCC 352", "category": "ibc"},

    # ── property and limitation ──
    {"name": "Suraj Lamp and Industries v State of Haryana",
     "citation": "(2012) 1 SCC 656", "category": "property"},
    {"name": "Ravinder Kaur Grewal v Manjit Kaur",
     "citation": "(2019) 8 SCC 729", "category": "property"},
    {"name": "Vidyadhar v Manikrao",
     "citation": "(1999) 3 SCC 573", "category": "property"},

    # ── service law and pensions ──
    {"name": "Secretary State of Karnataka v Umadevi",
     "citation": "(2006) 4 SCC 1", "category": "service_law"},
    {"name": "DS Nakara v Union of India",
     "citation": "(1983) 1 SCC 305", "category": "service_law"},

    # ── family law and maintenance ──
    {"name": "Rajnesh v Neha",
     "citation": "(2021) 2 SCC 324", "category": "family"},
    {"name": "Mohd Abdul Samad v State of Telangana",
     "citation": "(2024) SCC OnLine SC 1686", "category": "family"},
    {"name": "Joseph Shine v Union of India",
     "citation": "(2019) 3 SCC 39", "category": "family"},

    # ── PMLA and economic offences (post-Vijay Madanlal landscape) ──
    {"name": "Pavana Dibbur v Directorate of Enforcement",
     "citation": "(2024) 2 SCC 752", "category": "pmla"},
    {"name": "Tarsem Lal v Directorate of Enforcement",
     "citation": "(2024) 7 SCC 61", "category": "pmla"},

    # ── tax and writ ──
    {"name": "Calcutta Discount Co Ltd v ITO",
     "citation": "AIR 1961 SC 372", "category": "tax_writ"},
    {"name": "Whirlpool Corporation v Registrar of Trade Marks",
     "citation": "(1998) 8 SCC 1", "category": "tax_writ"},
]


if __name__ == "__main__":
    from collections import Counter
    cats = Counter(c["category"] for c in LANDMARK_SUPPLEMENT)
    print(f"Total cases: {len(LANDMARK_SUPPLEMENT)}")
    print("By category:")
    for cat, n in cats.most_common():
        print(f"  {n:>3}  {cat}")
