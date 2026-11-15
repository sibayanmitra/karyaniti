"""HTTP client for indiankanoon.org public website. Polite, retry-aware."""
import time
import httpx

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/120.0.0.0 Safari/537.36")

REQUEST_DELAY_SECONDS = 3.0


class IKClient:
    """Singleton-ish wrapper. One session per phase. Honours delay."""

    def __init__(self, delay: float = REQUEST_DELAY_SECONDS):
        self.delay = delay
        self._last_request_t = 0.0
        self.session = httpx.Client(
            headers={"User-Agent": USER_AGENT,
                     "Accept": "text/html,application/xhtml+xml",
                     "Accept-Language": "en-US,en;q=0.9"},
            timeout=30,
            follow_redirects=True,
        )

    def _throttle(self):
        wait = self.delay - (time.time() - self._last_request_t)
        if wait > 0:
            time.sleep(wait)
        self._last_request_t = time.time()

    def fetch(self, url: str, retries: int = 3) -> str | None:
        last_err = None
        for attempt in range(retries):
            self._throttle()
            try:
                r = self.session.get(url)
                if r.status_code == 200:
                    return r.text
                if r.status_code in (429, 503):
                    wait = 30 * (attempt + 1)
                    print(f"   rate-limited ({r.status_code}), sleeping {wait}s")
                    time.sleep(wait)
                    continue
                return None
            except Exception as e:
                last_err = e
                time.sleep(5 * (attempt + 1))
        if last_err:
            print(f"   fetch exhausted: {last_err}")
        return None

    def search(self, query: str) -> str | None:
        """Run IK search query. Returns raw HTML."""
        from urllib.parse import quote_plus
        return self.fetch(f"https://indiankanoon.org/search/?formInput={quote_plus(query)}")

    def doc(self, tid: str) -> str | None:
        return self.fetch(f"https://indiankanoon.org/doc/{tid}/")

    def close(self):
        self.session.close()
