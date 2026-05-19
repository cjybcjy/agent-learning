from __future__ import annotations

import math
from typing import Any


class PositionSizingEngine:
    """MGFS 1.5 仓位引擎: Half-Kelly + Sector Exposure Clip + Normalization Safeguard."""

    # Three-level stop-loss constants
    STOP_LOSS_HARD = -0.20          # Hard floor: 20% below cost
    STOP_LOSS_TRAILING = -0.15      # Trailing stop: 15% below peak
    STOP_LOSS_PORTFOLIO = -0.10     # Portfolio emergency: 10% NAV drawdown

    def __init__(
        self,
        *,
        sector_limits: dict[str, float] | None = None,
        kelly_k: float = 0.15,
        kelly_x0: float = 78.0,
        kelly_half_factor: float = 0.5,
        min_kelly_fraction: float = 0.0,
        max_kelly_fraction: float = 0.25,
    ) -> None:
        self.sector_limits = sector_limits or {}
        self.kelly_k = kelly_k
        self.kelly_x0 = kelly_x0
        self.kelly_half_factor = kelly_half_factor
        self.min_kelly_fraction = min_kelly_fraction
        self.max_kelly_fraction = max_kelly_fraction

    # -- probability mapping ------------------------------------------------

    def _sigmoid_probability(self, score: float) -> float:
        """Map final_score to win probability via sigmoid, clamped to [0.01, 0.95]."""
        p = 1.0 / (1.0 + math.exp(-self.kelly_k * (score - self.kelly_x0)))
        return max(0.01, min(0.95, p))

    # -- Kelly core ---------------------------------------------------------

    def _kelly_fraction(self, p: float, b: float) -> float:
        """Half-Kelly fraction with negative-EV guard.

        Returns 0.0 if expected value is non-positive (p·b <= 1-p).
        Otherwise f* = half_factor × (p·b - q) / b, clamped to
        [min_kelly_fraction, max_kelly_fraction].
        """
        q = 1.0 - p
        if p * b <= q:
            return 0.0
        f = self.kelly_half_factor * (p * b - q) / b
        return max(self.min_kelly_fraction, min(self.max_kelly_fraction, f))

    # -- exposure clipping --------------------------------------------------

    @staticmethod
    def _apply_proportional_limits(
        recs: list[dict[str, Any]],
        group_key: str,
        limits: dict[str, float],
    ) -> list[dict[str, Any]]:
        """Compress all positions in an over-limit group by scale = limit / total.

        Groups whose total is within the limit are untouched.
        """
        # Group by key
        groups: dict[str, list[dict[str, Any]]] = {}
        for r in recs:
            key = r.get(group_key, "")
            groups.setdefault(key, []).append(r)

        out: list[dict[str, Any]] = []
        for key, items in groups.items():
            limit = limits.get(key)
            if limit is None or limit <= 0:
                out.extend(items)
                continue

            total = sum(i["weight"] for i in items)
            if total <= limit + 1e-12:
                out.extend(items)
                continue

            scale = limit / total
            for i in items:
                cloned = dict(i)
                cloned["weight"] = i["weight"] * scale
                out.append(cloned)

        return out

    # -- public API ---------------------------------------------------------

    def build_portfolio(self, candidates: list[dict[str, Any]]) -> dict[str, Any]:
        """Convert candidate signals into a sized portfolio with stop-loss metadata.

        Steps:
        1. Compute raw Kelly fraction for each candidate.
        2. Drop zero-weight candidates.
        3. Apply proportional sector exposure limits.
        4. If total weight > 1.0, scale everything down proportionally.
        5. If total weight < 1.0, leave remainder as cash reserve (never scale up).
        6. Attach three-level stop-loss data to each holding.
        """
        # 1. Raw Kelly sizing
        recs: list[dict[str, Any]] = []
        for c in candidates:
            p = self._sigmoid_probability(c["final_score"])
            b = c["payoff_ratio"]
            f = self._kelly_fraction(p, b)
            if f <= 0.0:
                continue
            recs.append({
                "symbol": c["symbol"],
                "name": c["name"],
                "sector": c.get("sector", ""),
                "weight": f,
                "kelly_fraction": f,
                "win_prob": p,
                "payoff_ratio": b,
            })

        if not recs:
            return {
                "holdings": [],
                "cash_reserve": 1.0,
                "portfolio_stop_loss": self.STOP_LOSS_PORTFOLIO,
            }

        # 2. Sector exposure clip (proportional scaling down only)
        if self.sector_limits:
            recs = self._apply_proportional_limits(recs, "sector", self.sector_limits)

        # 3. Global normalization: scale DOWN if total > 1.0; never scale up
        total_weight = sum(r["weight"] for r in recs)
        if total_weight > 1.0:
            scale = 1.0 / total_weight
            for r in recs:
                r["weight"] *= scale

        # 4. Cash reserve = remainder (can be 0 if fully invested)
        cash_reserve = max(0.0, 1.0 - sum(r["weight"] for r in recs))

        # 5. Attach stop-loss levels
        holdings = []
        for r in recs:
            holdings.append({
                "symbol": r["symbol"],
                "name": r["name"],
                "sector": r["sector"],
                "weight": r["weight"],
                "kelly_fraction": r["kelly_fraction"],
                "win_prob": r["win_prob"],
                "payoff_ratio": r["payoff_ratio"],
                "stop_loss_hard": self.STOP_LOSS_HARD,
                "stop_loss_trailing": self.STOP_LOSS_TRAILING,
            })

        return {
            "holdings": holdings,
            "cash_reserve": cash_reserve,
            "portfolio_stop_loss": self.STOP_LOSS_PORTFOLIO,
        }
