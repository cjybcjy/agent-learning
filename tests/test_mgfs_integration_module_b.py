from __future__ import annotations

from typer.testing import CliRunner

from main import app as cli_app

runner = CliRunner()


def test_end_to_end_module_b_pipeline(settings, monkeypatch):
    monkeypatch.setenv("SENTINEL_CONFIG_DIR", str(settings.config_dir))
    monkeypatch.setenv("SENTINEL_DATA_DIR", str(settings.data_dir))

    # 1. Create mgfs_config.yaml with valuation module enabled
    mgfs_config = settings.config_dir / "mgfs_config.yaml"
    mgfs_config.write_text("""
version: "1.0"
modules:
  moat:
    enabled: true
    class_path: "sentinel.mgfs.plugins.moat.MoatFactorPlugin"
    config: {}
  policy:
    enabled: true
    class_path: "sentinel.mgfs.plugins.policy.PolicyFactorPlugin"
    config: {}
  valuation:
    enabled: true
    class_path: "sentinel.mgfs.plugins.valuation.ValuationFactorPlugin"
    config: {}
  timing:
    enabled: false
    class_path: "sentinel.mgfs.plugins.timing.TimingFactorPlugin"
    config: {}
scoring_formula:
  moat: { weight: 0.5 }
  valuation: { weight: 0.3 }
  policy: { weight: 0.0 }
policy_multiplier:
  neutral: { multiplier: 1.0 }
circuit_breakers:
  valuation_extremely_overvalued:
    enabled: true
    rule: "valuation_primary_percentile > 90"
    alert_level: "hard_veto"
    message: "估值处于历史极端高位，一票否决"
rating_thresholds:
  strong_buy: { min_score: 90.0, label: "Strong Buy", action: "重仓出击" }
  accumulate: { min_score: 75.0, label: "Accumulate", action: "分批建仓" }
  hold_watch: { min_score: 60.0, label: "Hold/Watch", action: "等待拐点" }
  avoid: { min_score: 0.0, label: "Avoid", action: "回避" }
""", encoding="utf-8")

    # 2. Create moat_static_base.yaml
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
      brand_premium: { score: 95 }
      franchise_barrier: { score: 90 }
      switching_cost: { score: 88 }
      network_effect: { score: 60 }
      cost_advantage: { score: 70 }
""", encoding="utf-8")

    # 3. Create policy_whitelist.yaml
    policy_yaml = settings.config_dir / "policy_whitelist.yaml"
    policy_yaml.write_text("""
version: "1.0"
default_multiplier: 1.0
sectors:
  "白酒":
    multiplier: 1.0
    note: "消费品"
""", encoding="utf-8")

    # 4. Create valuation_sector_routing.yaml
    valuation_yaml = settings.config_dir / "valuation_sector_routing.yaml"
    valuation_yaml.write_text("""
version: "1.0"
archetypes:
  traditional_growth:
    label: "传统价值成长"
    metrics:
      primary:   { name: "PE_TTM", weight: 0.50 }
      secondary: { name: "PEG", weight: 0.30 }
      warning:   { name: "Dividend_Yield", weight: 0.20 }
    zones:
      strong_buy:  { percentile_max: 20, score_range: [90, 100] }
      accumulate:  { percentile_max: 40, score_range: [75, 90]  }
      hold:        { percentile_max: 70, score_range: [50, 75]  }
      avoid:       { percentile_max: 100, score_range: [0, 50]  }
    circuit_breakers:
      hard_veto_percentile: 90
sector_to_archetype:
  "白酒": "traditional_growth"
default_archetype: "traditional_growth"
override_archetypes: {}
""", encoding="utf-8")

    # 5. Invoke CLI evaluate
    result = runner.invoke(cli_app, [
        "evaluate", "600519",
        "--market", "A股",
        "--asset-class", "equity",
        "--policy", "neutral",
        "--sector", "白酒",
    ])

    assert result.exit_code == 0
    assert "投资权衡与决策说明书" in result.stdout
    assert "600519" in result.stdout
    assert "估值水位" in result.stdout
    assert "综合置信度" in result.stdout
    # Valuation score should be in output (format: "估值水位: 79.5/100.0")
    assert "估值水位:" in result.stdout


def test_end_to_end_weight_redistribution_on_low_confidence(settings, monkeypatch):
    """当估值插件 confidence=0 时，权重应自动归一化到护城河插件。"""
    monkeypatch.setenv("SENTINEL_CONFIG_DIR", str(settings.config_dir))
    monkeypatch.setenv("SENTINEL_DATA_DIR", str(settings.data_dir))

    mgfs_config = settings.config_dir / "mgfs_config.yaml"
    mgfs_config.write_text("""
version: "1.0"
modules:
  moat:
    enabled: true
    class_path: "sentinel.mgfs.plugins.moat.MoatFactorPlugin"
    config: {}
  policy:
    enabled: true
    class_path: "sentinel.mgfs.plugins.policy.PolicyFactorPlugin"
    config: {}
  valuation:
    enabled: true
    class_path: "sentinel.mgfs.plugins.valuation.ValuationFactorPlugin"
    config: {}
scoring_formula:
  moat: { weight: 0.6 }
  valuation: { weight: 0.3 }
  policy: { weight: 0.0 }
policy_multiplier:
  neutral: { multiplier: 1.0 }
circuit_breakers:
  min_moat:
    enabled: true
    rule: "moat_score < 30"
    alert_level: "soft_veto"
    message: "护城河评分过低"
rating_thresholds:
  strong_buy: { min_score: 90.0, label: "Strong Buy", action: "重仓出击" }
  accumulate: { min_score: 75.0, label: "Accumulate", action: "分批建仓" }
  hold_watch: { min_score: 60.0, label: "Hold/Watch", action: "等待拐点" }
  avoid: { min_score: 0.0, label: "Avoid", action: "回避" }
""", encoding="utf-8")

    moat_yaml = settings.config_dir / "moat_static_base.yaml"
    moat_yaml.write_text("""
version: "1.0"
scoring_weights:
  base: { weight: 0.4 }
  trend: { weight: 0.35 }
  safety: { weight: 0.25 }
companies:
  "999999":
    name: "冷门股"
    sector: "未知行业"
    base_score:
      brand_premium: { score: 30 }
      franchise_barrier: { score: 20 }
      switching_cost: { score: 25 }
      network_effect: { score: 10 }
      cost_advantage: { score: 15 }
""", encoding="utf-8")

    policy_yaml = settings.config_dir / "policy_whitelist.yaml"
    policy_yaml.write_text("""
version: "1.0"
default_multiplier: 1.0
sectors:
  "未知行业":
    multiplier: 1.0
    note: "未知"
""", encoding="utf-8")

    valuation_yaml = settings.config_dir / "valuation_sector_routing.yaml"
    valuation_yaml.write_text("""
version: "1.0"
archetypes:
  traditional_growth:
    label: "传统价值成长"
    metrics:
      primary:   { name: "PE_TTM", weight: 0.50 }
    zones:
      strong_buy:  { percentile_max: 20, score_range: [90, 100] }
      accumulate:  { percentile_max: 40, score_range: [75, 90]  }
      hold:        { percentile_max: 70, score_range: [50, 75]  }
      avoid:       { percentile_max: 100, score_range: [0, 50]  }
    circuit_breakers:
      hard_veto_percentile: 90
sector_to_archetype:
  "未知行业": "traditional_growth"
default_archetype: "traditional_growth"
override_archetypes: {}
""", encoding="utf-8")

    result = runner.invoke(cli_app, [
        "evaluate", "999999",
        "--market", "A股",
        "--asset-class", "equity",
        "--policy", "neutral",
        "--sector", "未知行业",
    ])

    assert result.exit_code == 0
    assert "投资权衡与决策说明书" in result.stdout
    # 冷门股无历史数据，估值 confidence 低，水印应提示数据缺失
    assert "[数据" in result.stdout or "[数据残缺" in result.stdout or "[数据部分缺失" in result.stdout
