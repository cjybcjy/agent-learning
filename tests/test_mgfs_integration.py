from typer.testing import CliRunner

from main import app as cli_app

runner = CliRunner()


def test_end_to_end_with_realistic_config(settings, monkeypatch):
    monkeypatch.setenv("SENTINEL_CONFIG_DIR", str(settings.config_dir))
    monkeypatch.setenv("SENTINEL_DATA_DIR", str(settings.data_dir))

    mgfs_config = settings.config_dir / "mgfs_config.yaml"
    mgfs_config.write_text("""
version: "1.0"
modules:
  moat:
    enabled: true
    class_path: "sentinel.mgfs.plugins.valuation.ValuationFactorPlugin"
    config: {}
  token_metrics:
    enabled: true
    class_path: "sentinel.mgfs.plugins.timing.TimingFactorPlugin"
    config: {}
scoring_formula:
  moat: { weight: 0.5 }
  token_metrics: { weight: 0.5 }
policy_multiplier:
  core_support: { multiplier: 1.2 }
  neutral: { multiplier: 1.0 }
circuit_breakers:
  min_moat:
    enabled: true
    rule: "moat_score < 30"
    action: "soft_veto"
    alert_level: "soft_veto"
    message: "护城河评分过低"
rating_thresholds:
  strong_buy: { min_score: 90.0, label: "Strong Buy", action: "重仓出击" }
  accumulate: { min_score: 75.0, label: "Accumulate", action: "分批建仓" }
  hold_watch: { min_score: 60.0, label: "Hold/Watch", action: "等待拐点" }
  avoid: { min_score: 0.0, label: "Avoid", action: "回避" }
""", encoding="utf-8")

    result = runner.invoke(cli_app, [
        "evaluate", "600519",
        "--market", "A股",
        "--asset-class", "equity",
        "--policy", "neutral",
    ])

    assert result.exit_code == 0
    assert "投资权衡与决策说明书" in result.stdout
    assert "600519" in result.stdout
    assert "A股" in result.stdout
    assert "最终得分" in result.stdout
