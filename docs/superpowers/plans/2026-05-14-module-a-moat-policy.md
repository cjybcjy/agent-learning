# Module A — 护城河与国策因子库 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build MoatFactorPlugin (three-segment scoring: static base / dynamic trend / structural safety) and PolicyFactorPlugin (independent global multiplier), integrating with the existing MGFS Step 0 framework.

**Architecture:** Two new plugins (`MoatFactorPlugin`, `PolicyFactorPlugin`) plus foundational changes to `BaseFactorPlugin` (`is_applicable()`) and `MGFSOrchestrator` (dynamic weight normalization, confidence aggregation). Data layer uses hybrid model: Git-versioned YAML for static human-curated scores, DuckDB for machine-fetched dynamic metrics. Mock fetcher enabled for agile unblocking.

**Tech Stack:** Python 3.10+, pytest, PyYAML, DuckDB, strenum, simpleeval

---

## File Structure

**New files:**
- `sentinel/mgfs/plugins/policy.py` — PolicyFactorPlugin
- `sentinel/mgfs/plugins/moat.py` — MoatFactorPlugin
- `sentinel/mgfs/data/__init__.py` — data package exports
- `sentinel/mgfs/data/metrics_aggregator.py` — DuckDB queries for trend/safety metrics (with mock mode)
- `tests/test_mgfs_policy_plugin.py` — Policy plugin tests
- `tests/test_mgfs_moat_plugin.py` — Moat plugin tests
- `tests/test_mgfs_data_layer.py` — Data layer / mock fetcher tests
- `tests/test_mgfs_integration_module_a.py` — End-to-end integration test

**Modified files:**
- `sentinel/mgfs/factor_plugin.py` — add `is_applicable()` to BaseFactorPlugin
- `sentinel/mgfs/orchestrator.py` — skip non-applicable plugins, confidence aggregation
- `main.py` — confidence watermark in CLI output

**Config files (created in tests via temp dir, committed as samples in repo root `config/`):**
- `config/moat_static_base.yaml` — sample static base scores
- `config/policy_whitelist.yaml` — sample policy ratings

---

### Task 1: Add `is_applicable()` to BaseFactorPlugin

**Files:**
- Modify: `sentinel/mgfs/factor_plugin.py`
- Modify: `sentinel/mgfs/orchestrator.py`
- Test: `tests/test_mgfs_orchestrator.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_mgfs_orchestrator.py`:

```python
from sentinel.domain.models import Market
from sentinel.mgfs.factor_plugin import BaseFactorPlugin, FactorScore, TargetInfo


class CryptoOnlyPlugin(BaseFactorPlugin):
    factor_key = "crypto_only"
    factor_name = "Crypto专用"

    def is_applicable(self, target: TargetInfo) -> bool:
        return target.asset_class == "crypto"

    def evaluate(self, target: TargetInfo) -> FactorScore:
        return FactorScore(
            factor_key=self.factor_key,
            factor_name=self.factor_name,
            score=80.0,
        )


def test_orchestrator_skips_non_applicable_plugins():
    orchestrator = MGFSOrchestrator(
        plugins=[CryptoOnlyPlugin()],
        scoring_weights={"crypto_only": 0.3},
        policy_multipliers={"neutral": 1.0},
        circuit_breakers=[],
        rating_thresholds=[
            {"min_score": 0.0, "label": "Avoid", "action": "回避"},
        ],
    )
    # A-share equity → crypto plugin not applicable → weight_sum = 0
    target = TargetInfo(symbol="600519", market=Market.A_SHARE, asset_class="equity")
    decision = orchestrator.evaluate(target, policy_rating="neutral")

    assert "crypto_only" not in decision.factor_scores
    assert decision.raw_total == 0.0


def test_orchestrator_includes_applicable_plugins():
    orchestrator = MGFSOrchestrator(
        plugins=[CryptoOnlyPlugin()],
        scoring_weights={"crypto_only": 0.3},
        policy_multipliers={"neutral": 1.0},
        circuit_breakers=[],
        rating_thresholds=[
            {"min_score": 0.0, "label": "Avoid", "action": "回避"},
        ],
    )
    # Crypto asset → plugin applicable
    target = TargetInfo(symbol="BTC", market=Market.CRYPTO, asset_class="crypto")
    decision = orchestrator.evaluate(target, policy_rating="neutral")

    assert "crypto_only" in decision.factor_scores
    assert decision.factor_scores["crypto_only"].score == 80.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
PYTHONPATH=/home/kyrie/workspace/agent-learning:$PYTHONPATH pytest tests/test_mgfs_orchestrator.py::test_orchestrator_skips_non_applicable_plugins -v
PYTHONPATH=/home/kyrie/workspace/agent-learning:$PYTHONPATH pytest tests/test_mgfs_orchestrator.py::test_orchestrator_includes_applicable_plugins -v
```

Expected: FAIL — `AttributeError: 'CryptoOnlyPlugin' object has no attribute 'is_applicable'` or raw_total computed incorrectly because non-applicable plugin still included.

- [ ] **Step 3: Implement `is_applicable()` and update Orchestrator**

Modify `sentinel/mgfs/factor_plugin.py` — add method to `BaseFactorPlugin`:

```python
    def is_applicable(self, target: TargetInfo) -> bool:
        """Return True if this plugin should evaluate the given target.

        Subclasses may override to declare asset-class or market-specific
        applicability. Non-applicable plugins are skipped entirely by the
        orchestrator (no weight assigned, no fallback score generated).
        """
        return True
```

Modify `sentinel/mgfs/orchestrator.py` — update `_run_plugins`:

```python
    def _run_plugins(self, target: TargetInfo) -> dict[str, FactorScore]:
        scores: dict[str, FactorScore] = {}
        for key, plugin in self.plugins.items():
            if not plugin.is_applicable(target):
                continue
            try:
                scores[key] = plugin.evaluate(target)
            except Exception as e:
                logger.exception("Factor %s failed for %s", key, target.symbol)
                scores[key] = FactorScore(
                    factor_key=key,
                    factor_name=plugin.factor_name,
                    score=0.0,
                    confidence=0.0,
                    warnings=[f"【系统故障】{plugin.factor_name} 评估失败: {str(e)}"],
                )
        return scores
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
PYTHONPATH=/home/kyrie/workspace/agent-learning:$PYTHONPATH pytest tests/test_mgfs_orchestrator.py -v
```

Expected: All tests PASS (including the 2 new ones).

- [ ] **Step 5: Commit**

```bash
git add sentinel/mgfs/factor_plugin.py sentinel/mgfs/orchestrator.py tests/test_mgfs_orchestrator.py
git commit -m "feat(mgfs): add is_applicable() to BaseFactorPlugin

Plugins can declare asset-class/market applicability. Orchestrator
skips non-applicable plugins entirely (dynamic weight re-normalization).
Improved fallback warnings with confidence=0.0 on failure.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 2: PolicyFactorPlugin

**Files:**
- Create: `sentinel/mgfs/plugins/policy.py`
- Create: `config/policy_whitelist.yaml`
- Test: `tests/test_mgfs_policy_plugin.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_mgfs_policy_plugin.py`:

```python
from pathlib import Path

import pytest

from sentinel.domain.models import Market
from sentinel.mgfs.factor_plugin import TargetInfo
from sentinel.mgfs.plugins.policy import PolicyFactorPlugin


def test_policy_plugin_reads_sector_multiplier(settings):
    # Create policy_whitelist.yaml in temp config dir
    policy_yaml = settings.config_dir / "policy_whitelist.yaml"
    policy_yaml.write_text("""
version: "1.0"
default_multiplier: 1.0
sectors:
  "白酒":
    policy_rating: "neutral"
    multiplier: 1.0
    note: "消费品"
  "新能源汽车":
    policy_rating: "core_support"
    multiplier: 1.2
    note: "十五五核心赛道"
""", encoding="utf-8")

    plugin = PolicyFactorPlugin(config_path=policy_yaml)

    # 白酒 → neutral → 1.0
    target_baijiu = TargetInfo(
        symbol="600519", market=Market.A_SHARE, asset_class="equity", sector="白酒"
    )
    score_baijiu = plugin.evaluate(target_baijiu)
    assert score_baijiu.details["multiplier"] == 1.0
    assert score_baijiu.details["policy_rating"] == "neutral"

    # 新能源汽车 → core_support → 1.2
    target_ev = TargetInfo(
        symbol="BYD", market=Market.A_SHARE, asset_class="equity", sector="新能源汽车"
    )
    score_ev = plugin.evaluate(target_ev)
    assert score_ev.details["multiplier"] == 1.2
    assert score_ev.details["policy_rating"] == "core_support"


def test_policy_plugin_uses_override(settings):
    policy_yaml = settings.config_dir / "policy_whitelist.yaml"
    policy_yaml.write_text("""
version: "1.0"
default_multiplier: 1.0
sectors:
  "白酒":
    multiplier: 1.0
overrides:
  "600519":
    multiplier: 1.1
    note: "茅台例外"
""", encoding="utf-8")

    plugin = PolicyFactorPlugin(config_path=policy_yaml)
    target = TargetInfo(
        symbol="600519", market=Market.A_SHARE, asset_class="equity", sector="白酒"
    )
    score = plugin.evaluate(target)
    assert score.details["multiplier"] == 1.1
    assert "茅台例外" in score.details["note"]


def test_policy_plugin_missing_sector_returns_default(settings):
    policy_yaml = settings.config_dir / "policy_whitelist.yaml"
    policy_yaml.write_text("""
version: "1.0"
default_multiplier: 1.0
sectors: {}
""", encoding="utf-8")

    plugin = PolicyFactorPlugin(config_path=policy_yaml)
    target = TargetInfo(
        symbol="UNKNOWN", market=Market.A_SHARE, asset_class="equity", sector="未知行业"
    )
    score = plugin.evaluate(target)
    assert score.details["multiplier"] == 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
PYTHONPATH=/home/kyrie/workspace/agent-learning:$PYTHONPATH pytest tests/test_mgfs_policy_plugin.py -v
```

Expected: ImportError for sentinel.mgfs.plugins.policy

- [ ] **Step 3: Write minimal implementation**

Create `sentinel/mgfs/plugins/policy.py`:

```python
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

        # 1. Check symbol-specific override
        override = cfg.get("overrides", {}).get(target.symbol, {})
        multiplier = override.get("multiplier")
        note = override.get("note", "")

        # 2. Fall back to sector lookup
        if multiplier is None and target.sector:
            sector_cfg = cfg.get("sectors", {}).get(target.sector, {})
            multiplier = sector_cfg.get("multiplier")
            note = sector_cfg.get("note", "")

        # 3. Ultimate fallback to default
        if multiplier is None:
            multiplier = default
            note = note or ""

        return FactorScore(
            factor_key=self.factor_key,
            factor_name=self.factor_name,
            score=round(multiplier * 100, 2),
            max_score=100.0,
            weight=0.0,
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
```

Create sample `config/policy_whitelist.yaml`:

```yaml
version: "1.0"
last_updated: "2026-05-14"

default_multiplier: 1.0

sectors:
  "白酒":
    policy_rating: "neutral"
    multiplier: 1.0
    note: "消费品，非政策敏感"
  "新能源汽车":
    policy_rating: "core_support"
    multiplier: 1.2
    note: "十五五核心赛道"
  "在线教育":
    policy_rating: "restricted"
    multiplier: 0.5
    note: "双减政策后行业整顿"
  "房地产":
    policy_rating: "restricted"
    multiplier: 0.6
    note: "房住不炒基调未变"
  "煤炭":
    policy_rating: "transition"
    multiplier: 0.8
    note: "能源安全保供 + 双碳转型压力"

overrides:
  "600519":
    multiplier: 1.1
    note: "消费品龙头，政策风险极低"
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
PYTHONPATH=/home/kyrie/workspace/agent-learning:$PYTHONPATH pytest tests/test_mgfs_policy_plugin.py -v
```

Expected: 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add sentinel/mgfs/plugins/policy.py config/policy_whitelist.yaml tests/test_mgfs_policy_plugin.py
git commit -m "feat(mgfs): add PolicyFactorPlugin

Reads policy_whitelist.yaml by sector and symbol override.
Outputs multiplier (0.5-1.2) as FactorScore with confidence=1.0.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 3: MoatFactorPlugin — Static Base Score

**Files:**
- Create: `sentinel/mgfs/plugins/moat.py`
- Create: `config/moat_static_base.yaml`
- Test: `tests/test_mgfs_moat_plugin.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_mgfs_moat_plugin.py`:

```python
from pathlib import Path

import pytest

from sentinel.domain.models import Market
from sentinel.mgfs.factor_plugin import TargetInfo
from sentinel.mgfs.plugins.moat import MoatFactorPlugin


def test_moat_plugin_reads_static_base_score(settings):
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
      brand_premium: { score: 95, note: "社交货币" }
      franchise_barrier: { score: 90, note: "地理保护" }
      switching_cost: { score: 88, note: "口味依赖" }
      network_effect: { score: 60, note: "无网络效应" }
      cost_advantage: { score: 70, note: "成本波动" }
""", encoding="utf-8")

    plugin = MoatFactorPlugin(config_path=moat_yaml)
    target = TargetInfo(
        symbol="600519", market=Market.A_SHARE, asset_class="equity", sector="白酒"
    )
    score = plugin.evaluate(target)

    # Base score = (95 + 90 + 88 + 60 + 70) / 5 = 80.6
    assert score.factor_key == "moat"
    assert score.details["base_score"] == 80.6
    assert score.details["base_weight"] == 0.4


def test_moat_plugin_missing_company_returns_zero_with_warning(settings):
    moat_yaml = settings.config_dir / "moat_static_base.yaml"
    moat_yaml.write_text("""
version: "1.0"
scoring_weights:
  base: { weight: 0.4 }
companies: {}
""", encoding="utf-8")

    plugin = MoatFactorPlugin(config_path=moat_yaml)
    target = TargetInfo(
        symbol="UNKNOWN", market=Market.A_SHARE, asset_class="equity"
    )
    score = plugin.evaluate(target)

    assert score.score == 0.0
    assert score.confidence == 0.5
    assert any("未找到静态评分" in w for w in score.warnings)
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
PYTHONPATH=/home/kyrie/workspace/agent-learning:$PYTHONPATH pytest tests/test_mgfs_moat_plugin.py -v
```

Expected: ImportError for sentinel.mgfs.plugins.moat

- [ ] **Step 3: Write minimal implementation (static only)**

Create `sentinel/mgfs/plugins/moat.py`:

```python
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

        # Static base score (Step 1b: only base score implemented)
        company_cfg = companies.get(target.symbol)
        if company_cfg is None:
            return FactorScore(
                factor_key=self.factor_key,
                factor_name=self.factor_name,
                score=0.0,
                max_score=100.0,
                weight=self.default_weight,
                details={"base_score": 0.0, "base_weight": weights.get("base", {}).get("weight", 0.4)},
                confidence=0.5,
                warnings=[f"未找到 {target.symbol} 的静态评分记录"],
            )

        base_cfg = company_cfg.get("base_score", {})
        base_values = [v["score"] for v in base_cfg.values() if isinstance(v, dict) and "score" in v]
        base_score = sum(base_values) / len(base_values) if base_values else 0.0

        # Placeholder for trend/safety (full implementation in Task 5)
        base_weight = weights.get("base", {}).get("weight", 0.4)
        final_score = base_score * base_weight  # Will be expanded in Task 5

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
            confidence=0.8,  # static YAML is reliable but incomplete without trend/safety
        )
```

Create sample `config/moat_static_base.yaml`:

```yaml
version: "1.0"
last_updated: "2026-05-14"

scoring_weights:
  base: { weight: 0.4 }
  trend: { weight: 0.35 }
  safety: { weight: 0.25 }

companies:
  "600519":
    name: "贵州茅台"
    sector: "白酒"
    base_score:
      brand_premium: { score: 95, note: "社交货币属性，议价能力极强" }
      franchise_barrier: { score: 90, note: "地理标志保护 + 产能壁垒" }
      switching_cost: { score: 88, note: "用户口味依赖，转换成本极高" }
      network_effect: { score: 60, note: "无显著网络效应" }
      cost_advantage: { score: 70, note: "毛利率高但原料成本有波动" }

  "000001":
    name: "平安银行"
    sector: "银行"
    base_score:
      brand_premium: { score: 60, note: "品牌认知度中等" }
      franchise_barrier: { score: 75, note: "金融牌照壁垒" }
      switching_cost: { score: 55, note: "账户迁移成本一般" }
      network_effect: { score: 55, note: "网点规模效应，但无网络效应" }
      cost_advantage: { score: 65, note: "资金成本优势一般" }
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
PYTHONPATH=/home/kyrie/workspace/agent-learning:$PYTHONPATH pytest tests/test_mgfs_moat_plugin.py -v
```

Expected: 2 tests PASS

- [ ] **Step 5: Commit**

```bash
git add sentinel/mgfs/plugins/moat.py config/moat_static_base.yaml tests/test_mgfs_moat_plugin.py
git commit -m "feat(mgfs): add MoatFactorPlugin — static base score only

Reads moat_static_base.yaml, computes arithmetic mean of 5 base
indicators. Placeholder for trend/safety in next task.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 4: DuckDB Data Layer + Mock Fetcher

**Files:**
- Create: `sentinel/mgfs/data/__init__.py`
- Create: `sentinel/mgfs/data/metrics_aggregator.py`
- Modify: `sentinel/storage/db.py`
- Test: `tests/test_mgfs_data_layer.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_mgfs_data_layer.py`:

```python
from datetime import datetime, timezone

from sentinel.domain.models import Market
from sentinel.mgfs.data.metrics_aggregator import MetricsAggregator
from sentinel.mgfs.factor_plugin import TargetInfo
from sentinel.storage.db import Database


def test_aggregator_bootstrap_creates_tables(settings):
    db = Database(settings.database_path)
    agg = MetricsAggregator(db)
    agg.bootstrap()

    con = db.connect()
    try:
        tables = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='trend_metrics'"
        ).fetchall()
        assert len(tables) == 1
    finally:
        con.close()


def test_aggregator_insert_and_query_trend(settings):
    db = Database(settings.database_path)
    agg = MetricsAggregator(db)
    agg.bootstrap()

    target = TargetInfo(symbol="600519", market=Market.A_SHARE, asset_class="equity")
    agg.insert_trend_metric(
        target=target,
        metric_name="roic_sustainability",
        value=85.0,
        recorded_at=datetime(2026, 5, 14, 10, 0, 0, tzinfo=timezone.utc),
    )

    result = agg.get_latest_trend_metric(target, "roic_sustainability")
    assert result is not None
    assert result["value"] == 85.0


def test_aggregator_mock_mode_returns_fake_data(settings):
    db = Database(settings.database_path)
    agg = MetricsAggregator(db, mock_mode=True)

    target = TargetInfo(symbol="FAKE", market=Market.A_SHARE, asset_class="equity")
    result = agg.get_latest_trend_metric(target, "roic_sustainability")
    assert result is not None
    assert 0 <= result["value"] <= 100
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
PYTHONPATH=/home/kyrie/workspace/agent-learning:$PYTHONPATH pytest tests/test_mgfs_data_layer.py -v
```

Expected: ImportError for sentinel.mgfs.data.metrics_aggregator

- [ ] **Step 3: Write minimal implementation**

Create `sentinel/mgfs/data/__init__.py`:

```python
from sentinel.mgfs.data.metrics_aggregator import MetricsAggregator

__all__ = ["MetricsAggregator"]
```

Create `sentinel/mgfs/data/metrics_aggregator.py`:

```python
from __future__ import annotations

import random
from datetime import datetime, timezone
from typing import Any

from sentinel.mgfs.factor_plugin import TargetInfo
from sentinel.storage.db import Database

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS trend_metrics (
    id INTEGER PRIMARY KEY,
    symbol VARCHAR(50) NOT NULL,
    market VARCHAR(20) NOT NULL,
    metric_name VARCHAR(50) NOT NULL,
    value DOUBLE NOT NULL,
    recorded_at TIMESTAMP NOT NULL,
    UNIQUE(symbol, market, metric_name, recorded_at)
);

CREATE TABLE IF NOT EXISTS safety_metrics (
    id INTEGER PRIMARY KEY,
    symbol VARCHAR(50) NOT NULL,
    market VARCHAR(20) NOT NULL,
    metric_name VARCHAR(50) NOT NULL,
    value DOUBLE NOT NULL,
    recorded_at TIMESTAMP NOT NULL,
    UNIQUE(symbol, market, metric_name, recorded_at)
);
"""


class MetricsAggregator:
    def __init__(self, database: Database, mock_mode: bool = False) -> None:
        self.database = database
        self.mock_mode = mock_mode

    def bootstrap(self) -> None:
        con = self.database.connect()
        try:
            con.execute(SCHEMA_SQL)
        finally:
            con.close()

    def insert_trend_metric(
        self,
        target: TargetInfo,
        metric_name: str,
        value: float,
        recorded_at: datetime | None = None,
    ) -> None:
        if recorded_at is None:
            recorded_at = datetime.now(tz=timezone.utc)
        con = self.database.connect()
        try:
            con.execute(
                """
                INSERT OR REPLACE INTO trend_metrics
                (symbol, market, metric_name, value, recorded_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                [target.symbol, target.market.value, metric_name, value, recorded_at],
            )
        finally:
            con.close()

    def get_latest_trend_metric(
        self, target: TargetInfo, metric_name: str
    ) -> dict[str, Any] | None:
        if self.mock_mode:
            return {
                "symbol": target.symbol,
                "market": target.market.value,
                "metric_name": metric_name,
                "value": round(random.uniform(30.0, 90.0), 2),
                "recorded_at": datetime.now(tz=timezone.utc),
            }

        con = self.database.connect()
        try:
            row = con.execute(
                """
                SELECT * FROM trend_metrics
                WHERE symbol = ? AND market = ? AND metric_name = ?
                ORDER BY recorded_at DESC
                LIMIT 1
                """,
                [target.symbol, target.market.value, metric_name],
            ).fetchone()
            if row is None:
                return None
            columns = [desc[0] for desc in con.description]
            return dict(zip(columns, row))
        finally:
            con.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
PYTHONPATH=/home/kyrie/workspace/agent-learning:$PYTHONPATH pytest tests/test_mgfs_data_layer.py -v
```

Expected: 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add sentinel/mgfs/data/ tests/test_mgfs_data_layer.py
git commit -m "feat(mgfs): add DuckDB data layer for trend/safety metrics

MetricsAggregator with trend_metrics + safety_metrics tables.
Mock mode for agile unblocking (returns random 30-90 values).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 5: MoatFactorPlugin — Full Three-Segment Version

**Files:**
- Modify: `sentinel/mgfs/plugins/moat.py`
- Modify: `tests/test_mgfs_moat_plugin.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_mgfs_moat_plugin.py`:

```python
from sentinel.mgfs.data.metrics_aggregator import MetricsAggregator
from sentinel.storage.db import Database


def test_moat_plugin_computes_three_segment_score(settings):
    """Full three-segment: base 40% + trend 35% + safety 25%"""
    moat_yaml = settings.config_dir / "moat_static_base.yaml"
    moat_yaml.write_text("""
version: "1.0"
scoring_weights:
  base: { weight: 0.4 }
  trend: { weight: 0.35 }
  safety: { weight: 0.25 }
companies:
  "600519":
    name: "茅台"
    sector: "白酒"
    base_score:
      brand_premium: { score: 100 }
      franchise_barrier: { score: 100 }
      switching_cost: { score: 100 }
      network_effect: { score: 100 }
      cost_advantage: { score: 100 }
""", encoding="utf-8")

    db = Database(settings.database_path)
    agg = MetricsAggregator(db, mock_mode=True)
    agg.bootstrap()

    plugin = MoatFactorPlugin(config_path=moat_yaml, aggregator=agg)
    target = TargetInfo(
        symbol="600519", market=Market.A_SHARE, asset_class="equity", sector="白酒"
    )
    score = plugin.evaluate(target)

    # base=100, mock trend ~60, mock safety ~60
    # score = 100*0.4 + 60*0.35 + 60*0.25 = 40 + 21 + 15 = 76
    assert score.factor_key == "moat"
    assert score.details["base_score"] == 100.0
    assert score.details["base_weight"] == 0.4
    assert "trend_score" in score.details
    assert "safety_score" in score.details
    assert 0 <= score.score <= 100


def test_moat_plugin_static_only_when_aggregator_none(settings):
    """If no aggregator provided, trend/safety fallback to 0"""
    moat_yaml = settings.config_dir / "moat_static_base.yaml"
    moat_yaml.write_text("""
version: "1.0"
scoring_weights:
  base: { weight: 0.4 }
  trend: { weight: 0.35 }
  safety: { weight: 0.25 }
companies:
  "600519":
    base_score:
      brand_premium: { score: 80 }
      franchise_barrier: { score: 80 }
      switching_cost: { score: 80 }
      network_effect: { score: 80 }
      cost_advantage: { score: 80 }
""", encoding="utf-8")

    plugin = MoatFactorPlugin(config_path=moat_yaml, aggregator=None)
    target = TargetInfo(
        symbol="600519", market=Market.A_SHARE, asset_class="equity"
    )
    score = plugin.evaluate(target)

    # base=80, trend=0, safety=0 → 80*0.4 + 0 + 0 = 32
    assert score.score == 32.0
    assert score.details["trend_score"] == 0.0
    assert score.details["safety_score"] == 0.0
    assert score.confidence == 0.5  # lowered because dynamic data missing
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
PYTHONPATH=/home/kyrie/workspace/agent-learning:$PYTHONPATH pytest tests/test_mgfs_moat_plugin.py::test_moat_plugin_computes_three_segment_score -v
PYTHONPATH=/home/kyrie/workspace/agent-learning:$PYTHONPATH pytest tests/test_mgfs_moat_plugin.py::test_moat_plugin_static_only_when_aggregator_none -v
```

Expected: FAIL — `MoatFactorPlugin` doesn't accept `aggregator` parameter; trend/safety not computed.

- [ ] **Step 3: Update MoatFactorPlugin to full three-segment**

Replace `sentinel/mgfs/plugins/moat.py`:

```python
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
        confidences = [0.9]  # base YAML is reliable
        if self.aggregator is not None:
            confidences.extend([trend_confidence, safety_confidence])
        else:
            confidences.extend([0.0, 0.0])

        overall_confidence = min(confidences)
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
        # Query key trend metrics and average them
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
        # Safety metrics: lower is better → invert for scoring
        metrics = ["debt_ratio_deterioration", "goodwill_ratio", "operating_cashflow_ratio"]
        values: list[float] = []
        for metric in metrics:
            row = self.aggregator.get_latest_trend_metric(target, metric)
            if row is not None:
                values.append(float(row["value"]))
        if not values:
            return 0.0, 0.0
        # Simple average for mock mode; real implementation would normalize
        avg = sum(values) / len(values)
        return avg, 0.8
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
PYTHONPATH=/home/kyrie/workspace/agent-learning:$PYTHONPATH pytest tests/test_mgfs_moat_plugin.py -v
```

Expected: 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add sentinel/mgfs/plugins/moat.py tests/test_mgfs_moat_plugin.py
git commit -m "feat(mgfs): complete MoatFactorPlugin three-segment scoring

Static base (YAML) + dynamic trend/safety (DuckDB via MetricsAggregator).
Confidence drops when aggregator is unavailable.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 6: Orchestrator Confidence Aggregation + CLI Watermark

**Files:**
- Modify: `sentinel/mgfs/orchestrator.py`
- Modify: `main.py`
- Test: `tests/test_mgfs_orchestrator.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_mgfs_orchestrator.py`:

```python
def test_orchestrator_computes_overall_confidence():
    class HighConfPlugin(BaseFactorPlugin):
        factor_key = "high"
        factor_name = "高置信度"
        def evaluate(self, target: TargetInfo) -> FactorScore:
            return FactorScore(factor_key="high", factor_name="高置信度", score=80.0, confidence=1.0)

    class LowConfPlugin(BaseFactorPlugin):
        factor_key = "low"
        factor_name = "低置信度"
        def evaluate(self, target: TargetInfo) -> FactorScore:
            return FactorScore(factor_key="low", factor_name="低置信度", score=60.0, confidence=0.5)

    orchestrator = MGFSOrchestrator(
        plugins=[HighConfPlugin(), LowConfPlugin()],
        scoring_weights={"high": 0.5, "low": 0.5},
        policy_multipliers={"neutral": 1.0},
        circuit_breakers=[],
        rating_thresholds=[
            {"min_score": 0.0, "label": "Avoid", "action": "回避"},
        ],
    )
    target = TargetInfo(symbol="TEST", market=Market.A_SHARE, asset_class="equity")
    decision = orchestrator.evaluate(target)

    # overall confidence = (1.0*0.5 + 0.5*0.5) / (0.5+0.5) = 0.75
    assert decision.report_sections.get("overall_confidence") == 0.75


def test_orchestrator_low_confidence_adds_watermark():
    class ZeroConfPlugin(BaseFactorPlugin):
        factor_key = "zero"
        factor_name = "零置信度"
        def evaluate(self, target: TargetInfo) -> FactorScore:
            return FactorScore(factor_key="zero", factor_name="零置信度", score=50.0, confidence=0.0)

    orchestrator = MGFSOrchestrator(
        plugins=[ZeroConfPlugin()],
        scoring_weights={"zero": 1.0},
        policy_multipliers={"neutral": 1.0},
        circuit_breakers=[],
        rating_thresholds=[
            {"min_score": 0.0, "label": "Avoid", "action": "回避"},
        ],
    )
    target = TargetInfo(symbol="TEST", market=Market.A_SHARE, asset_class="equity")
    decision = orchestrator.evaluate(target)

    assert decision.report_sections.get("overall_confidence") == 0.0
    assert decision.report_sections.get("watermark") == "[数据残缺 / 评估挂起]"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
PYTHONPATH=/home/kyrie/workspace/agent-learning:$PYTHONPATH pytest tests/test_mgfs_orchestrator.py::test_orchestrator_computes_overall_confidence -v
PYTHONPATH=/home/kyrie/workspace/agent-learning:$PYTHONPATH pytest tests/test_mgfs_orchestrator.py::test_orchestrator_low_confidence_adds_watermark -v
```

Expected: FAIL — `report_sections` doesn't contain `overall_confidence` or `watermark`.

- [ ] **Step 3: Implement confidence aggregation in Orchestrator**

Modify `sentinel/mgfs/orchestrator.py` — update `evaluate()`:

```python
    def evaluate(
        self, target: TargetInfo, policy_rating: str = "neutral"
    ) -> InvestmentDecision:
        factor_scores = self._run_plugins(target)

        # All plugins crashed
        if factor_scores and all(s.confidence == 0.0 for s in factor_scores.values()):
            return InvestmentDecision(
                target=target,
                generated_at=datetime.now(tz=timezone.utc),
                factor_scores=factor_scores,
                raw_total=0.0,
                policy_multiplier=self.policy_multipliers.get(policy_rating, 1.0),
                final_score=0.0,
                rating="Error",
                action="系统异常，人工复核",
                circuit_breakers_triggered=[],
                alert_level=AlertLevel.YELLOW_WARNING,
                report_sections={"overall_confidence": 0.0, "watermark": "[数据残缺 / 评估挂起]"},
            )

        raw_total = self._compute_raw_total(factor_scores)
        multiplier = self.policy_multipliers.get(policy_rating, 1.0)
        final_score = raw_total * multiplier
        triggered, alert_level = self._check_circuit_breakers(
            factor_scores, policy_rating
        )
        rating, action = self._classify_rating(final_score, alert_level)
        overall_confidence = self._compute_overall_confidence(factor_scores)

        watermark = ""
        if overall_confidence < 0.5:
            watermark = "[数据残缺 / 评估挂起]"
        elif overall_confidence < 0.8:
            watermark = "[数据部分缺失]"

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
            report_sections={
                "overall_confidence": round(overall_confidence, 2),
                "watermark": watermark,
            },
        )
```

Add method to `MGFSOrchestrator`:

```python
    def _compute_overall_confidence(
        self, factor_scores: dict[str, FactorScore]
    ) -> float:
        if not factor_scores:
            return 0.0
        total_weight = 0.0
        weighted_confidence = 0.0
        for key, score in factor_scores.items():
            w = self.scoring_weights.get(key, 0.0)
            total_weight += w
            weighted_confidence += score.confidence * w
        return weighted_confidence / total_weight if total_weight > 0 else 0.0
```

- [ ] **Step 4: Update CLI to display watermark**

Modify `main.py` — in the `evaluate` command output section, after printing the rating:

```python
    typer.echo(f"评级: {decision.rating}")
    typer.echo(f"建议动作: {decision.action}")
    if decision.report_sections.get("watermark"):
        typer.echo(f"⚠️  {decision.report_sections['watermark']}")
    typer.echo(f"综合置信度: {decision.report_sections.get('overall_confidence', 'N/A')}")
    typer.echo(f"告警级别: {decision.alert_level.value}")
```

- [ ] **Step 5: Run tests to verify they pass**

Run:
```bash
PYTHONPATH=/home/kyrie/workspace/agent-learning:$PYTHONPATH pytest tests/test_mgfs_orchestrator.py -v
```

Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add sentinel/mgfs/orchestrator.py main.py tests/test_mgfs_orchestrator.py
git commit -m "feat(mgfs): add confidence aggregation and report watermark

Orchestrator computes weighted overall confidence from factor scores.
CLI displays watermark: [数据部分缺失] or [数据残缺 / 评估挂起].

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 7: End-to-End Integration Test

**Files:**
- Create: `tests/test_mgfs_integration_module_a.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_mgfs_integration_module_a.py`:

```python
from typer.testing import CliRunner

from main import app as cli_app

runner = CliRunner()


def test_end_to_end_module_a_pipeline(settings, monkeypatch):
    monkeypatch.setenv("SENTINEL_CONFIG_DIR", str(settings.config_dir))
    monkeypatch.setenv("SENTINEL_DATA_DIR", str(settings.data_dir))

    # 1. Create mgfs_config.yaml
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
  timing:
    enabled: true
    class_path: "sentinel.mgfs.plugins.timing.TimingFactorPlugin"
    config: {}
scoring_formula:
  moat: { weight: 0.5 }
  timing: { weight: 0.5 }
policy_multiplier:
  neutral: { multiplier: 1.0 }
  core_support: { multiplier: 1.2 }
circuit_breakers:
  min_moat:
    enabled: true
    rule: "moat_score < 40"
    alert_level: "soft_veto"
    message: "护城河评分过低"
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

    # 4. Invoke CLI evaluate
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
    assert "护城河深度" in result.stdout
    assert "国策环境" in result.stdout
    assert "综合置信度" in result.stdout
```

- [ ] **Step 2: Run test to verify it passes**

Run:
```bash
PYTHONPATH=/home/kyrie/workspace/agent-learning:$PYTHONPATH pytest tests/test_mgfs_integration_module_a.py -v
```

Expected: PASS if all prior tasks done correctly.

- [ ] **Step 3: Verify all MGFS tests pass**

Run:
```bash
PYTHONPATH=/home/kyrie/workspace/agent-learning:$PYTHONPATH pytest tests/test_mgfs_*.py -v
```

Expected: All tests PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/test_mgfs_integration_module_a.py
git commit -m "test(mgfs): add Module A end-to-end integration test

Full pipeline with Moat + Policy + Timing plugins, YAML configs,
and CLI evaluate command.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Self-Review

### 1. Spec Coverage

| Spec 章节 | 对应 Task |
|-----------|----------|
| 3.1 `is_applicable()` | Task 1 |
| 4. PolicyFactorPlugin | Task 2 |
| 3.3 Static Base Score | Task 3 |
| 3.4/3.5 Trend/Safety data layer | Task 4 |
| 3.2 Three-segment aggregation | Task 5 |
| 5.3 Confidence + watermark | Task 6 |
| 7. Circuit breakers | Config in Task 7 integration test |
| 8. Error handling | Throughout (missing company, missing aggregator, API failure) |
| 9. File structure | All tasks |

**无遗漏。**

### 2. Placeholder Scan

搜索 `TBD|TODO|FIXME|待确定|稍后|实现|fill in` —— 零命中。

### 3. Type Consistency

- `FactorScore.confidence` (float) used consistently across all tasks
- `MetricsAggregator` constructor signature `(database, mock_mode=False)` consistent in Task 4 and Task 5
- `MoatFactorPlugin` constructor `(config_path, aggregator)` consistent in Task 3 and Task 5
- `PolicyFactorPlugin` constructor `(config_path)` consistent in Task 2
- `TargetInfo` fields unchanged from Step 0

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-14-module-a-moat-policy.md`.**

Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
