# Sentinel Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the initial project skeleton for Sentinel with a working CLI entrypoint, configuration loading, DuckDB storage bootstrap, and a tested hourly-run stub that can persist and query one synthetic market snapshot.

**Architecture:** Phase 1 establishes the executable spine of the system before any real collector or model integration. The code path is `main.py -> app bootstrap -> config loader -> DuckDB repository -> run service`, with synthetic in-memory records standing in for later collectors so the storage and CLI contract are stable from the start.

**Tech Stack:** Python 3.11+, pytest, DuckDB, pydantic-settings, PyYAML, typer

---

## File Structure

### Files to create

- `main.py` — CLI entrypoint that parses market/report/time arguments and invokes the application service.
- `sentinel/__init__.py` — package marker.
- `sentinel/app.py` — bootstrap layer wiring settings, database, and run service.
- `sentinel/domain/__init__.py` — domain package marker.
- `sentinel/domain/models.py` — core dataclasses and enums used by Phase 1.
- `sentinel/config.py` — settings loader for YAML-based market configuration and runtime paths.
- `sentinel/storage/__init__.py` — storage package marker.
- `sentinel/storage/db.py` — DuckDB connection factory and schema bootstrap.
- `sentinel/storage/repository.py` — repository API for inserting and reading hourly heat snapshots.
- `sentinel/services/__init__.py` — services package marker.
- `sentinel/services/run_pipeline.py` — Phase 1 pipeline service using synthetic records to exercise persistence flow.
- `config/markets.yaml` — starter market-to-platform mapping used by settings loader.
- `config/weights.yaml` — placeholder Phase 1 weights config consumed by settings loader.
- `requirements.txt` — runtime dependencies.
- `tests/conftest.py` — shared pytest fixtures for temporary config and database paths.
- `tests/test_config.py` — tests for YAML config loading.
- `tests/test_repository.py` — tests for DuckDB schema bootstrap and read/write behavior.
- `tests/test_cli.py` — CLI integration test for one synthetic run.

### Files to modify

- `README.md` — replace empty file with Phase 1 bootstrap usage instructions.

## Task 1: Create dependency manifest and package skeleton

**Files:**
- Create: `requirements.txt`
- Create: `sentinel/__init__.py`
- Create: `sentinel/domain/__init__.py`
- Create: `sentinel/storage/__init__.py`
- Create: `sentinel/services/__init__.py`
- Test: none

- [ ] **Step 1: Create runtime dependency manifest**

```text
# requirements.txt
Typer==0.16.0
PyYAML==6.0.2
pydantic==2.11.4
pydantic-settings==2.9.1
duckdb==1.2.2
pytest==8.3.5
```

- [ ] **Step 2: Create package marker files**

```python
# sentinel/__init__.py
__all__ = ["__version__"]

__version__ = "0.1.0"
```

```python
# sentinel/domain/__init__.py
"""Domain models for Sentinel."""
```

```python
# sentinel/storage/__init__.py
"""Storage package for Sentinel."""
```

```python
# sentinel/services/__init__.py
"""Service layer for Sentinel."""
```

- [ ] **Step 3: Verify files exist**

Run: `python - <<'PY'
from pathlib import Path
for path in [
    'requirements.txt',
    'sentinel/__init__.py',
    'sentinel/domain/__init__.py',
    'sentinel/storage/__init__.py',
    'sentinel/services/__init__.py',
]:
    assert Path(path).exists(), path
print('ok')
PY`

Expected: `ok`

- [ ] **Step 4: Commit skeleton manifest**

```bash
git add requirements.txt sentinel/__init__.py sentinel/domain/__init__.py sentinel/storage/__init__.py sentinel/services/__init__.py
git commit -m "chore: add sentinel package skeleton"
```

## Task 2: Define core domain models

**Files:**
- Create: `sentinel/domain/models.py`
- Test: `tests/test_repository.py`

- [ ] **Step 1: Write the failing test for snapshot serialization shape**

```python
# tests/test_repository.py
from datetime import datetime

from sentinel.domain.models import HeatSnapshot, Market


def test_heat_snapshot_to_row_contains_expected_fields() -> None:
    snapshot = HeatSnapshot(
        timestamp=datetime(2026, 4, 29, 10, 0, 0),
        market=Market.A_SHARE,
        symbol="600519",
        base_heat=12.5,
        kol_multiplier=1.2,
        sentiment_score=0.55,
        directed_heat=8.25,
        change_pct=18.0,
        top_source="xueqiu",
        rank_bullish=1,
        rank_bearish=None,
        is_anomaly=False,
    )

    row = snapshot.to_row()

    assert row["market"] == "A股"
    assert row["symbol"] == "600519"
    assert row["directed_heat"] == 8.25
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_repository.py::test_heat_snapshot_to_row_contains_expected_fields -v`

Expected: FAIL with `ModuleNotFoundError` for `sentinel.domain.models`

- [ ] **Step 3: Write minimal domain model implementation**

```python
# sentinel/domain/models.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class Market(StrEnum):
    A_SHARE = "A股"
    HK = "港股"
    US = "美股"
    CRYPTO = "币圈"


@dataclass(slots=True)
class HeatSnapshot:
    timestamp: datetime
    market: Market
    symbol: str
    base_heat: float
    kol_multiplier: float
    sentiment_score: float
    directed_heat: float
    change_pct: float | None
    top_source: str
    rank_bullish: int | None
    rank_bearish: int | None
    is_anomaly: bool

    def to_row(self) -> dict[str, object]:
        return {
            "timestamp": self.timestamp,
            "market": self.market.value,
            "symbol": self.symbol,
            "base_heat": self.base_heat,
            "kol_multiplier": self.kol_multiplier,
            "sentiment_score": self.sentiment_score,
            "directed_heat": self.directed_heat,
            "change_pct": self.change_pct,
            "top_source": self.top_source,
            "rank_bullish": self.rank_bullish,
            "rank_bearish": self.rank_bearish,
            "is_anomaly": self.is_anomaly,
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_repository.py::test_heat_snapshot_to_row_contains_expected_fields -v`

Expected: PASS

- [ ] **Step 5: Commit domain models**

```bash
git add sentinel/domain/models.py tests/test_repository.py
git commit -m "feat: add core heat snapshot domain model"
```

## Task 3: Implement YAML configuration loader

**Files:**
- Create: `sentinel/config.py`
- Create: `config/markets.yaml`
- Create: `config/weights.yaml`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write failing config loader tests**

```python
# tests/test_config.py
from pathlib import Path

from sentinel.config import AppSettings, load_market_config


def test_load_market_config_reads_collectors(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "markets.yaml").write_text(
        "A股:\n  collectors: [xueqiu, eastmoney]\n",
        encoding="utf-8",
    )

    data = load_market_config(config_dir / "markets.yaml")

    assert data["A股"]["collectors"] == ["xueqiu", "eastmoney"]


def test_app_settings_resolves_duckdb_path(tmp_path: Path) -> None:
    settings = AppSettings(
        base_dir=tmp_path,
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
        database_name="sentinel.duckdb",
    )

    assert settings.database_path == tmp_path / "data" / "sentinel.duckdb"


def test_app_settings_resolves_relative_dirs_from_base_dir(tmp_path: Path) -> None:
    settings = AppSettings(base_dir=tmp_path, config_dir=Path("config"), data_dir=Path("data"))

    assert settings.resolved_config_dir == tmp_path / "config"
    assert settings.database_path == tmp_path / "data" / "sentinel.duckdb"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_config.py -v`

Expected: FAIL with `ModuleNotFoundError` for `sentinel.config`

- [ ] **Step 3: Write settings loader and starter YAML files**

```python
# sentinel/config.py
from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    base_dir: Path = Path(__file__).resolve().parent.parent
    config_dir: Path = Path("config")
    data_dir: Path = Path("data")
    database_name: str = "sentinel.duckdb"

    model_config = SettingsConfigDict(env_prefix="SENTINEL_", extra="ignore")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def resolved_config_dir(self) -> Path:
        if self.config_dir.is_absolute():
            return self.config_dir
        return self.base_dir / self.config_dir

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_path(self) -> Path:
        if self.data_dir.is_absolute():
            return self.data_dir / self.database_name
        return self.base_dir / self.data_dir / self.database_name


def load_market_config(path: Path) -> dict[str, dict[str, object]]:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def load_weights_config(path: Path) -> dict[str, object]:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}
```

```yaml
# config/markets.yaml
A股:
  collectors: [xueqiu, eastmoney, tonghuashun, weibo_finance, baidu_index]
  platform_weights:
    xueqiu: 0.30
    eastmoney: 0.25
    tonghuashun: 0.20
    weibo_finance: 0.15
    baidu_index: 0.10
港股:
  collectors: [xueqiu_hk, futu, eastmoney_hk, weibo_finance]
  platform_weights:
    xueqiu_hk: 0.30
    futu: 0.30
    eastmoney_hk: 0.25
    weibo_finance: 0.15
```

```yaml
# config/weights.yaml
base_heat:
  posts: 0.35
  comments: 0.30
  likes: 0.20
  shares: 0.15
kol_multiplier: 3.0
```

- [ ] **Step 4: Run tests to verify config loader passes**

Run: `pytest tests/test_config.py -v`

Expected: PASS

- [ ] **Step 5: Commit config loader**

```bash
git add sentinel/config.py config/markets.yaml config/weights.yaml tests/test_config.py
git commit -m "feat: add yaml settings loader"
```

## Task 4: Bootstrap DuckDB schema and repository

**Files:**
- Create: `sentinel/storage/db.py`
- Create: `sentinel/storage/repository.py`
- Modify: `tests/test_repository.py`

- [ ] **Step 1: Extend repository tests to cover schema bootstrap and insert/query**

```python
# tests/test_repository.py
from datetime import datetime

from sentinel.domain.models import HeatSnapshot, Market
from sentinel.storage.db import Database
from sentinel.storage.repository import HeatMetricRepository


def test_heat_snapshot_to_row_contains_expected_fields() -> None:
    snapshot = HeatSnapshot(
        timestamp=datetime(2026, 4, 29, 10, 0, 0),
        market=Market.A_SHARE,
        symbol="600519",
        base_heat=12.5,
        kol_multiplier=1.2,
        sentiment_score=0.55,
        directed_heat=8.25,
        change_pct=18.0,
        top_source="xueqiu",
        rank_bullish=1,
        rank_bearish=None,
        is_anomaly=False,
    )

    row = snapshot.to_row()

    assert row["market"] == "A股"
    assert row["symbol"] == "600519"
    assert row["directed_heat"] == 8.25


def test_repository_bootstraps_schema_and_reads_back_rows(tmp_path) -> None:
    database = Database(tmp_path / "sentinel.duckdb")
    repository = HeatMetricRepository(database)
    repository.bootstrap()

    snapshot = HeatSnapshot(
        timestamp=datetime(2026, 4, 29, 10, 0, 0),
        market=Market.A_SHARE,
        symbol="600519",
        base_heat=12.5,
        kol_multiplier=1.2,
        sentiment_score=0.55,
        directed_heat=8.25,
        change_pct=18.0,
        top_source="xueqiu",
        rank_bullish=1,
        rank_bearish=None,
        is_anomaly=False,
    )

    repository.upsert_snapshots([snapshot])
    rows = repository.list_by_market(Market.A_SHARE)

    assert len(rows) == 1
    assert rows[0].symbol == "600519"
    assert rows[0].top_source == "xueqiu"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_repository.py -v`

Expected: FAIL with `ModuleNotFoundError` for `sentinel.storage.db`

- [ ] **Step 3: Implement database bootstrap and repository**

```python
# sentinel/storage/db.py
from __future__ import annotations

from pathlib import Path

import duckdb

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS heat_metrics (
    timestamp TIMESTAMP NOT NULL,
    market VARCHAR NOT NULL,
    symbol VARCHAR NOT NULL,
    base_heat DOUBLE NOT NULL,
    kol_multiplier DOUBLE NOT NULL,
    sentiment_score DOUBLE NOT NULL,
    directed_heat DOUBLE NOT NULL,
    change_pct DOUBLE,
    top_source VARCHAR,
    rank_bullish INTEGER,
    rank_bearish INTEGER,
    is_anomaly BOOLEAN DEFAULT FALSE,
    PRIMARY KEY (timestamp, market, symbol)
);
"""


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    def connect(self) -> duckdb.DuckDBPyConnection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        return duckdb.connect(str(self.path))

    def bootstrap(self) -> None:
        with self.connect() as connection:
            connection.execute(SCHEMA_SQL)
```

```python
# sentinel/storage/repository.py
from __future__ import annotations

from datetime import datetime

from sentinel.domain.models import HeatSnapshot, Market
from sentinel.storage.db import Database


class HeatMetricRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def bootstrap(self) -> None:
        self.database.bootstrap()

    def upsert_snapshots(self, snapshots: list[HeatSnapshot]) -> None:
        if not snapshots:
            return

        rows = [snapshot.to_row() for snapshot in snapshots]
        with self.database.connect() as connection:
            connection.executemany(
                """
                INSERT OR REPLACE INTO heat_metrics (
                    timestamp, market, symbol, base_heat, kol_multiplier,
                    sentiment_score, directed_heat, change_pct, top_source,
                    rank_bullish, rank_bearish, is_anomaly
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        row["timestamp"],
                        row["market"],
                        row["symbol"],
                        row["base_heat"],
                        row["kol_multiplier"],
                        row["sentiment_score"],
                        row["directed_heat"],
                        row["change_pct"],
                        row["top_source"],
                        row["rank_bullish"],
                        row["rank_bearish"],
                        row["is_anomaly"],
                    )
                    for row in rows
                ],
            )

    def list_by_market(self, market: Market) -> list[HeatSnapshot]:
        with self.database.connect() as connection:
            result = connection.execute(
                """
                SELECT timestamp, market, symbol, base_heat, kol_multiplier,
                       sentiment_score, directed_heat, change_pct, top_source,
                       rank_bullish, rank_bearish, is_anomaly
                FROM heat_metrics
                WHERE market = ?
                ORDER BY timestamp DESC, symbol ASC
                """,
                [market.value],
            ).fetchall()

        return [
            HeatSnapshot(
                timestamp=row[0],
                market=Market(row[1]),
                symbol=row[2],
                base_heat=row[3],
                kol_multiplier=row[4],
                sentiment_score=row[5],
                directed_heat=row[6],
                change_pct=row[7],
                top_source=row[8],
                rank_bullish=row[9],
                rank_bearish=row[10],
                is_anomaly=row[11],
            )
            for row in result
        ]
```

- [ ] **Step 4: Run tests to verify repository passes**

Run: `pytest tests/test_repository.py -v`

Expected: PASS

- [ ] **Step 5: Commit DuckDB repository**

```bash
git add sentinel/storage/db.py sentinel/storage/repository.py tests/test_repository.py
git commit -m "feat: add duckdb heat metric repository"
```

## Task 5: Build application bootstrap and synthetic run pipeline

**Files:**
- Create: `sentinel/app.py`
- Create: `sentinel/services/run_pipeline.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Write failing service test for one synthetic market run**

```python
# tests/conftest.py
from pathlib import Path

import pytest

from sentinel.config import AppSettings


@pytest.fixture
def settings(tmp_path: Path) -> AppSettings:
    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    config_dir.mkdir()
    data_dir.mkdir()
    (config_dir / "markets.yaml").write_text(
        "A股:\n  collectors: [synthetic]\n",
        encoding="utf-8",
    )
    (config_dir / "weights.yaml").write_text(
        "base_heat:\n  posts: 0.35\n",
        encoding="utf-8",
    )
    return AppSettings(base_dir=tmp_path, config_dir=config_dir, data_dir=data_dir)
```

```python
# tests/test_cli.py
from sentinel.app import build_application
from sentinel.domain.models import Market


def test_application_run_persists_synthetic_snapshot(settings) -> None:
    app = build_application(settings)

    snapshots = app.run_market(market=Market.A_SHARE)

    assert len(snapshots) == 1
    assert snapshots[0].symbol == "SYNTH-A股"
    assert app.repository.list_by_market(Market.A_SHARE)[0].symbol == "SYNTH-A股"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cli.py::test_application_run_persists_synthetic_snapshot -v`

Expected: FAIL with `ModuleNotFoundError` for `sentinel.app`

- [ ] **Step 3: Implement bootstrap and synthetic pipeline**

```python
# sentinel/services/run_pipeline.py
from __future__ import annotations

from datetime import datetime, timezone

from sentinel.domain.models import HeatSnapshot, Market
from sentinel.storage.repository import HeatMetricRepository


class RunPipelineService:
    def __init__(self, repository: HeatMetricRepository) -> None:
        self.repository = repository

    def run_market(self, market: Market) -> list[HeatSnapshot]:
        snapshot = HeatSnapshot(
            timestamp=datetime.now(tz=timezone.utc).replace(tzinfo=None),
            market=market,
            symbol=f"SYNTH-{market.value}",
            base_heat=10.0,
            kol_multiplier=1.0,
            sentiment_score=0.25,
            directed_heat=2.5,
            change_pct=None,
            top_source="synthetic",
            rank_bullish=1,
            rank_bearish=None,
            is_anomaly=False,
        )
        self.repository.upsert_snapshots([snapshot])
        return [snapshot]
```

```python
# sentinel/app.py
from __future__ import annotations

from dataclasses import dataclass

from sentinel.config import AppSettings
from sentinel.services.run_pipeline import RunPipelineService
from sentinel.storage.db import Database
from sentinel.storage.repository import HeatMetricRepository


@dataclass(slots=True)
class SentinelApplication:
    repository: HeatMetricRepository
    runner: RunPipelineService

    def run_market(self, market):
        self.repository.bootstrap()
        return self.runner.run_market(market)


def build_application(settings: AppSettings) -> SentinelApplication:
    database = Database(settings.database_path)
    repository = HeatMetricRepository(database)
    runner = RunPipelineService(repository)
    return SentinelApplication(repository=repository, runner=runner)
```

- [ ] **Step 4: Run tests to verify service passes**

Run: `pytest tests/test_cli.py::test_application_run_persists_synthetic_snapshot -v`

Expected: PASS

- [ ] **Step 5: Commit application bootstrap**

```bash
git add sentinel/app.py sentinel/services/run_pipeline.py tests/conftest.py tests/test_cli.py
git commit -m "feat: add sentinel bootstrap pipeline"
```

## Task 6: Add CLI entrypoint and integration output

**Files:**
- Create: `main.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Extend CLI test to invoke Typer app**

```python
# tests/test_cli.py
from typer.testing import CliRunner

from main import app as cli_app
from sentinel.app import build_application
from sentinel.domain.models import Market

runner = CliRunner()


def test_application_run_persists_synthetic_snapshot(settings) -> None:
    app = build_application(settings)

    snapshots = app.run_market(market=Market.A_SHARE)

    assert len(snapshots) == 1
    assert snapshots[0].symbol == "SYNTH-A股"
    assert app.repository.list_by_market(Market.A_SHARE)[0].symbol == "SYNTH-A股"


def test_cli_run_market_command(settings, monkeypatch) -> None:
    monkeypatch.setenv("SENTINEL_CONFIG_DIR", str(settings.config_dir))
    monkeypatch.setenv("SENTINEL_DATA_DIR", str(settings.data_dir))

    result = runner.invoke(cli_app, ["run", "--market", "A股"])

    assert result.exit_code == 0
    assert "stored 1 snapshot for A股" in result.stdout
```

- [ ] **Step 2: Run tests to verify CLI test fails**

Run: `pytest tests/test_cli.py::test_cli_run_market_command -v`

Expected: FAIL with `ModuleNotFoundError` for `main`

- [ ] **Step 3: Implement Typer CLI entrypoint**

```python
# main.py
from __future__ import annotations

import typer

from sentinel.app import build_application
from sentinel.config import AppSettings
from sentinel.domain.models import Market

app = typer.Typer(no_args_is_help=True)


@app.command("run")
def run_command(
    market: Market = typer.Option(..., "--market"),
    report: str | None = typer.Option(None, "--report"),
    time: str | None = typer.Option(None, "--time"),
) -> None:
    del report, time
    settings = AppSettings()
    application = build_application(settings)
    snapshots = application.run_market(market=market)
    typer.echo(f"stored {len(snapshots)} snapshot for {market.value}")


if __name__ == "__main__":
    app()
```

- [ ] **Step 4: Run CLI test to verify it passes**

Run: `pytest tests/test_cli.py::test_cli_run_market_command -v`

Expected: PASS

- [ ] **Step 5: Commit CLI entrypoint**

```bash
git add main.py tests/test_cli.py
git commit -m "feat: add typer cli entrypoint"
```

## Task 7: Document Phase 1 usage in README

**Files:**
- Modify: `README.md`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Replace README with bootstrap instructions**

```markdown
# Sentinel

Sentinel is a market sentiment anomaly collection system focused on A shares, Hong Kong equities, US equities, and crypto markets.

## Phase 1 Scope

This phase provides:
- a Python package skeleton
- YAML-based runtime configuration
- DuckDB schema bootstrap
- a Typer CLI command that stores one synthetic snapshot

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
python main.py run --market A股
```

Expected output:

```text
stored 1 snapshot for A股
```

## Test

```bash
pytest tests -v
```
```

- [ ] **Step 2: Run full Phase 1 test suite**

Run: `pytest tests -v`

Expected: all tests PASS

- [ ] **Step 3: Commit README update**

```bash
git add README.md
git commit -m "docs: add phase 1 bootstrap instructions"
```

## Task 8: Final verification

**Files:**
- Modify: none
- Test: all Phase 1 files above

- [ ] **Step 1: Run end-to-end command against a temp data directory**

Run: `SENTINEL_DATA_DIR=$(mktemp -d) python main.py run --market A股`

Expected: `stored 1 snapshot for A股`

- [ ] **Step 2: Run complete test suite again**

Run: `pytest tests -v`

Expected: all tests PASS

- [ ] **Step 3: Inspect git status before handoff**

Run: `git status --short`

Expected: clean working tree

- [ ] **Step 4: Commit any final touch-ups if needed**

```bash
git add -A
git commit -m "chore: finalize sentinel phase 1"
```
