from __future__ import annotations

from datetime import date

import pytest

from sentinel.mgfs.evolution.batch_backtest import BatchBacktest
from sentinel.mgfs.evolution.bayes_calibrator import CalibrationReport


class TestBatchBacktest:
    """TDD for batch backtest: run multiple assets, feed to BayesCalibrator."""

    def test_batch_runs_multiple_assets_and_produces_calibration_reports(self):
        """Batch backtest on 3 assets → calibrate all → sorted worst-first."""
        dates = [date(2025, 1, i + 1) for i in range(14)]

        # 宁德: 95分, 价格暴跌
        ningde_prices = [100, 98, 95, 92, 88, 85, 82, 78, 75, 70, 65, 60, 55, 50]
        # 茅台: 88分, 稳步上涨
        moutai_prices = [100, 102, 105, 108, 110, 112, 115, 118, 120, 125, 130, 135, 138, 140]
        # 美的: 82分, 横盘微涨
        midea_prices = [100, 101, 99, 100, 101, 99, 100, 100, 101, 99, 100, 101, 100, 102]

        price_loaders = {
            "300750": {d: p for d, p in zip(dates, ningde_prices)},
            "600519": {d: p for d, p in zip(dates, moutai_prices)},
            "000333": {d: p for d, p in zip(dates, midea_prices)},
        }
        evaluators = {
            "300750": {d: 95.0 for d in dates},
            "600519": {d: 88.0 for d in dates},
            "000333": {d: 82.0 for d in dates},
        }

        from sentinel.mgfs.evolution.bayes_calibrator import BayesCalibrator

        batch = BatchBacktest(
            start_date=dates[0],
            end_date=dates[-1],
            calibrator=BayesCalibrator(min_samples=3),
        )
        reports = batch.run(
            symbols=["300750", "600519", "000333"],
            price_loaders=price_loaders,
            evaluators=evaluators,
            static_scores={"300750": 95.0, "600519": 88.0, "000333": 82.0},
            names={"300750": "宁德时代", "600519": "贵州茅台", "000333": "美的集团"},
        )

        assert len(reports) == 3
        # Sorted by bias_penalty ascending (worst first)
        assert reports[0].symbol == "300750"
        assert reports[0].bias_penalty < 0.0  # 宁德扣分最多
        assert reports[-1].symbol == "600519"
        assert reports[-1].bias_penalty >= -0.1  # 茅台扣分最少

    def test_batch_skips_assets_with_no_buy_signal(self):
        """评分从未达标的标的被跳过，不进入校准报告。"""
        dates = [date(2025, 1, i + 1) for i in range(10)]
        prices = [100, 101, 99, 100, 101, 99, 100, 100, 101, 99]

        price_loaders = {
            "000001": {d: p for d, p in zip(dates, prices)},
        }
        evaluators = {
            "000001": {d: 50.0 for d in dates},  # 从未达到 80
        }

        batch = BatchBacktest(
            start_date=dates[0],
            end_date=dates[-1],
        )
        reports = batch.run(
            symbols=["000001"],
            price_loaders=price_loaders,
            evaluators=evaluators,
            static_scores={"000001": 50.0},
            names={"000001": "平安银行"},
        )

        assert reports == []
