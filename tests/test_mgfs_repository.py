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


def test_repository_upsert_updates_existing(settings):
    db = Database(settings.database_path)
    repo = MGFSRepository(db)
    repo.bootstrap()

    target = TargetInfo(symbol="600519", market=Market.A_SHARE, asset_class="equity")
    decision = InvestmentDecision(
        target=target,
        generated_at=datetime(2026, 5, 12, 10, 0, 0, tzinfo=timezone.utc),
        factor_scores={"moat": FactorScore(factor_key="moat", factor_name="护城河", score=80.0)},
        raw_total=80.0,
        policy_multiplier=1.2,
        final_score=96.0,
        rating="Strong Buy",
        action="重仓出击",
        circuit_breakers_triggered=[],
        alert_level=AlertLevel.GREEN_PASS,
    )

    repo.save_decision(decision)
    # Modify and save again with same key
    decision.final_score = 50.0
    decision.rating = "Avoid"
    repo.save_decision(decision)

    decisions = repo.get_decisions_for_symbol("600519", Market.A_SHARE)
    assert len(decisions) == 1
    assert decisions[0]["final_score"] == 50.0
    assert decisions[0]["rating"] == "Avoid"


def test_repository_save_without_sector(settings):
    db = Database(settings.database_path)
    repo = MGFSRepository(db)
    repo.bootstrap()

    target = TargetInfo(symbol="000001", market=Market.A_SHARE, asset_class="equity", sector=None)
    decision = InvestmentDecision(
        target=target,
        generated_at=datetime(2026, 5, 12, 11, 0, 0, tzinfo=timezone.utc),
        factor_scores={},
        raw_total=0.0,
        policy_multiplier=1.0,
        final_score=0.0,
        rating="Avoid",
        action="回避",
        circuit_breakers_triggered=[],
        alert_level=AlertLevel.GREEN_PASS,
    )

    repo.save_decision(decision)
    decisions = repo.get_decisions_for_symbol("000001", Market.A_SHARE)
    assert len(decisions) == 1
    assert decisions[0]["sector"] is None


def test_active_holdings_crud(settings):
    db = Database(settings.database_path)
    repo = MGFSRepository(db)
    repo.bootstrap()

    repo.save_active_holding(
        symbol="600519",
        name="贵州茅台",
        sector="白酒",
        entry_price=1500.0,
        current_price=1500.0,
        highest_price=1500.0,
        weight=0.20,
        stop_loss_hard=-0.20,
        stop_loss_trailing=-0.15,
        portfolio_stop_loss=-0.10,
    )

    holdings = repo.list_active_holdings()
    assert len(holdings) == 1
    assert holdings[0]["symbol"] == "600519"
    assert holdings[0]["highest_price"] == 1500.0


def test_active_holdings_update_price_and_highest(settings):
    db = Database(settings.database_path)
    repo = MGFSRepository(db)
    repo.bootstrap()

    repo.save_active_holding(
        symbol="600519",
        name="贵州茅台",
        sector="白酒",
        entry_price=1500.0,
        current_price=1500.0,
        highest_price=1500.0,
        weight=0.20,
        stop_loss_hard=-0.20,
        stop_loss_trailing=-0.15,
        portfolio_stop_loss=-0.10,
    )

    # Price rises → highest_price updates
    repo.update_holding_price("600519", 1600.0)
    holdings = repo.list_active_holdings()
    assert holdings[0]["current_price"] == 1600.0
    assert holdings[0]["highest_price"] == 1600.0

    # Price falls → highest_price stays at peak
    repo.update_holding_price("600519", 1550.0)
    holdings = repo.list_active_holdings()
    assert holdings[0]["current_price"] == 1550.0
    assert holdings[0]["highest_price"] == 1600.0


def test_active_holdings_delete(settings):
    db = Database(settings.database_path)
    repo = MGFSRepository(db)
    repo.bootstrap()

    repo.save_active_holding(
        symbol="600519",
        name="贵州茅台",
        sector="白酒",
        entry_price=1500.0,
        current_price=1500.0,
        highest_price=1500.0,
        weight=0.20,
        stop_loss_hard=-0.20,
        stop_loss_trailing=-0.15,
        portfolio_stop_loss=-0.10,
    )

    repo.delete_active_holding("600519")
    assert repo.list_active_holdings() == []
