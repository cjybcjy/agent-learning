from typer.testing import CliRunner

from main import app as cli_app

runner = CliRunner()


def test_cli_evaluate_command_exists():
    result = runner.invoke(cli_app, ["evaluate", "--help"])
    assert result.exit_code == 0
    assert "evaluate" in result.stdout


def test_cli_evaluate_runs_with_mock_plugins(settings, monkeypatch):
    monkeypatch.setenv("SENTINEL_CONFIG_DIR", str(settings.config_dir))
    monkeypatch.setenv("SENTINEL_DATA_DIR", str(settings.data_dir))

    # Create minimal mgfs_config.yaml in temp config dir
    mgfs_config = settings.config_dir / "mgfs_config.yaml"
    mgfs_config.write_text("""
version: "1.0"
modules:
  valuation:
    enabled: true
    class_path: "sentinel.mgfs.plugins.valuation.ValuationFactorPlugin"
    config: {}
scoring_formula:
  valuation: { weight: 1.0 }
policy_multiplier:
  neutral: { multiplier: 1.0 }
circuit_breakers: {}
rating_thresholds:
  avoid: { min_score: 0.0, label: "Avoid", action: "回避" }
""", encoding="utf-8")

    result = runner.invoke(cli_app, [
        "evaluate", "TEST",
        "--market", "A股",
        "--asset-class", "equity",
        "--policy", "neutral",
    ])

    assert result.exit_code == 0
    assert "投资权衡与决策说明书" in result.stdout
    assert "估值水位" in result.stdout
