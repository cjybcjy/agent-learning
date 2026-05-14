from datetime import datetime, timezone

from sentinel.domain.models import Market
from sentinel.mgfs.data.metrics_aggregator import MetricsAggregator
from sentinel.mgfs.factor_plugin import TargetInfo
from sentinel.storage.db import Database


def test_aggregator_bootstrap_creates_tables(settings):
    db = Database(settings.database_path)
    agg = MetricsAggregator(db)
    agg.bootstrap()

    con = db.connect()
    try:
        tables = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('trend_metrics', 'safety_metrics')"
        ).fetchall()
        assert len(tables) == 2
    finally:
        con.close()


def test_aggregator_insert_and_query_trend(settings):
    db = Database(settings.database_path)
    agg = MetricsAggregator(db)
    agg.bootstrap()

    target = TargetInfo(symbol="600519", market=Market.A_SHARE, asset_class="equity")
    agg.insert_trend_metric(
        target=target,
        metric_name="roic_sustainability",
        value=85.0,
        recorded_at=datetime(2026, 5, 14, 10, 0, 0, tzinfo=timezone.utc),
    )

    result = agg.get_latest_trend_metric(target, "roic_sustainability")
    assert result is not None
    assert result["symbol"] == "600519"
    assert result["market"] == "A股"
    assert result["metric_name"] == "roic_sustainability"
    assert result["value"] == 85.0


def test_aggregator_mock_mode_returns_fake_data(settings):
    db = Database(settings.database_path)
    agg = MetricsAggregator(db, mock_mode=True)

    target = TargetInfo(symbol="FAKE", market=Market.A_SHARE, asset_class="equity")
    result = agg.get_latest_trend_metric(target, "roic_sustainability")
    assert result is not None
    assert 30.0 <= result["value"] <= 90.0


def test_aggregator_insert_and_query_safety(settings):
    db = Database(settings.database_path)
    agg = MetricsAggregator(db)
    agg.bootstrap()

    target = TargetInfo(symbol="600519", market=Market.A_SHARE, asset_class="equity")
    agg.insert_safety_metric(
        target=target,
        metric_name="debt_ratio",
        value=45.0,
        recorded_at=datetime(2026, 5, 14, 10, 0, 0, tzinfo=timezone.utc),
    )

    result = agg.get_latest_safety_metric(target, "debt_ratio")
    assert result is not None
    assert result["symbol"] == "600519"
    assert result["market"] == "A股"
    assert result["metric_name"] == "debt_ratio"
    assert result["value"] == 45.0
