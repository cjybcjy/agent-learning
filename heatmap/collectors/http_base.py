import asyncio
import logging
from abc import abstractmethod
from datetime import datetime, timezone

import httpx

from heatmap.extractor.ac import AhoCorasickExtractor
from heatmap.collectors.rate_limiter import RateLimiter
from heatmap.collectors.proxy_pool import ProxyPool
from heatmap.store.dao import RawMessage, Mention, QueuedMessage

LOG = logging.getLogger("heatmap.collectors.http")


class HttpCollector:
    """Base class for HTTP polling collectors."""

    def __init__(
        self,
        extractor: AhoCorasickExtractor,
        queue: asyncio.Queue,
        market: str,
        limiter: RateLimiter | None = None,
        proxy_pool: ProxyPool | None = None,
        poll_interval: float = 1800.0,
    ):
        self.extractor = extractor
        self.queue = queue
        self.market = market
        self.limiter = limiter
        self.proxy_pool = proxy_pool
        self.poll_interval = poll_interval

    async def close(self):
        pass

    async def run(self) -> None:
        """Main loop: poll at regular intervals."""
        while True:
            try:
                await self._poll_once()
            except Exception:
                LOG.exception("%s poll failed", self.__class__.__name__)
            await asyncio.sleep(self.poll_interval)

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
                platform=post.get("platform", self.__class__.__name__),
                channel=post.get("channel", "default"),
                author_id=post.get("author_id"),
                content=content,
                posted_at=post.get("posted_at", now),
                fetched_at=now,
                market=self.market,
            )
            try:
                self.queue.put_nowait(QueuedMessage(msg, mentions))
            except asyncio.QueueFull:
                LOG.warning("Queue full, dropping message from %s", msg.platform)

    async def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        """Make HTTP request with rate limiting and proxy support."""
        proxy = await self.proxy_pool.get() if self.proxy_pool else None
        if self.limiter:
            domain = url.split("/")[2]
            await self.limiter.acquire(domain, proxy)

        client = httpx.AsyncClient(timeout=30.0, follow_redirects=True, proxy=proxy)
        try:
            resp = await client.request(method, url, **kwargs)
            resp.raise_for_status()
            return resp
        except httpx.HTTPError:
            if self.proxy_pool and proxy:
                await self.proxy_pool.report_failure(proxy)
            raise
        finally:
            await client.aclose()
