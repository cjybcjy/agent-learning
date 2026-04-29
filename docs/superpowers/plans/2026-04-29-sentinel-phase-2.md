# Sentinel Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the collector plugin system for Sentinel, including the collector contract, raw mention models, registry-based market routing, and three representative collectors that can run through the pipeline with deterministic tests.

**Architecture:** Phase 2 replaces the synthetic single-record stub with a collector-driven pipeline. The runtime path becomes `main.py -> app bootstrap -> collector registry -> market collector set -> async collection -> raw mentions`, but keeps Phase 1 persistence intact by returning deterministic normalized records that later phases can feed into anti-spam and scoring.

**Tech Stack:** Python 3.11+, pytest, asyncio, aiohttp, pydantic-settings, PyYAML, DuckDB, typer

---

## File Structure

### Files to create

- `sentinel/collectors/__init__.py` — collector package exports.
- `sentinel/collectors/base.py` — `BaseCollector`, `RawMention`, `CollectorContext`, and collector protocol.
- `sentinel/collectors/registry.py` — registry for collector instances and market-based resolution.
- `sentinel/collectors/http.py` — thin async HTTP client abstraction to isolate network calls in tests.
- `sentinel/collectors/synthetic.py` — deterministic synthetic collector used as fallback and test harness.
- `sentinel/collectors/xueqiu.py` — representative A-share collector implementation with parser-only behavior in tests.
- `sentinel/collectors/reddit_stocks.py` — representative US-market collector implementation with parser-only behavior in tests.
- `sentinel/collectors/coingecko.py` — representative crypto collector implementation with parser-only behavior in tests.
- `tests/test_collectors_base.py` — unit tests for raw mention serialization and collector contract behavior.
- `tests/test_collectors_registry.py` — registry resolution tests.
- `tests/test_collectors_parsers.py` — parser tests for representative collectors.
- `tests/test_pipeline_collectors.py` — pipeline integration tests for multi-collector runs.

### Files to modify

- `sentinel/config.py` — add typed helpers for market collector config lookup.
- `sentinel/domain/models.py` — add `RawMention`-adjacent enums or shared market parsing helpers only if needed.
- `sentinel/services/run_pipeline.py` — replace single synthetic snapshot generation with async collector execution that returns raw mentions.
- `sentinel/app.py` — wire collector registry into the application bootstrap.
- `config/markets.yaml` — ensure all Phase 2 collector keys exist.
- `README.md` — add collector plugin usage notes for local development.
- `requirements.txt` — add `aiohttp`.
- `tests/test_cli.py` — switch CLI expectations from persisted synthetic snapshots to collector-backed raw mentions.

## Task 1: Add collector package and core raw mention model

**Files:**
- Create: `sentinel/collectors/__init__.py`
- Create: `sentinel/collectors/base.py`
- Create: `tests/test_collectors_base.py`
- Modify: `requirements.txt`

- [ ] **Step 1: Write failing tests for raw mention model and base collector metadata**

```python
# tests/test_collectors_base.py
from datetime import datetime

from sentinel.collectors.base import RawMention, StaticCollector
from sentinel.domain.models import Market


def test_raw_mention_to_dict_contains_market_and_platform() -> None:
    mention = RawMention(
        market=Market.A_SHARE,
        platform="xueqiu",
        symbol="600519",
        post_count=4,
        comment_count=10,
        like_count=20,
        share_count=3,
        raw_text="贵州茅台放量上涨",
        is_kol=False,
        account_age_days=365,
        account_followers=120,
        source_url="https://example.test/post/1",
        post_time=datetime(2026, 4, 29, 10, 0, 0),
    )

    payload = mention.to_dict()

    assert payload["market"] == "A股"
    assert payload["platform"] == "xueqiu"
    assert payload["symbol"] == "600519"


def test_static_collector_exposes_platform_and_market() -> None:
    collector = StaticCollector(market=Market.A_SHARE, platform="synthetic", mentions=[])

    assert collector.market is Market.A_SHARE
    assert collector.platform == "synthetic"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_collectors_base.py -v`

Expected: FAIL with `ModuleNotFoundError` for `sentinel.collectors.base`

- [ ] **Step 3: Add aiohttp dependency and collector base implementation**

```text
# requirements.txt
Typer==0.16.0
PyYAML==6.0.2
pydantic==2.11.4
pydantic-settings==2.9.1
duckdb==1.2.2
aiohttp==3.11.18
pytest==8.3.5
```

```python
# sentinel/collectors/base.py
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from sentinel.domain.models import Market


@dataclass(slots=True)
class RawMention:
    market: Market
    platform: str
    symbol: str
    post_count: int
    comment_count: int
    like_count: int
    share_count: int
    raw_text: str
    is_kol: bool
    account_age_days: int
    account_followers: int
    source_url: str
    post_time: datetime

    def to_dict(self) -> dict[str, object]:
        return {
            "market": self.market.value,
            "platform": self.platform,
            "symbol": self.symbol,
            "post_count": self.post_count,
            "comment_count": self.comment_count,
            "like_count": self.like_count,
            "share_count": self.share_count,
            "raw_text": self.raw_text,
            "is_kol": self.is_kol,
            "account_age_days": self.account_age_days,
            "account_followers": self.account_followers,
            "source_url": self.source_url,
            "post_time": self.post_time,
        }


class BaseCollector(ABC):
    market: Market
    platform: str

    @abstractmethod
    async def collect(self, timestamp: datetime) -> list[RawMention]:
        raise NotImplementedError


@dataclass(slots=True)
class StaticCollector(BaseCollector):
    market: Market
    platform: str
    mentions: list[RawMention]

    async def collect(self, timestamp: datetime) -> list[RawMention]:
        del timestamp
        return self.mentions
```

```python
# sentinel/collectors/__init__.py
from sentinel.collectors.base import BaseCollector, RawMention, StaticCollector

__all__ = ["BaseCollector", "RawMention", "StaticCollector"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_collectors_base.py -v`

Expected: PASS

- [ ] **Step 5: Commit collector base layer**

```bash
git add requirements.txt sentinel/collectors/__init__.py sentinel/collectors/base.py tests/test_collectors_base.py
git commit -m "feat: add collector base abstractions"
```

## Task 2: Add registry and config-backed market routing

**Files:**
- Create: `sentinel/collectors/registry.py`
- Create: `tests/test_collectors_registry.py`
- Modify: `sentinel/config.py`

- [ ] **Step 1: Write failing registry tests**

```python
# tests/test_collectors_registry.py
from sentinel.collectors.base import StaticCollector
from sentinel.collectors.registry import CollectorRegistry
from sentinel.domain.models import Market


def test_registry_resolves_collectors_for_market() -> None:
    registry = CollectorRegistry()
    registry.register(StaticCollector(market=Market.A_SHARE, platform="xueqiu", mentions=[]))
    registry.register(StaticCollector(market=Market.A_SHARE, platform="eastmoney", mentions=[]))

    collectors = registry.list_for_market(Market.A_SHARE, ["xueqiu"])

    assert len(collectors) == 1
    assert collectors[0].platform == "xueqiu"


def test_registry_raises_for_unknown_collector_key() -> None:
    registry = CollectorRegistry()

    try:
        registry.list_for_market(Market.US, ["reddit_stocks"])
    except KeyError as exc:
        assert "reddit_stocks" in str(exc)
    else:
        raise AssertionError("expected KeyError")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_collectors_registry.py -v`

Expected: FAIL with `ModuleNotFoundError` for `sentinel.collectors.registry`

- [ ] **Step 3: Implement registry and typed config helper**

```python
# sentinel/collectors/registry.py
from __future__ import annotations

from collections import defaultdict

from sentinel.collectors.base import BaseCollector
from sentinel.domain.models import Market


class CollectorRegistry:
    def __init__(self) -> None:
        self._collectors: dict[tuple[Market, str], BaseCollector] = {}

    def register(self, collector: BaseCollector) -> None:
        self._collectors[(collector.market, collector.platform)] = collector

    def list_for_market(self, market: Market, collector_keys: list[str]) -> list[BaseCollector]:
        resolved: list[BaseCollector] = []
        for key in collector_keys:
            try:
                resolved.append(self._collectors[(market, key)])
            except KeyError as exc:
                raise KeyError(f"collector not registered for {market.value}: {key}") from exc
        return resolved
```

```python
# sentinel/config.py
from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

from sentinel.domain.models import Market


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


def get_market_collectors(config: dict[str, dict[str, object]], market: Market) -> list[str]:
    raw = config[market.value]["collectors"]
    return [str(item) for item in raw]
```

- [ ] **Step 4: Run registry tests to verify they pass**

Run: `pytest tests/test_collectors_registry.py -v`

Expected: PASS

- [ ] **Step 5: Commit registry layer**

```bash
git add sentinel/collectors/registry.py sentinel/config.py tests/test_collectors_registry.py
git commit -m "feat: add collector registry"
```

## Task 3: Add async HTTP adapter and parser-oriented representative collectors

**Files:**
- Create: `sentinel/collectors/http.py`
- Create: `sentinel/collectors/xueqiu.py`
- Create: `sentinel/collectors/reddit_stocks.py`
- Create: `sentinel/collectors/coingecko.py`
- Create: `tests/test_collectors_parsers.py`

- [ ] **Step 1: Write failing parser tests using static payloads**

```python
# tests/test_collectors_parsers.py
from datetime import datetime

from sentinel.collectors.coingecko import parse_coingecko_payload
from sentinel.collectors.reddit_stocks import parse_reddit_listing
from sentinel.collectors.xueqiu import parse_xueqiu_timeline
from sentinel.domain.models import Market


def test_parse_xueqiu_timeline_builds_raw_mentions() -> None:
    payload = {
        "list": [
            {
                "title": "茅台走强",
                "description": "600519 再次走高",
                "comment_count": 12,
                "like_count": 30,
                "retweet_count": 2,
                "created_at": 1777437600000,
                "user": {"followers_count": 80, "created_at": 1640995200000},
                "target": "600519",
                "uri": "/S/SH600519",
            }
        ]
    }

    mentions = parse_xueqiu_timeline(payload, datetime(2026, 4, 29, 10, 0, 0))

    assert len(mentions) == 1
    assert mentions[0].market is Market.A_SHARE
    assert mentions[0].platform == "xueqiu"
    assert mentions[0].symbol == "600519"


def test_parse_reddit_listing_builds_raw_mentions() -> None:
    payload = {
        "data": {
            "children": [
                {
                    "data": {
                        "title": "NVDA is breaking out",
                        "selftext": "Bullish setup into earnings",
                        "num_comments": 88,
                        "score": 640,
                        "created_utc": 1777437600,
                        "author_created_utc": 1609459200,
                        "subreddit": "stocks",
                        "permalink": "/r/stocks/comments/demo",
                    }
                }
            ]
        }
    }

    mentions = parse_reddit_listing(payload, datetime(2026, 4, 29, 10, 0, 0), symbol="NVDA")

    assert len(mentions) == 1
    assert mentions[0].market is Market.US
    assert mentions[0].symbol == "NVDA"


def test_parse_coingecko_payload_builds_raw_mentions() -> None:
    payload = {
        "coins": [
            {
                "symbol": "btc",
                "name": "Bitcoin",
                "sentiment_votes_up_percentage": 82.3,
                "watchlist_portfolio_users": 250000,
            }
        ]
    }

    mentions = parse_coingecko_payload(payload, datetime(2026, 4, 29, 10, 0, 0))

    assert len(mentions) == 1
    assert mentions[0].market is Market.CRYPTO
    assert mentions[0].platform == "coingecko"
    assert mentions[0].symbol == "BTC"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_collectors_parsers.py -v`

Expected: FAIL with `ModuleNotFoundError` for representative collector modules

- [ ] **Step 3: Implement HTTP adapter and parser-oriented collectors**

```python
# sentinel/collectors/http.py
from __future__ import annotations

import aiohttp


class HttpClient:
    async def get_json(self, url: str, params: dict[str, object] | None = None, headers: dict[str, str] | None = None) -> dict[str, object]:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, headers=headers, timeout=20) as response:
                response.raise_for_status()
                return await response.json()
```

```python
# sentinel/collectors/xueqiu.py
from __future__ import annotations

from datetime import datetime

from sentinel.collectors.base import BaseCollector, RawMention
from sentinel.collectors.http import HttpClient
from sentinel.domain.models import Market


def parse_xueqiu_timeline(payload: dict[str, object], default_timestamp: datetime) -> list[RawMention]:
    items = payload.get("list", [])
    mentions: list[RawMention] = []
    for item in items:
        post = dict(item)
        user = dict(post.get("user", {}))
        created_at_ms = post.get("created_at")
        post_time = datetime.fromtimestamp(created_at_ms / 1000) if created_at_ms else default_timestamp
        account_created_ms = user.get("created_at", 0)
        account_age_days = max((post_time - datetime.fromtimestamp(account_created_ms / 1000)).days, 0) if account_created_ms else 0
        symbol = str(post.get("target") or "UNKNOWN")
        mentions.append(
            RawMention(
                market=Market.A_SHARE,
                platform="xueqiu",
                symbol=symbol,
                post_count=1,
                comment_count=int(post.get("comment_count", 0)),
                like_count=int(post.get("like_count", 0)),
                share_count=int(post.get("retweet_count", 0)),
                raw_text=f"{post.get('title', '')} {post.get('description', '')}".strip(),
                is_kol=False,
                account_age_days=account_age_days,
                account_followers=int(user.get("followers_count", 0)),
                source_url=f"https://xueqiu.com{post.get('uri', '')}",
                post_time=post_time,
            )
        )
    return mentions


class XueqiuCollector(BaseCollector):
    market = Market.A_SHARE
    platform = "xueqiu"

    def __init__(self, http_client: HttpClient) -> None:
        self.http_client = http_client

    async def collect(self, timestamp: datetime) -> list[RawMention]:
        payload = await self.http_client.get_json("https://xueqiu.com/statuses/hot/listV2.json")
        return parse_xueqiu_timeline(payload, timestamp)
```

```python
# sentinel/collectors/reddit_stocks.py
from __future__ import annotations

from datetime import datetime

from sentinel.collectors.base import BaseCollector, RawMention
from sentinel.collectors.http import HttpClient
from sentinel.domain.models import Market


def parse_reddit_listing(payload: dict[str, object], default_timestamp: datetime, symbol: str) -> list[RawMention]:
    children = payload.get("data", {}).get("children", [])
    mentions: list[RawMention] = []
    for child in children:
        post = dict(child.get("data", {}))
        post_time = datetime.fromtimestamp(float(post.get("created_utc", default_timestamp.timestamp())))
        account_created = float(post.get("author_created_utc", post_time.timestamp()))
        account_age_days = max((post_time - datetime.fromtimestamp(account_created)).days, 0)
        mentions.append(
            RawMention(
                market=Market.US,
                platform="reddit_stocks",
                symbol=symbol.upper(),
                post_count=1,
                comment_count=int(post.get("num_comments", 0)),
                like_count=int(post.get("score", 0)),
                share_count=0,
                raw_text=f"{post.get('title', '')} {post.get('selftext', '')}".strip(),
                is_kol=False,
                account_age_days=account_age_days,
                account_followers=0,
                source_url=f"https://reddit.com{post.get('permalink', '')}",
                post_time=post_time,
            )
        )
    return mentions


class RedditStocksCollector(BaseCollector):
    market = Market.US
    platform = "reddit_stocks"

    def __init__(self, http_client: HttpClient, symbol: str) -> None:
        self.http_client = http_client
        self.symbol = symbol

    async def collect(self, timestamp: datetime) -> list[RawMention]:
        payload = await self.http_client.get_json("https://www.reddit.com/r/stocks/new.json", headers={"User-Agent": "sentinel/0.1"})
        return parse_reddit_listing(payload, timestamp, self.symbol)
```

```python
# sentinel/collectors/coingecko.py
from __future__ import annotations

from datetime import datetime

from sentinel.collectors.base import BaseCollector, RawMention
from sentinel.collectors.http import HttpClient
from sentinel.domain.models import Market


def parse_coingecko_payload(payload: dict[str, object], default_timestamp: datetime) -> list[RawMention]:
    items = payload.get("coins", [])
    mentions: list[RawMention] = []
    for coin in items:
        record = dict(coin)
        mentions.append(
            RawMention(
                market=Market.CRYPTO,
                platform="coingecko",
                symbol=str(record.get("symbol", "")).upper(),
                post_count=1,
                comment_count=0,
                like_count=int(float(record.get("watchlist_portfolio_users", 0))),
                share_count=0,
                raw_text=str(record.get("name", "")),
                is_kol=False,
                account_age_days=9999,
                account_followers=0,
                source_url="https://www.coingecko.com",
                post_time=default_timestamp,
            )
        )
    return mentions


class CoinGeckoCollector(BaseCollector):
    market = Market.CRYPTO
    platform = "coingecko"

    def __init__(self, http_client: HttpClient) -> None:
        self.http_client = http_client

    async def collect(self, timestamp: datetime) -> list[RawMention]:
        payload = await self.http_client.get_json("https://api.coingecko.com/api/v3/search/trending")
        return parse_coingecko_payload(payload, timestamp)
```

- [ ] **Step 4: Run parser tests to verify they pass**

Run: `pytest tests/test_collectors_parsers.py -v`

Expected: PASS

- [ ] **Step 5: Commit representative collectors**

```bash
git add sentinel/collectors/http.py sentinel/collectors/xueqiu.py sentinel/collectors/reddit_stocks.py sentinel/collectors/coingecko.py tests/test_collectors_parsers.py
git commit -m "feat: add representative market collectors"
```

## Task 4: Replace synthetic pipeline with async collector execution

**Files:**
- Modify: `sentinel/services/run_pipeline.py`
- Modify: `sentinel/app.py`
- Create: `tests/test_pipeline_collectors.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write failing pipeline integration test**

```python
# tests/test_pipeline_collectors.py
from datetime import datetime

from sentinel.app import SentinelApplication
from sentinel.collectors.base import RawMention, StaticCollector
from sentinel.collectors.registry import CollectorRegistry
from sentinel.config import AppSettings
from sentinel.domain.models import Market
from sentinel.services.run_pipeline import RunPipelineService
from sentinel.storage.db import Database
from sentinel.storage.repository import HeatMetricRepository


def test_pipeline_collects_from_registered_collectors(tmp_path) -> None:
    database = Database(tmp_path / "sentinel.duckdb")
    repository = HeatMetricRepository(database)
    registry = CollectorRegistry()
    registry.register(
        StaticCollector(
            market=Market.A_SHARE,
            platform="synthetic",
            mentions=[
                RawMention(
                    market=Market.A_SHARE,
                    platform="synthetic",
                    symbol="600519",
                    post_count=1,
                    comment_count=2,
                    like_count=3,
                    share_count=0,
                    raw_text="贵州茅台",
                    is_kol=False,
                    account_age_days=100,
                    account_followers=20,
                    source_url="https://example.test/post/1",
                    post_time=datetime(2026, 4, 29, 10, 0, 0),
                )
            ],
        )
    )
    runner = RunPipelineService(registry=registry)
    app = SentinelApplication(repository=repository, runner=runner)

    mentions = app.run_market(market=Market.A_SHARE, collector_keys=["synthetic"])

    assert len(mentions) == 1
    assert mentions[0].symbol == "600519"
```

```python
# tests/test_cli.py
from pathlib import Path

from typer.testing import CliRunner

from main import app as cli_app
from sentinel.app import build_application
from sentinel.domain.models import Market

runner = CliRunner()


def test_application_run_collects_registered_mentions(settings) -> None:
    app = build_application(settings)

    mentions = app.run_market(market=Market.A_SHARE, collector_keys=["synthetic"])

    assert len(mentions) == 1
    assert mentions[0].symbol == "SYNTH-A股"


def test_cli_run_market_command(settings, monkeypatch) -> None:
    monkeypatch.setenv("SENTINEL_CONFIG_DIR", str(settings.config_dir))
    monkeypatch.setenv("SENTINEL_DATA_DIR", str(settings.data_dir))

    result = runner.invoke(cli_app, ["--market", "A股"])

    assert result.exit_code == 0
    assert "collected 1 mention for A股" in result.stdout
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pipeline_collectors.py -v`

Expected: FAIL because `run_market()` does not accept collector keys, runner is not registry-backed, and CLI still expects the Phase 1 snapshot behavior

- [ ] **Step 3: Implement async collector-driven pipeline**

```python
# sentinel/services/run_pipeline.py
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from sentinel.collectors.base import RawMention
from sentinel.collectors.registry import CollectorRegistry
from sentinel.domain.models import Market


class RunPipelineService:
    def __init__(self, registry: CollectorRegistry) -> None:
        self.registry = registry

    def run_market(self, market: Market, collector_keys: list[str]) -> list[RawMention]:
        timestamp = datetime.now(tz=timezone.utc).replace(tzinfo=None)
        return asyncio.run(self._collect_market(market, collector_keys, timestamp))

    async def _collect_market(self, market: Market, collector_keys: list[str], timestamp: datetime) -> list[RawMention]:
        collectors = self.registry.list_for_market(market, collector_keys)
        batches = await asyncio.gather(*(collector.collect(timestamp) for collector in collectors))
        return [mention for batch in batches for mention in batch]
```

```python
# sentinel/app.py
from __future__ import annotations

from dataclasses import dataclass

from sentinel.collectors.registry import CollectorRegistry
from sentinel.collectors.synthetic import build_default_registry
from sentinel.config import AppSettings, get_market_collectors, load_market_config
from sentinel.domain.models import Market
from sentinel.services.run_pipeline import RunPipelineService
from sentinel.storage.db import Database
from sentinel.storage.repository import HeatMetricRepository


@dataclass(slots=True)
class SentinelApplication:
    repository: HeatMetricRepository
    runner: RunPipelineService
    market_config: dict[str, dict[str, object]]

    def run_market(self, market: Market, collector_keys: list[str] | None = None):
        self.repository.bootstrap()
        keys = collector_keys or get_market_collectors(self.market_config, market)
        return self.runner.run_market(market=market, collector_keys=keys)


def build_application(settings: AppSettings) -> SentinelApplication:
    database = Database(settings.database_path)
    repository = HeatMetricRepository(database)
    registry = build_default_registry()
    runner = RunPipelineService(registry)
    market_config = load_market_config(settings.resolved_config_dir / "markets.yaml")
    return SentinelApplication(repository=repository, runner=runner, market_config=market_config)
```

```python
# sentinel/collectors/synthetic.py
from __future__ import annotations

from datetime import datetime

from sentinel.collectors.base import RawMention, StaticCollector
from sentinel.collectors.registry import CollectorRegistry
from sentinel.domain.models import Market


def build_default_registry() -> CollectorRegistry:
    registry = CollectorRegistry()
    now = datetime(2026, 4, 29, 10, 0, 0)
    registry.register(
        StaticCollector(
            market=Market.A_SHARE,
            platform="synthetic",
            mentions=[
                RawMention(
                    market=Market.A_SHARE,
                    platform="synthetic",
                    symbol="SYNTH-A股",
                    post_count=1,
                    comment_count=2,
                    like_count=3,
                    share_count=0,
                    raw_text="Synthetic A-share mention",
                    is_kol=False,
                    account_age_days=365,
                    account_followers=10,
                    source_url="https://example.test/a-share",
                    post_time=now,
                )
            ],
        )
    )
    registry.register(
        StaticCollector(
            market=Market.US,
            platform="synthetic",
            mentions=[
                RawMention(
                    market=Market.US,
                    platform="synthetic",
                    symbol="SYNTH-US",
                    post_count=1,
                    comment_count=2,
                    like_count=3,
                    share_count=0,
                    raw_text="Synthetic US mention",
                    is_kol=False,
                    account_age_days=365,
                    account_followers=10,
                    source_url="https://example.test/us",
                    post_time=now,
                )
            ],
        )
    )
    registry.register(
        StaticCollector(
            market=Market.CRYPTO,
            platform="synthetic",
            mentions=[
                RawMention(
                    market=Market.CRYPTO,
                    platform="synthetic",
                    symbol="SYNTH-CRYPTO",
                    post_count=1,
                    comment_count=2,
                    like_count=3,
                    share_count=0,
                    raw_text="Synthetic crypto mention",
                    is_kol=False,
                    account_age_days=365,
                    account_followers=10,
                    source_url="https://example.test/crypto",
                    post_time=now,
                )
            ],
        )
    )
    return registry
```

- [ ] **Step 4: Run pipeline integration tests**

Run: `pytest tests/test_pipeline_collectors.py tests/test_cli.py -v`

Expected: PASS

- [ ] **Step 5: Commit collector-driven pipeline**

```bash
git add sentinel/services/run_pipeline.py sentinel/app.py sentinel/collectors/synthetic.py tests/test_pipeline_collectors.py tests/test_cli.py
git commit -m "feat: wire collector registry into pipeline"
```

## Task 5: Update README and finish Phase 2 verification

**Files:**
- Modify: `README.md`
- Test: `tests/test_collectors_base.py`, `tests/test_collectors_registry.py`, `tests/test_collectors_parsers.py`, `tests/test_pipeline_collectors.py`, `tests/test_cli.py`, `tests/test_config.py`, `tests/test_repository.py`

- [ ] **Step 1: Update README with collector plugin notes**

```markdown
## Collector Development

Phase 2 adds a collector plugin system.

Representative collectors included in this phase:
- `xueqiu` for A shares
- `reddit_stocks` for US equities
- `coingecko` for crypto
- `synthetic` for deterministic local testing

Collector modules expose parser helpers so tests can validate payload handling without making live network calls.
```

- [ ] **Step 2: Run full test suite**

Run: `pytest tests -v`

Expected: all tests PASS

- [ ] **Step 3: Run CLI against synthetic market config**

Run: `tmpdir=$(mktemp -d) && mkdir -p "$tmpdir/config" "$tmpdir/data" && printf 'A股:\n  collectors: [synthetic]\n' > "$tmpdir/config/markets.yaml" && printf 'base_heat:\n  posts: 0.35\n' > "$tmpdir/config/weights.yaml" && SENTINEL_CONFIG_DIR="$tmpdir/config" SENTINEL_DATA_DIR="$tmpdir/data" python main.py --market A股`

Expected: command exits 0 and prints `collected 1 mention for A股`

- [ ] **Step 4: Commit README and verification updates**

```bash
git add README.md
git commit -m "docs: document collector plugin system"
```
