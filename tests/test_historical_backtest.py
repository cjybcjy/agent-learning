from __future__ import annotations

from datetime import date

import pytest

from sentinel.mgfs.evolution.historical_backtest import (
    BacktestResult,
    SingleAssetBacktest,
)


class TestSingleAssetBacktest:
    """TDD for historical backtest engine — time-travel single-asset simulation."""

    def test_fake_core_asset_records_trailing_and_hard_stops(self):
        """
        伪核心资产：静态评分 95，但价格从 100 一路阴跌到 50。
        验证回测引擎正确记录 trailing_stop (>= -15% from peak) 和
        hard_stop (>= -20% from entry)。
        """
        # 14 天价格序列：100 → 50，触发 trailing @85 (day6) 和 hard @80 (day8)
        prices = [100, 98, 95, 92, 88, 85, 82, 78, 75, 70, 65, 60, 55, 50]
        dates = [date(2025, 1, i + 1) for i in range(len(prices))]
        price_loader = {d: p for d, p in zip(dates, prices)}

        # 每天评分都是 95（Strong Buy）
        evaluator = {d: 95.0 for d in dates}

        engine = SingleAssetBacktest(
            symbol="300750",
            name="宁德时代",
            start_date=dates[0],
            end_date=dates[-1],
            static_score=95.0,
            entry_weight=0.20,
            stop_loss_hard=-0.20,
            stop_loss_trailing=-0.15,
        )

        result = engine.run(price_loader=price_loader, evaluator=evaluator)

        assert isinstance(result, BacktestResult)
        assert result.symbol == "300750"
        assert result.static_score == 95.0
        # 价格从 100 跌到 50，必然触发止损
        assert result.trailing_stop_count >= 1
        assert result.hard_stop_count >= 1
        # 总收益为负
        assert result.total_return < 0.0
        # 最大回撤至少 50%
        assert result.max_drawdown <= -0.50
        # 持有天数 = 14
        assert result.holding_days == 14

    def test_true_winner_records_no_stops(self):
        """
        真核心资产：价格稳步上涨 100 → 135，无止损触发。
        """
        prices = [100, 102, 105, 108, 110, 112, 115, 118, 120, 125, 130, 135]
        dates = [date(2025, 1, i + 1) for i in range(len(prices))]
        price_loader = {d: p for d, p in zip(dates, prices)}
        evaluator = {d: 88.0 for d in dates}

        engine = SingleAssetBacktest(
            symbol="600519",
            name="贵州茅台",
            start_date=dates[0],
            end_date=dates[-1],
            static_score=88.0,
            entry_weight=0.20,
            stop_loss_hard=-0.20,
            stop_loss_trailing=-0.15,
        )

        result = engine.run(price_loader=price_loader, evaluator=evaluator)

        assert result.trailing_stop_count == 0
        assert result.hard_stop_count == 0
        # 总收益约 +35%
        assert result.total_return == pytest.approx(0.35, abs=0.01)
        # 最大回撤很小
        assert result.max_drawdown >= -0.05

    def test_flat_market_records_neutral(self):
        """横盘震荡，价格几乎不变，无止损，收益接近 0。"""
        prices = [100, 101, 99, 100, 101, 99, 100, 100, 101, 99]
        dates = [date(2025, 1, i + 1) for i in range(len(prices))]
        price_loader = {d: p for d, p in zip(dates, prices)}
        evaluator = {d: 85.0 for d in dates}

        engine = SingleAssetBacktest(
            symbol="000001",
            name="平安银行",
            start_date=dates[0],
            end_date=dates[-1],
            static_score=85.0,
            entry_weight=0.15,
            stop_loss_hard=-0.20,
            stop_loss_trailing=-0.15,
        )

        result = engine.run(price_loader=price_loader, evaluator=evaluator)

        assert result.trailing_stop_count == 0
        assert result.hard_stop_count == 0
        assert result.total_return == pytest.approx(0.0, abs=0.02)

    def test_no_buy_signal_returns_none(self):
        """评分从未达到买入阈值，不建仓，返回 None。"""
        prices = [100, 98, 95, 92, 88, 85]
        dates = [date(2025, 1, i + 1) for i in range(len(prices))]
        price_loader = {d: p for d, p in zip(dates, prices)}
        # 评分始终低于买入阈值
        evaluator = {d: 50.0 for d in dates}

        engine = SingleAssetBacktest(
            symbol="300750",
            name="宁德时代",
            start_date=dates[0],
            end_date=dates[-1],
            static_score=50.0,
            entry_weight=0.20,
            stop_loss_hard=-0.20,
            stop_loss_trailing=-0.15,
        )

        result = engine.run(price_loader=price_loader, evaluator=evaluator)
        assert result is None
