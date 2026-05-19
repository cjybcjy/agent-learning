from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from sentinel.web.main import create_app


def test_eval_single_includes_moat_radar():
    """Decision card should include moat radar chart container."""
    with patch("sentinel.web.routers.research.evaluate_single") as mock_eval:
        decision = MagicMock()
        decision.target.symbol = "600519"
        decision.target.name = "贵州茅台"
        decision.target.market.value = "A股"
        decision.rating = "Strong Buy"
        decision.final_score = 95.0
        decision.policy_multiplier = 1.2
        decision.action = "重仓出击"
        decision.alert_level.value = "green_pass"
        decision.circuit_breakers_triggered = []
        decision.report_sections = {}
        decision.factor_scores = {
            "moat": MagicMock(factor_name="护城河深度", score=85.0, confidence=0.8, weight=0.5, details={}),
            "valuation": MagicMock(factor_name="估值水位", score=70.0, confidence=0.7, weight=0.3, details={}),
        }
        mock_eval.return_value = decision

        client = TestClient(create_app())
        response = client.post(
            "/api/eval/single",
            data={"symbol": "600519", "market": "A_SHARE", "policy": "neutral"},
        )
        assert response.status_code == 200
        html = response.text
        # Radar chart container should exist
        assert "moat-radar-chart" in html
        # Moat dimension data should be embedded
        assert "data-moat-dims" in html
        # Valuation band chart container
        assert "valuation-band-chart" in html


def test_moat_dimensions_parsing():
    """get_moat_dimensions should parse YAML config correctly."""
    from sentinel.web.services.moat_service import get_moat_dimensions

    dims = get_moat_dimensions("600519")
    assert dims is not None
    assert "brand_premium" in dims
    assert isinstance(dims["brand_premium"]["score"], (int, float))
