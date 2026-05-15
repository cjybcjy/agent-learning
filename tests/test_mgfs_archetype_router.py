from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml

from sentinel.config import AppSettings
from sentinel.mgfs.archetype_router import ArchetypeRouter


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


def _write_config(settings: AppSettings, config: dict[str, Any]) -> None:
    path = settings.config_dir / "valuation_sector_routing.yaml"
    path.write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")


class TestRouterResolvesSectorToArchetype:
    def test_baijiu_traditional_growth(self, settings: AppSettings) -> None:
        _write_config(settings, SAMPLE_CONFIG)
        router = ArchetypeRouter(settings.config_dir / "valuation_sector_routing.yaml")
        result = router.resolve_archetype("000858", "白酒")
        assert result["label"] == "传统价值成长"
        assert result["metrics"]["primary"]["name"] == "PE_TTM"

    def test_bank_heavy_asset_cyclical(self, settings: AppSettings) -> None:
        _write_config(settings, SAMPLE_CONFIG)
        router = ArchetypeRouter(settings.config_dir / "valuation_sector_routing.yaml")
        result = router.resolve_archetype("600036", "银行")
        assert result["label"] == "重资产与强周期"
        assert result["metrics"]["primary"]["name"] == "PB"


class TestRouterOverrideTakesPriority:
    def test_override_ignores_sector(self, settings: AppSettings) -> None:
        config = SAMPLE_CONFIG.copy()
        config["override_archetypes"] = {
            "601899": {
                "archetype": "heavy_asset_cyclical",
                "effective_until": (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d"),
            }
        }
        _write_config(settings, config)
        router = ArchetypeRouter(settings.config_dir / "valuation_sector_routing.yaml")
        result = router.resolve_archetype("601899", "银行")
        assert result["label"] == "重资产与强周期"
        assert result["metrics"]["primary"]["name"] == "PB"


class TestRouterExpiredOverrideIgnored:
    def test_expired_override_falls_back_to_sector(self, settings: AppSettings) -> None:
        config = SAMPLE_CONFIG.copy()
        config["override_archetypes"] = {
            "601899": {
                "archetype": "heavy_asset_cyclical",
                "effective_until": "2025-01-01",
            }
        }
        _write_config(settings, config)
        router = ArchetypeRouter(settings.config_dir / "valuation_sector_routing.yaml")
        result = router.resolve_archetype("601899", "银行")
        assert result["label"] == "重资产与强周期"
        assert result["metrics"]["primary"]["name"] == "PB"


class TestRouterUnknownSectorReturnsDefault:
    def test_empty_sector_map_unknown_sector(self, settings: AppSettings) -> None:
        config = SAMPLE_CONFIG.copy()
        config["sector_to_archetype"] = {}
        _write_config(settings, config)
        router = ArchetypeRouter(settings.config_dir / "valuation_sector_routing.yaml")
        result = router.resolve_archetype("999999", "未知行业")
        assert result["label"] == "传统价值成长"
        assert result["metrics"]["primary"]["name"] == "PE_TTM"
