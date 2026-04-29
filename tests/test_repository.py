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