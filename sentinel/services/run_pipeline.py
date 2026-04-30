from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from sentinel.collectors.base import RawMention
from sentinel.collectors.registry import CollectorRegistry
from sentinel.domain.models import Market


class RunPipelineService:
    def __init__(self, registry: CollectorRegistry) -> None:
        self.registry = registry

    def run_market(self, market: Market, collector_keys: list[str]) -> list[RawMention]:
        timestamp = datetime.now(tz=timezone.utc).replace(tzinfo=None)
        return asyncio.run(self._collect_market(market, collector_keys, timestamp))

    async def _collect_market(self, market: Market, collector_keys: list[str], timestamp: datetime) -> list[RawMention]:
        collectors = self.registry.list_for_market(market, collector_keys)
        batches = await asyncio.gather(*(collector.collect(timestamp) for collector in collectors))
        return [mention for batch in batches for mention in batch]
