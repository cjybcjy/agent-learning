from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from strenum import StrEnum


class Market(StrEnum):
    A_SHARE = "A股"
    HK = "港股"
    US = "美股"
    CRYPTO = "币圈"


@dataclass(slots=True)
class HeatSnapshot:
    timestamp: datetime
    market: Market
    symbol: str
    base_heat: float
    kol_multiplier: float
    sentiment_score: float
    directed_heat: float
    change_pct: float | None
    top_source: str
    rank_bullish: int | None
    rank_bearish: int | None
    is_anomaly: bool

    def to_row(self) -> dict[str, object]:
        return {
            "timestamp": self.timestamp,
            "market": self.market.value,
            "symbol": self.symbol,
            "base_heat": self.base_heat,
            "kol_multiplier": self.kol_multiplier,
            "sentiment_score": self.sentiment_score,
            "directed_heat": self.directed_heat,
            "change_pct": self.change_pct,
            "top_source": self.top_source,
            "rank_bullish": self.rank_bullish,
            "rank_bearish": self.rank_bearish,
            "is_anomaly": self.is_anomaly,
        }