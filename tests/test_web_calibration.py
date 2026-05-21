from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from sentinel.web.main import create_app


def test_calibration_page_shows_report_table():
    """Calibration endpoint should return HTML table with bias penalties."""
    with patch("sentinel.web.routers.ops._run_backtest") as mock_run:
        from sentinel.mgfs.evolution.bayes_calibrator import CalibrationReport

        mock_run.return_value = [
            CalibrationReport(
                symbol="300750",
                name="宁德时代",
                static_score=84.0,
                bias_penalty=-17.09,
                suggested_score=66.9,
                confidence=0.46,
                reason="1次止损; 总收益-2.5%",
            ),
            CalibrationReport(
                symbol="600519",
                name="贵州茅台",
                static_score=80.6,
                bias_penalty=-1.85,
                suggested_score=78.7,
                confidence=0.46,
                reason="总收益-5.3%",
            ),
        ]

        client = TestClient(create_app())
        response = client.get("/api/calibration/reports")
        assert response.status_code == 200
        html = response.text
        assert "300750" in html
        assert "宁德时代" in html
        assert "-17.09" in html
        assert "600519" in html
        assert "贵州茅台" in html


def test_calibration_page_shows_empty_state():
    """No reports → show empty message."""
    with patch("sentinel.web.routers.ops._run_backtest") as mock_run:
        mock_run.return_value = []

        client = TestClient(create_app())
        response = client.get("/api/calibration/reports")
        assert response.status_code == 200
        assert "暂无校准数据" in response.text
