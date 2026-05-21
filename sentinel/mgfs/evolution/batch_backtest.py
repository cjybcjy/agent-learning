from __future__ import annotations

from datetime import date
from typing import Any

from sentinel.mgfs.evolution.bayes_calibrator import (
    BacktestResult,
    BayesCalibrator,
    CalibrationReport,
)
from sentinel.mgfs.evolution.historical_backtest import SingleAssetBacktest


class BatchBacktest:
    """Run historical backtests across a basket of assets and calibrate scores.

    Orchestrates multiple SingleAssetBacktest runs, aggregates the
    BacktestResult list, and feeds it into BayesCalibrator.
    """

    def __init__(
        self,
        *,
        start_date: date,
        end_date: date,
        calibrator: BayesCalibrator | None = None,
    ) -> None:
        self.start_date = start_date
        self.end_date = end_date
        self.calibrator = calibrator or BayesCalibrator()

    def run(
        self,
        *,
        symbols: list[str],
        price_loaders: dict[str, dict[date, float]],
        evaluators: dict[str, dict[date, float]],
        static_scores: dict[str, float],
        names: dict[str, str],
        entry_weight: float = 0.20,
        stop_loss_hard: float = -0.20,
        stop_loss_trailing: float = -0.15,
    ) -> list[CalibrationReport]:
        """Execute backtests for all symbols and return calibration reports.

        Symbols with no entry signal (score never >= threshold) are skipped.
        """
        results: list[BacktestResult] = []

        for symbol in symbols:
            engine = SingleAssetBacktest(
                symbol=symbol,
                name=names.get(symbol, symbol),
                start_date=self.start_date,
                end_date=self.end_date,
                static_score=static_scores.get(symbol, 0.0),
                entry_weight=entry_weight,
                stop_loss_hard=stop_loss_hard,
                stop_loss_trailing=stop_loss_trailing,
            )
            result = engine.run(
                price_loader=price_loaders.get(symbol, {}),
                evaluator=evaluators.get(symbol, {}),
            )
            if result is not None:
                results.append(result)

        if not results:
            return []

        return self.calibrator.calibrate(results)
