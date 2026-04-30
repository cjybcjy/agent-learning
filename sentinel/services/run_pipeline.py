from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from sentinel.analyzers import WeightsConfig, compute_heat
from sentinel.analyzers.ranking import rank_snapshots
from sentinel.antispam import filter_spam
from sentinel.collectors.base import RawMention
from sentinel.collectors.registry import CollectorRegistry
from sentinel.domain.models import HeatSnapshot, Market


class RunPipelineService:
    def __init__(self, registry: CollectorRegistry, weights: WeightsConfig | None = None) -> None:
        self.registry = registry
        self.weights = weights or WeightsConfig()

    def run_market(self, market: Market, collector_keys: list[str]) -> list[HeatSnapshot]:
        timestamp = datetime.now(tz=timezone.utc).replace(tzinfo=None)
        raw = asyncio.run(self._collect_market(market, collector_keys, timestamp))
        clean = filter_spam(raw)
        snapshots = compute_heat(clean, self.weights, timestamp, sentiment_score=0.0)
        ranked = rank_snapshots(snapshots, top_n=10)
        return ranked

    async def _collect_market(self, market: Market, collector_keys: list[str], timestamp: datetime) -> list[RawMention]:
        collectors = self.registry.list_for_market(market, collector_keys)
        batches = await asyncio.gather(*(collector.collect(timestamp) for collector in collectors))
        return [mention for batch in batches for mention in batch]
