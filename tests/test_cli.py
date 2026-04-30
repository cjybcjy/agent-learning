from typer.testing import CliRunner

from main import app as cli_app
from sentinel.app import build_application
from sentinel.domain.models import Market

runner = CliRunner()


def test_application_run_collects_registered_mentions(settings) -> None:
    app = build_application(settings)

    mentions = app.run_market(market=Market.A_SHARE, collector_keys=["synthetic"])

    assert len(mentions) == 1
    assert mentions[0].symbol == "SYNTH-A股"


def test_cli_run_market_command(settings, monkeypatch) -> None:
    monkeypatch.setenv("SENTINEL_CONFIG_DIR", str(settings.config_dir))
    monkeypatch.setenv("SENTINEL_DATA_DIR", str(settings.data_dir))

    result = runner.invoke(cli_app, ["--market", "A股"])

    assert result.exit_code == 0
    assert "collected 1 mention for A股" in result.stdout
