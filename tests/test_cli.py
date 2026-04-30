from typer.testing import CliRunner

from main import app as cli_app
from sentinel.app import build_application
from sentinel.domain.models import Market

runner = CliRunner()


def test_application_run_produces_ranked_snapshots(settings) -> None:
    app = build_application(settings)

    snapshots = app.run_market(market=Market.A_SHARE, collector_keys=["synthetic"])

    assert len(snapshots) == 1
    assert snapshots[0].symbol == "SYNTH-A股"
    assert snapshots[0].base_heat > 0


def test_cli_run_market_command(settings, monkeypatch) -> None:
    monkeypatch.setenv("SENTINEL_CONFIG_DIR", str(settings.config_dir))
    monkeypatch.setenv("SENTINEL_DATA_DIR", str(settings.data_dir))

    result = runner.invoke(cli_app, ["--market", "A股"])

    assert result.exit_code == 0
    assert "collected 1 ranked snapshot for A股" in result.stdout
