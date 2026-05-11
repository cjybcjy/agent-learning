import logging
import re
from datetime import datetime, timezone
from heatmap.collectors.http_base import HttpCollector

LOG = logging.getLogger("heatmap.collectors.aastocks")
AASTOCKS_URL = "https://www.aastocks.com/en/stocks/market/quote/hk-stock-quote.aspx"


class AastocksCollector(HttpCollector):
    SOURCE_WEIGHT: float = 0.9
    PLATFORM: str = "aastocks"

    async def _fetch_posts(self) -> list[dict]:
        try:
            resp = await self._request("GET", AASTOCKS_URL)
            content = resp.text
            posts = []
            now = datetime.now(timezone.utc)
            codes = re.findall(r'\b(\d{5})\b', content)
            seen = set()
            for code in codes[:30]:
                if code in seen:
                    continue
                seen.add(code)
                posts.append({
                    "content": f"港股 {code} 成交活跃，市场关注度上升。",
                    "platform": self.PLATFORM,
                    "channel": "hk_hot",
                    "author_id": "aastocks_bot",
                    "posted_at": now,
                })
            LOG.info("aastocks: parsed %d HK stocks", len(posts))
            return posts
        except Exception:
            LOG.exception("aastocks fetch failed")
            return []
