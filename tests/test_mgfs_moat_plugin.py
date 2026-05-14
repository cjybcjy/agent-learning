from pathlib import Path

import pytest

from sentinel.domain.models import Market
from sentinel.mgfs.factor_plugin import TargetInfo
from sentinel.mgfs.plugins.moat import MoatFactorPlugin


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
    assert score.factor_key == "moat"
    assert score.factor_name == "护城河深度"
    assert score.details["base_score"] == 80.6
    assert score.details["base_weight"] == 0.4


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
    assert any("未找到" in w and "静态评分" in w for w in score.warnings)
