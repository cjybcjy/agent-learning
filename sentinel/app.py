from __future__ import annotations

from dataclasses import dataclass

from sentinel.config import AppSettings
from sentinel.domain.models import Market
from sentinel.services.run_pipeline import RunPipelineService
from sentinel.storage.db import Database
from sentinel.storage.repository import HeatMetricRepository


@dataclass(slots=True)
class SentinelApplication:
    repository: HeatMetricRepository
    runner: RunPipelineService

    def run_market(self, market: Market) -> list:
        self.repository.bootstrap()
        return self.runner.run_market(market)


def build_application(settings: AppSettings) -> SentinelApplication:
    database = Database(settings.database_path)
    repository = HeatMetricRepository(database)
    runner = RunPipelineService(repository)
    return SentinelApplication(repository=repository, runner=runner)
