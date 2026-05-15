from __future__ import annotations

import random
from abc import ABC, abstractmethod


class ValuationFetcher(ABC):
    @abstractmethod
    def fetch_history(
        self, symbol: str, market: str, metric: str, years: int = 5
    ) -> list[float]:
        """Return a list of daily metric values for the given symbol."""


class MockValuationFetcher(ValuationFetcher):
    def __init__(self, seed: int | None = None) -> None:
        self._rng = random.Random(seed)

    def fetch_history(
        self, symbol: str, market: str, metric: str, years: int = 5
    ) -> list[float]:
        days = years * 250
        base = self._rng.gauss(20.0, 5.0)
        values: list[float] = []
        for _ in range(days):
            base += self._rng.gauss(0.0, 0.3)
            values.append(round(max(base, 0.1), 4))
        return values
