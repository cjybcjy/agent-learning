import asyncio
import random
import time


class JitterManager:
    """Add random jitter to request intervals to mimic human reading patterns."""

    def __init__(self, jitter_range: tuple[float, float] = (0.7, 1.3)):
        self.jitter_range = jitter_range
        self._last_request: dict[str, float] = {}

    def compute_delay(self, domain: str, base_interval: float) -> float:
        return base_interval * random.uniform(*self.jitter_range)

    async def wait(self, domain: str, base_interval: float) -> None:
        delay = self.compute_delay(domain, base_interval)
        await asyncio.sleep(delay)
        self._last_request[domain] = time.monotonic()


class CookieJar:
    """In-memory per-domain cookie storage."""

    def __init__(self):
        self._jar: dict[str, dict[str, str]] = {}

    def save(self, domain: str, cookies: dict[str, str]) -> None:
        self._jar[domain] = dict(cookies)

    def load(self, domain: str) -> dict[str, str]:
        return self._jar.get(domain, {})

    def merge(self, domain: str, new_cookies: dict[str, str]) -> None:
        existing = self._jar.get(domain, {})
        existing.update(new_cookies)
        self._jar[domain] = existing

    def has(self, domain: str) -> bool:
        return domain in self._jar


class ReferrerChain:
    """Build realistic referrer chains for HTTP requests."""

    _SEARCH_ENGINES = [
        "https://www.google.com/search?q={query}",
        "https://www.bing.com/search?q={query}",
    ]
    _QUERIES = [
        "stock+market+today",
        "hot+stocks+热门股票",
        "market+analysis",
        "investment+news",
    ]

    def __init__(self):
        self._chain: dict[str, str] = {}

    def build(self, target_url: str) -> str | None:
        if random.random() > 0.3:
            engine = random.choice(self._SEARCH_ENGINES)
            query = random.choice(self._QUERIES)
            return engine.format(query=query)
        return None
