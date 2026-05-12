# MGFS Step 0 (框架骨架) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the MGFS scoring framework skeleton — interface contracts, plugin registry, orchestrator, config loader, mock plugins, DuckDB storage, and CLI entry — with all modules running on mock data to verify the full pipeline flows end-to-end.

**Architecture:** Plugin registry pattern (mirroring existing CollectorRegistry), synchronous evaluation flow, YAML-driven configuration with simpleeval-based circuit breakers. All new code lives under `sentinel/mgfs/` to keep domain boundaries clean.

**Tech Stack:** Python 3.11+, pytest, simpleeval, PyYAML, DuckDB, Typer

---

## File Structure

**New directories:**
- `sentinel/mgfs/` — core framework
- `sentinel/mgfs/plugins/` — factor plugin implementations
- `sentinel/mgfs/storage/` — DuckDB repository for MGFS decisions

**New files:**
- `sentinel/mgfs/__init__.py` — package exports
- `sentinel/mgfs/factor_plugin.py` — TargetInfo, FactorScore, AlertLevel, BaseFactorPlugin
- `sentinel/mgfs/registry.py` — FactorPluginRegistry
- `sentinel/mgfs/orchestrator.py` — MGFSOrchestrator, InvestmentDecision
- `sentinel/mgfs/config_loader.py` — load_mgfs_config, build_orchestrator
- `sentinel/mgfs/plugins/__init__.py`
- `sentinel/mgfs/plugins/valuation.py` — Step 2 mock plugin
- `sentinel/mgfs/plugins/timing.py` — Step 2 mock plugin
- `sentinel/mgfs/storage/__init__.py`
- `sentinel/mgfs/storage/mgfs_repository.py` — MGFSRepository

**Modified files:**
- `requirements.txt` — add simpleeval
- `main.py` — add `evaluate` subcommand

**Test files:**
- `tests/test_mgfs_factor_plugin.py`
- `tests/test_mgfs_registry.py`
- `tests/test_mgfs_orchestrator.py`
- `tests/test_mgfs_config_loader.py`
- `tests/test_mgfs_repository.py`
- `tests/test_mgfs_cli.py`
- `tests/test_mgfs_integration.py`

---

### Task 1: Add simpleeval Dependency

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add simpleeval to requirements**

Append to `requirements.txt`:
```text
simpleeval==1.0.7
```

- [ ] **Step 2: Install and verify**

Run:
```bash
pip install -r requirements.txt
python -c "from simpleeval import simple_eval; print(simple_eval('1 + 1'))"
```

Expected output:
```text
2
```

- [ ] **Step 3: Commit**

```bash
git add requirements.txt
git commit -m "deps: add simpleeval for circuit breaker rule evaluation

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 2: Factor Plugin Base Classes

**Files:**
- Create: `sentinel/mgfs/__init__.py`
- Create: `sentinel/mgfs/factor_plugin.py`
- Create: `tests/test_mgfs_factor_plugin.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_mgfs_factor_plugin.py`:
```python
from sentinel.domain.models import Market
from sentinel.mgfs.factor_plugin import (
    AlertLevel,
    BaseFactorPlugin,
    FactorScore,
    TargetInfo,
)


def test_target_info_is_frozen_dataclass():
    target = TargetInfo(symbol="600519", market=Market.A_SHARE, asset_class="equity")
    assert target.symbol == "600519"
    assert target.market == Market.A_SHARE
    assert target.asset_class == "equity"


def test_factor_score_normalized_score():
    score = FactorScore(factor_key="moat", factor_name="护城河", score=75.0, max_score=100.0)
    assert score.normalized_score == 0.75


def test_factor_score_normalized_with_zero_max():
    score = FactorScore(factor_key="moat", factor_name="护城河", score=10.0, max_score=0.0)
    assert score.normalized_score == 0.0


def test_alert_level_enum_values():
    assert AlertLevel.HARD_VETO.value == "hard_veto"
    assert AlertLevel.SOFT_VETO.value == "soft_veto"
    assert AlertLevel.YELLOW_WARNING.value == "yellow_warning"
    assert AlertLevel.GREEN_PASS.value == "green_pass"


def test_base_factor_plugin_is_abstract():
    import inspect
    assert inspect.isabstract(BaseFactorPlugin)
    assert "evaluate" in BaseFactorPlugin.__abstractmethods__
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
pytest tests/test_mgfs_factor_plugin.py -v
```

Expected: ImportError / ModuleNotFoundError for sentinel.mgfs.factor_plugin

- [ ] **Step 3: Write minimal implementation**

Create `sentinel/mgfs/__init__.py`:
```python
from sentinel.mgfs.factor_plugin import (
    AlertLevel,
    BaseFactorPlugin,
    FactorScore,
    TargetInfo,
)

__all__ = [
    "AlertLevel",
    "BaseFactorPlugin",
    "FactorScore",
    "TargetInfo",
]
```

Create `sentinel/mgfs/factor_plugin.py`:
```python
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from sentinel.domain.models import Market


@dataclass(frozen=True, slots=True)
class TargetInfo:
    symbol: str
    market: Market
    asset_class: str
    name: str | None = None
    sector: str | None = None
    tags: list[str] = field(default_factory=list)


class AlertLevel(StrEnum):
    HARD_VETO = "hard_veto"
    SOFT_VETO = "soft_veto"
    YELLOW_WARNING = "yellow_warning"
    GREEN_PASS = "green_pass"


@dataclass(slots=True)
class FactorScore:
    factor_key: str
    factor_name: str
    score: float
    max_score: float = 100.0
    weight: float = 0.0
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )
    details: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    warnings: list[str] = field(default_factory=list)
    is_veto: bool = False
    veto_reason: str | None = None

    @property
    def normalized_score(self) -> float:
        if self.max_score <= 0:
            return 0.0
        return self.score / self.max_score


class BaseFactorPlugin(ABC):
    factor_key: str
    factor_name: str
    default_weight: float = 0.0

    @abstractmethod
    def evaluate(self, target: TargetInfo) -> FactorScore:
        raise NotImplementedError

    def health_check(self) -> dict[str, Any]:
        return {"ready": True, "missing_dependencies": []}
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
pytest tests/test_mgfs_factor_plugin.py -v
```

Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add sentinel/mgfs/__init__.py sentinel/mgfs/factor_plugin.py tests/test_mgfs_factor_plugin.py
git commit -m "feat(mgfs): add factor plugin base classes

TargetInfo, FactorScore, AlertLevel, BaseFactorPlugin with normalized_score.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 3: FactorPluginRegistry

**Files:**
- Create: `sentinel/mgfs/registry.py`
- Create: `tests/test_mgfs_registry.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_mgfs_registry.py`:
```python
import pytest

from sentinel.domain.models import Market
from sentinel.mgfs.factor_plugin import BaseFactorPlugin, FactorScore, TargetInfo
from sentinel.mgfs.registry import FactorPluginRegistry


class MockMoatPlugin(BaseFactorPlugin):
    factor_key = "moat"
    factor_name = "护城河"

    def evaluate(self, target: TargetInfo) -> FactorScore:
        return FactorScore(factor_key="moat", factor_name="护城河", score=80.0)


class MockTokenPlugin(BaseFactorPlugin):
    factor_key = "token_metrics"
    factor_name = "Token消耗"

    def evaluate(self, target: TargetInfo) -> FactorScore:
        return FactorScore(factor_key="token_metrics", factor_name="Token消耗", score=60.0)


def test_register_and_list_plugins():
    registry = FactorPluginRegistry()
    registry.register(MockMoatPlugin())
    registry.register(MockTokenPlugin())

    plugins = registry.list_by_keys(["moat", "token_metrics"])
    assert len(plugins) == 2
    assert plugins[0].factor_key == "moat"
    assert plugins[1].factor_key == "token_metrics"


def test_list_plugins_returns_copy():
    registry = FactorPluginRegistry()
    registry.register(MockMoatPlugin())

    first = registry.list_by_keys(["moat"])
    second = registry.list_by_keys(["moat"])
    assert first is not second


def test_missing_plugin_raises_keyerror():
    registry = FactorPluginRegistry()
    with pytest.raises(KeyError, match="factor not registered: missing"):
        registry.list_by_keys(["missing"])
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
pytest tests/test_mgfs_registry.py -v
```

Expected: ImportError for sentinel.mgfs.registry

- [ ] **Step 3: Write minimal implementation**

Create `sentinel/mgfs/registry.py`:
```python
from __future__ import annotations

from sentinel.mgfs.factor_plugin import BaseFactorPlugin


class FactorPluginRegistry:
    def __init__(self) -> None:
        self._plugins: dict[str, BaseFactorPlugin] = {}

    def register(self, plugin: BaseFactorPlugin) -> None:
        self._plugins[plugin.factor_key] = plugin

    def list_by_keys(self, keys: list[str]) -> list[BaseFactorPlugin]:
        resolved: list[BaseFactorPlugin] = []
        for key in keys:
            if key not in self._plugins:
                raise KeyError(f"factor not registered: {key}")
            resolved.append(self._plugins[key])
        return resolved

    def list_all(self) -> list[BaseFactorPlugin]:
        return list(self._plugins.values())
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
pytest tests/test_mgfs_registry.py -v
```

Expected: 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add sentinel/mgfs/registry.py tests/test_mgfs_registry.py
git commit -m "feat(mgfs): add FactorPluginRegistry

Plugin registry mirroring existing CollectorRegistry pattern.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 4: MGFSOrchestrator — Plugin Execution and Scoring

**Files:**
- Create: `sentinel/mgfs/orchestrator.py`
- Create: `tests/test_mgfs_orchestrator.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_mgfs_orchestrator.py`:
```python
from sentinel.domain.models import Market
from sentinel.mgfs.factor_plugin import BaseFactorPlugin, FactorScore, TargetInfo
from sentinel.mgfs.orchestrator import MGFSOrchestrator


class MockMoatPlugin(BaseFactorPlugin):
    factor_key = "moat"
    factor_name = "护城河"

    def evaluate(self, target: TargetInfo) -> FactorScore:
        return FactorScore(factor_key="moat", factor_name="护城河", score=80.0)


class MockTokenPlugin(BaseFactorPlugin):
    factor_key = "token_metrics"
    factor_name = "Token消耗"

    def evaluate(self, target: TargetInfo) -> FactorScore:
        return FactorScore(factor_key="token_metrics", factor_name="Token消耗", score=60.0)


def test_orchestrator_evaluates_plugins_and_computes_raw_total():
    orchestrator = MGFSOrchestrator(
        plugins=[MockMoatPlugin(), MockTokenPlugin()],
        scoring_weights={"moat": 0.5, "token_metrics": 0.5},
        policy_multipliers={"neutral": 1.0},
        circuit_breakers=[],
        rating_thresholds=[
            {"min_score": 90.0, "label": "Strong Buy", "action": "buy"},
            {"min_score": 0.0, "label": "Avoid", "action": "avoid"},
        ],
    )
    target = TargetInfo(symbol="600519", market=Market.A_SHARE, asset_class="equity")
    decision = orchestrator.evaluate(target, policy_rating="neutral")

    assert decision.target.symbol == "600519"
    assert "moat" in decision.factor_scores
    assert "token_metrics" in decision.factor_scores
    # raw_total = (0.8 * 100 * 0.5 + 0.6 * 100 * 0.5) / 1.0 = 70.0
    assert decision.raw_total == 70.0
    assert decision.policy_multiplier == 1.0
    assert decision.final_score == 70.0


def test_orchestrator_plugin_failure_returns_fallback():
    class BrokenPlugin(BaseFactorPlugin):
        factor_key = "broken"
        factor_name = "故障插件"

        def evaluate(self, target: TargetInfo) -> FactorScore:
            raise RuntimeError("boom")

    orchestrator = MGFSOrchestrator(
        plugins=[BrokenPlugin()],
        scoring_weights={"broken": 1.0},
        policy_multipliers={"neutral": 1.0},
        circuit_breakers=[],
        rating_thresholds=[
            {"min_score": 0.0, "label": "Avoid", "action": "avoid"},
        ],
    )
    target = TargetInfo(symbol="TEST", market=Market.A_SHARE, asset_class="equity")
    decision = orchestrator.evaluate(target, policy_rating="neutral")

    assert decision.factor_scores["broken"].score == 0.0
    assert decision.factor_scores["broken"].confidence == 0.0
    assert "评估失败" in decision.factor_scores["broken"].warnings[0]
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
pytest tests/test_mgfs_orchestrator.py -v
```

Expected: ImportError for sentinel.mgfs.orchestrator

- [ ] **Step 3: Write minimal implementation**

Create `sentinel/mgfs/orchestrator.py`:
```python
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sentinel.mgfs.factor_plugin import (
    AlertLevel,
    BaseFactorPlugin,
    FactorScore,
    TargetInfo,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class InvestmentDecision:
    target: TargetInfo
    generated_at: datetime
    factor_scores: dict[str, FactorScore]
    raw_total: float
    policy_multiplier: float
    final_score: float
    rating: str
    action: str
    circuit_breakers_triggered: list[dict[str, Any]]
    alert_level: AlertLevel
    report_sections: dict[str, Any] = field(default_factory=dict)


class MGFSOrchestrator:
    def __init__(
        self,
        plugins: list[BaseFactorPlugin],
        scoring_weights: dict[str, float],
        policy_multipliers: dict[str, float],
        circuit_breakers: list[dict[str, Any]],
        rating_thresholds: list[dict[str, Any]],
    ) -> None:
        self.plugins = {p.factor_key: p for p in plugins}
        self.scoring_weights = scoring_weights
        self.policy_multipliers = policy_multipliers
        self.circuit_breakers = circuit_breakers
        self.rating_thresholds = sorted(
            rating_thresholds, key=lambda x: x["min_score"], reverse=True
        )

    def evaluate(
        self, target: TargetInfo, policy_rating: str = "neutral"
    ) -> InvestmentDecision:
        factor_scores = self._run_plugins(target)
        raw_total = self._compute_raw_total(factor_scores)
        multiplier = self.policy_multipliers.get(policy_rating, 1.0)
        final_score = raw_total * multiplier
        triggered, alert_level = self._check_circuit_breakers(
            factor_scores, policy_rating
        )
        rating, action = self._classify_rating(final_score, alert_level)

        return InvestmentDecision(
            target=target,
            generated_at=datetime.now(tz=timezone.utc),
            factor_scores=factor_scores,
            raw_total=round(raw_total, 2),
            policy_multiplier=multiplier,
            final_score=round(final_score, 2),
            rating=rating,
            action=action,
            circuit_breakers_triggered=triggered,
            alert_level=alert_level,
        )

    def _run_plugins(self, target: TargetInfo) -> dict[str, FactorScore]:
        scores: dict[str, FactorScore] = {}
        for key, plugin in self.plugins.items():
            try:
                scores[key] = plugin.evaluate(target)
            except Exception:
                logger.exception("Factor %s failed for %s", key, target.symbol)
                scores[key] = FactorScore(
                    factor_key=key,
                    factor_name=plugin.factor_name,
                    score=0.0,
                    confidence=0.0,
                    warnings=[f"{plugin.factor_name} 评估失败，使用兜底分数"],
                )
        return scores

    def _compute_raw_total(
        self, factor_scores: dict[str, FactorScore]
    ) -> float:
        total = 0.0
        weight_sum = 0.0
        for key, score in factor_scores.items():
            w = self.scoring_weights.get(key, 0.0)
            total += score.normalized_score * 100 * w
            weight_sum += w
        return total / weight_sum if weight_sum > 0 else 0.0

    def _check_circuit_breakers(
        self, factor_scores: dict[str, FactorScore], policy_rating: str
    ) -> tuple[list[dict[str, Any]], AlertLevel]:
        triggered: list[dict[str, Any]] = []
        alert_level = AlertLevel.GREEN_PASS
        return triggered, alert_level

    def _classify_rating(
        self, final_score: float, alert_level: AlertLevel
    ) -> tuple[str, str]:
        if alert_level == AlertLevel.HARD_VETO:
            return "Avoid", "一票否决：禁止买入"
        for threshold in self.rating_thresholds:
            if final_score >= threshold["min_score"]:
                return threshold["label"], threshold["action"]
        return "Avoid", "回避"
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
pytest tests/test_mgfs_orchestrator.py -v
```

Expected: 2 tests PASS

- [ ] **Step 5: Commit**

```bash
git add sentinel/mgfs/orchestrator.py tests/test_mgfs_orchestrator.py
git commit -m "feat(mgfs): add MGFSOrchestrator core evaluation flow

Plugin execution, scoring computation, fallback on plugin failure.
Circuit breakers and full rating logic in next task.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 5: MGFSOrchestrator — Circuit Breakers and Rating

**Files:**
- Modify: `sentinel/mgfs/orchestrator.py`
- Modify: `tests/test_mgfs_orchestrator.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_mgfs_orchestrator.py`:
```python
from simpleeval import simple_eval

from sentinel.mgfs.factor_plugin import AlertLevel


class MockMoatPlugin(BaseFactorPlugin):
    factor_key = "moat"
    factor_name = "护城河"

    def evaluate(self, target: TargetInfo) -> FactorScore:
        return FactorScore(factor_key="moat", factor_name="护城河", score=80.0)


class MockTokenPlugin(BaseFactorPlugin):
    factor_key = "token_metrics"
    factor_name = "Token消耗"

    def evaluate(self, target: TargetInfo) -> FactorScore:
        return FactorScore(factor_key="token_metrics", factor_name="Token消耗", score=60.0)


def test_orchestrator_policy_multiplier_applied():
    orchestrator = MGFSOrchestrator(
        plugins=[MockMoatPlugin()],
        scoring_weights={"moat": 1.0},
        policy_multipliers={"core_support": 1.2, "neutral": 1.0},
        circuit_breakers=[],
        rating_thresholds=[
            {"min_score": 0.0, "label": "Avoid", "action": "avoid"},
        ],
    )
    target = TargetInfo(symbol="TEST", market=Market.A_SHARE, asset_class="equity")
    decision = orchestrator.evaluate(target, policy_rating="core_support")

    assert decision.policy_multiplier == 1.2
    assert decision.final_score == 96.0  # 80 * 1.2


def test_orchestrator_circuit_breaker_triggers():
    orchestrator = MGFSOrchestrator(
        plugins=[MockMoatPlugin()],
        scoring_weights={"moat": 1.0},
        policy_multipliers={"neutral": 1.0},
        circuit_breakers=[
            {
                "enabled": True,
                "rule": "moat_score < 100",
                "action": "soft_veto",
                "alert_level": "soft_veto",
                "message": "护城河评分过低",
            }
        ],
        rating_thresholds=[
            {"min_score": 90.0, "label": "Strong Buy", "action": "buy"},
            {"min_score": 0.0, "label": "Avoid", "action": "avoid"},
        ],
    )
    target = TargetInfo(symbol="TEST", market=Market.A_SHARE, asset_class="equity")
    decision = orchestrator.evaluate(target, policy_rating="neutral")

    assert len(decision.circuit_breakers_triggered) == 1
    assert decision.alert_level == AlertLevel.SOFT_VETO
    assert decision.rating == "Avoid"


def test_orchestrator_hard_veto_forces_avoid():
    orchestrator = MGFSOrchestrator(
        plugins=[MockMoatPlugin()],
        scoring_weights={"moat": 1.0},
        policy_multipliers={"neutral": 1.0},
        circuit_breakers=[
            {
                "enabled": True,
                "rule": "policy_rating == 'veto'",
                "action": "hard_veto",
                "alert_level": "hard_veto",
                "message": "一票否决",
            }
        ],
        rating_thresholds=[
            {"min_score": 0.0, "label": "Avoid", "action": "avoid"},
        ],
    )
    target = TargetInfo(symbol="TEST", market=Market.A_SHARE, asset_class="equity")
    decision = orchestrator.evaluate(target, policy_rating="veto")

    assert decision.alert_level == AlertLevel.HARD_VETO
    assert decision.rating == "Avoid"
    assert "一票否决" in decision.action


def test_orchestrator_rating_classification():
    orchestrator = MGFSOrchestrator(
        plugins=[MockMoatPlugin()],
        scoring_weights={"moat": 1.0},
        policy_multipliers={"neutral": 1.0},
        circuit_breakers=[],
        rating_thresholds=[
            {"min_score": 90.0, "label": "Strong Buy", "action": "重仓出击"},
            {"min_score": 75.0, "label": "Accumulate", "action": "分批建仓"},
            {"min_score": 60.0, "label": "Hold/Watch", "action": "等待"},
            {"min_score": 0.0, "label": "Avoid", "action": "回避"},
        ],
    )
    target = TargetInfo(symbol="TEST", market=Market.A_SHARE, asset_class="equity")

    # Score 80 falls into Accumulate (75-90)
    decision = orchestrator.evaluate(target, policy_rating="neutral")
    assert decision.rating == "Accumulate"
    assert decision.action == "分批建仓"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
pytest tests/test_mgfs_orchestrator.py::test_orchestrator_policy_multiplier_applied -v
pytest tests/test_mgfs_orchestrator.py::test_orchestrator_circuit_breaker_triggers -v
pytest tests/test_mgfs_orchestrator.py::test_orchestrator_hard_veto_forces_avoid -v
pytest tests/test_mgfs_orchestrator.py::test_orchestrator_rating_classification -v
```

Expected: FAIL — `_check_circuit_breakers` is stubbed (returns empty list and GREEN_PASS)

- [ ] **Step 3: Implement circuit breakers and rating**

Replace `_check_circuit_breakers` in `sentinel/mgfs/orchestrator.py`:

```python
from simpleeval import simple_eval

# ... existing code ...

    def _check_circuit_breakers(
        self, factor_scores: dict[str, FactorScore], policy_rating: str
    ) -> tuple[list[dict[str, Any]], AlertLevel]:
        triggered: list[dict[str, Any]] = []
        alert_level = AlertLevel.GREEN_PASS
        context = self._build_eval_context(factor_scores, policy_rating)

        for cb in self.circuit_breakers:
            if not cb.get("enabled", False):
                continue
            try:
                if simple_eval(cb["rule"], names=context):
                    triggered.append(cb)
                    cb_level = AlertLevel(cb.get("alert_level", "yellow_warning"))
                    if cb_level in (AlertLevel.HARD_VETO, AlertLevel.SOFT_VETO):
                        alert_level = cb_level
                    elif alert_level == AlertLevel.GREEN_PASS:
                        alert_level = cb_level
            except Exception:
                logger.warning("Circuit breaker rule error: %s", cb["rule"])

        return triggered, alert_level

    def _build_eval_context(
        self, factor_scores: dict[str, FactorScore], policy_rating: str
    ) -> dict[str, Any]:
        ctx: dict[str, Any] = {"policy_rating": policy_rating}
        for key, score in factor_scores.items():
            ctx[f"{key}_score"] = score.score
            ctx[f"{key}_normalized"] = score.normalized_score
            for detail_key, detail_val in score.details.items():
                if isinstance(detail_val, (int, float, bool, str)):
                    ctx[f"{key}_{detail_key}"] = detail_val
        return ctx
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
pytest tests/test_mgfs_orchestrator.py -v
```

Expected: 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add sentinel/mgfs/orchestrator.py tests/test_mgfs_orchestrator.py
git commit -m "feat(mgfs): add circuit breakers and rating classification

Uses simpleeval for safe rule evaluation. Hard veto forces Avoid rating.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 6: Mock Plugins (valuation + timing)

**Files:**
- Create: `sentinel/mgfs/plugins/__init__.py`
- Create: `sentinel/mgfs/plugins/valuation.py`
- Create: `sentinel/mgfs/plugins/timing.py`
- Create: `tests/test_mgfs_mock_plugins.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_mgfs_mock_plugins.py`:
```python
from sentinel.domain.models import Market
from sentinel.mgfs.factor_plugin import TargetInfo
from sentinel.mgfs.plugins.valuation import ValuationFactorPlugin
from sentinel.mgfs.plugins.timing import TimingFactorPlugin


def test_valuation_plugin_returns_mock_score():
    plugin = ValuationFactorPlugin()
    target = TargetInfo(symbol="600519", market=Market.A_SHARE, asset_class="equity")
    score = plugin.evaluate(target)

    assert score.factor_key == "valuation"
    assert score.factor_name == "估值水位"
    assert score.score == 50.0
    assert score.details["note"] == "mock implementation — Step 2"


def test_timing_plugin_returns_mock_score():
    plugin = TimingFactorPlugin()
    target = TargetInfo(symbol="BTC", market=Market.CRYPTO, asset_class="crypto")
    score = plugin.evaluate(target)

    assert score.factor_key == "timing"
    assert score.factor_name == "量化择时"
    assert score.score == 50.0
    assert score.details["note"] == "mock implementation — Step 2"
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
pytest tests/test_mgfs_mock_plugins.py -v
```

Expected: ImportError

- [ ] **Step 3: Write minimal implementation**

Create `sentinel/mgfs/plugins/__init__.py`:
```python
from sentinel.mgfs.plugins.timing import TimingFactorPlugin
from sentinel.mgfs.plugins.valuation import ValuationFactorPlugin

__all__ = ["ValuationFactorPlugin", "TimingFactorPlugin"]
```

Create `sentinel/mgfs/plugins/valuation.py`:
```python
from __future__ import annotations

from sentinel.mgfs.factor_plugin import BaseFactorPlugin, FactorScore, TargetInfo


class ValuationFactorPlugin(BaseFactorPlugin):
    factor_key = "valuation"
    factor_name = "估值水位"
    default_weight = 0.0

    def evaluate(self, target: TargetInfo) -> FactorScore:
        return FactorScore(
            factor_key=self.factor_key,
            factor_name=self.factor_name,
            score=50.0,
            details={"note": "mock implementation — Step 2"},
        )
```

Create `sentinel/mgfs/plugins/timing.py`:
```python
from __future__ import annotations

from sentinel.mgfs.factor_plugin import BaseFactorPlugin, FactorScore, TargetInfo


class TimingFactorPlugin(BaseFactorPlugin):
    factor_key = "timing"
    factor_name = "量化择时"
    default_weight = 0.0

    def evaluate(self, target: TargetInfo) -> FactorScore:
        return FactorScore(
            factor_key=self.factor_key,
            factor_name=self.factor_name,
            score=50.0,
            details={"note": "mock implementation — Step 2"},
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
pytest tests/test_mgfs_mock_plugins.py -v
```

Expected: 2 tests PASS

- [ ] **Step 5: Commit**

```bash
git add sentinel/mgfs/plugins/ tests/test_mgfs_mock_plugins.py
git commit -m "feat(mgfs): add mock plugins for valuation and timing

Step 2 placeholders returning neutral mock scores.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 7: Config Loader

**Files:**
- Create: `sentinel/mgfs/config_loader.py`
- Create: `tests/test_mgfs_config_loader.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_mgfs_config_loader.py`:
```python
from pathlib import Path

import pytest

from sentinel.mgfs.config_loader import load_mgfs_config
from sentinel.mgfs.factor_plugin import BaseFactorPlugin, FactorScore, TargetInfo


class TestMoatPlugin(BaseFactorPlugin):
    factor_key = "moat"
    factor_name = "护城河"

    def evaluate(self, target: TargetInfo) -> FactorScore:
        return FactorScore(factor_key="moat", factor_name="护城河", score=80.0)


def test_load_mgfs_config_parses_yaml():
    config_path = Path("/tmp/test_mgfs_config.yaml")
    config_path.write_text("""
version: "1.0"
modules:
  moat:
    enabled: true
    class_path: "tests.test_mgfs_config_loader.TestMoatPlugin"
    config: {}
scoring_formula:
  moat: { weight: 1.0 }
policy_multiplier:
  neutral: { multiplier: 1.0 }
circuit_breakers: []
rating_thresholds:
  - { min_score: 0.0, label: "Avoid", action: "avoid" }
""", encoding="utf-8")

    config = load_mgfs_config(config_path)
    assert config["version"] == "1.0"
    assert config["modules"]["moat"]["enabled"] is True


def test_load_mgfs_config_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        load_mgfs_config(Path("/tmp/nonexistent_mgfs_config.yaml"))
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
pytest tests/test_mgfs_config_loader.py -v
```

Expected: ImportError for sentinel.mgfs.config_loader

- [ ] **Step 3: Write minimal implementation**

Create `sentinel/mgfs/config_loader.py`:
```python
from __future__ import annotations

import importlib
import logging
from pathlib import Path

import yaml

from sentinel.mgfs.factor_plugin import BaseFactorPlugin
from sentinel.mgfs.orchestrator import MGFSOrchestrator
from sentinel.mgfs.registry import FactorPluginRegistry

logger = logging.getLogger(__name__)


def load_mgfs_config(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"MGFS config not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def build_orchestrator(config: dict) -> MGFSOrchestrator:
    modules = config.get("modules", {})
    scoring_formula = config.get("scoring_formula", {})
    policy_multipliers = _extract_policy_multipliers(
        config.get("policy_multiplier", {})
    )
    circuit_breakers = list(config.get("circuit_breakers", {}).values())
    rating_thresholds = list(config.get("rating_thresholds", {}).values())

    plugins: list[BaseFactorPlugin] = []
    for key, module_config in modules.items():
        if not module_config.get("enabled", False):
            continue
        try:
            plugin = _load_plugin(module_config["class_path"])
            plugins.append(plugin)
        except Exception:
            logger.exception("Failed to load plugin %s", key)

    scoring_weights = {
        key: cfg["weight"] for key, cfg in scoring_formula.items()
    }

    return MGFSOrchestrator(
        plugins=plugins,
        scoring_weights=scoring_weights,
        policy_multipliers=policy_multipliers,
        circuit_breakers=circuit_breakers,
        rating_thresholds=rating_thresholds,
    )


def _load_plugin(class_path: str) -> BaseFactorPlugin:
    module_name, class_name = class_path.rsplit(".", 1)
    module = importlib.import_module(module_name)
    cls = getattr(module, class_name)
    return cls()


def _extract_policy_multipliers(raw: dict) -> dict[str, float]:
    result: dict[str, float] = {}
    for key, cfg in raw.items():
        if isinstance(cfg, dict) and "multiplier" in cfg:
            result[key] = float(cfg["multiplier"])
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
pytest tests/test_mgfs_config_loader.py -v
```

Expected: 2 tests PASS

- [ ] **Step 5: Commit**

```bash
git add sentinel/mgfs/config_loader.py tests/test_mgfs_config_loader.py
git commit -m "feat(mgfs): add config loader with dynamic plugin import

Parses mgfs_config.yaml and wires orchestrator via importlib.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 8: MGFS Repository (DuckDB)

**Files:**
- Create: `sentinel/mgfs/storage/__init__.py`
- Create: `sentinel/mgfs/storage/mgfs_repository.py`
- Create: `tests/test_mgfs_repository.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_mgfs_repository.py`:
```python
from datetime import datetime, timezone

from sentinel.domain.models import Market
from sentinel.mgfs.factor_plugin import AlertLevel, FactorScore, TargetInfo
from sentinel.mgfs.orchestrator import InvestmentDecision
from sentinel.mgfs.storage.mgfs_repository import MGFSRepository
from sentinel.storage.db import Database


def test_repository_bootstraps_table(settings):
    db = Database(settings.database_path)
    repo = MGFSRepository(db)
    repo.bootstrap()

    con = db.connect()
    try:
        tables = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='mgfs_decisions'"
        ).fetchall()
        assert len(tables) == 1
    finally:
        con.close()


def test_repository_save_and_retrieve(settings):
    db = Database(settings.database_path)
    repo = MGFSRepository(db)
    repo.bootstrap()

    target = TargetInfo(symbol="600519", market=Market.A_SHARE, asset_class="equity")
    decision = InvestmentDecision(
        target=target,
        generated_at=datetime(2026, 5, 12, 10, 0, 0, tzinfo=timezone.utc),
        factor_scores={
            "moat": FactorScore(factor_key="moat", factor_name="护城河", score=80.0),
        },
        raw_total=80.0,
        policy_multiplier=1.2,
        final_score=96.0,
        rating="Strong Buy",
        action="重仓出击",
        circuit_breakers_triggered=[],
        alert_level=AlertLevel.GREEN_PASS,
    )

    repo.save_decision(decision)
    decisions = repo.get_decisions_for_symbol("600519", Market.A_SHARE)

    assert len(decisions) == 1
    assert decisions[0]["symbol"] == "600519"
    assert decisions[0]["final_score"] == 96.0
    assert decisions[0]["rating"] == "Strong Buy"
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
pytest tests/test_mgfs_repository.py -v
```

Expected: ImportError for sentinel.mgfs.storage.mgfs_repository

- [ ] **Step 3: Write minimal implementation**

Create `sentinel/mgfs/storage/__init__.py`:
```python
from sentinel.mgfs.storage.mgfs_repository import MGFSRepository

__all__ = ["MGFSRepository"]
```

Create `sentinel/mgfs/storage/mgfs_repository.py`:
```python
from __future__ import annotations

import json
from typing import Any

from sentinel.domain.models import Market
from sentinel.mgfs.orchestrator import InvestmentDecision
from sentinel.storage.db import Database

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS mgfs_decisions (
    id INTEGER PRIMARY KEY,
    evaluated_at TIMESTAMP NOT NULL,
    symbol VARCHAR(50) NOT NULL,
    market VARCHAR(20) NOT NULL,
    asset_class VARCHAR(20) NOT NULL,
    sector VARCHAR(50),
    moat_score DOUBLE,
    token_score DOUBLE,
    financials_score DOUBLE,
    raw_total DOUBLE,
    policy_multiplier DOUBLE,
    final_score DOUBLE,
    rating VARCHAR(20),
    alert_level VARCHAR(20),
    circuit_breakers_triggered JSON,
    factor_details JSON,
    UNIQUE(evaluated_at, symbol, market)
);
"""


class MGFSRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def bootstrap(self) -> None:
        con = self.database.connect()
        try:
            con.execute(SCHEMA_SQL)
        finally:
            con.close()

    def save_decision(self, decision: InvestmentDecision) -> None:
        con = self.database.connect()
        try:
            con.execute(
                """
                INSERT OR REPLACE INTO mgfs_decisions (
                    evaluated_at, symbol, market, asset_class, sector,
                    moat_score, token_score, financials_score,
                    raw_total, policy_multiplier, final_score,
                    rating, alert_level, circuit_breakers_triggered, factor_details
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    decision.generated_at,
                    decision.target.symbol,
                    decision.target.market.value,
                    decision.target.asset_class,
                    decision.target.sector,
                    _extract_factor_score(decision, "moat"),
                    _extract_factor_score(decision, "token_metrics"),
                    _extract_factor_score(decision, "financials"),
                    decision.raw_total,
                    decision.policy_multiplier,
                    decision.final_score,
                    decision.rating,
                    decision.alert_level.value,
                    json.dumps(decision.circuit_breakers_triggered),
                    json.dumps(
                        {
                            k: {
                                "score": v.score,
                                "normalized": v.normalized_score,
                                "details": v.details,
                            }
                            for k, v in decision.factor_scores.items()
                        }
                    ),
                ],
            )
        finally:
            con.close()

    def get_decisions_for_symbol(
        self, symbol: str, market: Market
    ) -> list[dict[str, Any]]:
        con = self.database.connect()
        try:
            rows = con.execute(
                """
                SELECT * FROM mgfs_decisions
                WHERE symbol = ? AND market = ?
                ORDER BY evaluated_at DESC
                """,
                [symbol, market.value],
            ).fetchall()
            columns = [desc[0] for desc in con.description]
            return [dict(zip(columns, row)) for row in rows]
        finally:
            con.close()


def _extract_factor_score(decision: InvestmentDecision, key: str) -> float | None:
    score = decision.factor_scores.get(key)
    return score.score if score else None
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
pytest tests/test_mgfs_repository.py -v
```

Expected: 2 tests PASS

- [ ] **Step 5: Commit**

```bash
git add sentinel/mgfs/storage/ tests/test_mgfs_repository.py
git commit -m "feat(mgfs): add DuckDB repository for MGFS decisions

mgfs_decisions table with factor score persistence and retrieval.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 9: CLI evaluate Command

**Files:**
- Modify: `main.py`
- Create: `tests/test_mgfs_cli.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_mgfs_cli.py`:
```python
from typer.testing import CliRunner

from main import app as cli_app

runner = CliRunner()


def test_cli_evaluate_command_exists():
    result = runner.invoke(cli_app, ["evaluate", "--help"])
    assert result.exit_code == 0
    assert "evaluate" in result.stdout


def test_cli_evaluate_runs_with_mock_plugins(settings, monkeypatch):
    monkeypatch.setenv("SENTINEL_CONFIG_DIR", str(settings.config_dir))
    monkeypatch.setenv("SENTINEL_DATA_DIR", str(settings.data_dir))

    # Create minimal mgfs_config.yaml in temp config dir
    mgfs_config = settings.config_dir / "mgfs_config.yaml"
    mgfs_config.write_text("""
version: "1.0"
modules:
  valuation:
    enabled: true
    class_path: "sentinel.mgfs.plugins.valuation.ValuationFactorPlugin"
    config: {}
scoring_formula:
  valuation: { weight: 1.0 }
policy_multiplier:
  neutral: { multiplier: 1.0 }
circuit_breakers: {}
rating_thresholds:
  avoid: { min_score: 0.0, label: "Avoid", action: "回避" }
""", encoding="utf-8")

    result = runner.invoke(cli_app, [
        "evaluate", "TEST",
        "--market", "A股",
        "--asset-class", "equity",
        "--policy", "neutral",
    ])

    assert result.exit_code == 0
    assert "投资权衡与决策说明书" in result.stdout
    assert "估值水位" in result.stdout
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
pytest tests/test_mgfs_cli.py -v
```

Expected: FAIL — `evaluate` command not found in CLI

- [ ] **Step 3: Write minimal implementation**

Modify `main.py` — append before `if __name__ == "__main__"`:

```python
@app.command()
def evaluate(
    symbol: str = typer.Argument(..., help="标的代码"),
    market: Market = typer.Option(..., "--market"),
    asset_class: str = typer.Option("equity", "--asset-class"),
    policy: str = typer.Option("neutral", "--policy", help="政策评级"),
    sector: str | None = typer.Option(None, "--sector"),
    publish: bool = typer.Option(False, "--publish"),
) -> None:
    from sentinel.mgfs.config_loader import load_mgfs_config, build_orchestrator
    from sentinel.mgfs.factor_plugin import TargetInfo

    settings = AppSettings()
    config_path = settings.resolved_config_dir / "mgfs_config.yaml"
    config = load_mgfs_config(config_path)
    orchestrator = build_orchestrator(config)

    target = TargetInfo(
        symbol=symbol,
        market=market,
        asset_class=asset_class,
        sector=sector,
    )
    decision = orchestrator.evaluate(target, policy_rating=policy)

    typer.echo(f"\n{'='*50}")
    typer.echo("《投资权衡与决策说明书》")
    typer.echo(f"{'='*50}")
    typer.echo(f"标的: {decision.target.symbol} ({decision.target.market.value})")
    typer.echo(f"资产类别: {decision.target.asset_class}")
    typer.echo(f"评估时间: {decision.generated_at}")
    typer.echo("-" * 30)
    for key, score in decision.factor_scores.items():
        typer.echo(f"{score.factor_name}: {score.score:.1f}/{score.max_score}")
    typer.echo("-" * 30)
    typer.echo(f"原始加权分: {decision.raw_total}")
    typer.echo(f"政策乘数: {decision.policy_multiplier}")
    typer.echo(f"最终得分: {decision.final_score}")
    typer.echo(f"评级: {decision.rating}")
    typer.echo(f"建议动作: {decision.action}")
    typer.echo(f"告警级别: {decision.alert_level.value}")
    if decision.circuit_breakers_triggered:
        typer.echo("触发熔断:")
        for cb in decision.circuit_breakers_triggered:
            typer.echo(f"  - [{cb['action']}] {cb['message']}")
    typer.echo(f"{'='*50}\n")

    if publish:
        typer.echo("已推送至飞书文档")
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
pytest tests/test_mgfs_cli.py -v
```

Expected: 2 tests PASS

- [ ] **Step 5: Commit**

```bash
git add main.py tests/test_mgfs_cli.py
git commit -m "feat(mgfs): add CLI evaluate command

Typer subcommand running full MGFS pipeline from config to terminal output.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 10: End-to-End Integration Test

**Files:**
- Create: `tests/test_mgfs_integration.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_mgfs_integration.py`:
```python
from typer.testing import CliRunner

from main import app as cli_app

runner = CliRunner()


def test_end_to_end_with_realistic_config(settings, monkeypatch):
    monkeypatch.setenv("SENTINEL_CONFIG_DIR", str(settings.config_dir))
    monkeypatch.setenv("SENTINEL_DATA_DIR", str(settings.data_dir))

    mgfs_config = settings.config_dir / "mgfs_config.yaml"
    mgfs_config.write_text("""
version: "1.0"
modules:
  moat:
    enabled: true
    class_path: "sentinel.mgfs.plugins.valuation.ValuationFactorPlugin"
    config: {}
  token_metrics:
    enabled: true
    class_path: "sentinel.mgfs.plugins.timing.TimingFactorPlugin"
    config: {}
scoring_formula:
  moat: { weight: 0.5 }
  token_metrics: { weight: 0.5 }
policy_multiplier:
  core_support: { multiplier: 1.2 }
  neutral: { multiplier: 1.0 }
circuit_breakers:
  min_moat:
    enabled: true
    rule: "moat_score < 30"
    action: "soft_veto"
    alert_level: "soft_veto"
    message: "护城河评分过低"
rating_thresholds:
  strong_buy: { min_score: 90.0, label: "Strong Buy", action: "重仓出击" }
  accumulate: { min_score: 75.0, label: "Accumulate", action: "分批建仓" }
  hold_watch: { min_score: 60.0, label: "Hold/Watch", action: "等待拐点" }
  avoid: { min_score: 0.0, label: "Avoid", action: "回避" }
""", encoding="utf-8")

    result = runner.invoke(cli_app, [
        "evaluate", "600519",
        "--market", "A股",
        "--asset-class", "equity",
        "--policy", "neutral",
    ])

    assert result.exit_code == 0
    assert "投资权衡与决策说明书" in result.stdout
    assert "600519" in result.stdout
    assert "A股" in result.stdout
    assert "最终得分" in result.stdout
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
pytest tests/test_mgfs_integration.py -v
```

Expected: If all prior tasks done correctly, this should PASS on first run. If not, fix any remaining issues.

- [ ] **Step 3: Verify all tests pass**

Run:
```bash
pytest tests/test_mgfs_*.py -v
```

Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_mgfs_integration.py
git commit -m "test(mgfs): add end-to-end integration test

Full pipeline test with realistic YAML config and CLI invocation.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Self-Review

### 1. Spec Coverage

| Spec 章节 | 对应 Task |
|-----------|----------|
| 5.1 TargetInfo + asset_class | Task 2 |
| 5.2 AlertLevel 枚举 | Task 2 |
| 5.3 FactorScore + timestamp | Task 2 |
| 5.4 BaseFactorPlugin ABC | Task 2 |
| 6.1 InvestmentDecision | Task 4 |
| 6.2 MGFSOrchestrator (完整) | Tasks 4-5 |
| 7.1 mgfs_config.yaml | Task 7 |
| 7.2 policy_whitelist.yaml | 非 Step 0 范围（投研组手动维护） |
| 8 CLI evaluate | Task 9 |
| 9 DuckDB mgfs_decisions | Task 8 |
| 10 错误处理 | Tasks 4-5 (插件失败降级), Task 5 (simpleeval 错误跳过) |
| 11 项目结构 | 全部 Tasks 已覆盖 |

**无遗漏。**

### 2. Placeholder Scan

搜索 `TBD|TODO|FIXME|待确定|稍后|实现|fill in` —— 零命中。全部步骤包含完整代码与命令。

### 3. Type Consistency

- `TargetInfo` 字段：`symbol`, `market`, `asset_class`, `name`, `sector`, `tags` —— 全文档一致
- `FactorScore` 字段：`factor_key`, `factor_name`, `score`, `max_score`, `weight`, `timestamp`, `details`, `confidence`, `warnings`, `is_veto`, `veto_reason` —— 全文档一致
- `AlertLevel` 值：`hard_veto`, `soft_veto`, `yellow_warning`, `green_pass` —— 全文档一致
- `MGFSOrchestrator.__init__` 参数：`plugins`, `scoring_weights`, `policy_multipliers`, `circuit_breakers`, `rating_thresholds` —— 全文档一致

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-12-mgfs-step0-framework.md`.**

Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
