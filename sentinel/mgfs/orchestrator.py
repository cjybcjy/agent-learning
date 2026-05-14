from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from simpleeval import simple_eval

from sentinel.mgfs.factor_plugin import (
    AlertLevel,
    BaseFactorPlugin,
    FactorScore,
    TargetInfo,
)

logger = logging.getLogger(__name__)

__all__ = ["InvestmentDecision", "MGFSOrchestrator"]


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
        plugin_keys = set(self.plugins.keys())
        weight_keys = set(self.scoring_weights.keys())
        missing_weights = plugin_keys - weight_keys
        if missing_weights:
            logger.warning("Plugins without scoring weights: %s", missing_weights)
        self.policy_multipliers = policy_multipliers
        self.circuit_breakers = circuit_breakers
        self.rating_thresholds = sorted(
            rating_thresholds, key=lambda x: x["min_score"], reverse=True
        )

    def evaluate(
        self, target: TargetInfo, policy_rating: str = "neutral"
    ) -> InvestmentDecision:
        factor_scores = self._run_plugins(target)

        # All plugins crashed → spec-mandated error rating
        if factor_scores and all(s.confidence == 0.0 for s in factor_scores.values()):
            return InvestmentDecision(
                target=target,
                generated_at=datetime.now(tz=timezone.utc),
                factor_scores=factor_scores,
                raw_total=0.0,
                policy_multiplier=self.policy_multipliers.get(policy_rating, 1.0),
                final_score=0.0,
                rating="Error",
                action="系统异常，人工复核",
                circuit_breakers_triggered=[],
                alert_level=AlertLevel.YELLOW_WARNING,
                report_sections={"overall_confidence": 0.0, "watermark": "[数据残缺 / 评估挂起]"},
            )

        raw_total = self._compute_raw_total(factor_scores)
        multiplier = self.policy_multipliers.get(policy_rating, 1.0)
        final_score = raw_total * multiplier
        triggered, alert_level = self._check_circuit_breakers(
            factor_scores, policy_rating
        )
        rating, action = self._classify_rating(final_score, alert_level)
        overall_confidence = self._compute_overall_confidence(factor_scores)
        if overall_confidence < 0.5:
            watermark = "[数据残缺 / 评估挂起]"
        elif overall_confidence < 0.8:
            watermark = "[数据部分缺失]"
        else:
            watermark = ""

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
            report_sections={"overall_confidence": overall_confidence, "watermark": watermark},
        )

    def _run_plugins(self, target: TargetInfo) -> dict[str, FactorScore]:
        scores: dict[str, FactorScore] = {}
        for key, plugin in self.plugins.items():
            if not plugin.is_applicable(target):
                continue
            try:
                scores[key] = plugin.evaluate(target)
            except Exception as e:
                logger.exception("Factor %s failed for %s", key, target.symbol)
                scores[key] = FactorScore(
                    factor_key=key,
                    factor_name=plugin.factor_name,
                    score=0.0,
                    confidence=0.0,
                    warnings=[f"【系统故障】{plugin.factor_name} 评估失败: {str(e)}"],
                )
        return scores

    def _compute_overall_confidence(
        self, factor_scores: dict[str, FactorScore]
    ) -> float:
        if not factor_scores:
            return 0.0
        total_weight = 0.0
        weighted_confidence = 0.0
        for key, score in factor_scores.items():
            w = self.scoring_weights.get(key, 0.0)
            total_weight += w
            weighted_confidence += score.confidence * w
        return weighted_confidence / total_weight if total_weight > 0 else 0.0

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
        context = self._build_eval_context(factor_scores, policy_rating)

        for cb in self.circuit_breakers:
            if not cb.get("enabled", False):
                continue
            try:
                if simple_eval(cb["rule"], names=context):
                    triggered.append(cb)
                    try:
                        cb_level = AlertLevel(cb.get("alert_level", "yellow_warning"))
                    except ValueError:
                        logger.warning(
                            "Invalid alert_level '%s' in circuit breaker, defaulting to yellow_warning",
                            cb.get("alert_level"),
                        )
                        cb_level = AlertLevel.YELLOW_WARNING
                    if cb_level in (AlertLevel.HARD_VETO, AlertLevel.SOFT_VETO):
                        alert_level = cb_level
                    elif alert_level == AlertLevel.GREEN_PASS:
                        alert_level = cb_level
            except Exception:
                logger.warning("Circuit breaker rule error: %s", cb["rule"])

        return triggered, alert_level

    def _build_eval_context(
        self, factor_scores: dict[str, FactorScore], policy_rating: str
    ) -> dict[str, Any]:
        ctx: dict[str, Any] = {}
        # Only primitive types allowed in simpleeval context
        if isinstance(policy_rating, (int, float, bool, str)):
            ctx["policy_rating"] = policy_rating
        for key, score in factor_scores.items():
            if isinstance(score.score, (int, float, bool, str)):
                ctx[f"{key}_score"] = score.score
            if isinstance(score.normalized_score, (int, float, bool, str)):
                ctx[f"{key}_normalized"] = score.normalized_score
            for detail_key, detail_val in score.details.items():
                if isinstance(detail_val, (int, float, bool, str)):
                    ctx[f"{key}_{detail_key}"] = detail_val
        return ctx

    def _classify_rating(
        self, final_score: float, alert_level: AlertLevel
    ) -> tuple[str, str]:
        if alert_level == AlertLevel.HARD_VETO:
            return "Avoid", "一票否决：禁止买入"
        for threshold in self.rating_thresholds:
            if final_score >= threshold["min_score"]:
                return threshold["label"], threshold["action"]
        return "Avoid", "回避"
