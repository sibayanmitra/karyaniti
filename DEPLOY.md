# Vakeel AI — Beta Deploy Guide

---

## What you need before starting

- A laptop/PC with Python 3.10+ installed
- Your Indian Kanoon API token (from api.indiankanoon.org)
- Your OpenRouter API key (from openrouter.ai)
- 5 minutes

---

## Step 1 — Unzip and enter the folder

```bash
unzip vakeel_beta.zip -d vakeel
cd vakeel
```

---

## Step 2 — Create your .env file

```bash
cp .env.example .env
```

Open `.env` in any text editor and fill in your two keys:

```
INDIAN_KANOON_API_TOKEN=your_ik_token_here
OPENROUTER_API_KEY=your_openrouter_key_here
```

Save and close. Do not share this file or commit it to Git.

---

## Step 3 — Install Python dependencies

```bash
pip install -r requirements.txt
```

If you get a permissions error on Linux/Mac:

```bash
pip install -r requirements.txt --user
```

If you are on a system Python (Ubuntu):

```bash
pip install -r requirements.txt --break-system-packages
```

---

## Step 4 — Run the server

```bash
python main.py
```

You should see:

```
── Vakeel AI Local Server ──────────────────────
  IK Token : ✓ SET
  OR Key   : ✓ SET
  Extractor: nvidia/nemotron-3-super-120b-a12b:free
  Judge    : nvidia/nemotron-3-super-120b-a12b:free
  Open     : http://localhost:8765
────────────────────────────────────────────────
```

If either token shows `✗ MISSING`, re-check your `.env` file.

---

## Step 5 — Open the app

Open your browser and go to:

```
http://localhost:8765
```

The green dot next to "Corpus" in the top right means both API keys are connected.

---

## Step 6 — Run your first query

1. Type a legal query in the text box, e.g.: `natural justice audi alteram partem administrative decision`
2. Click **Search Case Law →** or press `Ctrl+Enter`
3. Watch the pipeline trace at the bottom as it runs
4. Results appear below with PASS/FAIL badges per holding

For the beta: run the **False premise test** example first (amber button). It should detect and warn about the false premise before even hitting the corpus. If it does — pipeline is working.

---

## Choosing models for the beta test

Click **Model configuration** to expand the selector panel.

**Recommended beta sequence (in order):**

| Run | Extractor | Judge | Synthesis | Purpose |
|-----|-----------|-------|-----------|---------|
| 1 | Nemotron 120B (free) | Nemotron 120B (free) | Ling 2.6 (free) | Baseline — free |
| 2 | Gemini 2.5 Flash | Gemini 2.5 Flash | Gemini 2.5 Flash | Cheap paid — ~$0.03/query |
| 3 | DeepSeek V3.1 (free) | Claude Sonnet 4.5 | Gemini 2.5 Flash | Mixed — paid judge only |
| 4 | GPT-4.1 | GPT-4.1 | GPT-4.1 | Full GPT-4.1 — ~$0.15/query |

Run the same 5-10 queries across all 4 configs. Compare:
- Did the same hallucinated cases appear?
- Did a paid judge catch FAILs the free judge passed?
- Was the synthesis note coherent and legally accurate?

**With $10 OpenRouter credit:** Run 60 queries at Gemini Flash pricing (~$0.03) = ~$1.80. 
Run 20 queries at Sonnet judge only (~$0.08 each) = ~$1.60. Plenty of headroom.

---

## Stopping the server

Press `Ctrl+C` in the terminal.

---

## If something breaks

**"No results from Indian Kanoon"**
→ Your IK token may be invalid, or the query has no matching SC cases. Try broader keywords.

**"All models in fallback chain unavailable"**
→ Free models are overloaded. Open Model configuration and switch to any paid model.

**Server won't start — port in use**
→ Something else is on port 8765. Change the port in the last line of `main.py`:
```python
uvicorn.run("main:app", host="0.0.0.0", port=8766, reload=True)
```

**ModuleNotFoundError**
→ Re-run `pip install -r requirements.txt`. Make sure you're running `python main.py` from inside the vakeel folder.

---

## Sharing with a beta tester on the same network

1. Find your local IP:
   - Mac/Linux: `ifconfig | grep inet`
   - Windows: `ipconfig`
2. Give them: `http://YOUR_IP:8765`
3. They need to be on the same WiFi.

For external access (sharing with Drishti remotely), see the cloud deploy section below.

---

## Cloud deploy (Railway — 10 minutes, free tier)

Railway is the fastest way to make Vakeel accessible from anywhere.

### 1. Push code to GitHub

```bash
git init
git add main.py index.html requirements.txt
# Do NOT add .env — it contains your keys
echo ".env" >> .gitignore
git add .gitignore
git commit -m "vakeel beta"
gh repo create vakeel-beta --private --source=. --push
# or: git remote add origin https://github.com/YOUR_USERNAME/vakeel-beta.git && git push -u origin main
```

### 2. Deploy on Railway

1. Go to railway.app → New Project → Deploy from GitHub repo
2. Select your `vakeel-beta` repo
3. Railway auto-detects Python and runs `python main.py`

### 3. Add environment variables on Railway

In the Railway dashboard → your service → Variables tab:

```
INDIAN_KANOON_API_TOKEN = your_ik_token
OPENROUTER_API_KEY      = your_openrouter_key
```

### 4. Fix the port for Railway

Railway assigns a dynamic port via `$PORT`. Change the last block in `main.py`:

```python
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8765))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
```

Commit and push — Railway redeploys automatically.

### 5. Get your public URL

Railway gives you a URL like `https://vakeel-beta-production.up.railway.app`.
Share this with beta testers. It works from any browser, anywhere.

**Railway free tier:** 500 hours/month. More than enough for beta testing.

---

## Security note for beta

The server has no authentication. Anyone with the URL can run queries (and spend your OpenRouter credits). 

Quick fix — add a password gate. Add to `.env`:
```
BETA_PASSWORD=choose_something
```

Add to the top of `main.py` after `load_dotenv()`:
```python
BETA_PASS = os.getenv("BETA_PASSWORD", "")
```

Add to the `/api/research` route:
```python
@app.post("/api/research")
async def research(req: ResearchRequest, request: Request):
    if BETA_PASS and request.headers.get("X-Beta-Pass") != BETA_PASS:
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    return StreamingResponse(...)
```

Then give testers the password separately.

---

## Data source attribution

Per Indian Kanoon API terms, any public-facing product must attribute the data source.
This is handled in Vakeel's documentation and terms page — not in the main UI.
Template text for your docs/terms:

> "Case law and judgment data is sourced from Indian Kanoon (indiankanoon.org),
> which indexes official Indian court records. Vakeel AI uses the Indian Kanoon
> API to retrieve primary source documents. All holdings are AI-extracted and
> unverified — users must verify citations against primary sources before
> relying on them in legal proceedings."
