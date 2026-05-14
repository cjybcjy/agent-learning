from __future__ import annotations

from pathlib import Path

import yaml

from sentinel.mgfs.factor_plugin import BaseFactorPlugin, FactorScore, TargetInfo


class PolicyFactorPlugin(BaseFactorPlugin):
    factor_key = "policy"
    factor_name = "国策环境"
    default_weight = 0.0

    def __init__(self, config_path: Path | None = None) -> None:
        self.config_path = config_path
        self._config: dict | None = None

    def _load_config(self) -> dict:
        if self._config is not None:
            return self._config
        if self.config_path is None or not self.config_path.exists():
            return {"default_multiplier": 1.0, "sectors": {}, "overrides": {}}
        with self.config_path.open("r", encoding="utf-8") as handle:
            self._config = yaml.safe_load(handle) or {}
        return self._config

    def evaluate(self, target: TargetInfo) -> FactorScore:
        cfg = self._load_config()
        default = float(cfg.get("default_multiplier", 1.0))

        # 1. Symbol override
        override = cfg.get("overrides", {}).get(target.symbol, {})
        multiplier = override.get("multiplier")
        note = override.get("note", "")

        # 2. Sector lookup
        if multiplier is None and target.sector:
            sector_cfg = cfg.get("sectors", {}).get(target.sector, {})
            multiplier = sector_cfg.get("multiplier")
            note = sector_cfg.get("note", "")

        # 3. Default fallback
        if multiplier is None:
            multiplier = default
            note = ""

        return FactorScore(
            factor_key=self.factor_key,
            factor_name=self.factor_name,
            score=round(multiplier * 100, 2),
            max_score=100.0,
            weight=self.default_weight,
            details={
                "multiplier": multiplier,
                "policy_rating": self._rating_from_multiplier(multiplier),
                "note": note,
            },
            confidence=1.0,
        )

    @staticmethod
    def _rating_from_multiplier(multiplier: float) -> str:
        mapping = [
            (1.2, "core_support"),
            (1.1, "favorable"),
            (1.0, "neutral"),
            (0.8, "transition"),
            (0.6, "restricted"),
        ]
        for threshold, rating in mapping:
            if multiplier >= threshold:
                return rating
        return "hard_restricted"
