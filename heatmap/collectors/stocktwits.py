import logging
from datetime import datetime, timezone
from heatmap.collectors.http_base import HttpCollector

LOG = logging.getLogger("heatmap.collectors.stocktwits")
STOCKTWITS_TRENDING_URL = "https://api.stocktwits.com/api/2/trending/symbols.json"


class StocktwitsCollector(HttpCollector):
    SOURCE_WEIGHT: float = 0.6
    PLATFORM: str = "stocktwits"

    async def _fetch_posts(self) -> list[dict]:
        try:
            resp = await self._request("GET", STOCKTWITS_TRENDING_URL)
            data = resp.json()
            symbols = data.get("symbols", [])
            posts = []
            now = datetime.now(timezone.utc)
            for sym in symbols[:30]:
                symbol = sym.get("symbol", "")
                title = sym.get("title", "")
                watch_count = sym.get("watch_count", 0)
                if not symbol:
                    continue
                posts.append({
                    "content": f"${symbol} ({title}) trending on StockTwits · {watch_count} watchers",
                    "platform": self.PLATFORM,
                    "channel": "trending",
                    "author_id": "stocktwits_bot",
                    "posted_at": now,
                })
            LOG.info("stocktwits: fetched %d trending symbols", len(posts))
            return posts
        except Exception:
            LOG.exception("stocktwits fetch failed")
            return []
