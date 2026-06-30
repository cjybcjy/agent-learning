from __future__ import annotations

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from sentinel.web.main import create_app
from sentinel.web.services.shadow_position_service import (
    ShadowPortfolioPreview,
    ShadowPreviewRow,
    ShadowRefreshResult,
)


def test_legacy_paper_trade_route_is_removed():
    """The fixed-weight legacy paper-trade endpoint should no longer be callable."""
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
    assert response.status_code == 404


def test_shadow_positions_panel_renders_kelly_simulator(monkeypatch):
    class FakeService:
        repository = MagicMock()
        repository.list_active_holdings.return_value = []

    monkeypatch.setattr(
        "sentinel.web.routers.ops._get_shadow_position_service",
        lambda: FakeService(),
    )

    client = TestClient(create_app())
    response = client.get("/api/shadow-positions/panel")

    assert response.status_code == 200
    assert "Kelly 仓位模拟器" in response.text
    assert "成本价" in response.text
    assert "清理旧数据" in response.text
    assert "影子风控" in response.text
    assert "风控正常" in response.text
    assert 'hx-post="/api/shadow-positions/preview"' in response.text
    assert 'hx-post="/api/shadow-positions/refresh"' in response.text
    assert 'name="current_price"' not in response.text


def test_shadow_positions_preview_renders_kelly_weights(monkeypatch):
    class FakeService:
        def preview_candidates(self, candidates, market):
            assert candidates[0].symbol == "600519"
            return ShadowPortfolioPreview(
                rows=[
                    ShadowPreviewRow(
                        symbol="600519",
                        name="贵州茅台",
                        sector="白酒",
                        final_score=92.0,
                        payoff_ratio=2.2,
                        price=1500.0,
                        weight=0.18,
                        kelly_fraction=0.20,
                        win_prob=0.72,
                    )
                ],
                total_weight=0.18,
                cash_reserve=0.82,
                portfolio_stop_loss=-0.10,
            )

    monkeypatch.setattr(
        "sentinel.web.routers.ops._get_shadow_position_service",
        lambda: FakeService(),
    )

    client = TestClient(create_app())
    response = client.post(
        "/api/shadow-positions/preview",
        data={
            "symbol": "600519",
            "name": "贵州茅台",
            "sector": "白酒",
            "final_score": "92",
            "payoff_ratio": "2.2",
            "price": "1500",
        },
    )

    assert response.status_code == 200
    assert "贵州茅台" in response.text
    assert "18%" in response.text
    assert 'hx-post="/api/shadow-positions/confirm"' in response.text


def test_shadow_positions_confirm_calls_service_and_renders_holdings(monkeypatch):
    class FakeService:
        repository = MagicMock()
        repository.list_active_holdings.return_value = [
            {
                "symbol": "600519",
                "name": "贵州茅台",
                "sector": "白酒",
                "entry_price": 1500.0,
                "current_price": 1500.0,
                "highest_price": 1500.0,
                "weight": 0.18,
                "kelly_fraction": 0.20,
                "win_prob": 0.72,
                "payoff_ratio": 2.2,
            }
        ]

        def confirm_candidates(self, candidates, market):
            return ShadowPortfolioPreview([], 0.18, 0.82, -0.10)

    monkeypatch.setattr(
        "sentinel.web.routers.ops._get_shadow_position_service",
        lambda: FakeService(),
    )

    client = TestClient(create_app())
    response = client.post(
        "/api/shadow-positions/confirm",
        data={
            "symbol": "600519",
            "name": "贵州茅台",
            "sector": "白酒",
            "final_score": "92",
            "payoff_ratio": "2.2",
            "price": "1500",
        },
    )

    assert response.status_code == 200
    assert "已写入影子持仓" in response.text
    assert "贵州茅台" in response.text
    assert 'hx-post="/api/shadow-positions/600519/cost"' in response.text
    assert 'hx-post="/api/shadow-positions/600519/delete"' in response.text


def test_shadow_positions_update_cost_calls_service(monkeypatch):
    class FakeService:
        repository = MagicMock()
        repository.list_active_holdings.return_value = []
        updated: tuple[str, float] | None = None

        def update_holding_cost(self, symbol, entry_price):
            self.updated = (symbol, entry_price)

    service = FakeService()
    monkeypatch.setattr(
        "sentinel.web.routers.ops._get_shadow_position_service",
        lambda: service,
    )

    response = TestClient(create_app()).post(
        "/api/shadow-positions/600519/cost",
        data={"entry_price": "1488.50"},
    )

    assert response.status_code == 200
    assert service.updated == ("600519", 1488.50)


def test_shadow_positions_delete_calls_service(monkeypatch):
    class FakeService:
        repository = MagicMock()
        repository.list_active_holdings.return_value = []
        deleted: str | None = None

        def delete_holding(self, symbol):
            self.deleted = symbol

    service = FakeService()
    monkeypatch.setattr(
        "sentinel.web.routers.ops._get_shadow_position_service",
        lambda: service,
    )

    response = TestClient(create_app()).post("/api/shadow-positions/300750/delete")

    assert response.status_code == 200
    assert service.deleted == "300750"


def test_shadow_positions_cleanup_legacy_calls_service(monkeypatch):
    class FakeService:
        repository = MagicMock()
        repository.list_active_holdings.return_value = []

        def cleanup_legacy_holdings(self):
            return ["300750", "300760"]

    monkeypatch.setattr(
        "sentinel.web.routers.ops._get_shadow_position_service",
        lambda: FakeService(),
    )

    response = TestClient(create_app()).post("/api/shadow-positions/cleanup-legacy")

    assert response.status_code == 200
    assert "已清理旧影子持仓 2 条" in response.text


def test_shadow_positions_refresh_calls_service(monkeypatch):
    class FakeService:
        repository = MagicMock()
        repository.list_active_holdings.return_value = []

        def refresh_active_holdings(self, source):
            assert source == "manual"
            return ShadowRefreshResult(updated_count=2, source="manual")

    monkeypatch.setattr(
        "sentinel.web.routers.ops._get_shadow_position_service",
        lambda: FakeService(),
    )

    client = TestClient(create_app())
    response = client.post("/api/shadow-positions/refresh", data={"source": "manual"})

    assert response.status_code == 200
    assert "已刷新 2 个影子持仓" in response.text
