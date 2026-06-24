from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sentinel.mgfs.factor_plugin import AlertLevel


@dataclass(frozen=True, slots=True)
class ConfigValidationIssue:
    path: str
    message: str


class MGFSConfigValidationError(ValueError):
    def __init__(self, issues: list[ConfigValidationIssue]) -> None:
        self.issues = issues
        paths = ", ".join(issue.path for issue in issues)
        super().__init__(f"MGFS config validation failed: {paths}")


def validate_mgfs_config(
    config: dict[str, Any],
    *,
    raise_on_error: bool = False,
) -> list[ConfigValidationIssue]:
    issues: list[ConfigValidationIssue] = []
    if not isinstance(config, dict):
        issues.append(ConfigValidationIssue("", "配置必须是 mapping"))
        return _finish(issues, raise_on_error)

    _validate_modules(config.get("modules", {}), issues)
    _validate_scoring_formula(config.get("scoring_formula", {}), issues)
    _validate_policy_multiplier(config.get("policy_multiplier", {}), issues)
    _validate_circuit_breakers(config.get("circuit_breakers", {}), issues)
    _validate_rating_thresholds(config.get("rating_thresholds", {}), issues)
    return _finish(issues, raise_on_error)


def _finish(
    issues: list[ConfigValidationIssue],
    raise_on_error: bool,
) -> list[ConfigValidationIssue]:
    if issues and raise_on_error:
        raise MGFSConfigValidationError(issues)
    return issues


def _validate_modules(raw: Any, issues: list[ConfigValidationIssue]) -> None:
    if not isinstance(raw, dict):
        issues.append(ConfigValidationIssue("modules", "modules 必须是 mapping"))
        return
    for key, cfg in raw.items():
        path = f"modules.{key}"
        if not isinstance(cfg, dict):
            issues.append(ConfigValidationIssue(path, "module 配置必须是 mapping"))
            continue
        if cfg.get("enabled") is True and not _non_empty_str(cfg.get("class_path")):
            issues.append(
                ConfigValidationIssue(f"{path}.class_path", "启用模块必须提供 class_path")
            )


def _validate_scoring_formula(raw: Any, issues: list[ConfigValidationIssue]) -> None:
    if not isinstance(raw, dict):
        issues.append(ConfigValidationIssue("scoring_formula", "scoring_formula 必须是 mapping"))
        return
    for key, cfg in raw.items():
        path = f"scoring_formula.{key}"
        if not isinstance(cfg, dict):
            issues.append(ConfigValidationIssue(path, "评分权重配置必须是 mapping"))
            continue
        weight = cfg.get("weight")
        if not _is_number(weight) or float(weight) < 0:
            issues.append(
                ConfigValidationIssue(f"{path}.weight", "weight 必须是非负数字")
            )


def _validate_policy_multiplier(raw: Any, issues: list[ConfigValidationIssue]) -> None:
    if not isinstance(raw, dict):
        issues.append(ConfigValidationIssue("policy_multiplier", "policy_multiplier 必须是 mapping"))
        return
    for key, cfg in raw.items():
        path = f"policy_multiplier.{key}"
        if not isinstance(cfg, dict):
            issues.append(ConfigValidationIssue(path, "policy multiplier 配置必须是 mapping"))
            continue
        multiplier = cfg.get("multiplier")
        if not _is_number(multiplier) or float(multiplier) < 0:
            issues.append(
                ConfigValidationIssue(f"{path}.multiplier", "multiplier 必须是非负数字")
            )


def _validate_circuit_breakers(raw: Any, issues: list[ConfigValidationIssue]) -> None:
    if not isinstance(raw, dict):
        issues.append(ConfigValidationIssue("circuit_breakers", "circuit_breakers 必须是 mapping"))
        return
    valid_alerts = {level.value for level in AlertLevel}
    for key, cfg in raw.items():
        path = f"circuit_breakers.{key}"
        if not isinstance(cfg, dict):
            issues.append(ConfigValidationIssue(path, "circuit breaker 配置必须是 mapping"))
            continue
        if cfg.get("enabled") is True and not _non_empty_str(cfg.get("rule")):
            issues.append(ConfigValidationIssue(f"{path}.rule", "启用熔断器必须提供 rule"))
        alert_level = cfg.get("alert_level")
        if alert_level is not None and alert_level not in valid_alerts:
            issues.append(
                ConfigValidationIssue(
                    f"{path}.alert_level",
                    f"alert_level 必须是 {sorted(valid_alerts)} 之一",
                )
            )


def _validate_rating_thresholds(raw: Any, issues: list[ConfigValidationIssue]) -> None:
    if not isinstance(raw, dict):
        issues.append(ConfigValidationIssue("rating_thresholds", "rating_thresholds 必须是 mapping"))
        return
    for key, threshold in raw.items():
        path = f"rating_thresholds.{key}"
        if not isinstance(threshold, dict):
            issues.append(ConfigValidationIssue(path, "rating threshold 必须是 mapping"))
            continue
        if not _is_number(threshold.get("min_score")):
            issues.append(ConfigValidationIssue(f"{path}.min_score", "min_score 必须是数字"))
        if not _non_empty_str(threshold.get("label")):
            issues.append(ConfigValidationIssue(f"{path}.label", "label 必须是非空字符串"))
        if not _non_empty_str(threshold.get("action")):
            issues.append(ConfigValidationIssue(f"{path}.action", "action 必须是非空字符串"))

        min_overall = threshold.get("min_overall_confidence")
        if min_overall is not None and not _is_unit_interval(min_overall):
            issues.append(
                ConfigValidationIssue(
                    f"{path}.min_overall_confidence",
                    "min_overall_confidence 必须在 0..1",
                )
            )
        _validate_required_factors(path, threshold.get("required_factors"), issues)


def _validate_required_factors(
    threshold_path: str,
    raw: Any,
    issues: list[ConfigValidationIssue],
) -> None:
    if raw is None:
        return
    if not isinstance(raw, dict):
        issues.append(
            ConfigValidationIssue(
                f"{threshold_path}.required_factors",
                "required_factors 必须是 mapping",
            )
        )
        return
    for factor_key, rules in raw.items():
        path = f"{threshold_path}.required_factors.{factor_key}"
        if not isinstance(rules, dict):
            issues.append(ConfigValidationIssue(path, "factor gate 必须是 mapping"))
            continue
        min_score = rules.get("min_score")
        if min_score is not None and not _is_number(min_score):
            issues.append(ConfigValidationIssue(f"{path}.min_score", "min_score 必须是数字"))
        min_confidence = rules.get("min_confidence")
        if min_confidence is not None and not _is_unit_interval(min_confidence):
            issues.append(
                ConfigValidationIssue(f"{path}.min_confidence", "min_confidence 必须在 0..1")
            )
        _validate_detail_rules(path, rules.get("details"), issues)


def _validate_detail_rules(
    factor_path: str,
    raw: Any,
    issues: list[ConfigValidationIssue],
) -> None:
    if raw is None:
        return
    if not isinstance(raw, dict):
        issues.append(ConfigValidationIssue(f"{factor_path}.details", "details 必须是 mapping"))
        return
    for detail_key, rule in raw.items():
        path = f"{factor_path}.details.{detail_key}"
        if isinstance(rule, dict):
            allowed_keys = {"min", "max", "equals", "in"}
            for key in rule:
                if key not in allowed_keys:
                    issues.append(ConfigValidationIssue(f"{path}.{key}", "不支持的 detail rule"))
            if "min" in rule and not _is_number(rule["min"]):
                issues.append(ConfigValidationIssue(f"{path}.min", "min 必须是数字"))
            if "max" in rule and not _is_number(rule["max"]):
                issues.append(ConfigValidationIssue(f"{path}.max", "max 必须是数字"))
            if "in" in rule and (
                not isinstance(rule["in"], list) or not rule["in"]
            ):
                issues.append(ConfigValidationIssue(f"{path}.in", "in 必须是非空列表"))


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_unit_interval(value: Any) -> bool:
    return _is_number(value) and 0.0 <= float(value) <= 1.0


def _non_empty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())
