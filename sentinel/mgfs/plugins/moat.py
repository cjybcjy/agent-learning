from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

from sentinel.mgfs.data.metrics_aggregator import MetricsAggregator
from sentinel.mgfs.factor_plugin import BaseFactorPlugin, FactorScore, TargetInfo


class MoatFactorPlugin(BaseFactorPlugin):
    factor_key = "moat"
    factor_name = "护城河深度"
    default_weight = 0.5

    DEFAULT_BASE_WEIGHT = 0.4
    DEFAULT_TREND_WEIGHT = 0.35
    DEFAULT_SAFETY_WEIGHT = 0.25
    BASE_CONFIDENCE = 0.9
    DYNAMIC_CONFIDENCE = 0.8
    FALLBACK_CONFIDENCE = 0.5

    def __init__(
        self,
        config_path: Path | None = None,
        aggregator: MetricsAggregator | None = None,
    ) -> None:
        self.config_path = config_path
        self.aggregator = aggregator
        self._config: dict | None = None

    def _load_config(self) -> dict:
        if self._config is not None:
            return self._config
        if self.config_path is None or not self.config_path.exists():
            return {
                "scoring_weights": {
                    "base": {"weight": self.DEFAULT_BASE_WEIGHT},
                    "trend": {"weight": self.DEFAULT_TREND_WEIGHT},
                    "safety": {"weight": self.DEFAULT_SAFETY_WEIGHT},
                },
                "companies": {},
            }
        with self.config_path.open("r", encoding="utf-8") as handle:
            self._config = yaml.safe_load(handle) or {}
        return self._config

    def evaluate(self, target: TargetInfo) -> FactorScore:
        cfg = self._load_config()
        weights = cfg.get("scoring_weights", {})
        companies = cfg.get("companies", {})

        company_cfg = companies.get(target.symbol)
        if company_cfg is None:
            return FactorScore(
                factor_key=self.factor_key,
                factor_name=self.factor_name,
                score=0.0,
                max_score=100.0,
                weight=self.default_weight,
                details={
                    "base_score": 0.0,
                    "base_weight": weights.get("base", {}).get("weight", self.DEFAULT_BASE_WEIGHT),
                    "trend_score": 0.0,
                    "trend_weight": weights.get("trend", {}).get("weight", self.DEFAULT_TREND_WEIGHT),
                    "safety_score": 0.0,
                    "safety_weight": weights.get("safety", {}).get("weight", self.DEFAULT_SAFETY_WEIGHT),
                },
                confidence=self.FALLBACK_CONFIDENCE,
                warnings=[f"未找到 {target.symbol} 的静态评分记录"],
            )

        # 1. Static base score
        base_cfg = company_cfg.get("base_score", {})
        base_values = [
            v["score"] for v in base_cfg.values()
            if isinstance(v, dict) and "score" in v
        ]
        base_score = sum(base_values) / len(base_values) if base_values else 0.0

        # 2. Dynamic trend score (from aggregator)
        trend_score, trend_confidence = self._compute_trend_score(target)

        # 3. Safety score (from aggregator)
        safety_score, safety_confidence = self._compute_safety_score(target)

        # 4. Weighted aggregation
        base_w = weights.get("base", {}).get("weight", self.DEFAULT_BASE_WEIGHT)
        trend_w = weights.get("trend", {}).get("weight", self.DEFAULT_TREND_WEIGHT)
        safety_w = weights.get("safety", {}).get("weight", self.DEFAULT_SAFETY_WEIGHT)

        final_score = base_score * base_w + trend_score * trend_w + safety_score * safety_w

        # Confidence calculation:
        # - If aggregator is None: fallback confidence
        # - If aggregator exists but no dynamic data at all: fallback confidence
        # - If base + some dynamic segments have data: min of available segment confidences
        if self.aggregator is not None:
            segment_confidences = [self.BASE_CONFIDENCE]
            if trend_confidence > 0.0:
                segment_confidences.append(trend_confidence)
            if safety_confidence > 0.0:
                segment_confidences.append(safety_confidence)
            if len(segment_confidences) == 1:
                # Only base data available
                overall_confidence = self.FALLBACK_CONFIDENCE
            else:
                overall_confidence = min(segment_confidences)
        else:
            overall_confidence = self.FALLBACK_CONFIDENCE
        warnings: list[str] = []
        if self.aggregator is None:
            warnings.append("动态指标数据缺失，仅使用静态评分")

        return FactorScore(
            factor_key=self.factor_key,
            factor_name=self.factor_name,
            score=round(final_score, 2),
            max_score=100.0,
            weight=self.default_weight,
            details={
                "base_score": round(base_score, 2),
                "base_weight": base_w,
                "trend_score": round(trend_score, 2),
                "trend_weight": trend_w,
                "safety_score": round(safety_score, 2),
                "safety_weight": safety_w,
            },
            confidence=round(overall_confidence, 2),
            warnings=warnings,
        )

    def _compute_segment_score(
        self,
        target: TargetInfo,
        metrics: list[str],
        fetch_fn: Callable[[TargetInfo, str], dict[str, Any] | None],
    ) -> tuple[float, float]:
        """Compute average score and confidence for a segment of metrics."""
        if self.aggregator is None:
            return 0.0, 0.0
        values: list[float] = []
        for metric in metrics:
            row = fetch_fn(target, metric)
            if row is not None:
                values.append(float(row["value"]))
        if not values:
            return 0.0, 0.0
        return sum(values) / len(values), self.DYNAMIC_CONFIDENCE

    def _compute_trend_score(self, target: TargetInfo) -> tuple[float, float]:
        if self.aggregator is None:
            return 0.0, 0.0
        metrics = ["roic_sustainability", "gmoat_stability", "rd_efficiency"]
        return self._compute_segment_score(
            target, metrics, self.aggregator.get_latest_trend_metric
        )

    def _compute_safety_score(self, target: TargetInfo) -> tuple[float, float]:
        if self.aggregator is None:
            return 0.0, 0.0
        metrics = ["debt_ratio_deterioration", "goodwill_ratio", "operating_cashflow_ratio"]
        return self._compute_segment_score(
            target, metrics, self.aggregator.get_latest_safety_metric
        )
