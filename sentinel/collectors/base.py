from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from sentinel.domain.models import Market


@dataclass(slots=True)
class RawMention:
    market: Market
    platform: str
    symbol: str
    post_count: int
    comment_count: int
    like_count: int
    share_count: int
    raw_text: str
    is_kol: bool
    account_age_days: int
    account_followers: int
    source_url: str
    post_time: datetime

    def to_dict(self) -> dict[str, object]:
        return {
            "market": self.market.value,
            "platform": self.platform,
            "symbol": self.symbol,
            "post_count": self.post_count,
            "comment_count": self.comment_count,
            "like_count": self.like_count,
            "share_count": self.share_count,
            "raw_text": self.raw_text,
            "is_kol": self.is_kol,
            "account_age_days": self.account_age_days,
            "account_followers": self.account_followers,
            "source_url": self.source_url,
            "post_time": self.post_time,
        }


class BaseCollector(ABC):
    market: Market
    platform: str

    @abstractmethod
    async def collect(self, timestamp: datetime) -> list[RawMention]:
        raise NotImplementedError


@dataclass(slots=True)
class StaticCollector(BaseCollector):
    market: Market
    platform: str
    mentions: list[RawMention]

    async def collect(self, timestamp: datetime) -> list[RawMention]:
        del timestamp
        return self.mentions
