from __future__ import annotations

from datetime import datetime, timezone

from sentinel.domain.models import Market
from sentinel.mgfs.factor_plugin import AlertLevel, FactorScore, TargetInfo
from sentinel.mgfs.orchestrator import InvestmentDecision
from sentinel.mgfs.storage.mgfs_repository import MGFSRepository
from sentinel.storage.db import Database


def test_repository_bootstraps_table(settings):
    db = Database(settings.database_path)
    repo = MGFSRepository(db)
    repo.bootstrap()

    con = db.connect()
    try:
        tables = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='mgfs_decisions'"
        ).fetchall()
        assert len(tables) == 1
    finally:
        con.close()


def test_repository_save_and_retrieve(settings):
    db = Database(settings.database_path)
    repo = MGFSRepository(db)
    repo.bootstrap()

    target = TargetInfo(symbol="600519", market=Market.A_SHARE, asset_class="equity")
    decision = InvestmentDecision(
        target=target,
        generated_at=datetime(2026, 5, 12, 10, 0, 0, tzinfo=timezone.utc),
        factor_scores={
            "moat": FactorScore(factor_key="moat", factor_name="护城河", score=80.0),
        },
        raw_total=80.0,
        policy_multiplier=1.2,
        final_score=96.0,
        rating="Strong Buy",
        action="重仓出击",
        circuit_breakers_triggered=[],
        alert_level=AlertLevel.GREEN_PASS,
    )

    repo.save_decision(decision)
    decisions = repo.get_decisions_for_symbol("600519", Market.A_SHARE)

    assert len(decisions) == 1
    assert decisions[0]["symbol"] == "600519"
    assert decisions[0]["final_score"] == 96.0
    assert decisions[0]["rating"] == "Strong Buy"
