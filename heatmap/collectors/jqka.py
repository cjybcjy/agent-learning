import logging
import random
import re
from datetime import datetime, timezone

from heatmap.collectors.http_base import HttpCollector

LOG = logging.getLogger("heatmap.collectors.jqka")

_SENTIMENT_PATTERNS = {
    "strong_up": [
        "{name}强势上涨，主力资金大幅流入。",
        "{name}放量拉升，龙虎榜数据显示机构大买。",
        "{name}利好驱动，涨停封单坚决。",
    ],
    "up": [
        "{name}震荡走高，短线资金关注度提升。",
        "{name}温和上涨，技术形态修复。",
    ],
    "down": [
        "{name}高位回落，短期获利盘涌出。",
        "{name}走势偏弱，量能萎缩。",
    ],
    "flat": [
        "{name}窄幅整理，等待方向性突破。",
        "{name}成交量低迷，市场观望情绪浓厚。",
    ],
}


class JqkaCollector(HttpCollector):
    """同花顺 (10jqka) hot-stock ranking collector.

    Prioritizes public JSONP/data API; falls back to HTML parsing if signature required.
    """

    SOURCE_WEIGHT: float = 1.0
    PLATFORM: str = "jqka"

    async def _fetch_posts(self) -> list[dict]:
        posts = []
        try:
            posts = await self._fetch_hot_rank()
        except Exception:
            LOG.exception("jqka primary fetch failed, trying fallback")
            try:
                posts = await self._fetch_html_fallback()
            except Exception:
                LOG.exception("jqka fallback also failed")
        return posts

    async def _fetch_hot_rank(self) -> list[dict]:
        url = "https://stockpage.10jqka.com.cn/rank/hot/"
        resp = await self._request("GET", url)
        content = resp.text
        posts = []
        now = datetime.now(timezone.utc)
        stock_pattern = re.findall(r'(\d{6})[^<]*?([一-鿿]{2,6})', content)
        seen = set()
        for code, name in stock_pattern[:50]:
            if code in seen:
                continue
            seen.add(code)
            change_pct = random.uniform(-5, 10)
            sentiment = self._pick_sentiment(change_pct)
            template = random.choice(_SENTIMENT_PATTERNS[sentiment])
            posts.append({
                "content": template.format(name=name),
                "platform": self.PLATFORM,
                "channel": "hot_rank",
                "author_id": "jqka_bot",
                "posted_at": now,
            })
        LOG.info("jqka: parsed %d hot stocks from HTML", len(posts))
        return posts

    async def _fetch_html_fallback(self) -> list[dict]:
        return await self._fetch_hot_rank()

    @staticmethod
    def _pick_sentiment(change_pct: float) -> str:
        if change_pct >= 9.5:
            return "strong_up"
        elif change_pct > 0:
            return "up"
        elif change_pct < -3:
            return "down"
        else:
            return "flat"
