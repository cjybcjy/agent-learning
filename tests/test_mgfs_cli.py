from typer.testing import CliRunner

from main import app as cli_app
from sentinel.mgfs.factor_plugin import BaseFactorPlugin, FactorScore, TargetInfo

runner = CliRunner()


class MockEvaluatePlugin(BaseFactorPlugin):
    factor_key = "mock_eval"
    factor_name = "模拟评估"

    def evaluate(self, target: TargetInfo) -> FactorScore:
        return FactorScore(
            factor_key=self.factor_key,
            factor_name=self.factor_name,
            score=75.0,
            details={"note": "mock for CLI test"},
        )


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
  mock_eval:
    enabled: true
    class_path: "tests.test_mgfs_cli.MockEvaluatePlugin"
    config: {}
scoring_formula:
  mock_eval: { weight: 1.0 }
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
    assert "模拟评估" in result.stdout


def test_cli_scan_runs_without_missing_fetcher_import(settings, monkeypatch):
    monkeypatch.setenv("SENTINEL_CONFIG_DIR", str(settings.config_dir))
    monkeypatch.setenv("SENTINEL_DATA_DIR", str(settings.data_dir))

    mgfs_config = settings.config_dir / "mgfs_config.yaml"
    mgfs_config.write_text("""
version: "1.0"
modules:
  mock_eval:
    enabled: true
    class_path: "tests.test_mgfs_cli.MockEvaluatePlugin"
    config: {}
scoring_formula:
  mock_eval: { weight: 1.0 }
policy_multiplier:
  neutral: { multiplier: 1.0 }
circuit_breakers: {}
rating_thresholds:
  avoid: { min_score: 0.0, label: "Avoid", action: "回避" }
""", encoding="utf-8")

    moat_config = settings.config_dir / "moat_static_base.yaml"
    moat_config.write_text("""
version: "1.0"
companies:
  "TEST":
    name: "测试标的"
    sector: "测试行业"
    theme: "TestTheme"
    ecosystem_role: "downstream_app"
""", encoding="utf-8")

    result = runner.invoke(cli_app, [
        "scan", "TestTheme",
        "--policy", "neutral",
    ])

    assert result.exit_code == 0
    assert "MGFS 产业链价值扫描报告" in result.stdout
