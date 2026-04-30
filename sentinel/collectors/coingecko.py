from __future__ import annotations

from datetime import datetime

from sentinel.collectors.base import BaseCollector, RawMention
from sentinel.collectors.http import HttpClient
from sentinel.domain.models import Market


def parse_coingecko_payload(payload: dict[str, object], default_timestamp: datetime) -> list[RawMention]:
    items = payload.get("coins", [])
    mentions: list[RawMention] = []
    for coin in items:
        record = dict(coin)
        mentions.append(
            RawMention(
                market=Market.CRYPTO,
                platform="coingecko",
                symbol=str(record.get("symbol", "")).upper(),
                post_count=1,
                comment_count=0,
                like_count=int(float(record.get("watchlist_portfolio_users", 0))),
                share_count=0,
                raw_text=str(record.get("name", "")),
                is_kol=False,
                account_age_days=9999,
                account_followers=0,
                source_url="https://www.coingecko.com",
                post_time=default_timestamp,
            )
        )
    return mentions


class CoinGeckoCollector(BaseCollector):
    market = Market.CRYPTO
    platform = "coingecko"

    def __init__(self, http_client: HttpClient) -> None:
        self.http_client = http_client

    async def collect(self, timestamp: datetime) -> list[RawMention]:
        payload = await self.http_client.get_json("https://api.coingecko.com/api/v3/search/trending")
        return parse_coingecko_payload(payload, timestamp)
