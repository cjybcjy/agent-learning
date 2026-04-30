from __future__ import annotations

from datetime import datetime

from sentinel.collectors.base import BaseCollector, RawMention
from sentinel.collectors.http import HttpClient
from sentinel.domain.models import Market


def parse_xueqiu_timeline(payload: dict[str, object], default_timestamp: datetime) -> list[RawMention]:
    items = payload.get("list", [])
    mentions: list[RawMention] = []
    for item in items:
        post = dict(item)
        user = dict(post.get("user", {}))
        created_at_ms = post.get("created_at")
        post_time = datetime.fromtimestamp(created_at_ms / 1000) if created_at_ms else default_timestamp
        account_created_ms = user.get("created_at", 0)
        account_age_days = max((post_time - datetime.fromtimestamp(account_created_ms / 1000)).days, 0) if account_created_ms else 0
        symbol = str(post.get("target") or "UNKNOWN")
        mentions.append(
            RawMention(
                market=Market.A_SHARE,
                platform="xueqiu",
                symbol=symbol,
                post_count=1,
                comment_count=int(post.get("comment_count", 0)),
                like_count=int(post.get("like_count", 0)),
                share_count=int(post.get("retweet_count", 0)),
                raw_text=f"{post.get('title', '')} {post.get('description', '')}".strip(),
                is_kol=False,
                account_age_days=account_age_days,
                account_followers=int(user.get("followers_count", 0)),
                source_url=f"https://xueqiu.com{post.get('uri', '')}",
                post_time=post_time,
            )
        )
    return mentions


class XueqiuCollector(BaseCollector):
    market = Market.A_SHARE
    platform = "xueqiu"

    def __init__(self, http_client: HttpClient) -> None:
        self.http_client = http_client

    async def collect(self, timestamp: datetime) -> list[RawMention]:
        payload = await self.http_client.get_json("https://xueqiu.com/statuses/hot/listV2.json")
        return parse_xueqiu_timeline(payload, timestamp)
