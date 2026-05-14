from typer.testing import CliRunner

from main import app as cli_app

runner = CliRunner()


def test_end_to_end_module_a_pipeline(settings, monkeypatch):
    monkeypatch.setenv("SENTINEL_CONFIG_DIR", str(settings.config_dir))
    monkeypatch.setenv("SENTINEL_DATA_DIR", str(settings.data_dir))

    # 1. Create mgfs_config.yaml
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
  timing:
    enabled: true
    class_path: "sentinel.mgfs.plugins.timing.TimingFactorPlugin"
    config: {}
scoring_formula:
  moat: { weight: 0.5 }
  timing: { weight: 0.5 }
policy_multiplier:
  neutral: { multiplier: 1.0 }
  core_support: { multiplier: 1.2 }
circuit_breakers:
  min_moat:
    enabled: true
    rule: "moat_score < 40"
    alert_level: "soft_veto"
    message: "护城河评分过低"
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

    # 4. Invoke CLI evaluate
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
    assert "护城河深度" in result.stdout
    assert "国策环境" in result.stdout
    assert "综合置信度" in result.stdout
    # Stronger assertions on computed values
    assert "原始加权分: 41.12" in result.stdout
    assert "政策乘数: 1.0" in result.stdout
    assert "最终得分: 41.12" in result.stdout
    assert "评级: Avoid" in result.stdout
    assert "建议动作: 回避" in result.stdout
