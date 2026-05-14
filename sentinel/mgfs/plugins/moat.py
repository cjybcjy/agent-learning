from __future__ import annotations

from pathlib import Path

import yaml

from sentinel.mgfs.factor_plugin import BaseFactorPlugin, FactorScore, TargetInfo


class MoatFactorPlugin(BaseFactorPlugin):
    factor_key = "moat"
    factor_name = "护城河深度"
    default_weight = 0.5

    def __init__(self, config_path: Path | None = None) -> None:
        self.config_path = config_path
        self._config: dict | None = None

    def _load_config(self) -> dict:
        if self._config is not None:
            return self._config
        if self.config_path is None or not self.config_path.exists():
            return {
                "scoring_weights": {"base": {"weight": 0.4}},
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

        base_cfg = company_cfg.get("base_score", {})
        base_values = [v["score"] for v in base_cfg.values() if isinstance(v, dict) and "score" in v]
        base_score = sum(base_values) / len(base_values) if base_values else 0.0

        base_weight = weights.get("base", {}).get("weight", 0.4)
        final_score = base_score * base_weight

        return FactorScore(
            factor_key=self.factor_key,
            factor_name=self.factor_name,
            score=round(final_score, 2),
            max_score=100.0,
            weight=self.default_weight,
            details={
                "base_score": round(base_score, 2),
                "base_weight": base_weight,
                "trend_score": 0.0,
                "trend_weight": weights.get("trend", {}).get("weight", 0.35),
                "safety_score": 0.0,
                "safety_weight": weights.get("safety", {}).get("weight", 0.25),
            },
            confidence=0.8,
        )
