from __future__ import annotations

import json
import os
import tempfile
from datetime import date
from pathlib import Path

import pytest

from sentinel.mgfs.evolution.backtest_cli import (
    _load_eastmoney_cache,
    _run_backtest,
)


class TestBacktestCLI:
    """TDD for backtest CLI — Eastmoney cache parsing + batch execution."""

    def test_load_eastmoney_cache_filters_by_date_range(self):
        """Parse Eastmoney JSON and return prices within date range."""
        raw = [
            {"TRADE_DATE": "2025-01-02 00:00:00", "CLOSE_PRICE": 100.0},
            {"TRADE_DATE": "2025-01-03 00:00:00", "CLOSE_PRICE": 102.0},
            {"TRADE_DATE": "2025-01-06 00:00:00", "CLOSE_PRICE": 99.0},
            {"TRADE_DATE": "2025-01-07 00:00:00", "CLOSE_PRICE": 95.0},
        ]
        prices = _load_eastmoney_cache(raw, date(2025, 1, 2), date(2025, 1, 7))

        assert len(prices) == 4
        assert prices[date(2025, 1, 2)] == 100.0
        assert prices[date(2025, 1, 7)] == 95.0

    def test_load_eastmoney_cache_skips_out_of_range(self):
        """Records outside [start, end] are dropped."""
        raw = [
            {"TRADE_DATE": "2024-12-30 00:00:00", "CLOSE_PRICE": 90.0},
            {"TRADE_DATE": "2025-01-02 00:00:00", "CLOSE_PRICE": 100.0},
            {"TRADE_DATE": "2025-02-01 00:00:00", "CLOSE_PRICE": 110.0},
        ]
        prices = _load_eastmoney_cache(raw, date(2025, 1, 1), date(2025, 1, 31))

        assert len(prices) == 1
        assert date(2025, 1, 2) in prices

    def test_run_backtest_produces_calibration_reports(self):
        """End-to-end: two assets, one winner one loser → sorted reports."""
        dates = [date(2025, 1, i + 1) for i in range(20)]

        # 宁德: 100 → 70 (crash)
        ningde = [100, 99, 98, 96, 94, 92, 90, 88, 86, 84, 82, 80, 78, 76, 74, 72, 71, 70, 70, 70]
        # 茅台: 100 → 130 (rally)
        moutai = [100, 101, 102, 103, 104, 105, 107, 109, 111, 113, 115, 117, 119, 121, 123, 125, 127, 129, 130, 130]

        price_loaders = {
            "300750": {d: p for d, p in zip(dates, ningde)},
            "600519": {d: p for d, p in zip(dates, moutai)},
        }
        evaluators = {
            "300750": {d: 95.0 for d in dates},
            "600519": {d: 88.0 for d in dates},
        }

        reports = _run_backtest(
            symbols=["300750", "600519"],
            price_loaders=price_loaders,
            evaluators=evaluators,
            static_scores={"300750": 95.0, "600519": 88.0},
            names={"300750": "宁德时代", "600519": "贵州茅台"},
            start_date=dates[0],
            end_date=dates[-1],
            min_samples=3,
        )

        assert len(reports) == 2
        # Worst first
        assert reports[0].symbol == "300750"
        assert reports[0].bias_penalty < 0.0
        assert reports[-1].symbol == "600519"
        assert reports[-1].bias_penalty >= -0.1

    def test_run_backtest_with_empty_data_returns_empty(self):
        """No price data → no reports."""
        reports = _run_backtest(
            symbols=["000001"],
            price_loaders={"000001": {}},
            evaluators={"000001": {}},
            static_scores={"000001": 70.0},
            names={"000001": "平安银行"},
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 10),
            min_samples=3,
        )
        assert reports == []
