import logging
import asyncio
import os
from datetime import datetime, timezone
from heatmap.collectors.http_base import HttpCollector

LOG = logging.getLogger("heatmap.collectors.lunarcrush")
LUNARCRUSH_API = "https://lunarcrush.com/api4/public/coins/list/v2"

class LunarcrushCollector(HttpCollector):
    SOURCE_WEIGHT: float = 0.5
    PLATFORM: str = "lunarcrush"

    def __init__(self, *args, **kwargs):
        kwargs["poll_interval"] = kwargs.get("poll_interval", 3600)
        super().__init__(*args, **kwargs)
        self._backoff = 0

    async def _fetch_posts(self) -> list[dict]:
        api_key = os.environ.get("LUNARCRUSH_API_KEY", "")
        if not api_key:
            LOG.warning("lunarcrush: no API key configured, skipping")
            return []
        backoff_delay = min(2 ** self._backoff, 300)
        if self._backoff > 0:
            LOG.info("lunarcrush: backoff %ds", backoff_delay)
            await asyncio.sleep(backoff_delay)
        try:
            resp = await self._request("GET", LUNARCRUSH_API, headers={"Authorization": f"Bearer {api_key}"})
            remaining = resp.headers.get("X-RateLimit-Remaining")
            if remaining is not None and int(remaining) < 5:
                LOG.warning("lunarcrush: rate limit low (%s remaining), backing off", remaining)
                self._backoff += 1
            data = resp.json()
            coins = data.get("data", [])
            posts = []
            now = datetime.now(timezone.utc)
            for coin in coins[:30]:
                name = coin.get("name", "")
                symbol = coin.get("symbol", "")
                galaxy_score = coin.get("galaxy_score", 0)
                if not name: continue
                posts.append({"content": f"{name} (${symbol.upper()}) Galaxy Score: {galaxy_score} · social volume trending on LunarCrush", "platform": self.PLATFORM, "channel": "social_sentiment", "author_id": "lunarcrush_bot", "posted_at": now})
            self._backoff = 0
            LOG.info("lunarcrush: fetched %d coins", len(posts))
            return posts
        except Exception:
            LOG.exception("lunarcrush fetch failed")
            self._backoff += 1
            return []
