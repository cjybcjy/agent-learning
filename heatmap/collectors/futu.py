import logging
import re
from datetime import datetime, timezone
from heatmap.collectors.http_base import HttpCollector

LOG = logging.getLogger("heatmap.collectors.futu")
FUTU_COMMUNITY_URL = "https://www.futunn.com/community/hot"


class FutuCollector(HttpCollector):
    SOURCE_WEIGHT: float = 0.7
    PLATFORM: str = "futu"

    def __init__(self, *args, **kwargs):
        kwargs["browser_fallback"] = True
        kwargs["poll_interval"] = kwargs.get("poll_interval", 3600)
        super().__init__(*args, **kwargs)

    async def _fetch_posts(self) -> list[dict]:
        try:
            resp = await self._request("GET", FUTU_COMMUNITY_URL)
            content = resp.text
        except Exception:
            LOG.info("futu: HTTP failed, using browser fallback")
            content = await self._browser.fetch(FUTU_COMMUNITY_URL) if self._browser else ""
        posts = []
        now = datetime.now(timezone.utc)
        hk_codes = set(re.findall(r'\b(\d{5})\b', content))
        us_tickers = set(re.findall(r'\b([A-Z]{2,5})\b', content))
        for code in list(hk_codes)[:25]:
            posts.append({
                "content": f"富途社区热议: 港股 {code}",
                "platform": self.PLATFORM,
                "channel": "futu_community",
                "author_id": "futu_bot",
                "posted_at": now,
            })
        for ticker in list(us_tickers)[:25]:
            posts.append({
                "content": f"富途社区热议: {ticker}",
                "platform": self.PLATFORM,
                "channel": "futu_community",
                "author_id": "futu_bot",
                "posted_at": now,
            })
        LOG.info("futu: parsed %d posts", len(posts))
        return posts
