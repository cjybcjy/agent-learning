from __future__ import annotations

from sentinel.collectors.base import BaseCollector
from sentinel.domain.models import Market


class CollectorRegistry:
    def __init__(self) -> None:
        self._collectors: dict[tuple[Market, str], BaseCollector] = {}

    def register(self, collector: BaseCollector) -> None:
        self._collectors[(collector.market, collector.platform)] = collector

    def list_for_market(self, market: Market, collector_keys: list[str]) -> list[BaseCollector]:
        resolved: list[BaseCollector] = []
        for key in collector_keys:
            try:
                resolved.append(self._collectors[(market, key)])
            except KeyError as exc:
                raise KeyError(f"collector not registered for {market.value}: {key}") from exc
        return resolved
