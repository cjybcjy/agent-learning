from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from sentinel.web.main import create_app


def test_paper_trade_buy_writes_holding_to_repository():
    """POST paper trade should insert a holding into active_holdings."""
    with patch("sentinel.web.routers.ops._get_repository") as mock_repo:
        repo = MagicMock()
        mock_repo.return_value = repo

        client = TestClient(create_app())
        response = client.post(
            "/api/paper_trade",
            data={
                "symbol": "600519",
                "name": "贵州茅台",
                "sector": "白酒",
                "price": "1500.00",
                "weight": "0.20",
            },
        )
        assert response.status_code == 200
        repo.save_active_holding.assert_called_once()
        call_kwargs = repo.save_active_holding.call_args.kwargs
        assert call_kwargs["symbol"] == "600519"
        assert call_kwargs["entry_price"] == 1500.0
        assert call_kwargs["highest_price"] == 1500.0
        assert call_kwargs["weight"] == 0.20


def test_paper_trade_invalid_price_returns_error():
    """Zero or negative price should be rejected."""
    client = TestClient(create_app())
    response = client.post(
        "/api/paper_trade",
        data={
            "symbol": "600519",
            "name": "贵州茅台",
            "price": "0",
            "weight": "0.20",
        },
    )
    assert response.status_code == 400
