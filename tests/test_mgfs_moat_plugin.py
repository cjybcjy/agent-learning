from pathlib import Path

import pytest

from sentinel.domain.models import Market
from sentinel.mgfs.data.metrics_aggregator import MetricsAggregator
from sentinel.mgfs.factor_plugin import TargetInfo
from sentinel.mgfs.plugins.moat import MoatFactorPlugin
from sentinel.storage.db import Database


def test_moat_plugin_reads_static_base_score(settings):
    moat_yaml = settings.config_dir / "moat_static_base.yaml"
    moat_yaml.write_text("""
version: "1.0"
scoring_weights:
  base: { weight: 0.4 }
  trend: { weight: 0.35 }
  safety: { weight: 0.25 }

companies:
  "600519":
    name: "贵州茅台"
    sector: "白酒"
    base_score:
      brand_premium: { score: 95, note: "社交货币" }
      franchise_barrier: { score: 90, note: "地理保护" }
      switching_cost: { score: 88, note: "口味依赖" }
      network_effect: { score: 60, note: "无网络效应" }
      cost_advantage: { score: 70, note: "成本波动" }
""", encoding="utf-8")

    plugin = MoatFactorPlugin(config_path=moat_yaml)
    target = TargetInfo(
        symbol="600519", market=Market.A_SHARE, asset_class="equity", sector="白酒"
    )
    score = plugin.evaluate(target)

    # Base score = (95 + 90 + 88 + 60 + 70) / 5 = 80.6
    # With no aggregator, weights are renormalized: base gets 100% weight
    assert score.factor_key == "moat"
    assert score.factor_name == "护城河深度"
    assert score.details["base_score"] == 80.6
    assert score.details["base_weight"] == 0.4
    assert score.score == 80.6


def test_moat_plugin_missing_company_returns_zero_with_warning(settings):
    moat_yaml = settings.config_dir / "moat_static_base.yaml"
    moat_yaml.write_text("""
version: "1.0"
scoring_weights:
  base: { weight: 0.4 }
companies: {}
""", encoding="utf-8")

    plugin = MoatFactorPlugin(config_path=moat_yaml)
    target = TargetInfo(
        symbol="UNKNOWN", market=Market.A_SHARE, asset_class="equity"
    )
    score = plugin.evaluate(target)

    assert score.score == 0.0
    assert score.confidence == 0.5
    assert score.details["base_score"] == 0.0
    assert score.details["base_weight"] == 0.4
    assert score.details["trend_score"] == 0.0
    assert score.details["trend_weight"] == 0.35
    assert score.details["safety_score"] == 0.0
    assert score.details["safety_weight"] == 0.25
    assert any("未找到" in w and "静态评分" in w for w in score.warnings)


def test_moat_plugin_computes_three_segment_score(settings):
    """Full three-segment: base 40% + trend 35% + safety 25%"""
    moat_yaml = settings.config_dir / "moat_static_base.yaml"
    moat_yaml.write_text("""
version: "1.0"
scoring_weights:
  base: { weight: 0.4 }
  trend: { weight: 0.35 }
  safety: { weight: 0.25 }
companies:
  "600519":
    name: "茅台"
    sector: "白酒"
    base_score:
      brand_premium: { score: 100 }
      franchise_barrier: { score: 100 }
      switching_cost: { score: 100 }
      network_effect: { score: 100 }
      cost_advantage: { score: 100 }
""", encoding="utf-8")

    db = Database(settings.database_path)
    agg = MetricsAggregator(db, mock_mode=True)
    agg.bootstrap()

    plugin = MoatFactorPlugin(config_path=moat_yaml, aggregator=agg)
    target = TargetInfo(
        symbol="600519", market=Market.A_SHARE, asset_class="equity", sector="白酒"
    )
    score = plugin.evaluate(target)

    # base=100, mock trend ~60, mock safety ~60
    # score = 100*0.4 + 60*0.35 + 60*0.25 = 40 + 21 + 15 = 76
    assert score.factor_key == "moat"
    assert score.details["base_score"] == 100.0
    assert score.details["base_weight"] == 0.4
    assert "trend_score" in score.details
    assert "safety_score" in score.details
    assert 0 <= score.score <= 100


def test_moat_plugin_static_only_when_aggregator_none(settings):
    """If no aggregator provided, trend/safety fallback to 0"""
    moat_yaml = settings.config_dir / "moat_static_base.yaml"
    moat_yaml.write_text("""
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
""", encoding="utf-8")

    plugin = MoatFactorPlugin(config_path=moat_yaml, aggregator=None)
    target = TargetInfo(
        symbol="600519", market=Market.A_SHARE, asset_class="equity"
    )
    score = plugin.evaluate(target)

    # base=80, trend=0, safety=0 → weights renormalized to base=100%
    assert score.score == 80.0
    assert score.details["trend_score"] == 0.0
    assert score.details["safety_score"] == 0.0
    assert score.confidence == 0.5  # lowered because dynamic data missing


def test_moat_plugin_reports_static_score_evidence_gaps(settings):
    moat_yaml = settings.config_dir / "moat_static_base.yaml"
    moat_yaml.write_text("""
version: "1.0"
scoring_weights:
  base: { weight: 0.4 }
companies:
  "600519":
    base_score:
      brand_premium: { score: 95, note: "高端白酒定价权" }
""", encoding="utf-8")

    plugin = MoatFactorPlugin(config_path=moat_yaml, aggregator=None)
    target = TargetInfo(symbol="600519", market=Market.A_SHARE, asset_class="equity")
    score = plugin.evaluate(target)

    assert score.details["evidence_coverage"] == 0.0
    assert score.details["evidence_missing_fields"] == 4
    assert score.details["evidence_invalid_fields"] == 0
    assert any("护城河静态评分证据字段缺失" in warning for warning in score.warnings)


def test_moat_plugin_accepts_complete_static_score_evidence(settings):
    moat_yaml = settings.config_dir / "moat_static_base.yaml"
    moat_yaml.write_text("""
version: "1.0"
scoring_weights:
  base: { weight: 0.4 }
companies:
  "600519":
    base_score:
      brand_premium:
        score: 95
        note: "高端白酒定价权"
        source: "2025 annual report"
        as_of: "2026-05-01"
        confidence: 0.86
        bear_case: "渠道库存持续恶化会削弱品牌溢价"
""", encoding="utf-8")

    plugin = MoatFactorPlugin(config_path=moat_yaml, aggregator=None)
    target = TargetInfo(symbol="600519", market=Market.A_SHARE, asset_class="equity")
    score = plugin.evaluate(target)

    assert score.details["evidence_coverage"] == 1.0
    assert score.details["evidence_missing_fields"] == 0
    assert score.details["evidence_invalid_fields"] == 0
    assert not any("证据字段" in warning for warning in score.warnings)


def test_moat_plugin_partial_aggregator_data(settings):
    """Aggregator exists but returns no trend data (only safety data available)."""
    moat_yaml = settings.config_dir / "moat_static_base.yaml"
    moat_yaml.write_text("""
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
""", encoding="utf-8")

    db = Database(settings.database_path)
    agg = MetricsAggregator(db, mock_mode=False)
    agg.bootstrap()

    target = TargetInfo(
        symbol="600519", market=Market.A_SHARE, asset_class="equity"
    )

    # Insert only safety metrics, no trend metrics
    agg.insert_safety_metric(
        target, "debt_ratio_deterioration", 70.0, "2024-01-01"
    )

    plugin = MoatFactorPlugin(config_path=moat_yaml, aggregator=agg)
    score = plugin.evaluate(target)

    # base=80, trend=0, safety=70
    # Weights renormalized: base=0.4/0.65=61.5%, safety=0.25/0.65=38.5%
    # score = 80*0.615 + 70*0.385 = 76.15
    assert score.score == 76.15
    assert score.details["base_score"] == 80.0
    assert score.details["trend_score"] == 0.0
    assert score.details["safety_score"] == 70.0
    # Confidence should not be 0.0; with base + safety available, it's min(0.9, 0.8) = 0.8
    assert score.confidence == 0.8


def test_moat_plugin_warns_when_aggregator_has_no_dynamic_rows(settings):
    moat_yaml = settings.config_dir / "moat_static_base.yaml"
    moat_yaml.write_text("""
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
""", encoding="utf-8")

    db = Database(settings.database_path)
    agg = MetricsAggregator(db, mock_mode=False)
    agg.bootstrap()
    plugin = MoatFactorPlugin(config_path=moat_yaml, aggregator=agg)
    target = TargetInfo(symbol="600519", market=Market.A_SHARE, asset_class="equity")

    score = plugin.evaluate(target)

    assert score.score == 80.0
    assert score.confidence == 0.5
    assert any("动态指标数据缺失" in warning for warning in score.warnings)
