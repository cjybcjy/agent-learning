from __future__ import annotations

from dataclasses import dataclass

from sentinel.collectors.registry import CollectorRegistry
from sentinel.collectors.synthetic import build_default_registry
from sentinel.config import AppSettings, get_market_collectors, load_market_config
from sentinel.domain.models import Market
from sentinel.services.run_pipeline import RunPipelineService
from sentinel.storage.db import Database
from sentinel.storage.repository import HeatMetricRepository


@dataclass(slots=True)
class SentinelApplication:
    repository: HeatMetricRepository
    runner: RunPipelineService
    market_config: dict[str, dict[str, object]]

    def run_market(self, market: Market, collector_keys: list[str] | None = None):
        self.repository.bootstrap()
        keys = collector_keys or get_market_collectors(self.market_config, market.value)
        return self.runner.run_market(market=market, collector_keys=keys)


def build_application(settings: AppSettings) -> SentinelApplication:
    database = Database(settings.database_path)
    repository = HeatMetricRepository(database)
    registry = build_default_registry()
    runner = RunPipelineService(registry)
    market_config = load_market_config(settings.resolved_config_dir / "markets.yaml")
    return SentinelApplication(repository=repository, runner=runner, market_config=market_config)
