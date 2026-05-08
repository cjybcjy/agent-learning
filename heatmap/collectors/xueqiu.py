import json
import logging
from datetime import datetime, timezone

from heatmap.collectors.http_base import HttpCollector

LOG = logging.getLogger("heatmap.collectors.xueqiu")


class XueqiuCollector(HttpCollector):
    """Xueqiu (雪球) hot stock discussion collector.

    Fetches trending stock discussions from Xueqiu's public API.
    On WAF block or any failure, returns empty list — never synthesize
    fake discussion content from fallback sources.
    """

    async def _fetch_posts(self) -> list[dict]:
        try:
            await self._request("GET", "https://xueqiu.com", headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.0",
            })

            url = "https://xueqiu.com/query/v1/symbol/search/status.json"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.0",
                "Accept": "application/json",
                "Referer": "https://xueqiu.com/",
            }
            resp = await self._request("GET", url, headers=headers)
            content_type = resp.headers.get("content-type", "")
            if "application/json" in content_type:
                data = resp.json()
                posts = []
                for item in data.get("list", []):
                    posts.append({
                        "content": item.get("description", ""),
                        "platform": "xueqiu",
                        "channel": item.get("symbol", "hot"),
                        "author_id": str(item.get("user_id", "")),
                        "posted_at": datetime.fromtimestamp(
                            item.get("created_at", 0) / 1000, tz=timezone.utc
                        ) if item.get("created_at") else datetime.now(timezone.utc),
                    })
                LOG.info("xueqiu: fetched %d posts", len(posts))
                return posts
            else:
                LOG.warning("xueqiu returned non-JSON (WAF blocked), skipping this poll")
        except Exception:
            LOG.exception("xueqiu fetch failed, skipping this poll")

        return []
