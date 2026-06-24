from datetime import date, datetime, timezone

from sentinel.domain.models import Market
from sentinel.mgfs.data.metrics_aggregator import MetricsAggregator
from sentinel.mgfs.factor_plugin import TargetInfo
from sentinel.mgfs.plugins.moat import MoatFactorPlugin
from sentinel.storage.db import Database
from sentinel.web.services.serenity_metric_backfill_service import (
    SerenityMetricBackfillService,
)


def test_serenity_metric_backfill_writes_metrics_and_audit_trail(settings):
    service = SerenityMetricBackfillService(database_path=settings.database_path)

    result = service.backfill(
        symbol="600519",
        market="A_SHARE",
        values={
            "roic_sustainability": 84.0,
            "gmoat_stability": 78.0,
            "rd_efficiency": 72.0,
            "debt_ratio_deterioration": 68.0,
            "goodwill_ratio": 92.0,
            "operating_cashflow_ratio": 88.0,
        },
        source="2025 年报/2026 一季报手动核验",
        as_of=date(2026, 5, 1),
        source_url="https://example.com/report",
    )

    assert result.inserted_count == 6
    assert result.trend_count == 3
    assert result.safety_count == 3
    assert result.recorded_at.tzinfo is not None

    target = TargetInfo(symbol="600519", market=Market.A_SHARE, asset_class="equity")
    agg = MetricsAggregator(Database(settings.database_path))
    agg.bootstrap()

    trend = agg.get_latest_trend_metric(target, "roic_sustainability")
    safety = agg.get_latest_safety_metric(target, "operating_cashflow_ratio")
    assert trend is not None
    assert trend["value"] == 84.0
    assert safety is not None
    assert safety["value"] == 88.0

    audit_rows = agg.get_metric_source_audit(target)
    assert len(audit_rows) == 6
    assert audit_rows[0]["source"] == "2025 年报/2026 一季报手动核验"
    assert audit_rows[0]["as_of"] == date(2026, 5, 1)
    assert audit_rows[0]["source_url"] == "https://example.com/report"


def test_backfilled_metrics_feed_moat_plugin_without_dynamic_missing_warning(settings):
    moat_yaml = settings.config_dir / "moat_static_base.yaml"
    moat_yaml.write_text(
        """
version: "1.0"
scoring_weights:
  base: { weight: 0.4 }
  trend: { weight: 0.35 }
  safety: { weight: 0.25 }
companies:
  "600519":
    base_score:
      brand_premium: { score: 80 }
      franchise_barrier: { score: 80 }
      switching_cost: { score: 80 }
      network_effect: { score: 80 }
      cost_advantage: { score: 80 }
""",
        encoding="utf-8",
    )

    service = SerenityMetricBackfillService(database_path=settings.database_path)
    service.backfill(
        symbol="600519",
        market="A_SHARE",
        values={
            "roic_sustainability": 84.0,
            "gmoat_stability": 78.0,
            "rd_efficiency": 72.0,
            "debt_ratio_deterioration": 68.0,
            "goodwill_ratio": 92.0,
            "operating_cashflow_ratio": 88.0,
        },
        source="年报手动核验",
        as_of=date(2026, 5, 1),
    )

    agg = MetricsAggregator(Database(settings.database_path))
    agg.bootstrap()
    plugin = MoatFactorPlugin(config_path=moat_yaml, aggregator=agg)
    target = TargetInfo(symbol="600519", market=Market.A_SHARE, asset_class="equity")
    score = plugin.evaluate(target)

    assert score.details["trend_score"] == 78.0
    assert score.details["safety_score"] == 82.67
    assert score.confidence == 0.8
    assert not any("动态指标数据缺失" in warning for warning in score.warnings)


def test_metric_source_audit_uses_the_same_recorded_at_for_all_inserted_rows(settings):
    service = SerenityMetricBackfillService(database_path=settings.database_path)
    recorded_at = datetime(2026, 5, 1, 9, 30, tzinfo=timezone.utc)

    result = service.backfill(
        symbol="600519",
        market="A_SHARE",
        values={"roic_sustainability": 84.0, "operating_cashflow_ratio": 88.0},
        source="手动核验",
        as_of=date(2026, 5, 1),
        recorded_at=recorded_at,
    )

    assert result.recorded_at == recorded_at

    target = TargetInfo(symbol="600519", market=Market.A_SHARE, asset_class="equity")
    audit_rows = MetricsAggregator(
        Database(settings.database_path)
    ).get_metric_source_audit(target)
    assert {row["recorded_at"] for row in audit_rows} == {recorded_at}
