from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Callable

from sentinel.mgfs.evolution.bayes_calibrator import BacktestResult


@dataclass(frozen=True, slots=True)
class DailyBar:
    """A single day's price + score snapshot for backtest simulation."""

    trade_date: date
    close_price: float
    score: float


class SingleAssetBacktest:
    """Time-travel simulation for a single asset over a historical window.

    Walks forward day-by-day, enters a virtual position on the first day
    the score is >= the buy_threshold, and tracks stop-loss triggers
    until the end of the window.
    """

    BUY_THRESHOLD = 80.0  # Strong Buy / Accumulate threshold

    def __init__(
        self,
        *,
        symbol: str,
        name: str,
        start_date: date,
        end_date: date,
        static_score: float,
        entry_weight: float = 0.20,
        stop_loss_hard: float = -0.20,
        stop_loss_trailing: float = -0.15,
    ) -> None:
        self.symbol = symbol
        self.name = name
        self.start_date = start_date
        self.end_date = end_date
        self.static_score = static_score
        self.entry_weight = entry_weight
        self.stop_loss_hard = stop_loss_hard
        self.stop_loss_trailing = stop_loss_trailing

    def run(
        self,
        *,
        price_loader: dict[date, float],
        evaluator: dict[date, float],
    ) -> BacktestResult | None:
        """Execute the backtest and return result, or None if no entry signal."""
        bars = self._build_bars(price_loader, evaluator)
        if not bars:
            return None

        # Find first entry day (score >= threshold)
        entry_idx = None
        for i, bar in enumerate(bars):
            if bar.score >= self.BUY_THRESHOLD:
                entry_idx = i
                break

        if entry_idx is None:
            return None

        entry_price = bars[entry_idx].close_price
        highest_price = entry_price
        trailing_triggered = False
        hard_triggered = False
        max_drawdown = 0.0

        # Walk forward from entry to end
        for bar in bars[entry_idx:]:
            current_price = bar.close_price
            highest_price = max(highest_price, current_price)

            # Drawdown from peak
            dd = (current_price - highest_price) / highest_price
            max_drawdown = min(max_drawdown, dd)

            # Trailing stop check
            trail_trigger = highest_price * (1.0 + self.stop_loss_trailing)
            if current_price <= trail_trigger:
                trailing_triggered = True

            # Hard stop check
            hard_trigger = entry_price * (1.0 + self.stop_loss_hard)
            if current_price <= hard_trigger:
                hard_triggered = True

        final_price = bars[-1].close_price
        total_return = (final_price - entry_price) / entry_price
        holding_days = len(bars) - entry_idx

        return BacktestResult(
            symbol=self.symbol,
            name=self.name,
            static_score=self.static_score,
            trailing_stop_count=int(trailing_triggered),
            hard_stop_count=int(hard_triggered),
            total_return=total_return,
            max_drawdown=max_drawdown,
            holding_days=holding_days,
        )

    def _build_bars(
        self,
        price_loader: dict[date, float],
        evaluator: dict[date, float],
    ) -> list[DailyBar]:
        """Merge price + score data into ordered DailyBar sequence."""
        bars: list[DailyBar] = []
        current = self.start_date
        while current <= self.end_date:
            price = price_loader.get(current)
            score = evaluator.get(current)
            if price is not None and score is not None:
                bars.append(DailyBar(trade_date=current, close_price=price, score=score))
            current += timedelta(days=1)
        return bars
