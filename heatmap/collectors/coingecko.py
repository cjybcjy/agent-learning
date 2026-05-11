import logging
from datetime import datetime, timezone
from heatmap.collectors.http_base import HttpCollector

LOG = logging.getLogger("heatmap.collectors.coingecko")
COINGECKO_TRENDING_URL = "https://api.coingecko.com/api/v3/search/trending"

class CoingeckoCollector(HttpCollector):
    SOURCE_WEIGHT: float = 0.7
    PLATFORM: str = "coingecko"

    async def _fetch_posts(self) -> list[dict]:
        try:
            resp = await self._request("GET", COINGECKO_TRENDING_URL)
            data = resp.json()
            coins = data.get("coins", [])
            posts = []
            now = datetime.now(timezone.utc)
            for coin_data in coins[:30]:
                item = coin_data.get("item", {})
                name = item.get("name", "")
                symbol = item.get("symbol", "")
                market_cap_rank = item.get("market_cap_rank", "N/A")
                score = item.get("score", 0)
                if not name: continue
                posts.append({"content": f"{name} (${symbol.upper()}) trending on CoinGecko · market cap rank #{market_cap_rank} · score {score}", "platform": self.PLATFORM, "channel": "trending", "author_id": "coingecko_bot", "posted_at": now})
            LOG.info("coingecko: fetched %d trending coins", len(posts))
            return posts
        except Exception:
            LOG.exception("coingecko fetch failed")
            return []
