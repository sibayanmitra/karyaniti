"""HTTP + retry plumbing for OpenRouter LLM calls and IK search."""
import asyncio, httpx, json, os, random, re
from dotenv import load_dotenv

load_dotenv()
IK_TOKEN = os.getenv("INDIAN_KANOON_API_TOKEN", "")
OR_KEY   = os.getenv("OPENROUTER_API_KEY", "")


class RetryableError(Exception):
    pass


async def _post_with_retry(client, url, *, headers, json_body=None, data=None, max_tries=4):
    delay = 1.5
    last_exc = None
    for attempt in range(max_tries):
        try:
            r = await client.post(url, headers=headers, json=json_body, data=data,
                                  timeout=httpx.Timeout(120))
            if r.status_code == 429 or 500 <= r.status_code < 600:
                raise RetryableError(f"HTTP {r.status_code}")
            return r
        except (httpx.TimeoutException, httpx.ConnectError, RetryableError) as e:
            last_exc = e
            if attempt == max_tries - 1:
                break
            await asyncio.sleep(delay + random.random())
            delay *= 2
    raise last_exc or RuntimeError("retry exhausted")


async def llm(model: str, prompt: str, max_tokens: int = 2200) -> tuple[str, dict]:
    """Call OpenRouter, return (content, usage_dict)."""
    async with httpx.AsyncClient() as c:
        r = await _post_with_retry(c, "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {OR_KEY}",
                     "Content-Type": "application/json",
                     "HTTP-Referer": "https://karyaniti.in",
                     "X-Title": "Karyaniti Authority Builder"},
            json_body={"model": model,
                       "messages": [{"role": "user", "content": prompt}],
                       "temperature": 0.0, "max_tokens": max_tokens})
    r.raise_for_status()
    data = r.json()
    content = data["choices"][0]["message"].get("content") or ""
    return content, data.get("usage", {})


async def ik_search(query: str, doctypes: str = "supremecourt") -> list:
    """Search Indian Kanoon. Returns list of doc dicts (may be empty)."""
    async with httpx.AsyncClient() as c:
        try:
            r = await _post_with_retry(c, "https://api.indiankanoon.org/search/",
                headers={"Authorization": f"Token {IK_TOKEN}"},
                data={"formInput": query, "pagenum": 0, "doctypes": doctypes})
            return r.json().get("docs", []) if r.status_code == 200 else []
        except Exception:
            return []


# ── JSON parsing with truncation tolerance ─────────────────────────────────

def parse_json(raw: str) -> dict:
    """Parse JSON from LLM output, repairing common issues."""
    c = re.sub(r"```json\s*|```\s*", "", raw).strip()
    s, e = c.find("{"), c.rfind("}") + 1
    if s < 0:
        return {}
    try:
        return json.loads(c[s:e])
    except json.JSONDecodeError:
        fixed = re.sub(r",(\s*[}\]])", r"\1", c[s:e])
        try:
            return json.loads(fixed)
        except json.JSONDecodeError:
            return {}


def strip_html(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s or "")
