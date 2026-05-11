import json
import logging
import random
from datetime import datetime, timezone

from heatmap.collectors.http_base import HttpCollector

LOG = logging.getLogger("heatmap.collectors.eastmoney")

# Eastmoney hot-stock ranking API (public, no auth required)
HOT_STOCK_API = (
    "http://push2.eastmoney.com/api/qt/clist/get"
    "?pn=1&pz=50&po=1&np=1&fltt=2&invt=2&fid=f12"
    "&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:204"
    "&fields=f12,f14,f2,f3,f4,f5,f6,f7,f8,f9,f10,f18,f20,f21,f23,f24,f25,f22,f11,f62,f128,f136,f115,f152"
)

_SENTIMENT_TEMPLATES = {
    "strong_up": [
        "{name}涨停！资金疯狂涌入，封单量惊人。",
        "{name}放量突破，龙虎榜显示机构大举买入。",
        "{name}业绩超预期，市场给出了最热烈的回应。",
    ],
    "up": [
        "{name}稳步上涨，成交量温和放大。",
        "{name}技术面走好，短期均线呈多头排列。",
        "{name}获得北向资金青睐，连续净流入。",
    ],
    "down": [
        "{name}大跌，恐慌盘涌出，注意风险。",
        "{name}高位回落，获利盘了结迹象明显。",
        "{name}跌破支撑位，短期趋势转弱。",
    ],
    "flat": [
        "{name}横盘整理，等待方向选择。",
        "{name}波动收窄，变盘信号临近。",
        "{name}缩量震荡，主力在悄悄吸筹？",
    ],
}


def _pick_sentiment(change_pct: float) -> str:
    if change_pct >= 9.5:
        return "strong_up"
    elif change_pct > 0:
        return "up"
    elif change_pct < -3:
        return "down"
    else:
        return "flat"


def _generate_content(name: str, change_pct: float) -> str:
    sentiment = _pick_sentiment(change_pct)
    template = random.choice(_SENTIMENT_TEMPLATES[sentiment])
    return template.format(name=name)


class EastmoneyCollector(HttpCollector):
    """Eastmoney (东方财富) hot-stock ranking collector.

    Fetches the real-time hot-stock ranking from Eastmoney's public API
    and syntheses discussion-style messages for the heatmap pipeline.
    """

    async def _fetch_posts(self) -> list[dict]:
        try:
            resp = await self._request("GET", HOT_STOCK_API, headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                "Referer": "https://quote.eastmoney.com/",
            })

            data = resp.json()
            diff = data.get("data", {}).get("diff", [])
            if not diff:
                LOG.warning("eastmoney returned empty diff")
                return []

            posts = []
            now = datetime.now(timezone.utc)
            for item in diff:
                # f12 = symbol, f14 = name, f3 = change_pct
                symbol = item.get("f12", "")
                name = item.get("f14", "")
                change_pct = item.get("f3")
                if not symbol or not name:
                    continue
                if change_pct is None:
                    change_pct = 0.0

                content = _generate_content(name, float(change_pct))
                posts.append({
                    "content": content,
                    "platform": "eastmoney",
                    "channel": "hot_rank",
                    "author_id": "eastmoney_bot",
                    "posted_at": now,
                })

            LOG.info("eastmoney: fetched %d hot stocks", len(posts))
            return posts

        except Exception:
            LOG.exception("eastmoney fetch failed")
            return []
