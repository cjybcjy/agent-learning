from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from simpleeval import simple_eval

from sentinel.mgfs.factor_plugin import (
    AlertLevel,
    BaseFactorPlugin,
    FactorScore,
    TargetInfo,
)
from sentinel.mgfs.rating_gates import RatingGateEvaluator

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
        self._rating_gate_evaluator = RatingGateEvaluator()

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

        adjusted_weights = self._get_adjusted_weights(factor_scores)
        weight_denominator = self._compute_weight_denominator(factor_scores)
        inactive_weight = max(weight_denominator - sum(adjusted_weights.values()), 0.0)
        raw_total = self._compute_raw_total(
            factor_scores,
            adjusted_weights,
            weight_denominator,
        )
        multiplier, effective_policy_rating, policy_source = (
            self._resolve_policy_adjustment(factor_scores, policy_rating)
        )
        final_score = raw_total * multiplier
        triggered, alert_level = self._check_circuit_breakers(
            factor_scores, effective_policy_rating
        )

        # Detect system failures (e.g. network outage in timing plugin)
        system_failure_keys = [
            key for key, score in factor_scores.items()
            if score.confidence == 0.0
            and any("系统故障" in w for w in score.warnings)
        ]

        overall_confidence = self._compute_overall_confidence(
            factor_scores,
            adjusted_weights,
            weight_denominator,
        )

        if system_failure_keys:
            # Force downgrade to Hold/Watch with system-failure watermark
            alert_level = AlertLevel.SOFT_VETO
            rating = "Hold/Watch"
            action = "等待拐点"
            rating_gate_failures: list[dict[str, Any]] = []
            failed_names = [
                factor_scores[k].factor_name for k in system_failure_keys
            ]
            watermark = f"⚠️ {'/'.join(failed_names)}系统故障，置信度熔断保护中"
        else:
            rating, action, rating_gate_failures = self._classify_rating_with_gates(
                final_score,
                alert_level,
                factor_scores,
                overall_confidence,
            )
            if overall_confidence < 0.5:
                watermark = "[数据残缺 / 评估挂起]"
            elif overall_confidence < 0.8:
                watermark = "[数据部分缺失]"
            else:
                watermark = ""
            if rating_gate_failures:
                watermark = f"{watermark} [Strong Buy 证据不足]".strip()

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
            report_sections={
                "overall_confidence": overall_confidence,
                "watermark": watermark,
                "adjusted_weights": adjusted_weights,
                "weight_denominator": round(weight_denominator, 4),
                "inactive_weight": round(inactive_weight, 4),
                "policy_source": policy_source,
                "effective_policy_rating": effective_policy_rating,
                "rating_gate_failures": rating_gate_failures,
            },
        )

    def _resolve_policy_adjustment(
        self,
        factor_scores: dict[str, FactorScore],
        fallback_policy_rating: str,
    ) -> tuple[float, str, str]:
        policy_score = factor_scores.get("policy")
        if policy_score is not None:
            multiplier = policy_score.details.get("multiplier")
            if isinstance(multiplier, (int, float)):
                policy_rating = policy_score.details.get("policy_rating")
                if not isinstance(policy_rating, str):
                    policy_rating = fallback_policy_rating
                return float(multiplier), policy_rating, "policy_factor"

        return (
            self.policy_multipliers.get(fallback_policy_rating, 1.0),
            fallback_policy_rating,
            "policy_rating",
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

    def _get_adjusted_weights(
        self, factor_scores: dict[str, FactorScore]
    ) -> dict[str, float]:
        """Return numerator weights after low-confidence plugins are dropped.

        Plugins with confidence < 0.5 have their weight set to 0.
        Remaining weights keep their configured weight; dropped weight stays
        in the score denominator so missing evidence cannot inflate the score.

        Exception: system failures (confidence == 0.0 with system-failure warning)
        retain their original weight so that a score of 0 drags the total down,
        preventing inflated ratings when a plugin crashes.
        """
        # Detect system failures — these must NOT trigger redistribution
        system_failure_keys = {
            key for key, score in factor_scores.items()
            if score.confidence == 0.0
            and any("系统故障" in w for w in score.warnings)
        }

        if system_failure_keys:
            # Keep original weights; failed plugin contributes 0 score naturally
            return {key: self.scoring_weights.get(key, 0.0) for key in factor_scores}

        adjusted: dict[str, float] = {}
        for key, score in factor_scores.items():
            w = self.scoring_weights.get(key, 0.0)
            if score.confidence >= 0.5 and w > 0:
                adjusted[key] = w
            else:
                adjusted[key] = 0.0

        return adjusted

    def _compute_weight_denominator(
        self,
        factor_scores: dict[str, FactorScore],
    ) -> float:
        return sum(
            self.scoring_weights.get(key, 0.0)
            for key in factor_scores
        )

    def _compute_overall_confidence(
        self,
        factor_scores: dict[str, FactorScore],
        adjusted_weights: dict[str, float] | None = None,
        weight_denominator: float | None = None,
    ) -> float:
        if not factor_scores:
            return 0.0
        weights = adjusted_weights if adjusted_weights is not None else self.scoring_weights
        total_weight = (
            weight_denominator
            if weight_denominator is not None
            else sum(self.scoring_weights.get(key, 0.0) for key in factor_scores)
        )
        weighted_confidence = 0.0
        for key, score in factor_scores.items():
            w = weights.get(key, 0.0)
            weighted_confidence += score.confidence * w
        return weighted_confidence / total_weight if total_weight > 0 else 0.0

    def _compute_raw_total(
        self,
        factor_scores: dict[str, FactorScore],
        adjusted_weights: dict[str, float] | None = None,
        weight_denominator: float | None = None,
    ) -> float:
        weights = adjusted_weights if adjusted_weights is not None else self.scoring_weights
        total = 0.0
        denominator = (
            weight_denominator
            if weight_denominator is not None
            else sum(self.scoring_weights.get(key, 0.0) for key in factor_scores)
        )
        for key, score in factor_scores.items():
            w = weights.get(key, 0.0)
            total += score.normalized_score * 100 * w
        return total / denominator if denominator > 0 else 0.0

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

    def _classify_rating_with_gates(
        self,
        final_score: float,
        alert_level: AlertLevel,
        factor_scores: dict[str, FactorScore],
        overall_confidence: float,
    ) -> tuple[str, str, list[dict[str, Any]]]:
        if alert_level == AlertLevel.HARD_VETO:
            return "Avoid", "一票否决：禁止买入", []

        gate_failures = []
        for threshold in self.rating_thresholds:
            if final_score < threshold["min_score"]:
                continue
            result = self._rating_gate_evaluator.evaluate(
                threshold=threshold,
                factor_scores=factor_scores,
                overall_confidence=overall_confidence,
            )
            if result.passed:
                return (
                    threshold["label"],
                    threshold["action"],
                    [asdict(failure) for failure in gate_failures],
                )
            gate_failures.extend(result.failures)

        return "Avoid", "回避", [asdict(failure) for failure in gate_failures]
