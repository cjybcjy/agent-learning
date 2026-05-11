import logging
from datetime import datetime, timezone

from heatmap.collectors.http_base import HttpCollector

LOG = logging.getLogger("heatmap.collectors.cls")

CLS_TELEGRAPH_API = "https://www.cls.cn/api/telegraph/list?app=cailianpress"


class ClsCollector(HttpCollector):
    """财联社 (cls.cn) telegraph collector."""

    SOURCE_WEIGHT: float = 0.8
    PLATFORM: str = "cls"

    async def _fetch_posts(self) -> list[dict]:
        try:
            resp = await self._request("GET", CLS_TELEGRAPH_API, headers={
                "Referer": "https://www.cls.cn/telegraph",
            })
            data = resp.json()
            items = data.get("data", {}).get("roll_data", [])
            posts = []
            now = datetime.now(timezone.utc)
            for item in items[:50]:
                title = item.get("title", "") or item.get("brief", "")
                content = item.get("content", title)
                if not content:
                    continue
                posts.append({
                    "content": content,
                    "platform": self.PLATFORM,
                    "channel": "telegraph",
                    "author_id": "cls_bot",
                    "posted_at": now,
                })
            LOG.info("cls: fetched %d telegraph items", len(posts))
            return posts
        except Exception:
            LOG.exception("cls fetch failed")
            return []
