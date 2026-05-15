from __future__ import annotations

import math


class PercentileEngine:
    INSUFFICIENT_DATA_FALLBACK = 50.0
    NEGATIVE_SENTINEL = -1.0
    MIN_HISTORY_DAYS = 60
    MIN_VALID_HISTORY_DAYS = 30

    def compute_percentile(self, history: list[float]) -> float:
        if not history or len(history) < self.MIN_HISTORY_DAYS:
            return self.INSUFFICIENT_DATA_FALLBACK

        current = history[-1]
        if current < 0 or math.isnan(current):
            return self.NEGATIVE_SENTINEL

        valid_history = [
            v for v in history[:-1] if v >= 0 and not math.isnan(v)
        ]

        if len(valid_history) < self.MIN_VALID_HISTORY_DAYS:
            return self.INSUFFICIENT_DATA_FALLBACK

        valid_history.sort()
        below = sum(1 for v in valid_history if v < current)
        return (below / len(valid_history)) * 100
