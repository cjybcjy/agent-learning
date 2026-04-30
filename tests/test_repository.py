from datetime import datetime

from sentinel.domain.models import HeatSnapshot, Market
from sentinel.storage.db import Database
from sentinel.storage.repository import HeatMetricRepository


def test_heat_snapshot_to_row_contains_expected_fields() -> None:
    snapshot = HeatSnapshot(
        timestamp=datetime(2026, 4, 29, 10, 0, 0),
        market=Market.A_SHARE,
        symbol="600519",
        base_heat=12.5,
        kol_multiplier=1.2,
        sentiment_score=0.55,
        directed_heat=8.25,
        change_pct=18.0,
        top_source="xueqiu",
        rank_bullish=1,
        rank_bearish=None,
        is_anomaly=False,
    )

    row = snapshot.to_row()

    assert row["market"] == "A股"
    assert row["symbol"] == "600519"
    assert row["directed_heat"] == 8.25


def test_repository_bootstraps_schema_and_reads_back_rows(tmp_path) -> None:
    database = Database(tmp_path / "sentinel.duckdb")
    repository = HeatMetricRepository(database)
    repository.bootstrap()

    snapshot = HeatSnapshot(
        timestamp=datetime(2026, 4, 29, 10, 0, 0),
        market=Market.A_SHARE,
        symbol="600519",
        base_heat=12.5,
        kol_multiplier=1.2,
        sentiment_score=0.55,
        directed_heat=8.25,
        change_pct=18.0,
        top_source="xueqiu",
        rank_bullish=1,
        rank_bearish=None,
        is_anomaly=False,
    )

    repository.upsert_snapshots([snapshot])
    rows = repository.list_by_market(Market.A_SHARE)

    assert len(rows) == 1
    assert rows[0].symbol == "600519"
    assert rows[0].top_source == "xueqiu"


def test_get_previous_heats_returns_latest_period(tmp_path) -> None:
    database = Database(tmp_path / "sentinel.duckdb")
    repository = HeatMetricRepository(database)
    repository.bootstrap()

    # Insert two periods
    old = HeatSnapshot(
        timestamp=datetime(2026, 4, 29, 9, 0, 0),
        market=Market.A_SHARE,
        symbol="600519",
        base_heat=5.0,
        kol_multiplier=1.0,
        sentiment_score=0.5,
        directed_heat=2.5,
        change_pct=None,
        top_source="xueqiu",
        rank_bullish=1,
        rank_bearish=None,
        is_anomaly=False,
    )
    recent = HeatSnapshot(
        timestamp=datetime(2026, 4, 29, 10, 0, 0),
        market=Market.A_SHARE,
        symbol="600519",
        base_heat=10.0,
        kol_multiplier=1.0,
        sentiment_score=0.8,
        directed_heat=8.0,
        change_pct=None,
        top_source="xueqiu",
        rank_bullish=1,
        rank_bearish=None,
        is_anomaly=False,
    )
    repository.upsert_snapshots([old, recent])

    heats = repository.get_previous_heats(Market.A_SHARE)

    assert heats["600519"] == 8.0


def test_get_previous_heats_empty_when_no_data(tmp_path) -> None:
    database = Database(tmp_path / "sentinel.duckdb")
    repository = HeatMetricRepository(database)
    repository.bootstrap()

    heats = repository.get_previous_heats(Market.A_SHARE)
    assert heats == {}


def test_change_pct_computed_in_full_pipeline(tmp_path) -> None:
    """Run pipeline twice; second run should have change_pct populated."""
    from sentinel.app import SentinelApplication
    from sentinel.collectors.base import RawMention, StaticCollector
    from sentinel.collectors.registry import CollectorRegistry
    from sentinel.services.run_pipeline import RunPipelineService

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
                    post_count=10,
                    comment_count=20,
                    like_count=30,
                    share_count=5,
                    raw_text="test",
                    is_kol=False,
                    account_age_days=365,
                    account_followers=100,
                    source_url="https://example.test/1",
                    post_time=datetime(2026, 4, 29, 10, 0, 0),
                )
            ],
        )
    )
    runner = RunPipelineService(registry=registry)
    market_config = {"A股": {"collectors": ["synthetic"]}}
    app = SentinelApplication(repository=repository, runner=runner, market_config=market_config)

    # First run: no previous data → change_pct is None
    snapshots1 = app.run_market(market=Market.A_SHARE, collector_keys=["synthetic"])
    assert snapshots1[0].change_pct is None

    # Second run: previous data exists → change_pct should be 0% (same input)
    snapshots2 = app.run_market(market=Market.A_SHARE, collector_keys=["synthetic"])
    assert snapshots2[0].change_pct == 0.0