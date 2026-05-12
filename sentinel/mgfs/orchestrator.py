from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sentinel.mgfs.factor_plugin import (
    AlertLevel,
    BaseFactorPlugin,
    FactorScore,
    TargetInfo,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class InvestmentDecision:
    target: TargetInfo
    generated_at: datetime
    factor_scores: dict[str, FactorScore]
    raw_total: float
    policy_multiplier: float
    final_score: float
    rating: str
    action: str
    circuit_breakers_triggered: list[dict[str, Any]]
    alert_level: AlertLevel
    report_sections: dict[str, Any] = field(default_factory=dict)


class MGFSOrchestrator:
    def __init__(
        self,
        plugins: list[BaseFactorPlugin],
        scoring_weights: dict[str, float],
        policy_multipliers: dict[str, float],
        circuit_breakers: list[dict[str, Any]],
        rating_thresholds: list[dict[str, Any]],
    ) -> None:
        self.plugins = {p.factor_key: p for p in plugins}
        self.scoring_weights = scoring_weights
        self.policy_multipliers = policy_multipliers
        self.circuit_breakers = circuit_breakers
        self.rating_thresholds = sorted(
            rating_thresholds, key=lambda x: x["min_score"], reverse=True
        )

    def evaluate(
        self, target: TargetInfo, policy_rating: str = "neutral"
    ) -> InvestmentDecision:
        factor_scores = self._run_plugins(target)
        raw_total = self._compute_raw_total(factor_scores)
        multiplier = self.policy_multipliers.get(policy_rating, 1.0)
        final_score = raw_total * multiplier
        triggered, alert_level = self._check_circuit_breakers(
            factor_scores, policy_rating
        )
        rating, action = self._classify_rating(final_score, alert_level)

        return InvestmentDecision(
            target=target,
            generated_at=datetime.now(tz=timezone.utc),
            factor_scores=factor_scores,
            raw_total=round(raw_total, 2),
            policy_multiplier=multiplier,
            final_score=round(final_score, 2),
            rating=rating,
            action=action,
            circuit_breakers_triggered=triggered,
            alert_level=alert_level,
        )

    def _run_plugins(self, target: TargetInfo) -> dict[str, FactorScore]:
        scores: dict[str, FactorScore] = {}
        for key, plugin in self.plugins.items():
            try:
                scores[key] = plugin.evaluate(target)
            except Exception:
                logger.exception("Factor %s failed for %s", key, target.symbol)
                scores[key] = FactorScore(
                    factor_key=key,
                    factor_name=plugin.factor_name,
                    score=0.0,
                    confidence=0.0,
                    warnings=[f"{plugin.factor_name} 评估失败，使用兜底分数"],
                )
        return scores

    def _compute_raw_total(
        self, factor_scores: dict[str, FactorScore]
    ) -> float:
        total = 0.0
        weight_sum = 0.0
        for key, score in factor_scores.items():
            w = self.scoring_weights.get(key, 0.0)
            total += score.normalized_score * 100 * w
            weight_sum += w
        return total / weight_sum if weight_sum > 0 else 0.0

    def _check_circuit_breakers(
        self, factor_scores: dict[str, FactorScore], policy_rating: str
    ) -> tuple[list[dict[str, Any]], AlertLevel]:
        triggered: list[dict[str, Any]] = []
        alert_level = AlertLevel.GREEN_PASS
        return triggered, alert_level

    def _classify_rating(
        self, final_score: float, alert_level: AlertLevel
    ) -> tuple[str, str]:
        if alert_level == AlertLevel.HARD_VETO:
            return "Avoid", "一票否决：禁止买入"
        for threshold in self.rating_thresholds:
            if final_score >= threshold["min_score"]:
                return threshold["label"], threshold["action"]
        return "Avoid", "回避"
