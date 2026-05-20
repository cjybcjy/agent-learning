from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class BacktestResult:
    """Outcome of a single-asset historical backtest run."""

    symbol: str
    name: str
    static_score: float
    trailing_stop_count: int
    hard_stop_count: int
    total_return: float
    max_drawdown: float
    holding_days: int


@dataclass(frozen=True, slots=True)
class CalibrationReport:
    """Bias-adjustment recommendation for a single asset."""

    symbol: str
    name: str
    static_score: float
    bias_penalty: float
    suggested_score: float | None
    confidence: float
    reason: str


class BayesCalibrator:
    """Calibrate static YAML scores using historical backtest outcomes.

    Core intuition:
    - If an asset with a high static score frequently hits stop-losses and
      bleeds NAV, the static score is likely over-optimistic (positive bias).
    - Conversely, an asset with a modest static score that never stops out
      and compounds returns may be under-rated.

    The calibrator computes a *bias penalty* (negative = over-rated,
    positive = under-rated) and proposes a revised score.
    """

    def __init__(
        self,
        *,
        stop_loss_penalty_factor: float = 2.0,
        return_reward_factor: float = 1.0,
        drawdown_penalty_factor: float = 0.5,
        min_samples: int = 30,
    ) -> None:
        self.stop_loss_penalty_factor = stop_loss_penalty_factor
        self.return_reward_factor = return_reward_factor
        self.drawdown_penalty_factor = drawdown_penalty_factor
        self.min_samples = min_samples

    def calibrate(self, results: list[BacktestResult]) -> list[CalibrationReport]:
        reports: list[CalibrationReport] = []
        for r in results:
            reports.append(self._calibrate_single(r))
        # Sort by bias penalty ascending (worst offenders first)
        reports.sort(key=lambda x: x.bias_penalty)
        return reports

    def _calibrate_single(self, r: BacktestResult) -> CalibrationReport:
        confidence = self._compute_confidence(r.holding_days)

        if confidence == 0.0:
            return CalibrationReport(
                symbol=r.symbol,
                name=r.name,
                static_score=r.static_score,
                bias_penalty=0.0,
                suggested_score=None,
                confidence=0.0,
                reason="样本不足，无法校准",
            )

        # 1. Stop-loss penalty: each stop costs; scaled by holding period
        total_stops = r.trailing_stop_count + r.hard_stop_count
        # Normalize to "stops per 90 days" to make penalty comparable
        stop_frequency = total_stops / max(1, r.holding_days / 90.0)
        stop_component = -self.stop_loss_penalty_factor * stop_frequency * 10.0

        # 2. Return reward/penalty: annualized return contribution
        # total_return over holding_days → annualized
        annualized_return = r.total_return / max(1, r.holding_days) * 252.0
        return_component = self.return_reward_factor * annualized_return * 10.0

        # 3. Drawdown penalty: deeper drawdown = larger penalty
        # max_drawdown is negative (e.g. -0.35), so abs() gives positive depth
        dd_depth = abs(r.max_drawdown)
        drawdown_component = -self.drawdown_penalty_factor * dd_depth * 10.0

        bias_penalty = stop_component + return_component + drawdown_component

        # Clamp suggested score to [0, 100]
        suggested = max(0.0, min(100.0, r.static_score + bias_penalty))

        reason = self._build_reason(r, stop_component, return_component, drawdown_component)

        return CalibrationReport(
            symbol=r.symbol,
            name=r.name,
            static_score=r.static_score,
            bias_penalty=round(bias_penalty, 2),
            suggested_score=round(suggested, 1),
            confidence=round(confidence, 2),
            reason=reason,
        )

    def _compute_confidence(self, holding_days: int) -> float:
        if holding_days < self.min_samples:
            return 0.0
        return min(1.0, holding_days / 252.0)  # Full confidence at ~1 year

    @staticmethod
    def _build_reason(
        r: BacktestResult,
        stop_component: float,
        return_component: float,
        drawdown_component: float,
    ) -> str:
        parts: list[str] = []
        total_stops = r.trailing_stop_count + r.hard_stop_count
        if total_stops > 0:
            parts.append(
                f"{total_stops}次止损"
                f"(其中追踪{r.trailing_stop_count}次/硬{r.hard_stop_count}次)"
            )
        if r.total_return < 0:
            parts.append(f"总收益{r.total_return:.1%}")
        if r.max_drawdown < -0.10:
            parts.append(f"最大回撤{r.max_drawdown:.1%}")
        if not parts:
            return "表现稳健，无需修正"
        return "; ".join(parts)
