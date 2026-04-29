from typer.testing import CliRunner

from main import app as cli_app
from sentinel.app import build_application
from sentinel.domain.models import Market

runner = CliRunner()


def test_application_run_persists_synthetic_snapshot(settings) -> None:
    app = build_application(settings)

    snapshots = app.run_market(market=Market.A_SHARE)

    assert len(snapshots) == 1
    assert snapshots[0].symbol == "SYNTH-A股"
    assert app.repository.list_by_market(Market.A_SHARE)[0].symbol == "SYNTH-A股"


def test_cli_run_market_command(settings, monkeypatch) -> None:
    monkeypatch.setenv("SENTINEL_CONFIG_DIR", str(settings.config_dir))
    monkeypatch.setenv("SENTINEL_DATA_DIR", str(settings.data_dir))

    result = runner.invoke(cli_app, ["--market", "A股"])

    assert result.exit_code == 0
    assert "stored 1 snapshot for A股" in result.stdout
