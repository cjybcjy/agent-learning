from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from sentinel.domain.models import Market
from sentinel.mgfs.data.multi_source_fetcher import MultiSourceFetcher
from sentinel.mgfs.data.price_fetcher import OHLCV
from sentinel.web.services.shadow_position_service import (
    ManualShadowCandidate,
    ShadowPositionSimulatorService,
)


class FakePriceFetcher:
    def __init__(self, prices: dict[str, float], failures: set[str] | None = None) -> None:
        self.prices = prices
        self.failures = failures or set()

    def fetch_ohlcv(self, symbol: str, market: Market, days: int = 120) -> list[OHLCV]:
        if symbol in self.failures:
            raise RuntimeError(f"price unavailable for {symbol}")
        price = self.prices[symbol]
        return [
            OHLCV(
                date="2026-06-30",
                open=price,
                high=price,
                low=price,
                close=price,
                volume=1_000_000,
            )
        ]


def test_preview_candidates_uses_manual_cost_and_builds_kelly_weights():
    service = ShadowPositionSimulatorService(
        repository=MagicMock(),
        price_fetcher=FakePriceFetcher({}),
        sector_limits={"白酒": 0.25},
    )

    preview = service.preview_candidates(
        [
            ManualShadowCandidate(
                symbol="600519",
                name="贵州茅台",
                sector="白酒",
                final_score=92.0,
                payoff_ratio=2.2,
                price=1500.0,
            )
        ],
        market=Market.A_SHARE,
    )

    assert preview.rows[0].symbol == "600519"
    assert preview.rows[0].price == 1500.0
    assert preview.rows[0].error is None
    assert 0.0 < preview.rows[0].weight <= 0.25
    assert preview.cash_reserve == pytest.approx(
        1.0 - sum(row.weight for row in preview.rows),
        abs=1e-9,
    )


def test_preview_candidates_requires_manual_cost_price():
    service = ShadowPositionSimulatorService(
        repository=MagicMock(),
        price_fetcher=FakePriceFetcher({}),
    )

    preview = service.preview_candidates(
        [
            ManualShadowCandidate(
                symbol="300750",
                name="宁德时代",
                sector="新能源",
                final_score=88.0,
                payoff_ratio=2.0,
            )
        ],
        market=Market.A_SHARE,
    )

    assert preview.rows[0].symbol == "300750"
    assert preview.rows[0].weight == 0.0
    assert "成本价必须手动输入" in preview.rows[0].error


def test_confirm_candidates_saves_kelly_weighted_active_holdings():
    repo = MagicMock()
    service = ShadowPositionSimulatorService(
        repository=repo,
        price_fetcher=FakePriceFetcher({}),
        sector_limits={"白酒": 0.25},
    )

    preview = service.confirm_candidates(
        [
            ManualShadowCandidate(
                symbol="600519",
                name="贵州茅台",
                sector="白酒",
                final_score=92.0,
                payoff_ratio=2.2,
                price=1500.0,
            )
        ],
        market=Market.A_SHARE,
    )

    repo.save_active_holding.assert_called_once()
    call = repo.save_active_holding.call_args.kwargs
    assert call["symbol"] == "600519"
    assert call["entry_price"] == 1500.0
    assert call["current_price"] == 1500.0
    assert call["highest_price"] == 1500.0
    assert call["weight"] == pytest.approx(preview.rows[0].weight)
    assert call["weight"] != 0.20
    assert call["stop_loss_hard"] == -0.20
    assert call["stop_loss_trailing"] == -0.15
    assert call["portfolio_stop_loss"] == -0.10


def test_refresh_active_holdings_updates_price_writes_snapshot_and_alerts():
    repo = MagicMock()
    repo.list_active_holdings.return_value = [
        {
            "symbol": "600519",
            "name": "贵州茅台",
            "sector": "白酒",
            "entry_price": 1500.0,
            "current_price": 1500.0,
            "highest_price": 1550.0,
            "weight": 0.18,
            "stop_loss_hard": -0.20,
            "stop_loss_trailing": -0.15,
            "portfolio_stop_loss": -0.10,
        }
    ]
    stop_monitor = MagicMock()
    stop_monitor.scan.return_value = []
    service = ShadowPositionSimulatorService(
        repository=repo,
        price_fetcher=FakePriceFetcher({"600519": 1600.0}),
        stop_monitor=stop_monitor,
    )

    result = service.refresh_active_holdings(source="manual")

    assert result.updated_count == 1
    assert result.failures == []
    repo.update_holding_price.assert_called_once_with("600519", 1600.0)
    repo.save_shadow_position_snapshot.assert_called_once()
    snapshot = repo.save_shadow_position_snapshot.call_args.kwargs
    assert snapshot["symbol"] == "600519"
    assert snapshot["current_price"] == 1600.0
    assert snapshot["highest_price"] == 1600.0
    assert snapshot["unrealized_return"] == pytest.approx(1600.0 / 1500.0 - 1.0)
    assert snapshot["refresh_source"] == "manual"
    stop_monitor.scan.assert_called_once()


def test_refresh_active_holdings_continues_when_one_symbol_price_fails():
    repo = MagicMock()
    repo.list_active_holdings.return_value = [
        {
            "symbol": "600519",
            "name": "贵州茅台",
            "sector": "白酒",
            "entry_price": 1500.0,
            "current_price": 1500.0,
            "highest_price": 1500.0,
            "weight": 0.18,
            "stop_loss_hard": -0.20,
            "stop_loss_trailing": -0.15,
            "portfolio_stop_loss": -0.10,
        },
        {
            "symbol": "300750",
            "name": "宁德时代",
            "sector": "新能源",
            "entry_price": 200.0,
            "current_price": 200.0,
            "highest_price": 210.0,
            "weight": 0.12,
            "stop_loss_hard": -0.20,
            "stop_loss_trailing": -0.15,
            "portfolio_stop_loss": -0.10,
        },
    ]
    service = ShadowPositionSimulatorService(
        repository=repo,
        price_fetcher=FakePriceFetcher({"600519": 1510.0}, failures={"300750"}),
        stop_monitor=MagicMock(scan=MagicMock(return_value=[])),
    )

    result = service.refresh_active_holdings(source="pipeline")

    assert result.updated_count == 1
    assert len(result.failures) == 1
    assert result.failures[0].symbol == "300750"
    repo.update_holding_price.assert_called_once_with("600519", 1510.0)
    repo.save_shadow_position_snapshot.assert_called_once()


def test_update_holding_cost_validates_and_delegates_to_repository():
    repo = MagicMock()
    service = ShadowPositionSimulatorService(
        repository=repo,
        price_fetcher=FakePriceFetcher({}),
    )

    service.update_holding_cost("600519", 1488.0)

    repo.update_holding_cost.assert_called_once_with("600519", 1488.0)

    with pytest.raises(ValueError, match="成本价必须大于 0"):
        service.update_holding_cost("600519", 0.0)


def test_delete_holding_delegates_to_repository():
    repo = MagicMock()
    service = ShadowPositionSimulatorService(
        repository=repo,
        price_fetcher=FakePriceFetcher({}),
    )

    service.delete_holding("300750")

    repo.delete_active_holding.assert_called_once_with("300750")


def test_cleanup_legacy_holdings_removes_code_named_empty_sector_rows():
    repo = MagicMock()
    repo.list_active_holdings.return_value = [
        {
            "symbol": "300750",
            "name": "300750",
            "sector": None,
            "entry_price": 100.0,
            "current_price": 100.0,
            "highest_price": 100.0,
            "weight": 0.20,
            "payoff_ratio": 0.0,
        },
        {
            "symbol": "600519",
            "name": "贵州茅台",
            "sector": "白酒",
            "entry_price": 100.0,
            "current_price": 1500.0,
            "highest_price": 1500.0,
            "weight": 0.20,
            "payoff_ratio": 0.0,
        },
    ]
    service = ShadowPositionSimulatorService(
        repository=repo,
        price_fetcher=FakePriceFetcher({}),
    )

    removed = service.cleanup_legacy_holdings()

    assert removed == ["300750"]
    repo.delete_active_holding.assert_called_once_with("300750")


def test_default_service_uses_fast_market_refresh_chain():
    service = ShadowPositionSimulatorService(repository=MagicMock())

    assert isinstance(service.price_fetcher, MultiSourceFetcher)
    adapter_sources = [
        source
        for source in service.price_fetcher._sources
        if hasattr(source, "_adapter")
    ]
    assert adapter_sources
    for source in adapter_sources:
        assert source._adapter._request_timeout <= 5.0
        assert source._adapter._delay_scale == 0.0
