from __future__ import annotations

from pathlib import Path
from typing import Any

from sentinel.mgfs.archetype_router import ArchetypeRouter
from sentinel.mgfs.data.valuation_fetcher import MockValuationFetcher, ValuationFetcher
from sentinel.mgfs.factor_plugin import BaseFactorPlugin, FactorScore, TargetInfo
from sentinel.mgfs.percentile_engine import PercentileEngine
from sentinel.mgfs.zone_mapper import ZoneMapper


class ValuationFactorPlugin(BaseFactorPlugin):
    factor_key = "valuation"
    factor_name = "估值水位"
    default_weight = 0.2

    def __init__(
        self,
        config_path: Path | None = None,
        fetcher: ValuationFetcher | None = None,
    ) -> None:
        self._router = ArchetypeRouter(config_path)
        self._engine = PercentileEngine()
        self._mapper = ZoneMapper()
        self._fetcher = fetcher if fetcher is not None else MockValuationFetcher()

    def evaluate(self, target: TargetInfo) -> FactorScore:
        archetype = self._router.resolve_archetype(target.symbol, target.sector)
        if not archetype:
            return FactorScore(
                factor_key=self.factor_key,
                factor_name=self.factor_name,
                score=0.0,
                weight=self.default_weight,
                confidence=0.0,
                warnings=["估值范式路由失败"],
            )

        primary_metric = archetype["metrics"]["primary"]["name"]
        secondary_metric = archetype["metrics"].get("secondary", {}).get("name")

        history = self._fetcher.fetch_history(
            target.symbol, target.market, primary_metric, years=5
        )
        data_points = len(history)

        percentile = self._engine.compute_percentile(history)
        score, zone = self._mapper.map_percentile(percentile, archetype)

        warnings: list[str] = []
        if percentile < 0:
            warnings.append(
                "标的处于亏损状态，PE 指标失效，建议切换至 PS/PB 评估"
            )

        if zone == "avoid":
            hard_veto = archetype.get("circuit_breakers", {}).get(
                "hard_veto_percentile", 90
            )
            label = archetype.get("label", "")
            warnings.append(
                f"当前估值处于历史 {percentile:.1f}% 分位，接近 {label} 危险区域"
                f"（一票否决线: {hard_veto}%）"
            )

        if data_points < 500:
            warnings.append(
                f"历史数据仅 {data_points} 个交易日，百分位可靠性较低"
            )

        if percentile < 0:
            confidence = 0.3
        elif data_points >= 1000:
            confidence = 0.9
        elif data_points >= 500:
            confidence = 0.85
        elif data_points >= 250:
            confidence = 0.7
        else:
            confidence = 0.5

        current_value = history[-1] if history else None
        valid_history = [v for v in history if v >= 0]

        details: dict[str, Any] = {
            "archetype": archetype.get("label"),
            "primary_metric": primary_metric,
            "primary_percentile": percentile,
            "secondary_metric": secondary_metric,
            "zone": zone,
            "history_span_years": 5,
            "data_points": data_points,
            "current_value": current_value,
            "history_min": min(valid_history) if valid_history else None,
            "history_max": max(valid_history) if valid_history else None,
            "history_median": sorted(valid_history)[len(valid_history) // 2]
            if valid_history
            else None,
        }

        return FactorScore(
            factor_key=self.factor_key,
            factor_name=self.factor_name,
            score=score,
            weight=self.default_weight,
            details=details,
            confidence=confidence,
            warnings=warnings,
        )
