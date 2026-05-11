import asyncio
import logging
from abc import abstractmethod
from datetime import datetime, timezone

import httpx

from heatmap.extractor.ac import AhoCorasickExtractor
from heatmap.collectors.rate_limiter import RateLimiter
from heatmap.collectors.proxy_pool import ProxyPool
from heatmap.collectors.ua_pool import UserAgentPool
from heatmap.collectors.jitter import JitterManager, CookieJar, ReferrerChain
from heatmap.collectors.circuit_breaker import CircuitBreaker
from heatmap.collectors.browser_fallback import BrowserFallback
from heatmap.store.dao import RawMessage, Mention, QueuedMessage

LOG = logging.getLogger("heatmap.collectors.http")


class HttpCollector:
    """Base class for HTTP polling collectors with L1-L4 anti-crawl capabilities."""

    # Source weight for weighted scoring (override in subclasses)
    SOURCE_WEIGHT: float = 0.5

    # Platform name for DB (override in subclasses)
    PLATFORM: str = "http"

    def __init__(
        self,
        extractor: AhoCorasickExtractor,
        queue: asyncio.Queue,
        market: str,
        limiter: RateLimiter | None = None,
        proxy_pool: ProxyPool | None = None,
        circuit_breaker: CircuitBreaker | None = None,
        poll_interval: float = 1800.0,
        browser_fallback: bool = False,
    ):
        self.extractor = extractor
        self.queue = queue
        self.market = market
        self.limiter = limiter
        self.proxy_pool = proxy_pool
        self.circuit_breaker = circuit_breaker
        self.poll_interval = poll_interval
        self.browser_fallback_enabled = browser_fallback

        # L1: UA pool
        self.ua_pool = UserAgentPool()

        # L2: Jitter + Cookie + Referrer
        self.jitter = JitterManager()
        self.cookie_jar = CookieJar()
        self.referrer_chain = ReferrerChain()

        # L3: Browser fallback
        self._browser: BrowserFallback | None = None
        self._consecutive_failures: dict[str, int] = {}

    async def close(self):
        if self._browser:
            await self._browser.close()

    async def run(self) -> None:
        """Main loop: poll at regular intervals with circuit breaker check."""
        while True:
            # Check circuit breaker before polling
            if self.circuit_breaker and not self.circuit_breaker.allow_request():
                LOG.info("%s: circuit breaker tripped, sleeping 60s", self.PLATFORM)
                await asyncio.sleep(60)
                continue

            try:
                await self._poll_once()
            except Exception:
                LOG.exception("%s poll failed", self.PLATFORM)
            await self.jitter.wait(self.PLATFORM, self.poll_interval)

    @abstractmethod
    async def _fetch_posts(self) -> list[dict]:
        """Fetch posts from source. Return list of {content, platform, channel, posted_at}."""
        ...

    async def _poll_once(self) -> None:
        posts = await self._fetch_posts()
        now = datetime.now(timezone.utc)
        for post in posts:
            content = post.get("content", "")
            hits = self.extractor.extract(content)
            mentions = [
                Mention(0, h.symbol, h.matched_alias, h.is_ambiguous, 1.0)
                for h in hits
            ]
            msg = RawMessage(
                platform=post.get("platform", self.PLATFORM),
                channel=post.get("channel", "default"),
                author_id=post.get("author_id"),
                content=content,
                posted_at=post.get("posted_at", now),
                fetched_at=now,
                market=self.market,
            )
            try:
                self.queue.put_nowait(QueuedMessage(msg, mentions, source_weight=self.SOURCE_WEIGHT))
            except asyncio.QueueFull:
                LOG.warning("Queue full, dropping message from %s", msg.platform)

    async def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        """Make HTTP request with L1-L4 anti-crawl protection."""
        domain = url.split("/")[2]

        # L1: Randomize headers
        headers = self.ua_pool.random_headers()
        if "headers" in kwargs:
            headers.update(kwargs.pop("headers"))
        kwargs["headers"] = headers

        # L2: Inject cookies
        cookies = self.cookie_jar.load(domain)
        if cookies:
            kwargs.setdefault("cookies", {}).update(cookies)

        # L2: Set referrer
        referrer = self.referrer_chain.build(url)
        if referrer:
            headers["Referer"] = referrer

        # L4: Proxy
        proxy = await self.proxy_pool.get(domain) if self.proxy_pool else None

        client = httpx.AsyncClient(timeout=30.0, follow_redirects=True, proxy=proxy)
        try:
            resp = await client.request(method, url, **kwargs)
            resp.raise_for_status()

            # L2: Save cookies from response
            set_cookie_headers = resp.headers.get_list("set-cookie") if hasattr(resp.headers, 'get_list') else []
            if not set_cookie_headers:
                set_cookie_header = resp.headers.get("set-cookie", "")
                set_cookie_headers = [set_cookie_header] if set_cookie_header else []
            for cookie_str in set_cookie_headers:
                if "=" in cookie_str:
                    key = cookie_str.split("=")[0]
                    val = cookie_str.split("=")[1].split(";")[0]
                    self.cookie_jar.merge(domain, {key: val})

            # Reset failure count on success
            self._consecutive_failures[domain] = 0

            return resp

        except httpx.HTTPError as e:
            LOG.warning("%s: HTTP request failed for %s: %s", self.PLATFORM, domain, e)
            if self.proxy_pool and proxy:
                await self.proxy_pool.report_failure(proxy, domain)
                if self.circuit_breaker:
                    self.circuit_breaker.report_availability(self.proxy_pool.availability_ratio)

            # Track consecutive failures for L3 fallback
            self._consecutive_failures[domain] = self._consecutive_failures.get(domain, 0) + 1

            raise
        finally:
            await client.aclose()

    async def _request_with_fallback(self, method: str, url: str, **kwargs) -> httpx.Response | str:
        """Request with L3 browser fallback on repeated failure."""
        domain = url.split("/")[2]
        try:
            return await self._request(method, url, **kwargs)
        except httpx.HTTPError:
            if self.browser_fallback_enabled and self._consecutive_failures.get(domain, 0) >= 3:
                LOG.info("%s: Falling back to browser for %s", self.PLATFORM, domain)
                if self._browser is None:
                    self._browser = BrowserFallback(headless=True)
                try:
                    content = await self._browser.fetch(url)
                    self._consecutive_failures[domain] = 0
                    return content  # type: ignore
                except Exception:
                    LOG.exception("%s: Browser fallback also failed for %s", self.PLATFORM, domain)
            raise
