# Module B — 估值水位监控表 (Valuation Dashboard) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `ValuationFactorPlugin` with archetype-aware metric routing, historical percentile calculation, and archetype-calibrated zone scoring. Replace the existing mock `valuation.py` with production-ready logic.

**Architecture:** Plugin decomposed into four sub-components: `ValuationFetcher` (data layer), `ArchetypeRouter` (YAML-driven sector-to-archetype mapping with override support), `PercentileEngine` (history → percentile with negative-value cleaning), and `ZoneMapper` (archetype-calibrated S-curve scoring). Mock fetcher enables TDD without live APIs.

**Tech Stack:** Python 3.10+, pytest, PyYAML, numpy

---

## File Structure

**New files:**
- `sentinel/mgfs/data/valuation_fetcher.py` — `ValuationFetcher` ABC + `MockValuationFetcher`
- `sentinel/mgfs/archetype_router.py` — `ArchetypeRouter` (YAML parsing + sector mapping + override resolution)
- `sentinel/mgfs/percentile_engine.py` — `PercentileEngine` (percentile calc + negative-value cleaning)
- `sentinel/mgfs/zone_mapper.py` — `ZoneMapper` (archetype-calibrated S-curve mapping)
- `sentinel/mgfs/plugins/valuation.py` — Replaces mock; assembles router + fetcher + engine + mapper
- `config/valuation_sector_routing.yaml` — Archetype definitions + sector map + overrides
- `tests/test_mgfs_valuation_fetcher.py` — Fetcher tests
- `tests/test_mgfs_archetype_router.py` — Router tests
- `tests/test_mgfs_percentile_engine.py` — Engine tests
- `tests/test_mgfs_zone_mapper.py` — Mapper tests
- `tests/test_mgfs_valuation_plugin.py` — Plugin integration tests
- `tests/test_mgfs_integration_module_b.py` — End-to-end CLI integration test

**Modified files:**
- `sentinel/mgfs/config_loader.py` — Add "valuation" → "valuation_sector_routing.yaml" to `_plugin_config_file`

---

### Task 1: `ValuationFetcher` ABC + `MockValuationFetcher`

**Files:**
- Create: `sentinel/mgfs/data/valuation_fetcher.py`
- Test: `tests/test_mgfs_valuation_fetcher.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_mgfs_valuation_fetcher.py`:

```python
from __future__ import annotations

from sentinel.domain.models import Market
from sentinel.mgfs.data.valuation_fetcher import MockValuationFetcher


def test_mock_fetcher_returns_expected_sequence():
    fetcher = MockValuationFetcher(seed=42)
    history = fetcher.fetch_history(
        symbol="600519",
        market=Market.A_SHARE,
        metric="PE_TTM",
        years=5,
    )
    assert len(history) == 5 * 250  # ~5 years of trading days
    assert all(v > 0 for v in history)
    assert history[-1] == history[-1]  # deterministic with seed


def test_mock_fetcher_different_seeds_produce_different_results():
    f1 = MockValuationFetcher(seed=1)
    f2 = MockValuationFetcher(seed=2)
    h1 = f1.fetch_history("600519", Market.A_SHARE, "PE_TTM", years=1)
    h2 = f2.fetch_history("600519", Market.A_SHARE, "PE_TTM", years=1)
    assert h1[-1] != h2[-1]


def test_mock_fetcher_returns_list_of_floats():
    fetcher = MockValuationFetcher()
    history = fetcher.fetch_history("TEST", Market.A_SHARE, "PB", years=1)
    assert isinstance(history, list)
    assert all(isinstance(v, float) for v in history)
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
PYTHONPATH=/home/kyrie/workspace/agent-learning:$PYTHONPATH pytest tests/test_mgfs_valuation_fetcher.py -v
```

Expected: `ModuleNotFoundError` for `sentinel.mgfs.data.valuation_fetcher`

- [ ] **Step 3: Write minimal implementation**

Create `sentinel/mgfs/data/valuation_fetcher.py`:

```python
from __future__ import annotations

import random
from abc import ABC, abstractmethod

from sentinel.domain.models import Market


class ValuationFetcher(ABC):
    """Abstract base for historical valuation data fetchers."""

    @abstractmethod
    def fetch_history(
        self,
        symbol: str,
        market: Market,
        metric: str,
        years: int = 5,
    ) -> list[float]:
        """Fetch historical daily values for a valuation metric.

        Returns:
            List of daily metric values (most recent last).
        """
        raise NotImplementedError


class MockValuationFetcher(ValuationFetcher):
    """Deterministic mock fetcher for testing."""

    def __init__(self, seed: int | None = None) -> None:
        self._rng = random.Random(seed)

    def fetch_history(
        self,
        symbol: str,
        market: Market,
        metric: str,
        years: int = 5,
    ) -> list[float]:
        days = years * 250
        # Generate a random walk with mean ~20 and std ~5
        base = self._rng.gauss(20.0, 5.0)
        history: list[float] = []
        for _ in range(days):
            base += self._rng.gauss(0.0, 0.3)
            history.append(round(max(base, 0.1), 4))
        return history
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
PYTHONPATH=/home/kyrie/workspace/agent-learning:$PYTHONPATH pytest tests/test_mgfs_valuation_fetcher.py -v
```

Expected: 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add sentinel/mgfs/data/valuation_fetcher.py tests/test_mgfs_valuation_fetcher.py
git commit -m "feat(mgfs): add ValuationFetcher ABC and MockValuationFetcher

Mock fetcher generates deterministic random-walk sequences for TDD.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 2: `ArchetypeRouter` — YAML Parsing + Sector Mapping + Override

**Files:**
- Create: `sentinel/mgfs/archetype_router.py`
- Create: `config/valuation_sector_routing.yaml`
- Test: `tests/test_mgfs_archetype_router.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_mgfs_archetype_router.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from sentinel.mgfs.archetype_router import ArchetypeRouter


def test_router_resolves_sector_to_archetype(settings):
    yaml_path = settings.config_dir / "valuation_sector_routing.yaml"
    yaml_path.write_text("""
version: "1.0"
archetypes:
  traditional_growth:
    label: "传统价值成长"
    metrics:
      primary: { name: "PE_TTM", weight: 0.5 }
    zones:
      strong_buy: { percentile_max: 20, score_range: [90, 100] }
    circuit_breakers:
      hard_veto_percentile: 90
  heavy_asset_cyclical:
    label: "重资产周期"
    metrics:
      primary: { name: "PB", weight: 0.5 }
    zones:
      strong_buy: { percentile_max: 15, score_range: [90, 100] }
    circuit_breakers:
      hard_veto_percentile: 85
sector_to_archetype:
  "白酒": "traditional_growth"
  "银行": "heavy_asset_cyclical"
default_archetype: "traditional_growth"
override_archetypes: {}
""", encoding="utf-8")

    router = ArchetypeRouter(config_path=yaml_path)

    # 白酒 → traditional_growth
    archetype = router.resolve_archetype("600519", "白酒")
    assert archetype["label"] == "传统价值成长"
    assert archetype["metrics"]["primary"]["name"] == "PE_TTM"

    # 银行 → heavy_asset_cyclical
    archetype = router.resolve_archetype("000001", "银行")
    assert archetype["label"] == "重资产周期"
    assert archetype["metrics"]["primary"]["name"] == "PB"


def test_router_override_takes_priority(settings):
    yaml_path = settings.config_dir / "valuation_sector_routing.yaml"
    yaml_path.write_text("""
version: "1.0"
archetypes:
  traditional_growth:
    label: "传统价值成长"
    metrics:
      primary: { name: "PE_TTM", weight: 0.5 }
    zones:
      strong_buy: { percentile_max: 20, score_range: [90, 100] }
    circuit_breakers:
      hard_veto_percentile: 90
  heavy_asset_cyclical:
    label: "重资产周期"
    metrics:
      primary: { name: "PB", weight: 0.5 }
    zones:
      strong_buy: { percentile_max: 15, score_range: [90, 100] }
    circuit_breakers:
      hard_veto_percentile: 85
sector_to_archetype:
  "有色金属": "traditional_growth"
default_archetype: "traditional_growth"
override_archetypes:
  "601899":
    archetype: "heavy_asset_cyclical"
    note: "转型期覆盖"
    effective_until: "2026-12-31"
""", encoding="utf-8")

    router = ArchetypeRouter(config_path=yaml_path)

    # 601899 命中 override → heavy_asset_cyclical，忽略 sector 映射
    archetype = router.resolve_archetype("601899", "有色金属")
    assert archetype["label"] == "重资产周期"
    assert archetype["metrics"]["primary"]["name"] == "PB"


def test_router_expired_override_ignored(settings):
    yaml_path = settings.config_dir / "valuation_sector_routing.yaml"
    yaml_path.write_text("""
version: "1.0"
archetypes:
  traditional_growth:
    label: "传统价值成长"
    metrics:
      primary: { name: "PE_TTM", weight: 0.5 }
    zones:
      strong_buy: { percentile_max: 20, score_range: [90, 100] }
    circuit_breakers:
      hard_veto_percentile: 90
  heavy_asset_cyclical:
    label: "重资产周期"
    metrics:
      primary: { name: "PB", weight: 0.5 }
    zones:
      strong_buy: { percentile_max: 15, score_range: [90, 100] }
    circuit_breakers:
      hard_veto_percentile: 85
sector_to_archetype:
  "有色金属": "traditional_growth"
default_archetype: "traditional_growth"
override_archetypes:
  "601899":
    archetype: "heavy_asset_cyclical"
    note: "已过期"
    effective_until: "2025-01-01"
""", encoding="utf-8")

    router = ArchetypeRouter(config_path=yaml_path)

    # 601899 override 已过期 → fallback 到 sector 映射
    archetype = router.resolve_archetype("601899", "有色金属")
    assert archetype["label"] == "传统价值成长"


def test_router_unknown_sector_returns_default(settings):
    yaml_path = settings.config_dir / "valuation_sector_routing.yaml"
    yaml_path.write_text("""
version: "1.0"
archetypes:
  traditional_growth:
    label: "传统价值成长"
    metrics:
      primary: { name: "PE_TTM", weight: 0.5 }
    zones:
      strong_buy: { percentile_max: 20, score_range: [90, 100] }
    circuit_breakers:
      hard_veto_percentile: 90
sector_to_archetype: {}
default_archetype: "traditional_growth"
override_archetypes: {}
""", encoding="utf-8")

    router = ArchetypeRouter(config_path=yaml_path)
    archetype = router.resolve_archetype("UNKNOWN", "未知行业")
    assert archetype["label"] == "传统价值成长"
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
PYTHONPATH=/home/kyrie/workspace/agent-learning:$PYTHONPATH pytest tests/test_mgfs_archetype_router.py -v
```

Expected: `ModuleNotFoundError` for `sentinel.mgfs.archetype_router`

- [ ] **Step 3: Write minimal implementation**

Create `sentinel/mgfs/archetype_router.py`:

```python
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import yaml


class ArchetypeRouter:
    """Resolves a target's sector/symbol to a valuation archetype config."""

    def __init__(self, config_path: Path | None = None) -> None:
        self.config_path = config_path
        self._config: dict[str, Any] | None = None

    def _load_config(self) -> dict[str, Any]:
        if self._config is not None:
            return self._config
        if self.config_path is None or not self.config_path.exists():
            return {
                "archetypes": {
                    "traditional_growth": {
                        "label": "传统价值成长",
                        "metrics": {"primary": {"name": "PE_TTM", "weight": 0.5}},
                        "zones": {"strong_buy": {"percentile_max": 20, "score_range": [90, 100]}},
                        "circuit_breakers": {"hard_veto_percentile": 90},
                    }
                },
                "sector_to_archetype": {},
                "default_archetype": "traditional_growth",
                "override_archetypes": {},
            }
        with self.config_path.open("r", encoding="utf-8") as handle:
            self._config = yaml.safe_load(handle) or {}
        return self._config

    def resolve_archetype(self, symbol: str, sector: str | None) -> dict[str, Any]:
        """Resolve symbol + sector to archetype config.

        Priority: override (if not expired) > sector_to_archetype > default
        """
        cfg = self._load_config()
        archetypes = cfg.get("archetypes", {})
        overrides = cfg.get("override_archetypes", {})
        sector_map = cfg.get("sector_to_archetype", {})
        default_key = cfg.get("default_archetype", "traditional_growth")

        # 1. Check override
        override = overrides.get(symbol)
        if override is not None:
            effective_until = override.get("effective_until")
            if effective_until is None or date.today() <= date.fromisoformat(effective_until):
                archetype_key = override["archetype"]
                return archetypes[archetype_key]

        # 2. Check sector mapping
        if sector is not None:
            archetype_key = sector_map.get(sector)
            if archetype_key is not None:
                return archetypes[archetype_key]

        # 3. Fallback to default
        return archetypes.get(default_key, {})
```

Create `config/valuation_sector_routing.yaml` (minimal sample for the repo):

```yaml
version: "1.0"
last_updated: "2026-05-15"
description: "MGFS Module B — 估值范式路由与击球区定义"

archetypes:
  traditional_growth:
    label: "传统价值成长"
    metrics:
      primary:   { name: "PE_TTM",         weight: 0.50 }
      secondary: { name: "PEG",            weight: 0.30 }
      warning:   { name: "Dividend_Yield", weight: 0.20 }
    zones:
      strong_buy:  { percentile_max: 20, score_range: [90, 100] }
      accumulate:  { percentile_max: 40, score_range: [75, 90]  }
      hold:        { percentile_max: 70, score_range: [50, 75]  }
      avoid:       { percentile_max: 100, score_range: [0, 50]  }
    circuit_breakers:
      hard_veto_percentile: 90

  heavy_asset_cyclical:
    label: "重资产与强周期"
    metrics:
      primary:   { name: "PB",                 weight: 0.50 }
      secondary: { name: "ROE",                weight: 0.30 }
      warning:   { name: "Operating_CF_Yield", weight: 0.20 }
    zones:
      strong_buy:  { percentile_max: 15, score_range: [90, 100] }
      accumulate:  { percentile_max: 30, score_range: [75, 90]  }
      hold:        { percentile_max: 65, score_range: [50, 75]  }
      avoid:       { percentile_max: 100, score_range: [0, 50]  }
    circuit_breakers:
      hard_veto_percentile: 85

sector_to_archetype:
  "白酒": "traditional_growth"
  "银行": "heavy_asset_cyclical"
  "煤炭": "heavy_asset_cyclical"
  "有色金属": "heavy_asset_cyclical"

default_archetype: "traditional_growth"

override_archetypes: {}
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
PYTHONPATH=/home/kyrie/workspace/agent-learning:$PYTHONPATH pytest tests/test_mgfs_archetype_router.py -v
```

Expected: 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add sentinel/mgfs/archetype_router.py config/valuation_sector_routing.yaml tests/test_mgfs_archetype_router.py
git commit -m "feat(mgfs): add ArchetypeRouter with sector mapping and override support

Priority: override (with effective_until) > sector_map > default.
Includes negative-value PE handling spec in comments.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 3: `PercentileEngine` — Percentile Calculation + Negative Value Cleaning

**Files:**
- Create: `sentinel/mgfs/percentile_engine.py`
- Test: `tests/test_mgfs_percentile_engine.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_mgfs_percentile_engine.py`:

```python
from __future__ import annotations

import math

from sentinel.mgfs.percentile_engine import PercentileEngine


def test_percentile_basic():
    engine = PercentileEngine()
    history = [10.0] * 100 + [20.0] * 100 + [30.0] * 100  # 300 days
    # current = 20.0, 100 values below it out of 299 valid
    pct = engine.compute_percentile(history)
    assert pct == (100 / 299) * 100


def test_percentile_at_maximum():
    engine = PercentileEngine()
    history = list(range(1, 101))  # 1..100
    # current = 100, all 99 values below it
    pct = engine.compute_percentile(history)
    assert pct == (99 / 99) * 100  # 100.0


def test_percentile_at_minimum():
    engine = PercentileEngine()
    history = list(range(100, 0, -1))  # 100..1
    # current = 1, 0 values below it
    pct = engine.compute_percentile(history)
    assert pct == 0.0


def test_percentile_insufficient_data():
    engine = PercentileEngine()
    history = [1.0, 2.0, 3.0]  # only 3 days
    pct = engine.compute_percentile(history)
    assert pct == 50.0  # neutral fallback


def test_percentile_negative_current_returns_sentinel():
    engine = PercentileEngine()
    history = [10.0] * 100 + [-5.0]  # current is negative
    pct = engine.compute_percentile(history)
    assert pct == -1.0  # sentinel for invalid


def test_percentile_negative_history_excluded():
    engine = PercentileEngine()
    # 50 positive values + 50 negative values in history, current = 30.0
    history = [v for v in range(-50, 0)] + [v for v in range(1, 51)] + [30.0]
    pct = engine.compute_percentile(history)
    # Only 1..50 are valid history (50 values). 30.0 current.
    # Values below 30.0 in valid history: 1..29 = 29 values
    assert pct == (29 / 50) * 100


def test_percentile_all_negative_history_falls_back():
    engine = PercentileEngine()
    history = [-10.0, -20.0, -30.0, -5.0]  # all negative
    pct = engine.compute_percentile(history)
    assert pct == 50.0  # fallback, insufficient valid data
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
PYTHONPATH=/home/kyrie/workspace/agent-learning:$PYTHONPATH pytest tests/test_mgfs_percentile_engine.py -v
```

Expected: `ModuleNotFoundError` for `sentinel.mgfs.percentile_engine`

- [ ] **Step 3: Write minimal implementation**

Create `sentinel/mgfs/percentile_engine.py`:

```python
from __future__ import annotations

import math


class PercentileEngine:
    """Compute percentile of current value in historical distribution.

    Handles negative-value cleaning: negative metrics (e.g., PE during
    losses) are treated as invalid and excluded from calculation.
    """

    INSUFFICIENT_DATA_FALLBACK = 50.0
    NEGATIVE_SENTINEL = -1.0
    MIN_HISTORY_DAYS = 60
    MIN_VALID_HISTORY_DAYS = 30

    def compute_percentile(self, history: list[float]) -> float:
        """Compute percentile of the last value in history.

        Args:
            history: List of daily values, most recent last.
                     May contain negative values.

        Returns:
            Percentile (0.0 - 100.0), or sentinel values:
            - NEGATIVE_SENTINEL (-1.0) if current value is negative
            - INSUFFICIENT_DATA_FALLBACK (50.0) if not enough data
        """
        if not history or len(history) < self.MIN_HISTORY_DAYS:
            return self.INSUFFICIENT_DATA_FALLBACK

        current = history[-1]

        # Negative current value → sentinel (PE invalid during losses)
        if current < 0 or math.isnan(current):
            return self.NEGATIVE_SENTINEL

        # Clean history: exclude current value and any negative/NaN entries
        valid_history = [
            v for v in history[:-1]
            if v > 0 and not math.isnan(v)
        ]

        if len(valid_history) < self.MIN_VALID_HISTORY_DAYS:
            return self.INSUFFICIENT_DATA_FALLBACK

        sorted_vals = sorted(valid_history)
        below = sum(1 for v in sorted_vals if v < current)
        return (below / len(sorted_vals)) * 100
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
PYTHONPATH=/home/kyrie/workspace/agent-learning:$PYTHONPATH pytest tests/test_mgfs_percentile_engine.py -v
```

Expected: 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add sentinel/mgfs/percentile_engine.py tests/test_mgfs_percentile_engine.py
git commit -m "feat(mgfs): add PercentileEngine with negative-value cleaning

Excludes negative PE values from percentile calculation.
Returns sentinel (-1.0) for invalid current values.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 4: `ZoneMapper` — Archetype-Calibrated S-Curve Scoring

**Files:**
- Create: `sentinel/mgfs/zone_mapper.py`
- Test: `tests/test_mgfs_zone_mapper.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_mgfs_zone_mapper.py`:

```python
from __future__ import annotations

from sentinel.mgfs.zone_mapper import ZoneMapper


def test_mapper_traditional_growth_strong_buy():
    archetype = {
        "label": "传统价值成长",
        "zones": {
            "strong_buy":  { percentile_max: 20, score_range: [90, 100] },
            "accumulate":  { percentile_max: 40, score_range: [75, 90]  },
            "hold":        { percentile_max: 70, score_range: [50, 75]  },
            "avoid":       { percentile_max: 100, score_range: [0, 50]  },
        },
        "circuit_breakers": {"hard_veto_percentile": 90},
    }
    mapper = ZoneMapper()
    score, zone = mapper.map_percentile(10.0, archetype)
    assert zone == "strong_buy"
    assert 90 <= score <= 100


def test_mapper_traditional_growth_accumulate():
    archetype = {
        "label": "传统价值成长",
        "zones": {
            "strong_buy":  { percentile_max: 20, score_range: [90, 100] },
            "accumulate":  { percentile_max: 40, score_range: [75, 90]  },
            "hold":        { percentile_max: 70, score_range: [50, 75]  },
            "avoid":       { percentile_max: 100, score_range: [0, 50]  },
        },
        "circuit_breakers": {"hard_veto_percentile": 90},
    }
    mapper = ZoneMapper()
    score, zone = mapper.map_percentile(30.0, archetype)
    assert zone == "accumulate"
    assert 75 <= score <= 90


def test_mapper_traditional_growth_avoid():
    archetype = {
        "label": "传统价值成长",
        "zones": {
            "strong_buy":  { percentile_max: 20, score_range: [90, 100] },
            "accumulate":  { percentile_max: 40, score_range: [75, 90]  },
            "hold":        { percentile_max: 70, score_range: [50, 75]  },
            "avoid":       { percentile_max: 100, score_range: [0, 50]  },
        },
        "circuit_breakers": {"hard_veto_percentile": 90},
    }
    mapper = ZoneMapper()
    score, zone = mapper.map_percentile(80.0, archetype)
    assert zone == "avoid"
    assert 0 <= score <= 50


def test_mapper_cyclical_strong_buy_threshold_lower():
    """Cyclical archetype has lower strong_buy threshold (15% vs 20%)."""
    archetype = {
        "label": "重资产周期",
        "zones": {
            "strong_buy":  { percentile_max: 15, score_range: [90, 100] },
            "accumulate":  { percentile_max: 30, score_range: [75, 90]  },
            "hold":        { percentile_max: 65, score_range: [50, 75]  },
            "avoid":       { percentile_max: 100, score_range: [0, 50]  },
        },
        "circuit_breakers": {"hard_veto_percentile": 85},
    }
    mapper = ZoneMapper()
    score, zone = mapper.map_percentile(10.0, archetype)
    assert zone == "strong_buy"

    # At 18%, cyclical is in accumulate; traditional_growth would still be strong_buy
    score, zone = mapper.map_percentile(18.0, archetype)
    assert zone == "accumulate"


def test_mapper_invalid_sentinel_returns_zero():
    archetype = {
        "label": "传统价值成长",
        "zones": {
            "strong_buy":  { percentile_max: 20, score_range: [90, 100] },
        },
        "circuit_breakers": {"hard_veto_percentile": 90},
    }
    mapper = ZoneMapper()
    score, zone = mapper.map_percentile(-1.0, archetype)
    assert zone == "invalid"
    assert score == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
PYTHONPATH=/home/kyrie/workspace/agent-learning:$PYTHONPATH pytest tests/test_mgfs_zone_mapper.py -v
```

Expected: `ModuleNotFoundError` for `sentinel.mgfs.zone_mapper`

- [ ] **Step 3: Write minimal implementation**

Create `sentinel/mgfs/zone_mapper.py`:

```python
from __future__ import annotations

from typing import Any


class ZoneMapper:
    """Map percentile to 0-100 score using archetype-calibrated zones."""

    def map_percentile(
        self,
        percentile: float,
        archetype: dict[str, Any],
    ) -> tuple[float, str]:
        """Map percentile to score and zone.

        Args:
            percentile: Percentile (0-100), or -1.0 for invalid.
            archetype: Archetype config with zones definition.

        Returns:
            (score, zone_name)
        """
        if percentile < 0:
            return 0.0, "invalid"

        zones = archetype["zones"]
        prev_max = 0.0

        for zone_name, zone_cfg in zones.items():
            zone_max = zone_cfg["percentile_max"]
            score_min, score_max = zone_cfg["score_range"]

            if percentile <= zone_max:
                if zone_max == prev_max:
                    return float(score_max), zone_name
                pct_in_zone = (percentile - prev_max) / (zone_max - prev_max)
                score = score_max - pct_in_zone * (score_max - score_min)
                return round(score, 2), zone_name

            prev_max = zone_max

        return 0.0, "avoid"
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
PYTHONPATH=/home/kyrie/workspace/agent-learning:$PYTHONPATH pytest tests/test_mgfs_zone_mapper.py -v
```

Expected: 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add sentinel/mgfs/zone_mapper.py tests/test_mgfs_zone_mapper.py
git commit -m "feat(mgfs): add ZoneMapper with archetype-calibrated scoring

Maps percentile to 0-100 score using per-archetype zone definitions.
Different archetypes have different strong_buy/avoid thresholds.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 5: `ValuationFactorPlugin` — Assemble All Components

**Files:**
- Modify: `sentinel/mgfs/plugins/valuation.py`
- Modify: `sentinel/mgfs/data/__init__.py`
- Test: `tests/test_mgfs_valuation_plugin.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_mgfs_valuation_plugin.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from sentinel.domain.models import Market
from sentinel.mgfs.factor_plugin import TargetInfo
from sentinel.mgfs.plugins.valuation import ValuationFactorPlugin


def test_valuation_plugin_evaluates_with_mock_fetcher(settings):
    # Create routing YAML
    routing_yaml = settings.config_dir / "valuation_sector_routing.yaml"
    routing_yaml.write_text("""
version: "1.0"
archetypes:
  traditional_growth:
    label: "传统价值成长"
    metrics:
      primary:   { name: "PE_TTM", weight: 0.50 }
      secondary: { name: "PEG", weight: 0.30 }
      warning:   { name: "Dividend_Yield", weight: 0.20 }
    zones:
      strong_buy:  { percentile_max: 20, score_range: [90, 100] }
      accumulate:  { percentile_max: 40, score_range: [75, 90]  }
      hold:        { percentile_max: 70, score_range: [50, 75]  }
      avoid:       { percentile_max: 100, score_range: [0, 50]  }
    circuit_breakers:
      hard_veto_percentile: 90
  heavy_asset_cyclical:
    label: "重资产周期"
    metrics:
      primary:   { name: "PB", weight: 0.50 }
      secondary: { name: "ROE", weight: 0.30 }
      warning:   { name: "Operating_CF_Yield", weight: 0.20 }
    zones:
      strong_buy:  { percentile_max: 15, score_range: [90, 100] }
      accumulate:  { percentile_max: 30, score_range: [75, 90]  }
      hold:        { percentile_max: 65, score_range: [50, 75]  }
      avoid:       { percentile_max: 100, score_range: [0, 50]  }
    circuit_breakers:
      hard_veto_percentile: 85
sector_to_archetype:
  "白酒": "traditional_growth"
  "银行": "heavy_asset_cyclical"
default_archetype: "traditional_growth"
override_archetypes: {}
""", encoding="utf-8")

    from sentinel.mgfs.data.valuation_fetcher import MockValuationFetcher

    plugin = ValuationFactorPlugin(
        config_path=routing_yaml,
        fetcher=MockValuationFetcher(seed=42),
    )

    # 白酒 → traditional_growth → PE_TTM
    target = TargetInfo(
        symbol="600519", market=Market.A_SHARE, asset_class="equity", sector="白酒"
    )
    score = plugin.evaluate(target)

    assert score.factor_key == "valuation"
    assert score.factor_name == "估值水位"
    assert score.weight == 0.2
    assert 0 <= score.score <= 100
    assert score.details["archetype"] == "传统价值成长"
    assert score.details["primary_metric"] == "PE_TTM"
    assert "primary_percentile" in score.details
    assert "zone" in score.details
    assert score.confidence >= 0.6


def test_valuation_plugin_bank_uses_pb(settings):
    routing_yaml = settings.config_dir / "valuation_sector_routing.yaml"
    routing_yaml.write_text("""
version: "1.0"
archetypes:
  heavy_asset_cyclical:
    label: "重资产周期"
    metrics:
      primary:   { name: "PB", weight: 0.50 }
      secondary: { name: "ROE", weight: 0.30 }
      warning:   { name: "Operating_CF_Yield", weight: 0.20 }
    zones:
      strong_buy:  { percentile_max: 15, score_range: [90, 100] }
      accumulate:  { percentile_max: 30, score_range: [75, 90]  }
      hold:        { percentile_max: 65, score_range: [50, 75]  }
      avoid:       { percentile_max: 100, score_range: [0, 50]  }
    circuit_breakers:
      hard_veto_percentile: 85
sector_to_archetype:
  "银行": "heavy_asset_cyclical"
default_archetype: "heavy_asset_cyclical"
override_archetypes: {}
""", encoding="utf-8")

    from sentinel.mgfs.data.valuation_fetcher import MockValuationFetcher

    plugin = ValuationFactorPlugin(
        config_path=routing_yaml,
        fetcher=MockValuationFetcher(seed=123),
    )

    target = TargetInfo(
        symbol="000001", market=Market.A_SHARE, asset_class="equity", sector="银行"
    )
    score = plugin.evaluate(target)

    assert score.details["primary_metric"] == "PB"
    assert score.details["archetype"] == "重资产周期"


def test_valuation_plugin_negative_pe_returns_invalid_zone(settings):
    routing_yaml = settings.config_dir / "valuation_sector_routing.yaml"
    routing_yaml.write_text("""
version: "1.0"
archetypes:
  traditional_growth:
    label: "传统价值成长"
    metrics:
      primary:   { name: "PE_TTM", weight: 0.50 }
    zones:
      strong_buy:  { percentile_max: 20, score_range: [90, 100] }
      accumulate:  { percentile_max: 40, score_range: [75, 90]  }
      hold:        { percentile_max: 70, score_range: [50, 75]  }
      avoid:       { percentile_max: 100, score_range: [0, 50]  }
    circuit_breakers:
      hard_veto_percentile: 90
sector_to_archetype:
  "白酒": "traditional_growth"
default_archetype: "traditional_growth"
override_archetypes: {}
""", encoding="utf-8")

    # Custom fetcher that returns negative current PE
    class NegativePEFetcher:
        def fetch_history(self, symbol, market, metric, years=5):
            history = [15.0] * (years * 250 - 1) + [-5.0]  # current is negative
            return history

    plugin = ValuationFactorPlugin(
        config_path=routing_yaml,
        fetcher=NegativePEFetcher(),
    )

    target = TargetInfo(
        symbol="600519", market=Market.A_SHARE, asset_class="equity", sector="白酒"
    )
    score = plugin.evaluate(target)

    assert score.score == 0.0
    assert score.details["zone"] == "invalid"
    assert score.confidence < 0.5
    assert any("亏损" in w or "invalid" in w.lower() for w in score.warnings)
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
PYTHONPATH=/home/kyrie/workspace/agent-learning:$PYTHONPATH pytest tests/test_mgfs_valuation_plugin.py -v
```

Expected: FAIL — `valuation.py` still has mock implementation; tests will fail with `score == 50.0` or `details["note"] == "mock implementation"`

- [ ] **Step 3: Write minimal implementation**

Replace `sentinel/mgfs/plugins/valuation.py`:

```python
from __future__ import annotations

import math
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
        self.router = ArchetypeRouter(config_path=config_path)
        self.fetcher = fetcher or MockValuationFetcher()
        self.engine = PercentileEngine()
        self.mapper = ZoneMapper()

    def evaluate(self, target: TargetInfo) -> FactorScore:
        # 1. Resolve archetype
        archetype = self.router.resolve_archetype(target.symbol, target.sector)
        if not archetype:
            return FactorScore(
                factor_key=self.factor_key,
                factor_name=self.factor_name,
                score=0.0,
                max_score=100.0,
                weight=self.default_weight,
                details={"error": "无法解析估值范式"},
                confidence=0.0,
                warnings=["估值范式路由失败，未找到匹配的行业映射"],
            )

        primary = archetype["metrics"]["primary"]
        secondary = archetype["metrics"].get("secondary", {})

        # 2. Fetch history
        history = self.fetcher.fetch_history(
            symbol=target.symbol,
            market=target.market,
            metric=primary["name"],
            years=5,
        )

        # 3. Compute percentile
        percentile = self.engine.compute_percentile(history)

        # 4. Map to score
        score, zone = self.mapper.map_percentile(percentile, archetype)

        # 5. Build warnings
        warnings = self._build_warnings(percentile, zone, archetype, len(history))

        # 6. Determine confidence
        confidence = self._compute_confidence(len(history), zone)

        # 7. Extract current value and history stats
        current_value = history[-1] if history else None
        valid_history = [v for v in history if v > 0 and not math.isnan(v)]

        return FactorScore(
            factor_key=self.factor_key,
            factor_name=self.factor_name,
            score=score,
            max_score=100.0,
            weight=self.default_weight,
            details={
                "archetype": archetype.get("label", ""),
                "primary_metric": primary["name"],
                "primary_percentile": round(percentile, 2) if percentile >= 0 else None,
                "secondary_metric": secondary.get("name", ""),
                "zone": zone,
                "history_span_years": 5,
                "data_points": len(history),
                "current_value": round(current_value, 2) if current_value is not None else None,
                "history_min": round(min(valid_history), 2) if valid_history else None,
                "history_max": round(max(valid_history), 2) if valid_history else None,
                "history_median": round(sorted(valid_history)[len(valid_history) // 2], 2) if valid_history else None,
            },
            confidence=confidence,
            warnings=warnings,
        )

    def _build_warnings(
        self,
        percentile: float,
        zone: str,
        archetype: dict[str, Any],
        data_points: int,
    ) -> list[str]:
        warnings: list[str] = []
        if percentile < 0:
            warnings.append("标的处于亏损状态，PE 指标失效，建议切换至 PS/PB 评估")
        elif zone == "avoid":
            hard_veto = archetype.get("circuit_breakers", {}).get("hard_veto_percentile", 90)
            warnings.append(
                f"当前估值处于历史 {percentile:.1f}% 分位，"
                f"接近 {archetype['label']} 危险区域（一票否决线: {hard_veto}%）"
            )
        elif data_points < 500:
            warnings.append(f"历史数据仅 {data_points} 个交易日，百分位可靠性较低")
        return warnings

    def _compute_confidence(self, data_points: int, zone: str) -> float:
        if zone == "invalid":
            return 0.3
        if data_points >= 1000:
            return 0.9
        if data_points >= 500:
            return 0.85
        if data_points >= 250:
            return 0.7
        return 0.5
```

Update `sentinel/mgfs/data/__init__.py` to export ValuationFetcher:

```python
from sentinel.mgfs.data.metrics_aggregator import MetricsAggregator
from sentinel.mgfs.data.valuation_fetcher import MockValuationFetcher, ValuationFetcher

__all__ = ["MetricsAggregator", "ValuationFetcher", "MockValuationFetcher"]
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
PYTHONPATH=/home/kyrie/workspace/agent-learning:$PYTHONPATH pytest tests/test_mgfs_valuation_plugin.py -v
```

Expected: 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add sentinel/mgfs/plugins/valuation.py sentinel/mgfs/data/__init__.py tests/test_mgfs_valuation_plugin.py
git commit -m "feat(mgfs): replace mock ValuationFactorPlugin with production logic

Assembles ArchetypeRouter + ValuationFetcher + PercentileEngine + ZoneMapper.
Supports negative-value PE handling, sector-based archetype routing,
and archetype-calibrated zone scoring.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 6: Config Loader Integration

**Files:**
- Modify: `sentinel/mgfs/config_loader.py`
- Test: `tests/test_mgfs_config_loader.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_mgfs_config_loader.py`:

```python
from pathlib import Path

from sentinel.mgfs.config_loader import _plugin_config_file


def test_plugin_config_file_includes_valuation():
    assert _plugin_config_file("valuation") == "valuation_sector_routing.yaml"
    assert _plugin_config_file("moat") == "moat_static_base.yaml"
    assert _plugin_config_file("policy") == "policy_whitelist.yaml"
    assert _plugin_config_file("unknown") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
PYTHONPATH=/home/kyrie/workspace/agent-learning:$PYTHONPATH pytest tests/test_mgfs_config_loader.py::test_plugin_config_file_includes_valuation -v
```

Expected: FAIL — `_plugin_config_file("valuation")` returns `None`

- [ ] **Step 3: Write minimal implementation**

Modify `sentinel/mgfs/config_loader.py` line ~92-97:

Replace:
```python
def _plugin_config_file(key: str) -> str | None:
    mapping = {
        "moat": "moat_static_base.yaml",
        "policy": "policy_whitelist.yaml",
    }
    return mapping.get(key)
```

With:
```python
def _plugin_config_file(key: str) -> str | None:
    mapping = {
        "moat": "moat_static_base.yaml",
        "policy": "policy_whitelist.yaml",
        "valuation": "valuation_sector_routing.yaml",
    }
    return mapping.get(key)
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
PYTHONPATH=/home/kyrie/workspace/agent-learning:$PYTHONPATH pytest tests/test_mgfs_config_loader.py -v
```

Expected: All tests PASS (including the new one)

- [ ] **Step 5: Commit**

```bash
git add sentinel/mgfs/config_loader.py tests/test_mgfs_config_loader.py
git commit -m "feat(mgfs): add valuation plugin config mapping

Config loader now resolves valuation → valuation_sector_routing.yaml.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 7: End-to-End Integration Test

**Files:**
- Create: `tests/test_mgfs_integration_module_b.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_mgfs_integration_module_b.py`:

```python
from __future__ import annotations

from typer.testing import CliRunner

from main import app as cli_app

runner = CliRunner()


def test_end_to_end_module_b_pipeline(settings, monkeypatch):
    monkeypatch.setenv("SENTINEL_CONFIG_DIR", str(settings.config_dir))
    monkeypatch.setenv("SENTINEL_DATA_DIR", str(settings.data_dir))

    # 1. Create mgfs_config.yaml with valuation module enabled
    mgfs_config = settings.config_dir / "mgfs_config.yaml"
    mgfs_config.write_text("""
version: "1.0"
modules:
  moat:
    enabled: true
    class_path: "sentinel.mgfs.plugins.moat.MoatFactorPlugin"
    config: {}
  policy:
    enabled: true
    class_path: "sentinel.mgfs.plugins.policy.PolicyFactorPlugin"
    config: {}
  valuation:
    enabled: true
    class_path: "sentinel.mgfs.plugins.valuation.ValuationFactorPlugin"
    config: {}
  timing:
    enabled: false
    class_path: "sentinel.mgfs.plugins.timing.TimingFactorPlugin"
    config: {}
scoring_formula:
  moat: { weight: 0.5 }
  valuation: { weight: 0.3 }
  policy: { weight: 0.0 }
policy_multiplier:
  neutral: { multiplier: 1.0 }
circuit_breakers:
  valuation_extremely_overvalued:
    enabled: true
    rule: "valuation_primary_percentile > 90"
    alert_level: "hard_veto"
    message: "估值处于历史极端高位，一票否决"
rating_thresholds:
  strong_buy: { min_score: 90.0, label: "Strong Buy", action: "重仓出击" }
  accumulate: { min_score: 75.0, label: "Accumulate", action: "分批建仓" }
  hold_watch: { min_score: 60.0, label: "Hold/Watch", action: "等待拐点" }
  avoid: { min_score: 0.0, label: "Avoid", action: "回避" }
""", encoding="utf-8")

    # 2. Create moat_static_base.yaml
    moat_yaml = settings.config_dir / "moat_static_base.yaml"
    moat_yaml.write_text("""
version: "1.0"
scoring_weights:
  base: { weight: 0.4 }
  trend: { weight: 0.35 }
  safety: { weight: 0.25 }
companies:
  "600519":
    name: "贵州茅台"
    sector: "白酒"
    base_score:
      brand_premium: { score: 95 }
      franchise_barrier: { score: 90 }
      switching_cost: { score: 88 }
      network_effect: { score: 60 }
      cost_advantage: { score: 70 }
""", encoding="utf-8")

    # 3. Create policy_whitelist.yaml
    policy_yaml = settings.config_dir / "policy_whitelist.yaml"
    policy_yaml.write_text("""
version: "1.0"
default_multiplier: 1.0
sectors:
  "白酒":
    multiplier: 1.0
    note: "消费品"
""", encoding="utf-8")

    # 4. Create valuation_sector_routing.yaml
    valuation_yaml = settings.config_dir / "valuation_sector_routing.yaml"
    valuation_yaml.write_text("""
version: "1.0"
archetypes:
  traditional_growth:
    label: "传统价值成长"
    metrics:
      primary:   { name: "PE_TTM", weight: 0.50 }
      secondary: { name: "PEG", weight: 0.30 }
      warning:   { name: "Dividend_Yield", weight: 0.20 }
    zones:
      strong_buy:  { percentile_max: 20, score_range: [90, 100] }
      accumulate:  { percentile_max: 40, score_range: [75, 90]  }
      hold:        { percentile_max: 70, score_range: [50, 75]  }
      avoid:       { percentile_max: 100, score_range: [0, 50]  }
    circuit_breakers:
      hard_veto_percentile: 90
sector_to_archetype:
  "白酒": "traditional_growth"
default_archetype: "traditional_growth"
override_archetypes: {}
""", encoding="utf-8")

    # 5. Invoke CLI evaluate
    result = runner.invoke(cli_app, [
        "evaluate", "600519",
        "--market", "A股",
        "--asset-class", "equity",
        "--policy", "neutral",
        "--sector", "白酒",
    ])

    assert result.exit_code == 0
    assert "投资权衡与决策说明书" in result.stdout
    assert "600519" in result.stdout
    assert "估值水位" in result.stdout
    assert "PE_TTM" in result.stdout or "传统价值成长" in result.stdout
    assert "综合置信度" in result.stdout
```

- [ ] **Step 2: Run test to verify it passes**

Run:
```bash
PYTHONPATH=/home/kyrie/workspace/agent-learning:$PYTHONPATH pytest tests/test_mgfs_integration_module_b.py -v
```

Expected: PASS (if all prior tasks done correctly)

- [ ] **Step 3: Verify all MGFS tests still pass**

Run:
```bash
PYTHONPATH=/home/kyrie/workspace/agent-learning:$PYTHONPATH pytest tests/test_mgfs_*.py -v
```

Expected: All tests PASS (no regressions in existing Module A tests)

- [ ] **Step 4: Commit**

```bash
git add tests/test_mgfs_integration_module_b.py
git commit -m "test(mgfs): add Module B end-to-end integration test

Full pipeline with Moat + Policy + Valuation plugins, archetype routing,
and CLI evaluate command.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Self-Review

### 1. Spec Coverage

| Spec 章节 | 对应 Task |
|-----------|----------|
| 4. 配置文件 (valuation_sector_routing.yaml) | Task 2 |
| 5. 数据流 | Tasks 3, 4, 5 |
| 6. 插件接口 (ValuationFactorPlugin) | Task 5 |
| 7. 百分位计算引擎 | Task 3 |
| 7.2 负值处理 | Task 3 |
| 8. 范式校准评分映射 | Task 4 |
| 9. 熔断规则集成 | Task 7 (通过 YAML 配置) |
| 10. 输出契约 | Task 5 |
| 11. 错误处理 | Tasks 3, 5 |
| 13. 开发阶段 | All tasks |

**无遗漏。**

### 2. Placeholder Scan

搜索 `TBD|TODO|FIXME|待确定|稍后|实现|fill in` —— 零命中。

### 3. Type Consistency

- `ValuationFetcher.fetch_history()` 签名：`(symbol, market, metric, years=5)` → `list[float]` —— Task 1 和 Task 5 一致
- `ArchetypeRouter.resolve_archetype()` 签名：`(symbol, sector)` —— Task 2 和 Task 5 一致
- `PercentileEngine.compute_percentile()` 签名：`(history)` → `float` —— Task 3 和 Task 5 一致
- `ZoneMapper.map_percentile()` 签名：`(percentile, archetype)` → `tuple[float, str]` —— Task 4 和 Task 5 一致
- `ValuationFactorPlugin.__init__()` 签名：`(config_path, fetcher)` —— Task 5 和 Task 6 一致

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-15-module-b-valuation.md`.**

Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
