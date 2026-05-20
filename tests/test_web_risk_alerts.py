from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from sentinel.web.main import create_app


def test_risk_alerts_green_when_no_alerts():
    """No alerts → green banner with shield icon."""
    with patch("sentinel.web.routers.ops._get_stop_loss_monitor") as mock_mon:
        mock_instance = MagicMock()
        mock_instance.scan.return_value = []
        mock_mon.return_value = mock_instance

        client = TestClient(create_app())
        response = client.get("/api/risk/alerts")
        assert response.status_code == 200
        html = response.text
        assert "风控正常" in html
        assert "shield-check" in html
        assert "alert-triangle" not in html


def test_risk_alerts_red_when_hard_stop_triggered():
    """Hard stop alert → red flashing card with dismiss buttons."""
    from sentinel.mgfs.execution.stop_loss_monitor import RiskAlert

    with patch("sentinel.web.routers.ops._get_stop_loss_monitor") as mock_mon:
        mock_instance = MagicMock()
        mock_instance.scan.return_value = [
            RiskAlert(
                alert_type="HARD_STOP",
                symbol="600690",
                name="海尔智家",
                current_price=79.0,
                trigger_price=80.0,
                suggested_action="MARKET_SELL",
            ),
        ]
        mock_mon.return_value = mock_instance

        client = TestClient(create_app())
        response = client.get("/api/risk/alerts")
        assert response.status_code == 200
        html = response.text
        assert "HARD_STOP" in html
        assert "600690" in html
        assert "海尔智家" in html
        assert "MARKET_SELL" in html
        assert "确认清仓" in html
        assert "重置防线" in html
        assert "bg-red-600" in html


def test_risk_alerts_portfolio_emergency_no_dismiss_buttons():
    """Portfolio emergency has no individual dismiss buttons."""
    from sentinel.mgfs.execution.stop_loss_monitor import RiskAlert

    with patch("sentinel.web.routers.ops._get_stop_loss_monitor") as mock_mon:
        mock_instance = MagicMock()
        mock_instance.scan.return_value = [
            RiskAlert(
                alert_type="PORTFOLIO_EMERGENCY",
                symbol="PORTFOLIO",
                name="组合净值",
                current_price=0.85,
                trigger_price=0.90,
                suggested_action="REVIEW_IMMEDIATELY",
            ),
        ]
        mock_mon.return_value = mock_instance

        client = TestClient(create_app())
        response = client.get("/api/risk/alerts")
        assert response.status_code == 200
        html = response.text
        assert "PORTFOLIO_EMERGENCY" in html
        assert "立即检查组合" in html
        assert "确认清仓" not in html


def test_risk_dismiss_close_calls_monitor():
    """POST dismiss with action=close deletes the holding."""
    with patch("sentinel.web.routers.ops._get_stop_loss_monitor") as mock_mon:
        mock_instance = MagicMock()
        mock_instance.scan.return_value = []
        mock_mon.return_value = mock_instance

        client = TestClient(create_app())
        response = client.post(
            "/api/risk/dismiss",
            data={"symbol": "600690", "action": "close"},
        )
        assert response.status_code == 200
        mock_instance.dismiss_and_close_position.assert_called_once_with("600690")


def test_risk_dismiss_reset_calls_monitor():
    """POST dismiss with action=reset updates baseline."""
    with patch("sentinel.web.routers.ops._get_stop_loss_monitor") as mock_mon:
        mock_instance = MagicMock()
        mock_instance.scan.return_value = []
        mock_mon.return_value = mock_instance

        client = TestClient(create_app())
        response = client.post(
            "/api/risk/dismiss",
            data={"symbol": "600690", "action": "reset", "new_price": "79.0"},
        )
        assert response.status_code == 200
        mock_instance.dismiss_and_reset_baseline.assert_called_once_with("600690", 79.0)
