from __future__ import annotations

import pytest

from sentinel.mgfs.evolution.bayes_calibrator import (
    BacktestResult,
    BayesCalibrator,
    CalibrationReport,
)


class TestBayesCalibrator:
    """TDD for MGFS 2.0 Bayes Calibrator — bias penalty from historical backtest."""

    @pytest.fixture
    def calibrator(self) -> BayesCalibrator:
        return BayesCalibrator(
            stop_loss_penalty_factor=2.0,
            return_reward_factor=1.0,
            min_samples=3,
        )

    def test_fake_core_asset_gets_negative_bias_penalty(self, calibrator):
        """
        伪核心资产：静态 YAML 给了 95 满分，但历史回测中 4 次触发追踪止损、
        净值贡献 -18%。验证 calibrator 能精准计算出负向偏见惩罚。
        """
        results = [
            BacktestResult(
                symbol="300750",
                name="宁德时代",
                static_score=95.0,
                trailing_stop_count=4,
                hard_stop_count=1,
                total_return=-0.18,
                max_drawdown=-0.35,
                holding_days=180,
            ),
        ]

        reports = calibrator.calibrate(results)

        assert len(reports) == 1
        r = reports[0]
        assert r.symbol == "300750"
        assert r.static_score == 95.0
        # 频繁止损 + 负收益 → 必须有负向偏见惩罚
        assert r.bias_penalty < 0.0
        # 修正后的评分必须低于原始评分
        assert r.suggested_score < r.static_score
        # 建议评分应在合理区间 (0, 100)
        assert 0.0 < r.suggested_score < 100.0

    def test_true_winner_gets_positive_or_neutral_penalty(self, calibrator):
        """
        真核心资产：静态评分 88，历史回测中 0 次止损、净值贡献 +35%。
        验证 calibrator 不扣分（甚至可能有微小奖励）。
        """
        results = [
            BacktestResult(
                symbol="600519",
                name="贵州茅台",
                static_score=88.0,
                trailing_stop_count=0,
                hard_stop_count=0,
                total_return=0.35,
                max_drawdown=-0.05,
                holding_days=200,
            ),
        ]

        reports = calibrator.calibrate(results)

        r = reports[0]
        assert r.symbol == "600519"
        # 无止损 + 正收益 → 偏见惩罚应接近 0 或为正（奖励）
        assert r.bias_penalty >= -0.1
        assert r.suggested_score >= r.static_score - 0.1

    def test_insufficient_samples_returns_none(self, calibrator):
        """持有天数 < min_samples 时，无法校准，返回 None。"""
        results = [
            BacktestResult(
                symbol="000001",
                name="平安银行",
                static_score=70.0,
                trailing_stop_count=0,
                hard_stop_count=0,
                total_return=0.05,
                max_drawdown=-0.03,
                holding_days=1,  # 样本不足
            ),
        ]

        reports = calibrator.calibrate(results)

        # 样本不足，无法给出可靠校准
        assert reports[0].suggested_score is None
        assert reports[0].confidence == 0.0

    def test_multi_asset_ranking(self, calibrator):
        """多只标的回测，验证惩罚排序：伪核心资产扣分最多。"""
        results = [
            BacktestResult(
                symbol="300750",
                name="宁德时代",
                static_score=95.0,
                trailing_stop_count=4,
                hard_stop_count=1,
                total_return=-0.18,
                max_drawdown=-0.35,
                holding_days=180,
            ),
            BacktestResult(
                symbol="600519",
                name="贵州茅台",
                static_score=88.0,
                trailing_stop_count=0,
                hard_stop_count=0,
                total_return=0.35,
                max_drawdown=-0.05,
                holding_days=200,
            ),
            BacktestResult(
                symbol="000333",
                name="美的集团",
                static_score=82.0,
                trailing_stop_count=1,
                hard_stop_count=0,
                total_return=0.08,
                max_drawdown=-0.12,
                holding_days=150,
            ),
        ]

        reports = calibrator.calibrate(results)

        penalties = {r.symbol: r.bias_penalty for r in reports}
        # 宁德频繁止损 + 负收益 → 扣分最多
        assert penalties["300750"] < penalties["000333"]
        assert penalties["300750"] < penalties["600519"]
        # 茅台无止损 + 高收益 → 扣分最少（或为正）
        assert penalties["600519"] >= penalties["000333"]
