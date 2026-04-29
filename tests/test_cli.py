from sentinel.app import build_application
from sentinel.domain.models import Market


def test_application_run_persists_synthetic_snapshot(settings) -> None:
    app = build_application(settings)

    snapshots = app.run_market(market=Market.A_SHARE)

    assert len(snapshots) == 1
    assert snapshots[0].symbol == "SYNTH-A股"
    assert app.repository.list_by_market(Market.A_SHARE)[0].symbol == "SYNTH-A股"
