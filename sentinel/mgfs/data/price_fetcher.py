from __future__ import annotations

import random
from abc import ABC, abstractmethod
from dataclasses import dataclass

from sentinel.domain.models import Market


@dataclass(frozen=True, slots=True)
class OHLCV:
    """Single daily price bar."""

    date: str
    open: float
    high: float
    low: float
    close: float
    volume: int


class PriceFetcher(ABC):
    """Abstract base for daily OHLCV data sources."""

    @abstractmethod
    def fetch_ohlcv(
        self, symbol: str, market: Market, days: int = 120
    ) -> list[OHLCV]:
        """Fetch historical daily OHLCV bars.

        Args:
            symbol: Stock symbol (e.g. "600519").
            market: Market enum (e.g. Market.A_SHARE).
            days: Number of trading days to fetch (minimum 80 for MA60 + slope).

        Returns:
            List of OHLCV bars, chronological order (oldest first).
        """
        raise NotImplementedError


class MockPriceFetcher(PriceFetcher):
    """Generate synthetic price data for dry-run testing."""

    def __init__(self, seed: int | None = None) -> None:
        self._rng = random.Random(seed)

    def fetch_ohlcv(
        self, symbol: str, market: Market, days: int = 120
    ) -> list[OHLCV]:
        bars: list[OHLCV] = []
        close = self._rng.uniform(20.0, 200.0)
        date_base = 20240101

        for i in range(days):
            drift = self._rng.gauss(0.0, 0.001)
            intraday_vol = self._rng.gauss(0.0, 0.02)
            close = close * (1 + drift)
            open_p = close * (1 + self._rng.gauss(0.0, 0.005))
            high = max(open_p, close) * (1 + abs(self._rng.gauss(0.0, 0.01)))
            low = min(open_p, close) * (1 - abs(self._rng.gauss(0.0, 0.01)))
            volume = int(self._rng.gauss(1_000_000, 300_000))

            bars.append(
                OHLCV(
                    date=str(date_base + i),
                    open=round(open_p, 2),
                    high=round(high, 2),
                    low=round(low, 2),
                    close=round(close, 2),
                    volume=max(volume, 1),
                )
            )
        return bars
