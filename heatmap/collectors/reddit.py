import logging
from datetime import datetime, timezone
from heatmap.collectors.http_base import HttpCollector

LOG = logging.getLogger("heatmap.collectors.reddit")
REDDIT_WSB_URL = "https://www.reddit.com/r/wallstreetbets/hot.json?limit=50"
_NOISE_KEYWORDS = ["loss porn", "yolo", "wife's boyfriend", "tendies"]
_SIGNAL_FLAIRS = ["DD", "Due Diligence", "Technical Analysis", "Earnings", "News", "YOLO"]


class RedditCollector(HttpCollector):
    SOURCE_WEIGHT: float = 0.4
    PLATFORM: str = "reddit"

    async def _fetch_posts(self) -> list[dict]:
        try:
            resp = await self._request(
                "GET", REDDIT_WSB_URL,
                headers={"User-Agent": "HeatmapBot/1.0 (educational project)"},
            )
            data = resp.json()
            children = data.get("data", {}).get("children", [])
            posts = []
            now = datetime.now(timezone.utc)
            for child in children:
                post_data = child.get("data", {})
                title = post_data.get("title", "")
                selftext = post_data.get("selftext", "")
                flair = post_data.get("link_flair_text", "")
                score = post_data.get("score", 0)
                upvote_ratio = post_data.get("upvote_ratio", 0)
                content_lower = f"{title} {selftext}".lower()
                if any(kw in content_lower for kw in _NOISE_KEYWORDS):
                    continue
                if score < 5 or upvote_ratio < 0.5:
                    continue
                is_signal = any(s.lower() in (flair or "").lower() for s in _SIGNAL_FLAIRS)
                if is_signal and score < 3:
                    continue
                combined = f"{title}\n{selftext[:500]}" if selftext else title
                posts.append({
                    "content": combined,
                    "platform": self.PLATFORM,
                    "channel": f"wsb_{flair or 'general'}",
                    "author_id": post_data.get("author", "unknown"),
                    "posted_at": now,
                })
            LOG.info("reddit: fetched %d posts (filtered from %d)", len(posts), len(children))
            return posts
        except Exception:
            LOG.exception("reddit fetch failed")
            return []
