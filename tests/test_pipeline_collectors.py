from datetime import datetime

from sentinel.app import SentinelApplication
from sentinel.collectors.base import RawMention, StaticCollector
from sentinel.collectors.registry import CollectorRegistry
from sentinel.config import AppSettings
from sentinel.domain.models import Market
from sentinel.services.run_pipeline import RunPipelineService
from sentinel.storage.db import Database
from sentinel.storage.repository import HeatMetricRepository


def test_pipeline_collects_from_registered_collectors(tmp_path) -> None:
    database = Database(tmp_path / "sentinel.duckdb")
    repository = HeatMetricRepository(database)
    registry = CollectorRegistry()
    registry.register(
        StaticCollector(
            market=Market.A_SHARE,
            platform="synthetic",
            mentions=[
                RawMention(
                    market=Market.A_SHARE,
                    platform="synthetic",
                    symbol="600519",
                    post_count=1,
                    comment_count=2,
                    like_count=3,
                    share_count=0,
                    raw_text="贵州茅台",
                    is_kol=False,
                    account_age_days=100,
                    account_followers=20,
                    source_url="https://example.test/post/1",
                    post_time=datetime(2026, 4, 29, 10, 0, 0),
                )
            ],
        )
    )
    runner = RunPipelineService(registry=registry)
    market_config = {"A股": {"collectors": ["synthetic"]}}
    app = SentinelApplication(repository=repository, runner=runner, market_config=market_config)

    snapshots = app.run_market(market=Market.A_SHARE, collector_keys=["synthetic"])

    assert len(snapshots) == 1
    assert snapshots[0].symbol == "600519"
    assert snapshots[0].base_heat > 0
