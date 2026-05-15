from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from sentinel.config import AppSettings
from sentinel.domain.models import Market
from sentinel.mgfs.data.valuation_fetcher import MockValuationFetcher, ValuationFetcher
from sentinel.mgfs.factor_plugin import TargetInfo
from sentinel.mgfs.plugins.valuation import ValuationFactorPlugin


SAMPLE_CONFIG: dict[str, Any] = {
    "version": "1.0",
    "last_updated": "2026-05-15",
    "description": "MGFS Module B — 估值范式路由与击球区定义",
    "archetypes": {
        "traditional_growth": {
            "label": "传统价值成长",
            "metrics": {
                "primary": {"name": "PE_TTM", "weight": 0.50},
                "secondary": {"name": "PEG", "weight": 0.30},
                "warning": {"name": "Dividend_Yield", "weight": 0.20},
            },
            "zones": {
                "strong_buy": {"percentile_max": 20, "score_range": [90, 100]},
                "accumulate": {"percentile_max": 40, "score_range": [75, 90]},
                "hold": {"percentile_max": 70, "score_range": [50, 75]},
                "avoid": {"percentile_max": 100, "score_range": [0, 50]},
            },
            "circuit_breakers": {"hard_veto_percentile": 90},
        },
        "heavy_asset_cyclical": {
            "label": "重资产与强周期",
            "metrics": {
                "primary": {"name": "PB", "weight": 0.50},
                "secondary": {"name": "ROE", "weight": 0.30},
                "warning": {"name": "Operating_CF_Yield", "weight": 0.20},
            },
            "zones": {
                "strong_buy": {"percentile_max": 15, "score_range": [90, 100]},
                "accumulate": {"percentile_max": 30, "score_range": [75, 90]},
                "hold": {"percentile_max": 65, "score_range": [50, 75]},
                "avoid": {"percentile_max": 100, "score_range": [0, 50]},
            },
            "circuit_breakers": {"hard_veto_percentile": 85},
        },
    },
    "sector_to_archetype": {
        "白酒": "traditional_growth",
        "银行": "heavy_asset_cyclical",
        "煤炭": "heavy_asset_cyclical",
        "有色金属": "heavy_asset_cyclical",
    },
    "default_archetype": "traditional_growth",
    "override_archetypes": {},
}


def _write_config(settings: AppSettings, config: dict[str, Any]) -> Path:
    path = settings.config_dir / "valuation_sector_routing.yaml"
    path.write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")
    return path


class TestValuationPluginEvaluatesWithMockFetcher:
    def test_valuation_plugin_evaluates_with_mock_fetcher(self, settings: AppSettings) -> None:
        _write_config(settings, SAMPLE_CONFIG)
        config_path = settings.config_dir / "valuation_sector_routing.yaml"
        plugin = ValuationFactorPlugin(config_path=config_path, fetcher=MockValuationFetcher(seed=42))
        target = TargetInfo(symbol="000858", market=Market.A_SHARE, asset_class="stock", sector="白酒")

        score = plugin.evaluate(target)

        assert score.factor_key == "valuation"
        assert score.factor_name == "估值水位"
        assert score.weight == 0.2
        assert 0 <= score.score <= 100
        assert score.details["archetype"] == "传统价值成长"
        assert score.details["primary_metric"] == "PE_TTM"
        assert score.confidence >= 0.6


class TestValuationPluginBankUsesPB:
    def test_valuation_plugin_bank_uses_pb(self, settings: AppSettings) -> None:
        _write_config(settings, SAMPLE_CONFIG)
        config_path = settings.config_dir / "valuation_sector_routing.yaml"
        plugin = ValuationFactorPlugin(config_path=config_path, fetcher=MockValuationFetcher(seed=42))
        target = TargetInfo(symbol="600036", market=Market.A_SHARE, asset_class="stock", sector="银行")

        score = plugin.evaluate(target)

        assert score.details["primary_metric"] == "PB"
        assert score.details["archetype"] == "重资产与强周期"


class NegativePEFetcher(ValuationFetcher):
    def fetch_history(self, symbol: str, market: Market, metric: str, years: int = 5) -> list[float]:
        days = years * 250
        values = [15.0] * (days - 1) + [-5.0]
        return values


class TestValuationPluginNegativePEReturnsInvalidZone:
    def test_valuation_plugin_negative_pe_returns_invalid_zone(self, settings: AppSettings) -> None:
        _write_config(settings, SAMPLE_CONFIG)
        config_path = settings.config_dir / "valuation_sector_routing.yaml"
        plugin = ValuationFactorPlugin(config_path=config_path, fetcher=NegativePEFetcher())
        target = TargetInfo(symbol="000001", market=Market.A_SHARE, asset_class="stock", sector="白酒")

        score = plugin.evaluate(target)

        assert score.score == 0.0
        assert score.details["zone"] == "invalid"
        assert score.confidence < 0.5
        assert any("亏损" in w or "invalid" in w.lower() for w in score.warnings)
