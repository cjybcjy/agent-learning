from __future__ import annotations

from datetime import datetime

from sentinel.collectors.base import BaseCollector, RawMention
from sentinel.collectors.http import HttpClient
from sentinel.domain.models import Market


def parse_reddit_listing(payload: dict[str, object], default_timestamp: datetime, symbol: str) -> list[RawMention]:
    children = payload.get("data", {}).get("children", [])
    mentions: list[RawMention] = []
    for child in children:
        post = dict(child.get("data", {}))
        post_time = datetime.fromtimestamp(float(post.get("created_utc", default_timestamp.timestamp())))
        account_created = float(post.get("author_created_utc", post_time.timestamp()))
        account_age_days = max((post_time - datetime.fromtimestamp(account_created)).days, 0)
        mentions.append(
            RawMention(
                market=Market.US,
                platform="reddit_stocks",
                symbol=symbol.upper(),
                post_count=1,
                comment_count=int(post.get("num_comments", 0)),
                like_count=int(post.get("score", 0)),
                share_count=0,
                raw_text=f"{post.get('title', '')} {post.get('selftext', '')}".strip(),
                is_kol=False,
                account_age_days=account_age_days,
                account_followers=0,
                source_url=f"https://reddit.com{post.get('permalink', '')}",
                post_time=post_time,
            )
        )
    return mentions


class RedditStocksCollector(BaseCollector):
    market = Market.US
    platform = "reddit_stocks"

    def __init__(self, http_client: HttpClient, symbol: str) -> None:
        self.http_client = http_client
        self.symbol = symbol

    async def collect(self, timestamp: datetime) -> list[RawMention]:
        payload = await self.http_client.get_json("https://www.reddit.com/r/stocks/new.json", headers={"User-Agent": "sentinel/0.1"})
        return parse_reddit_listing(payload, timestamp, self.symbol)
