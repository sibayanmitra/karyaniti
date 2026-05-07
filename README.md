# Vakeel AI — Local Research Server

Real Indian legal research using Indian Kanoon official API + council pipeline.

## Setup (3 steps)

**Step 1 — Install dependencies**
```bash
pip install -r requirements.txt
```

**Step 2 — Add your keys**
```bash
cp .env.example .env
# Edit .env with your IK token and OpenRouter key
```

**Step 3 — Run**
```bash
python main.py
```

Open **http://localhost:8765**

## What it does differently from the playground

- Searches Indian Kanoon's real corpus (not LLM training memory)
- Fetches actual judgment text via IK official API
- Uses IK's paragraph classification to find holding paragraphs
- Runs full council on real text with L1 string verification
- Links back to the actual IK document for every holding
- Shows which High Court to search via the scope selector

## Cost per query

- IK API: Rs 0.50 (search) + Rs 0.20/doc (up to 4 docs) = Rs 1.30
- LLM (free models): Rs 0
- Total: ~Rs 1.30 per query from IK API balance

## Upgrade models

Edit `.env` to swap any council role to a better model.
Judge is the most important slot — use your best available model there.
