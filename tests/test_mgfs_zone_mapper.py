from __future__ import annotations

import pytest

from sentinel.mgfs.zone_mapper import ZoneMapper


traditional_growth = {
    "label": "传统价值成长",
    "zones": {
        "strong_buy":  {"percentile_max": 20, "score_range": [90, 100]},
        "accumulate":  {"percentile_max": 40, "score_range": [75, 90]},
        "hold":        {"percentile_max": 70, "score_range": [50, 75]},
        "avoid":       {"percentile_max": 100, "score_range": [0, 50]},
    },
    "circuit_breakers": {"hard_veto_percentile": 90},
}

heavy_asset_cyclical = {
    "label": "重资产周期",
    "zones": {
        "strong_buy":  {"percentile_max": 15, "score_range": [75, 90]},
        "accumulate":  {"percentile_max": 30, "score_range": [60, 75]},
        "hold":        {"percentile_max": 65, "score_range": [40, 60]},
        "avoid":       {"percentile_max": 100, "score_range": [0, 40]},
    },
    "circuit_breakers": {"hard_veto_percentile": 85},
}


def test_mapper_traditional_growth_strong_buy():
    mapper = ZoneMapper()
    score, zone = mapper.map_percentile(10, traditional_growth)
    assert zone == "strong_buy"
    assert 90 <= score <= 100


def test_mapper_traditional_growth_accumulate():
    mapper = ZoneMapper()
    score, zone = mapper.map_percentile(30, traditional_growth)
    assert zone == "accumulate"
    assert 75 <= score <= 90


def test_mapper_traditional_growth_avoid():
    mapper = ZoneMapper()
    score, zone = mapper.map_percentile(80, traditional_growth)
    assert zone == "avoid"
    assert 0 <= score <= 50


def test_mapper_cyclical_strong_buy_threshold_lower():
    mapper = ZoneMapper()
    score1, zone1 = mapper.map_percentile(10, heavy_asset_cyclical)
    assert zone1 == "strong_buy"

    score2, zone2 = mapper.map_percentile(18, heavy_asset_cyclical)
    assert zone2 == "accumulate"


def test_mapper_invalid_sentinel_returns_zero():
    mapper = ZoneMapper()
    score, zone = mapper.map_percentile(-1.0, traditional_growth)
    assert zone == "invalid"
    assert score == 0.0
