from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sentinel.mgfs.factor_plugin import FactorScore


@dataclass(frozen=True, slots=True)
class RatingGateFailure:
    threshold_label: str
    path: str
    message: str


@dataclass(frozen=True, slots=True)
class RatingGateResult:
    passed: bool
    failures: list[RatingGateFailure]


class RatingGateEvaluator:
    def evaluate(
        self,
        threshold: dict[str, Any],
        factor_scores: dict[str, FactorScore],
        overall_confidence: float,
    ) -> RatingGateResult:
        failures: list[RatingGateFailure] = []
        label = str(threshold.get("label", "rating"))

        min_overall = threshold.get("min_overall_confidence")
        if isinstance(min_overall, (int, float)) and overall_confidence < float(min_overall):
            failures.append(
                RatingGateFailure(
                    threshold_label=label,
                    path="overall_confidence",
                    message=(
                        f"综合置信度 {overall_confidence:.2f} 低于 "
                        f"{float(min_overall):.2f}"
                    ),
                )
            )

        required_factors = threshold.get("required_factors", {})
        if isinstance(required_factors, dict):
            for factor_key, rules in required_factors.items():
                factor = factor_scores.get(str(factor_key))
                if factor is None:
                    failures.append(
                        RatingGateFailure(
                            threshold_label=label,
                            path=str(factor_key),
                            message=f"缺少因子 {factor_key}",
                        )
                    )
                    continue
                if isinstance(rules, dict):
                    failures.extend(
                        self._evaluate_factor_rules(label, str(factor_key), factor, rules)
                    )

        return RatingGateResult(passed=not failures, failures=failures)

    def _evaluate_factor_rules(
        self,
        label: str,
        factor_key: str,
        factor: FactorScore,
        rules: dict[str, Any],
    ) -> list[RatingGateFailure]:
        failures: list[RatingGateFailure] = []

        min_score = rules.get("min_score")
        if isinstance(min_score, (int, float)) and factor.score < float(min_score):
            failures.append(
                RatingGateFailure(
                    threshold_label=label,
                    path=f"{factor_key}.score",
                    message=f"{factor_key} 分数 {factor.score:.2f} 低于 {float(min_score):.2f}",
                )
            )

        min_confidence = rules.get("min_confidence")
        if isinstance(min_confidence, (int, float)) and factor.confidence < float(min_confidence):
            failures.append(
                RatingGateFailure(
                    threshold_label=label,
                    path=f"{factor_key}.confidence",
                    message=(
                        f"{factor_key} 置信度 {factor.confidence:.2f} 低于 "
                        f"{float(min_confidence):.2f}"
                    ),
                )
            )

        detail_rules = rules.get("details", {})
        if isinstance(detail_rules, dict):
            for detail_key, rule in detail_rules.items():
                detail_path = f"{factor_key}.details.{detail_key}"
                value = factor.details.get(detail_key)
                if not self._detail_rule_passes(value, rule):
                    failures.append(
                        RatingGateFailure(
                            threshold_label=label,
                            path=detail_path,
                            message=f"{detail_path} 未满足门槛 {rule}",
                        )
                    )

        return failures

    @staticmethod
    def _detail_rule_passes(value: Any, rule: Any) -> bool:
        if isinstance(rule, dict):
            if "min" in rule:
                if not isinstance(value, (int, float)) or value < float(rule["min"]):
                    return False
            if "max" in rule:
                if not isinstance(value, (int, float)) or value > float(rule["max"]):
                    return False
            if "equals" in rule and value != rule["equals"]:
                return False
            if "in" in rule:
                allowed = rule["in"]
                if not isinstance(allowed, list) or value not in allowed:
                    return False
            return True
        return value == rule
