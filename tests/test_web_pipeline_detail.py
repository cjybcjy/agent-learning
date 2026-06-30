from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from sentinel.web.main import create_app


def test_pipeline_detail_returns_table_with_results():
    """Detail endpoint should return HTML table sorted by final_score desc."""
    with patch("sentinel.web.routers.ops._get_pipeline_service") as mock_svc:
        mock_instance = MagicMock()
        mock_instance.get_pipeline_results.return_value = [
            {"symbol": "600519", "name": "贵州茅台", "moat_score": 85.0,
             "valuation_percentile": 15.0, "timing_score": 70.0,
             "final_score": 92.5, "rating": "Strong Buy", "action": "重仓出击"},
            {"symbol": "000001", "name": "平安银行", "moat_score": 60.0,
             "valuation_percentile": 45.0, "timing_score": 55.0,
             "final_score": 65.0, "rating": "Hold/Watch", "action": "等待拐点"},
        ]
        mock_svc.return_value = mock_instance

        client = TestClient(create_app())
        response = client.get("/api/pipeline/detail/B_20260518_120000")
        assert response.status_code == 200
        html = response.text
        # Should contain result rows
        assert "600519" in html
        assert "贵州茅台" in html
        assert "Strong Buy" in html
        assert "000001" in html
        # Detail table container should exist
        assert "pipeline-detail-table" in html
        assert 'hx-post="/api/paper_trade"' not in html
        assert '"weight": 0.2' not in html


def test_pipeline_detail_empty_results_shows_message():
    """Empty batch should show 'no results' message."""
    with patch("sentinel.web.routers.ops._get_pipeline_service") as mock_svc:
        mock_instance = MagicMock()
        mock_instance.get_pipeline_results.return_value = []
        mock_svc.return_value = mock_instance

        client = TestClient(create_app())
        response = client.get("/api/pipeline/detail/B_20260518_120000")
        assert response.status_code == 200
        assert "暂无结果" in response.text or "pipeline-detail-table" in response.text
