from __future__ import annotations

import logging

import pytest

from sentinel.mgfs.execution.stop_loss_monitor import RiskAlert, StopLossMonitor
from sentinel.mgfs.storage.mgfs_repository import MGFSRepository
from sentinel.storage.db import Database


class TestStopLossMonitor:
    """TDD for StopLossMonitor — 三层熔断 + 零价防御 + dismiss 闭环."""

    @pytest.fixture
    def monitor(self, settings):
        db = Database(settings.database_path)
        repo = MGFSRepository(db)
        repo.bootstrap()
        return StopLossMonitor(repo)

    def test_hard_stop_triggered_when_price_drops_twenty_percent(self, monitor):
        """买入价 100，当前价 79 → 回撤 21%，触发 HARD_STOP."""
        monitor.repository.save_active_holding(
            symbol="600690", name="海尔智家", sector="家电",
            entry_price=100.0, current_price=79.0, highest_price=100.0,
            weight=0.15, stop_loss_hard=-0.20, stop_loss_trailing=-0.15,
            portfolio_stop_loss=-0.10,
        )
        alerts = monitor.scan()
        types = [a.alert_type for a in alerts]
        assert "HARD_STOP" in types
        hard = [a for a in alerts if a.alert_type == "HARD_STOP"][0]
        assert hard.symbol == "600690"
        assert hard.trigger_price == pytest.approx(80.0, abs=0.01)

    def test_hard_stop_not_triggered_when_price_above_floor(self, monitor):
        """买入价 100，当前价 81 → 回撤 19%，未触发."""
        monitor.repository.save_active_holding(
            symbol="600690", name="海尔智家", sector="家电",
            entry_price=100.0, current_price=81.0, highest_price=100.0,
            weight=0.15, stop_loss_hard=-0.20, stop_loss_trailing=-0.15,
            portfolio_stop_loss=-0.10,
        )
        alerts = monitor.scan()
        assert not any(a.alert_type == "HARD_STOP" for a in alerts)

    def test_trailing_stop_triggered_when_price_drops_fifteen_from_peak(self, monitor):
        """最高价 100，当前价 84 → 从峰值回撤 16%，触发 TRAILING_STOP."""
        monitor.repository.save_active_holding(
            symbol="600690", name="海尔智家", sector="家电",
            entry_price=80.0, current_price=84.0, highest_price=100.0,
            weight=0.15, stop_loss_hard=-0.20, stop_loss_trailing=-0.15,
            portfolio_stop_loss=-0.10,
        )
        alerts = monitor.scan()
        types = [a.alert_type for a in alerts]
        assert "TRAILING_STOP" in types
        trail = [a for a in alerts if a.alert_type == "TRAILING_STOP"][0]
        assert trail.trigger_price == pytest.approx(85.0, abs=0.01)

    def test_trailing_stop_not_triggered_when_above_trail(self, monitor):
        """最高价 100，当前价 86 → 从峰值回撤 14%，未触发."""
        monitor.repository.save_active_holding(
            symbol="600690", name="海尔智家", sector="家电",
            entry_price=80.0, current_price=86.0, highest_price=100.0,
            weight=0.15, stop_loss_hard=-0.20, stop_loss_trailing=-0.15,
            portfolio_stop_loss=-0.10,
        )
        alerts = monitor.scan()
        assert not any(a.alert_type == "TRAILING_STOP" for a in alerts)

    def test_portfolio_emergency_when_drawdown_exceeds_ten_percent(self, monitor):
        """两只持仓均回撤 12%，组合整体回撤 > 10%，触发 PORTFOLIO_EMERGENCY."""
        monitor.repository.save_active_holding(
            symbol="600690", name="海尔智家", sector="家电",
            entry_price=100.0, current_price=88.0, highest_price=100.0,
            weight=0.15, stop_loss_hard=-0.20, stop_loss_trailing=-0.15,
            portfolio_stop_loss=-0.10,
        )
        monitor.repository.save_active_holding(
            symbol="000333", name="美的集团", sector="家电",
            entry_price=100.0, current_price=88.0, highest_price=100.0,
            weight=0.15, stop_loss_hard=-0.20, stop_loss_trailing=-0.15,
            portfolio_stop_loss=-0.10,
        )
        alerts = monitor.scan()
        assert any(a.alert_type == "PORTFOLIO_EMERGENCY" for a in alerts)

    def test_portfolio_emergency_not_triggered_when_drawdown_small(self, monitor):
        """组合回撤 5%，未触发."""
        monitor.repository.save_active_holding(
            symbol="600690", name="海尔智家", sector="家电",
            entry_price=100.0, current_price=95.0, highest_price=100.0,
            weight=0.15, stop_loss_hard=-0.20, stop_loss_trailing=-0.15,
            portfolio_stop_loss=-0.10,
        )
        alerts = monitor.scan()
        assert not any(a.alert_type == "PORTFOLIO_EMERGENCY" for a in alerts)

    def test_zero_price_defense_logs_warning_no_false_alert(self, monitor, caplog):
        """current_price=0 时绝不触发虚假警报，仅记录 warning."""
        monitor.repository.save_active_holding(
            symbol="600690", name="海尔智家", sector="家电",
            entry_price=100.0, current_price=0.0, highest_price=100.0,
            weight=0.15, stop_loss_hard=-0.20, stop_loss_trailing=-0.15,
            portfolio_stop_loss=-0.10,
        )
        with caplog.at_level(logging.WARNING):
            alerts = monitor.scan()
        assert alerts == []
        assert any("invalid current_price" in rec.message.lower() for rec in caplog.records)

    def test_dismiss_close_position_removes_holding(self, monitor):
        """路径 A: dismiss 删除持仓后，scan 不再返回警报."""
        monitor.repository.save_active_holding(
            symbol="600690", name="海尔智家", sector="家电",
            entry_price=100.0, current_price=79.0, highest_price=100.0,
            weight=0.15, stop_loss_hard=-0.20, stop_loss_trailing=-0.15,
            portfolio_stop_loss=-0.10,
        )
        assert len(monitor.scan()) == 3  # HARD + TRAILING + PORTFOLIO

        monitor.dismiss_and_close_position("600690")
        assert monitor.repository.list_active_holdings() == []
        assert monitor.scan() == []

    def test_dismiss_reset_baseline_prevents_ghost_alert(self, monitor):
        """路径 B: dismiss 重置 entry/highest 为当前价后，同一条件不再触发."""
        monitor.repository.save_active_holding(
            symbol="600690", name="海尔智家", sector="家电",
            entry_price=100.0, current_price=79.0, highest_price=100.0,
            weight=0.15, stop_loss_hard=-0.20, stop_loss_trailing=-0.15,
            portfolio_stop_loss=-0.10,
        )
        assert len(monitor.scan()) == 3  # HARD + TRAILING + PORTFOLIO

        monitor.dismiss_and_reset_baseline("600690", new_price=79.0)

        # 重新扫描：entry=79, highest=79, current=79
        # hard: (79-79)/79 = 0% < 20% → 不触发
        # trailing: (79-79)/79 = 0% < 15% → 不触发
        assert monitor.scan() == []

        # 验证持仓表已更新
        holdings = monitor.repository.list_active_holdings()
        assert len(holdings) == 1
        assert holdings[0]["entry_price"] == 79.0
        assert holdings[0]["highest_price"] == 79.0
