from __future__ import annotations

from pathlib import Path

import yaml

from sentinel.mgfs.data.metrics_aggregator import MetricsAggregator
from sentinel.mgfs.factor_plugin import BaseFactorPlugin, FactorScore, TargetInfo


class MoatFactorPlugin(BaseFactorPlugin):
    factor_key = "moat"
    factor_name = "护城河深度"
    default_weight = 0.5

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
                    "base": {"weight": 0.4},
                    "trend": {"weight": 0.35},
                    "safety": {"weight": 0.25},
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
                    "base_weight": weights.get("base", {}).get("weight", 0.4),
                    "trend_score": 0.0,
                    "trend_weight": weights.get("trend", {}).get("weight", 0.35),
                    "safety_score": 0.0,
                    "safety_weight": weights.get("safety", {}).get("weight", 0.25),
                },
                confidence=0.5,
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
        base_w = weights.get("base", {}).get("weight", 0.4)
        trend_w = weights.get("trend", {}).get("weight", 0.35)
        safety_w = weights.get("safety", {}).get("weight", 0.25)

        final_score = base_score * base_w + trend_score * trend_w + safety_score * safety_w

        # Confidence is minimum of available segments
        if self.aggregator is not None:
            overall_confidence = min([0.9, trend_confidence, safety_confidence])
        else:
            overall_confidence = 0.5  # lowered because dynamic data missing
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

    def _compute_trend_score(self, target: TargetInfo) -> tuple[float, float]:
        if self.aggregator is None:
            return 0.0, 0.0
        metrics = ["roic_sustainability", "gmoat_stability", "rd_efficiency"]
        values: list[float] = []
        for metric in metrics:
            row = self.aggregator.get_latest_trend_metric(target, metric)
            if row is not None:
                values.append(float(row["value"]))
        if not values:
            return 0.0, 0.0
        return sum(values) / len(values), 0.8

    def _compute_safety_score(self, target: TargetInfo) -> tuple[float, float]:
        if self.aggregator is None:
            return 0.0, 0.0
        metrics = ["debt_ratio_deterioration", "goodwill_ratio", "operating_cashflow_ratio"]
        values: list[float] = []
        for metric in metrics:
            row = self.aggregator.get_latest_safety_metric(target, metric)
            if row is not None:
                values.append(float(row["value"]))
        if not values:
            return 0.0, 0.0
        return sum(values) / len(values), 0.8
