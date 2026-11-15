"""Quick check: is the OpenRouter key working with V4 Pro and Gemini?"""
import httpx, os
from dotenv import load_dotenv
load_dotenv()

KEY = os.getenv("OPENROUTER_API_KEY", "")
print(f"Key prefix: {KEY[:12]}  length: {len(KEY)}\n")

for model in ["deepseek/deepseek-v4-pro", "google/gemini-3.1-pro-preview"]:
    try:
        r = httpx.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://karyaniti.in",
                "X-Title": "Karyaniti",
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": "Say 'ok' and nothing else."}],
                "max_tokens": 10,
            },
            timeout=30,
        )
        print(f"{model}")
        print(f"  status: {r.status_code}")
        print(f"  body:   {r.text[:400]}\n")
    except Exception as e:
        print(f"{model} → EXCEPTION: {e}\n")
