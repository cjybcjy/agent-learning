# Crypto Heatmap MVP 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 端到端跑通"币圈社媒热度采集 → 双闸门打分 → 飞书日报"闭环（v1，仅 Telegram + Discord）。

**Architecture:** 5 个解耦子模块（Collectors / Store / Extractor / Aggregator / Reporter），通过 SQLite 表与 dataclass 通信；调度器单进程 asyncio 常驻 + 每日 UTC 00:05 出报告。

**Tech Stack:** Python 3.11、`pyahocorasick`、`telethon`、`discord.py`、`aiosqlite`、`pydantic` v2、`PyYAML`、`pytest` + `pytest-asyncio`、`lark-cli`（外部命令）。

参考设计稿：[docs/superpowers/specs/2026-04-30-crypto-heatmap-design.md](../specs/2026-04-30-crypto-heatmap-design.md)

---

## Task 1：项目骨架与依赖

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `heatmap/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/unit/__init__.py`
- Create: `tests/integration/__init__.py`

- [ ] **Step 1：写 `pyproject.toml`**

```toml
[project]
name = "heatmap"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
  "pyahocorasick>=2.1",
  "telethon>=1.36",
  "discord.py>=2.4",
  "aiosqlite>=0.20",
  "pydantic>=2.7",
  "PyYAML>=6.0",
]

[project.optional-dependencies]
dev = ["pytest>=8", "pytest-asyncio>=0.23", "pytest-cov>=5"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 2：写 `.gitignore`**

```
__pycache__/
*.pyc
.venv/
data/
.env
.pytest_cache/
.coverage
```

- [ ] **Step 3：创建空包占位**

每个 `__init__.py` 留空文件即可。

- [ ] **Step 4：建虚拟环境并安装依赖**

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

预期：无报错，`pytest --version` 正常输出。

- [ ] **Step 5：提交**

```bash
git add pyproject.toml .gitignore heatmap/__init__.py tests/
git commit -m "chore: bootstrap heatmap package skeleton"
```

---

## Task 2：配置加载器

**Files:**
- Create: `config/thresholds.yaml`
- Create: `config/sources.yaml`
- Create: `config/aliases.csv`
- Create: `heatmap/config.py`
- Test: `tests/unit/test_config.py`

- [ ] **Step 1：写测试 `tests/unit/test_config.py`**

```python
from pathlib import Path
from heatmap.config import load_thresholds, load_sources

def test_load_thresholds(tmp_path: Path):
    p = tmp_path / "t.yaml"
    p.write_text("stage_a_top_n: 50\nstage_b_top_n: 10\nalpha_min: 0.5\nbeta_min: 1.5\n")
    cfg = load_thresholds(p)
    assert cfg.stage_a_top_n == 50
    assert cfg.alpha_min == 0.5

def test_load_sources(tmp_path: Path):
    p = tmp_path / "s.yaml"
    p.write_text("telegram:\n  channels: ['@a', '@b']\ndiscord:\n  guilds: []\n")
    cfg = load_sources(p)
    assert cfg.telegram.channels == ["@a", "@b"]
    assert cfg.discord.guilds == []
```

- [ ] **Step 2：跑测试确认失败**

```bash
pytest tests/unit/test_config.py -v
```
预期：`ImportError`。

- [ ] **Step 3：实现 `heatmap/config.py`**

```python
from pathlib import Path
from typing import Any
import yaml
from pydantic import BaseModel

class Thresholds(BaseModel):
    stage_a_top_n: int
    stage_b_top_n: int
    alpha_min: float
    beta_min: float

class DiscordGuild(BaseModel):
    guild_id: str
    channel_ids: list[str]

class TelegramSources(BaseModel):
    channels: list[str] = []

class DiscordSources(BaseModel):
    guilds: list[DiscordGuild] = []

class Sources(BaseModel):
    telegram: TelegramSources = TelegramSources()
    discord: DiscordSources = DiscordSources()

def _load_yaml(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

def load_thresholds(path: Path) -> Thresholds:
    return Thresholds(**_load_yaml(path))

def load_sources(path: Path) -> Sources:
    return Sources(**_load_yaml(path))
```

- [ ] **Step 4：写真实配置文件**

`config/thresholds.yaml`：

```yaml
stage_a_top_n: 50
stage_b_top_n: 10
alpha_min: 0.5
beta_min: 1.5
```

`config/sources.yaml`：

```yaml
telegram:
  channels: []
discord:
  guilds: []
```

`config/aliases.csv`（4 条种子）：

```csv
symbol,alias,is_ambiguous,source
BTC,比特币,false,seed
BTC,btc,false,seed
DOGE,狗狗,false,seed
DOGE,doge,false,seed
```

- [ ] **Step 5：跑测试确认通过 + 提交**

```bash
pytest tests/unit/test_config.py -v
git add config/ heatmap/config.py tests/unit/test_config.py
git commit -m "feat(config): add thresholds and sources loader"
```

---

## Task 3：SQLite Schema 与 DAO

**Files:**
- Create: `heatmap/store/__init__.py`
- Create: `heatmap/store/schema.sql`
- Create: `heatmap/store/dao.py`
- Test: `tests/unit/test_dao.py`

- [ ] **Step 1：写 `heatmap/store/schema.sql`**

```sql
CREATE TABLE IF NOT EXISTS raw_messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  platform TEXT NOT NULL,
  channel TEXT NOT NULL,
  author_id TEXT,
  content TEXT NOT NULL,
  posted_at TEXT NOT NULL,   -- ISO8601 UTC
  fetched_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_raw_posted_at ON raw_messages(posted_at);

CREATE TABLE IF NOT EXISTS mentions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  message_id INTEGER NOT NULL,
  symbol TEXT NOT NULL,
  matched_alias TEXT NOT NULL,
  is_ambiguous INTEGER NOT NULL,
  confidence REAL NOT NULL DEFAULT 1.0,
  FOREIGN KEY (message_id) REFERENCES raw_messages(id)
);
CREATE INDEX IF NOT EXISTS idx_mentions_symbol ON mentions(symbol);

CREATE TABLE IF NOT EXISTS daily_scores (
  symbol TEXT NOT NULL,
  date TEXT NOT NULL,        -- YYYY-MM-DD UTC
  mention_count INTEGER NOT NULL,
  weighted_score REAL NOT NULL,
  alpha REAL,
  beta REAL,
  composite REAL,
  PRIMARY KEY (symbol, date)
);
```

- [ ] **Step 2：写测试 `tests/unit/test_dao.py`**

```python
import pytest
from datetime import datetime, timezone
from heatmap.store.dao import Store, RawMessage, Mention

@pytest.fixture
async def store(tmp_path):
    s = Store(tmp_path / "t.db")
    await s.init()
    yield s
    await s.close()

async def test_insert_and_query_message(store):
    msg = RawMessage(
        platform="telegram", channel="@x", author_id="u1",
        content="$DOGE to the moon", posted_at=datetime(2026,4,30,tzinfo=timezone.utc),
        fetched_at=datetime(2026,4,30,tzinfo=timezone.utc),
    )
    msg_id = await store.insert_message(msg)
    assert msg_id > 0

async def test_insert_mentions_and_count(store):
    msg_id = await store.insert_message(RawMessage(
        platform="telegram", channel="@x", author_id="u1",
        content="DOGE", posted_at=datetime(2026,4,30,tzinfo=timezone.utc),
        fetched_at=datetime(2026,4,30,tzinfo=timezone.utc),
    ))
    await store.insert_mentions([Mention(message_id=msg_id, symbol="DOGE",
        matched_alias="DOGE", is_ambiguous=False, confidence=1.0)])
    counts = await store.daily_mention_counts("2026-04-30")
    assert counts["DOGE"] == 1
```

- [ ] **Step 3：跑测试确认失败**

```bash
pytest tests/unit/test_dao.py -v
```

- [ ] **Step 4：实现 `heatmap/store/dao.py`**

```python
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import aiosqlite

SCHEMA = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")

@dataclass
class RawMessage:
    platform: str
    channel: str
    author_id: str | None
    content: str
    posted_at: datetime
    fetched_at: datetime
    id: int | None = None

@dataclass
class Mention:
    message_id: int
    symbol: str
    matched_alias: str
    is_ambiguous: bool
    confidence: float

class Store:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def init(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self.db_path)
        await self._db.executescript(SCHEMA)
        await self._db.commit()

    async def close(self):
        if self._db:
            await self._db.close()

    async def insert_message(self, m: RawMessage) -> int:
        cur = await self._db.execute(
            "INSERT INTO raw_messages(platform,channel,author_id,content,posted_at,fetched_at)"
            " VALUES (?,?,?,?,?,?)",
            (m.platform, m.channel, m.author_id, m.content,
             m.posted_at.isoformat(), m.fetched_at.isoformat()),
        )
        await self._db.commit()
        return cur.lastrowid

    async def insert_mentions(self, mentions: list[Mention]) -> None:
        await self._db.executemany(
            "INSERT INTO mentions(message_id,symbol,matched_alias,is_ambiguous,confidence)"
            " VALUES (?,?,?,?,?)",
            [(x.message_id, x.symbol, x.matched_alias, int(x.is_ambiguous), x.confidence)
             for x in mentions],
        )
        await self._db.commit()

    async def daily_mention_counts(self, date: str) -> dict[str, int]:
        cur = await self._db.execute(
            "SELECT m.symbol, COUNT(*) FROM mentions m "
            "JOIN raw_messages r ON r.id = m.message_id "
            "WHERE substr(r.posted_at,1,10) = ? GROUP BY m.symbol",
            (date,),
        )
        return {row[0]: row[1] async for row in cur} if False else {
            row[0]: row[1] for row in await cur.fetchall()
        }

    async def upsert_daily_score(self, symbol: str, date: str,
                                 mention_count: int, weighted_score: float,
                                 alpha: float | None, beta: float | None,
                                 composite: float | None) -> None:
        await self._db.execute(
            "INSERT INTO daily_scores(symbol,date,mention_count,weighted_score,alpha,beta,composite)"
            " VALUES (?,?,?,?,?,?,?) "
            " ON CONFLICT(symbol,date) DO UPDATE SET "
            "  mention_count=excluded.mention_count,"
            "  weighted_score=excluded.weighted_score,"
            "  alpha=excluded.alpha, beta=excluded.beta, composite=excluded.composite",
            (symbol, date, mention_count, weighted_score, alpha, beta, composite),
        )
        await self._db.commit()

    async def get_weighted_score(self, symbol: str, date: str) -> float | None:
        cur = await self._db.execute(
            "SELECT weighted_score FROM daily_scores WHERE symbol=? AND date=?",
            (symbol, date),
        )
        row = await cur.fetchone()
        return row[0] if row else None
```

- [ ] **Step 5：跑测试通过 + 提交**

```bash
pytest tests/unit/test_dao.py -v
git add heatmap/store/ tests/unit/test_dao.py
git commit -m "feat(store): SQLite schema and async DAO"
```

---

## Task 4：词典加载与 AC 自动机

**Files:**
- Create: `heatmap/extractor/__init__.py`
- Create: `heatmap/extractor/dictionary.py`
- Create: `heatmap/extractor/ac.py`
- Test: `tests/unit/test_extractor.py`

- [ ] **Step 1：写测试**

```python
from pathlib import Path
from heatmap.extractor.dictionary import load_aliases
from heatmap.extractor.ac import AhoCorasickExtractor

def test_load_aliases(tmp_path: Path):
    p = tmp_path / "a.csv"
    p.write_text("symbol,alias,is_ambiguous,source\nBTC,比特币,false,seed\nAPT,apt,true,seed\n",
                 encoding="utf-8")
    entries = load_aliases(p)
    assert len(entries) == 2
    assert entries[0].symbol == "BTC"
    assert entries[1].is_ambiguous is True

def test_ac_extracts_ticker():
    from heatmap.extractor.dictionary import AliasEntry
    ext = AhoCorasickExtractor([
        AliasEntry("BTC", "比特币", False, "seed"),
        AliasEntry("DOGE", "doge", False, "seed"),
    ])
    hits = ext.extract("今天比特币和 doge 都飞了")
    symbols = sorted({h.symbol for h in hits})
    assert symbols == ["BTC", "DOGE"]

def test_ac_case_insensitive_for_latin():
    from heatmap.extractor.dictionary import AliasEntry
    ext = AhoCorasickExtractor([AliasEntry("DOGE", "doge", False, "seed")])
    hits = ext.extract("DOGE pump")
    assert len(hits) == 1
```

- [ ] **Step 2：跑测试确认失败**

- [ ] **Step 3：实现 `heatmap/extractor/dictionary.py`**

```python
from dataclasses import dataclass
from pathlib import Path
import csv

@dataclass(frozen=True)
class AliasEntry:
    symbol: str
    alias: str
    is_ambiguous: bool
    source: str

def load_aliases(path: Path) -> list[AliasEntry]:
    out: list[AliasEntry] = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            out.append(AliasEntry(
                symbol=row["symbol"].strip(),
                alias=row["alias"].strip(),
                is_ambiguous=row["is_ambiguous"].strip().lower() == "true",
                source=row.get("source", "").strip(),
            ))
    return out
```

- [ ] **Step 4：实现 `heatmap/extractor/ac.py`**

```python
from dataclasses import dataclass
import ahocorasick
from heatmap.extractor.dictionary import AliasEntry

@dataclass(frozen=True)
class Hit:
    symbol: str
    matched_alias: str
    is_ambiguous: bool
    start: int
    end: int

class AhoCorasickExtractor:
    def __init__(self, entries: list[AliasEntry]):
        self._auto = ahocorasick.Automaton()
        for e in entries:
            key = e.alias.lower()
            self._auto.add_word(key, (e.symbol, e.alias, e.is_ambiguous))
        self._auto.make_automaton()

    def extract(self, text: str) -> list[Hit]:
        lower = text.lower()
        hits: list[Hit] = []
        for end_idx, (symbol, alias, is_amb) in self._auto.iter(lower):
            start_idx = end_idx - len(alias) + 1
            hits.append(Hit(symbol, alias, is_amb, start_idx, end_idx + 1))
        return hits
```

- [ ] **Step 5：跑测试通过 + 提交**

```bash
pytest tests/unit/test_extractor.py -v
git add heatmap/extractor/__init__.py heatmap/extractor/dictionary.py heatmap/extractor/ac.py tests/unit/test_extractor.py
git commit -m "feat(extractor): alias dictionary loader and Aho-Corasick extractor"
```

---

## Task 5：消歧接口（仅占位）

**Files:**
- Create: `heatmap/extractor/disambiguator.py`
- Test: `tests/unit/test_disambiguator.py`

- [ ] **Step 1：写测试**

```python
from heatmap.extractor.disambiguator import NoopDisambiguator
from heatmap.extractor.ac import Hit

def test_noop_returns_input_unchanged():
    d = NoopDisambiguator()
    hits = [Hit("BTC", "btc", False, 0, 3)]
    assert d.resolve("any text", hits) is hits
```

- [ ] **Step 2：跑测试确认失败**

- [ ] **Step 3：实现**

```python
from typing import Protocol
from heatmap.extractor.ac import Hit

class Disambiguator(Protocol):
    def resolve(self, text: str, hits: list[Hit]) -> list[Hit]: ...

class NoopDisambiguator:
    def resolve(self, text: str, hits: list[Hit]) -> list[Hit]:
        return hits
```

- [ ] **Step 4：跑测试通过 + 提交**

```bash
pytest tests/unit/test_disambiguator.py -v
git add heatmap/extractor/disambiguator.py tests/unit/test_disambiguator.py
git commit -m "feat(extractor): disambiguator interface and noop impl"
```

---

## Task 6：打分模块（含零互动回退边界用例）

**Files:**
- Create: `heatmap/aggregator/__init__.py`
- Create: `heatmap/aggregator/scoring.py`
- Test: `tests/unit/test_scoring.py`

- [ ] **Step 1：写测试**

```python
import math
import pytest
from heatmap.aggregator.scoring import weighted_score

def test_weighted_score_zero_interactions_falls_back_to_mention():
    assert weighted_score(mention=10, interactions=0) == pytest.approx(10.0)

def test_weighted_score_uses_log10():
    # interactions=99 → 1 + log10(100) = 3
    assert weighted_score(mention=2, interactions=99) == pytest.approx(2 * 3.0)

def test_weighted_score_never_zero_when_mention_positive():
    assert weighted_score(mention=1, interactions=0) > 0
```

- [ ] **Step 2：跑测试确认失败**

- [ ] **Step 3：实现 `heatmap/aggregator/scoring.py`**

```python
import math

def weighted_score(mention: int, interactions: int) -> float:
    """Stage B 加权分。零互动时回退为 mention（不会清零）。"""
    if mention <= 0:
        return 0.0
    factor = 1.0 + math.log10(1.0 + max(0, interactions))
    return mention * factor
```

- [ ] **Step 4：跑测试通过 + 提交**

```bash
pytest tests/unit/test_scoring.py -v
git add heatmap/aggregator/__init__.py heatmap/aggregator/scoring.py tests/unit/test_scoring.py
git commit -m "feat(aggregator): weighted_score with log10 and zero-interaction fallback"
```

---

## Task 7：双闸门与复合分

**Files:**
- Create: `heatmap/aggregator/gates.py`
- Test: `tests/unit/test_gates.py`

- [ ] **Step 1：写测试**

```python
import math
from heatmap.aggregator.gates import compute_alpha_beta, compose, select_top, Candidate

def test_alpha_normal():
    a, b = compute_alpha_beta(today=150, yesterday=100, market_avg=50)
    assert a == 0.5
    assert b == 3.0

def test_alpha_cold_start_yesterday_zero():
    a, _ = compute_alpha_beta(today=10, yesterday=0, market_avg=5)
    assert a == math.inf

def test_compose_uses_log10_of_beta():
    assert compose(alpha=1.0, beta=9.0) == 1.0 * math.log10(10.0)

def test_select_top_filters_by_thresholds_and_limits():
    cands = [
        Candidate("A", alpha=0.6, beta=2.0, composite=0.0, mention=10, weighted=10),
        Candidate("B", alpha=0.4, beta=3.0, composite=0.0, mention=10, weighted=10),  # alpha 不达
        Candidate("C", alpha=1.0, beta=1.2, composite=0.0, mention=10, weighted=10),  # beta 不达
        Candidate("D", alpha=2.0, beta=5.0, composite=0.0, mention=10, weighted=10),
    ]
    top = select_top(cands, alpha_min=0.5, beta_min=1.5, top_n=10)
    assert [c.symbol for c in top] == ["D", "A"]
```

- [ ] **Step 2：跑测试确认失败**

- [ ] **Step 3：实现 `heatmap/aggregator/gates.py`**

```python
import math
from dataclasses import dataclass

@dataclass
class Candidate:
    symbol: str
    alpha: float
    beta: float
    composite: float
    mention: int
    weighted: float

def compute_alpha_beta(today: float, yesterday: float, market_avg: float) -> tuple[float, float]:
    alpha = math.inf if yesterday <= 0 else (today / yesterday - 1.0)
    beta = 0.0 if market_avg <= 0 else today / market_avg
    return alpha, beta

def compose(alpha: float, beta: float) -> float:
    if alpha == math.inf:
        # 冷启动：仅按 beta 排序
        return math.log10(1.0 + max(0.0, beta))
    return alpha * math.log10(1.0 + max(0.0, beta))

def select_top(cands: list[Candidate], alpha_min: float, beta_min: float, top_n: int) -> list[Candidate]:
    qualified = [c for c in cands if c.alpha >= alpha_min and c.beta >= beta_min]
    for c in qualified:
        c.composite = compose(c.alpha, c.beta)
    qualified.sort(key=lambda x: x.composite, reverse=True)
    return qualified[:top_n]
```

- [ ] **Step 4：跑测试通过 + 提交**

```bash
pytest tests/unit/test_gates.py -v
git add heatmap/aggregator/gates.py tests/unit/test_gates.py
git commit -m "feat(aggregator): alpha/beta dual gate and composite ranking"
```

---

## Task 8：日聚合管道（把上面两步串起来）

**Files:**
- Create: `heatmap/aggregator/pipeline.py`
- Test: `tests/unit/test_pipeline.py`

- [ ] **Step 1：写测试**

```python
import pytest
from datetime import datetime, timezone, timedelta
from heatmap.store.dao import Store, RawMessage, Mention
from heatmap.aggregator.pipeline import run_daily_aggregation

@pytest.fixture
async def store(tmp_path):
    s = Store(tmp_path / "t.db")
    await s.init()
    yield s
    await s.close()

async def _seed(store, symbol: str, n: int, day: str):
    dt = datetime.fromisoformat(day + "T12:00:00+00:00")
    for _ in range(n):
        mid = await store.insert_message(RawMessage(
            platform="telegram", channel="@x", author_id=None,
            content=symbol, posted_at=dt, fetched_at=dt,
        ))
        await store.insert_mentions([Mention(mid, symbol, symbol.lower(), False, 1.0)])

async def test_pipeline_picks_surging_symbol(store):
    await _seed(store, "AAA", n=2, day="2026-04-29")   # yesterday
    await _seed(store, "AAA", n=10, day="2026-04-30")  # today, +400%
    await _seed(store, "BBB", n=1, day="2026-04-30")   # noise
    top = await run_daily_aggregation(store, date="2026-04-30",
                                      alpha_min=0.5, beta_min=1.5,
                                      stage_a_top_n=50, stage_b_top_n=10)
    assert top[0].symbol == "AAA"
```

- [ ] **Step 2：跑测试确认失败**

- [ ] **Step 3：实现 `heatmap/aggregator/pipeline.py`**

```python
from datetime import date as DateT, datetime, timedelta
from heatmap.store.dao import Store
from heatmap.aggregator.scoring import weighted_score
from heatmap.aggregator.gates import Candidate, compute_alpha_beta, select_top

def _prev_day(date: str) -> str:
    d = datetime.fromisoformat(date).date()
    return (d - timedelta(days=1)).isoformat()

async def run_daily_aggregation(store: Store, date: str,
                                 alpha_min: float, beta_min: float,
                                 stage_a_top_n: int, stage_b_top_n: int) -> list[Candidate]:
    today_counts = await store.daily_mention_counts(date)
    if not today_counts:
        return []

    # Stage A：按 mention 取 top N
    sorted_today = sorted(today_counts.items(), key=lambda kv: kv[1], reverse=True)
    candidates = sorted_today[:stage_a_top_n]

    # Stage B：加权分（v1 interactions=0，回退为 mention）
    today_weighted = {sym: weighted_score(cnt, 0) for sym, cnt in candidates}
    market_avg = sum(today_weighted.values()) / max(1, len(today_weighted))

    yesterday = _prev_day(date)
    yesterday_counts = await store.daily_mention_counts(yesterday)
    yesterday_weighted = {sym: weighted_score(cnt, 0) for sym, cnt in yesterday_counts.items()}

    cands: list[Candidate] = []
    for sym, w_today in today_weighted.items():
        w_yest = yesterday_weighted.get(sym, 0.0)
        a, b = compute_alpha_beta(w_today, w_yest, market_avg)
        cands.append(Candidate(symbol=sym, alpha=a, beta=b, composite=0.0,
                                mention=today_counts[sym], weighted=w_today))

    top = select_top(cands, alpha_min=alpha_min, beta_min=beta_min, top_n=stage_b_top_n)

    for c in cands:
        await store.upsert_daily_score(
            symbol=c.symbol, date=date, mention_count=c.mention,
            weighted_score=c.weighted, alpha=(None if c.alpha == float("inf") else c.alpha),
            beta=c.beta, composite=c.composite,
        )
    return top
```

- [ ] **Step 4：跑测试通过 + 提交**

```bash
pytest tests/unit/test_pipeline.py -v
git add heatmap/aggregator/pipeline.py tests/unit/test_pipeline.py
git commit -m "feat(aggregator): daily aggregation pipeline"
```

---

## Task 9：Reporter 模板（XML 渲染）

**Files:**
- Create: `heatmap/reporter/__init__.py`
- Create: `heatmap/reporter/templates.py`
- Test: `tests/unit/test_templates.py`

- [ ] **Step 1：写测试**

```python
from heatmap.reporter.templates import render_today_table, render_archive_collapsible
from heatmap.aggregator.gates import Candidate

def _cands():
    return [Candidate("DOGE", 2.2, 3.4, 1.18, 1234, 1234.0)]

def test_today_table_contains_symbol_and_alpha():
    xml = render_today_table(_cands(), date="2026-04-30")
    assert "DOGE" in xml
    assert "+220" in xml  # alpha%
    assert "<table" in xml

def test_archive_wraps_in_collapsible_with_date_title():
    xml = render_archive_collapsible(_cands(), date="2026-04-30")
    assert "<collapsible" in xml
    assert "2026-04-30" in xml
```

- [ ] **Step 2：跑测试确认失败**

- [ ] **Step 3：实现 `heatmap/reporter/templates.py`**

```python
from heatmap.aggregator.gates import Candidate

def _row(idx: int, c: Candidate) -> str:
    new_flag = "🆕" if c.alpha == float("inf") else ""
    alpha_str = "NEW" if c.alpha == float("inf") else f"+{c.alpha*100:.0f}%"
    return (
        f"<tr><td>{idx}</td><td>{c.symbol}</td>"
        f"<td>{c.mention}</td><td>{alpha_str}</td>"
        f"<td>{c.beta:.2f}</td><td>{c.composite:.3f}</td>"
        f"<td>{new_flag}</td></tr>"
    )

def _table(cands: list[Candidate]) -> str:
    head = "<tr><th>排名</th><th>标的</th><th>提及</th><th>α</th><th>β</th><th>复合分</th><th>标记</th></tr>"
    body = "".join(_row(i + 1, c) for i, c in enumerate(cands))
    return f"<table>{head}{body}</table>"

def render_today_table(cands: list[Candidate], date: str) -> str:
    return f"<p>📅 数据日期：{date}</p>" + _table(cands)

def render_archive_collapsible(cands: list[Candidate], date: str) -> str:
    return f"<collapsible><heading2>{date}</heading2>{_table(cands)}</collapsible>"
```

- [ ] **Step 4：跑测试通过 + 提交**

```bash
pytest tests/unit/test_templates.py -v
git add heatmap/reporter/__init__.py heatmap/reporter/templates.py tests/unit/test_templates.py
git commit -m "feat(reporter): xml templates for today table and archive"
```

---

## Task 10：飞书文档发布器（lark-cli 子进程封装）

**Files:**
- Create: `heatmap/reporter/lark_doc.py`
- Test: `tests/unit/test_lark_doc.py`

- [ ] **Step 1：写测试（用 monkeypatch 替换子进程）**

```python
import json
from pathlib import Path
import pytest
from heatmap.reporter.lark_doc import LarkPublisher

class FakeRunner:
    def __init__(self):
        self.calls: list[list[str]] = []
        self.return_token = "doctok123"
    async def run(self, args: list[str]) -> dict:
        self.calls.append(args)
        if "+create" in args:
            return {"data": {"document_id": self.return_token}}
        return {"ok": True}

@pytest.fixture
def state_file(tmp_path: Path):
    return tmp_path / "state.json"

async def test_first_run_creates_doc_and_persists_token(state_file):
    runner = FakeRunner()
    pub = LarkPublisher(state_file=state_file, runner=runner)
    await pub.publish_today(today_xml="<p>today</p>", archive_xml="<collapsible/>")
    assert any("+create" in a for a in runner.calls)
    saved = json.loads(state_file.read_text())
    assert saved["feishu_doc_token"] == "doctok123"

async def test_second_run_uses_persisted_token_only_updates(state_file):
    state_file.write_text(json.dumps({"feishu_doc_token": "tok"}))
    runner = FakeRunner()
    pub = LarkPublisher(state_file=state_file, runner=runner)
    await pub.publish_today(today_xml="<p>today</p>", archive_xml="<collapsible/>")
    flat = [" ".join(a) for a in runner.calls]
    assert not any("+create" in s for s in flat)
    assert any("block_replace" in s for s in flat)
    assert any("append" in s for s in flat)
```

- [ ] **Step 2：跑测试确认失败**

- [ ] **Step 3：实现 `heatmap/reporter/lark_doc.py`**

```python
import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

INITIAL_DOC_XML = (
    "<title>币圈市场热度日报</title>"
    "<heading1>📊 今日榜单</heading1>"
    "<p id=\"cover-anchor\">（首次创建占位）</p>"
    "<heading1>🗂 历史归档</heading1>"
    "<p id=\"archive-anchor\">（每日 append 折叠块到此 anchor 之后）</p>"
)

class CommandRunner(Protocol):
    async def run(self, args: list[str]) -> dict: ...

class LarkCliRunner:
    async def run(self, args: list[str]) -> dict:
        proc = await asyncio.create_subprocess_exec(
            "lark-cli", *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"lark-cli failed: {err.decode()}")
        try:
            return json.loads(out.decode())
        except json.JSONDecodeError:
            return {"raw": out.decode()}

@dataclass
class LarkPublisher:
    state_file: Path
    runner: CommandRunner

    def _load_token(self) -> str | None:
        if not self.state_file.exists():
            return None
        return json.loads(self.state_file.read_text()).get("feishu_doc_token")

    def _save_token(self, token: str) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps({"feishu_doc_token": token}))

    async def _create_doc(self) -> str:
        result = await self.runner.run([
            "docs", "+create", "--api-version", "v2",
            "--content", INITIAL_DOC_XML,
        ])
        token = result.get("data", {}).get("document_id") or result.get("document_id")
        if not token:
            raise RuntimeError(f"cannot extract document_id from: {result}")
        self._save_token(token)
        return token

    async def publish_today(self, today_xml: str, archive_xml: str) -> None:
        token = self._load_token() or await self._create_doc()
        await self.runner.run([
            "docs", "+update", "--api-version", "v2",
            "--doc", token,
            "--command", "block_replace",
            "--target", "cover-anchor",
            "--content", today_xml,
        ])
        await self.runner.run([
            "docs", "+update", "--api-version", "v2",
            "--doc", token,
            "--command", "append",
            "--content", archive_xml,
        ])
```

- [ ] **Step 4：跑测试通过 + 提交**

```bash
pytest tests/unit/test_lark_doc.py -v
git add heatmap/reporter/lark_doc.py tests/unit/test_lark_doc.py
git commit -m "feat(reporter): lark-cli publisher with state persistence"
```

> **注意：** `--target` 与 `--command block_replace` 的实际 flag 形式需在实施时按 lark-doc skill 的 `lark-doc-update.md` 复核；如 CLI 不支持按 anchor id 定位，则改为先 `docs +fetch` 拿到 block_id 后再 `block_replace`。此调整若发生，**只改动 LarkPublisher 内部**，不影响其他模块。

---

## Task 11：Telegram Collector

**Files:**
- Create: `heatmap/collectors/__init__.py`
- Create: `heatmap/collectors/base.py`
- Create: `heatmap/collectors/telegram.py`
- Test: `tests/unit/test_collectors_base.py`

- [ ] **Step 1：写 base 接口测试**

```python
from heatmap.collectors.base import BaseCollector

def test_base_collector_is_protocol_like():
    assert hasattr(BaseCollector, "run")
```

- [ ] **Step 2：跑测试确认失败**

- [ ] **Step 3：实现 `heatmap/collectors/base.py`**

```python
from typing import Protocol

class BaseCollector(Protocol):
    async def run(self) -> None: ...
```

- [ ] **Step 4：实现 `heatmap/collectors/telegram.py`**

```python
import os
from datetime import datetime, timezone
from telethon import TelegramClient, events
from heatmap.store.dao import Store, RawMessage
from heatmap.extractor.ac import AhoCorasickExtractor
from heatmap.store.dao import Mention

class TelegramCollector:
    def __init__(self, store: Store, extractor: AhoCorasickExtractor, channels: list[str]):
        self.store = store
        self.extractor = extractor
        self.channels = channels
        api_id = int(os.environ["TELEGRAM_API_ID"])
        api_hash = os.environ["TELEGRAM_API_HASH"]
        session = os.environ.get("TELEGRAM_SESSION", "heatmap_session")
        self.client = TelegramClient(session, api_id, api_hash)

    async def run(self) -> None:
        await self.client.start()

        @self.client.on(events.NewMessage(chats=self.channels))
        async def handler(event):
            now = datetime.now(timezone.utc)
            content = event.raw_text or ""
            mid = await self.store.insert_message(RawMessage(
                platform="telegram",
                channel=str(event.chat_id),
                author_id=str(event.sender_id) if event.sender_id else None,
                content=content,
                posted_at=event.date.astimezone(timezone.utc) if event.date else now,
                fetched_at=now,
            ))
            hits = self.extractor.extract(content)
            if hits:
                await self.store.insert_mentions([
                    Mention(mid, h.symbol, h.matched_alias, h.is_ambiguous, 1.0)
                    for h in hits
                ])

        await self.client.run_until_disconnected()
```

- [ ] **Step 5：跑测试通过 + 提交**

```bash
pytest tests/unit/test_collectors_base.py -v
git add heatmap/collectors/__init__.py heatmap/collectors/base.py heatmap/collectors/telegram.py tests/unit/test_collectors_base.py
git commit -m "feat(collectors): base protocol and telegram collector"
```

> Telegram collector 集成测试需真实 API 凭证，归到手工烟雾测试（README 列出步骤），CI 不跑。

---

## Task 12：Discord Collector

**Files:**
- Create: `heatmap/collectors/discord.py`

- [ ] **Step 1：实现**

```python
import os
from datetime import datetime, timezone
import discord
from heatmap.store.dao import Store, RawMessage, Mention
from heatmap.extractor.ac import AhoCorasickExtractor

class DiscordCollector:
    def __init__(self, store: Store, extractor: AhoCorasickExtractor,
                 watch_channel_ids: set[int]):
        self.store = store
        self.extractor = extractor
        self.watch = watch_channel_ids
        intents = discord.Intents.default()
        intents.message_content = True
        self.client = discord.Client(intents=intents)
        self.client.event(self.on_message)

    async def on_message(self, message: discord.Message):
        if message.author.bot or message.channel.id not in self.watch:
            return
        now = datetime.now(timezone.utc)
        mid = await self.store.insert_message(RawMessage(
            platform="discord",
            channel=str(message.channel.id),
            author_id=str(message.author.id),
            content=message.content,
            posted_at=message.created_at.astimezone(timezone.utc),
            fetched_at=now,
        ))
        hits = self.extractor.extract(message.content)
        if hits:
            await self.store.insert_mentions([
                Mention(mid, h.symbol, h.matched_alias, h.is_ambiguous, 1.0) for h in hits
            ])

    async def run(self) -> None:
        token = os.environ["DISCORD_BOT_TOKEN"]
        await self.client.start(token)
```

- [ ] **Step 2：提交**

```bash
git add heatmap/collectors/discord.py
git commit -m "feat(collectors): discord collector"
```

---

## Task 13：Scheduler（串联 collectors + 每日聚合 + 飞书发布）

**Files:**
- Create: `heatmap/scheduler.py`
- Test: `tests/integration/test_end_to_end.py`
- Create: `tests/fixtures/sample_messages.jsonl`

- [ ] **Step 1：写 fixture（10 条消息，AAA 暴涨、BBB 普通）**

```jsonl
{"platform":"telegram","channel":"@x","author":"u1","content":"AAA pump","posted_at":"2026-04-29T12:00:00+00:00"}
{"platform":"telegram","channel":"@x","author":"u1","content":"AAA","posted_at":"2026-04-29T13:00:00+00:00"}
{"platform":"telegram","channel":"@x","author":"u1","content":"AAA AAA","posted_at":"2026-04-30T01:00:00+00:00"}
{"platform":"telegram","channel":"@x","author":"u1","content":"AAA","posted_at":"2026-04-30T02:00:00+00:00"}
{"platform":"telegram","channel":"@x","author":"u1","content":"AAA","posted_at":"2026-04-30T03:00:00+00:00"}
{"platform":"telegram","channel":"@x","author":"u1","content":"AAA","posted_at":"2026-04-30T04:00:00+00:00"}
{"platform":"telegram","channel":"@x","author":"u1","content":"AAA","posted_at":"2026-04-30T05:00:00+00:00"}
{"platform":"telegram","channel":"@x","author":"u1","content":"AAA","posted_at":"2026-04-30T06:00:00+00:00"}
{"platform":"telegram","channel":"@x","author":"u1","content":"BBB chill","posted_at":"2026-04-30T07:00:00+00:00"}
{"platform":"telegram","channel":"@x","author":"u1","content":"BBB","posted_at":"2026-04-30T08:00:00+00:00"}
```

- [ ] **Step 2：写集成测试**

```python
import json
from datetime import datetime
from pathlib import Path
import pytest
from heatmap.store.dao import Store, RawMessage, Mention
from heatmap.extractor.ac import AhoCorasickExtractor
from heatmap.extractor.dictionary import AliasEntry
from heatmap.aggregator.pipeline import run_daily_aggregation
from heatmap.reporter.templates import render_today_table, render_archive_collapsible
from heatmap.reporter.lark_doc import LarkPublisher

class FakeRunner:
    def __init__(self): self.calls = []
    async def run(self, args):
        self.calls.append(args)
        if "+create" in args: return {"data": {"document_id": "tok"}}
        return {"ok": True}

@pytest.mark.asyncio
async def test_end_to_end(tmp_path: Path):
    fixture = Path(__file__).parent.parent / "fixtures" / "sample_messages.jsonl"
    store = Store(tmp_path / "t.db"); await store.init()
    ext = AhoCorasickExtractor([
        AliasEntry("AAA", "AAA", False, "seed"),
        AliasEntry("BBB", "BBB", False, "seed"),
    ])
    for line in fixture.read_text().splitlines():
        rec = json.loads(line)
        dt = datetime.fromisoformat(rec["posted_at"])
        mid = await store.insert_message(RawMessage(
            platform=rec["platform"], channel=rec["channel"], author_id=rec["author"],
            content=rec["content"], posted_at=dt, fetched_at=dt,
        ))
        hits = ext.extract(rec["content"])
        if hits:
            await store.insert_mentions([
                Mention(mid, h.symbol, h.matched_alias, h.is_ambiguous, 1.0) for h in hits
            ])
    top = await run_daily_aggregation(store, "2026-04-30",
        alpha_min=0.5, beta_min=1.5, stage_a_top_n=50, stage_b_top_n=10)
    assert top and top[0].symbol == "AAA"

    today_xml = render_today_table(top, "2026-04-30")
    archive_xml = render_archive_collapsible(top, "2026-04-30")
    pub = LarkPublisher(state_file=tmp_path / "state.json", runner=FakeRunner())
    await pub.publish_today(today_xml=today_xml, archive_xml=archive_xml)
    await store.close()
```

- [ ] **Step 3：跑测试确认失败**

- [ ] **Step 4：实现 `heatmap/scheduler.py`**

```python
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

from heatmap.config import load_thresholds, load_sources
from heatmap.store.dao import Store
from heatmap.extractor.dictionary import load_aliases
from heatmap.extractor.ac import AhoCorasickExtractor
from heatmap.aggregator.pipeline import run_daily_aggregation
from heatmap.reporter.templates import render_today_table, render_archive_collapsible
from heatmap.reporter.lark_doc import LarkPublisher, LarkCliRunner
from heatmap.collectors.telegram import TelegramCollector
from heatmap.collectors.discord import DiscordCollector

LOG = logging.getLogger("heatmap.scheduler")

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"
DATA = ROOT / "data"

async def _daily_loop(store: Store, thresholds, publisher: LarkPublisher):
    while True:
        now = datetime.now(timezone.utc)
        next_run = (now + timedelta(days=1)).replace(hour=0, minute=5, second=0, microsecond=0)
        await asyncio.sleep((next_run - now).total_seconds())
        date = (next_run - timedelta(days=1)).date().isoformat()
        try:
            top = await run_daily_aggregation(store, date,
                alpha_min=thresholds.alpha_min, beta_min=thresholds.beta_min,
                stage_a_top_n=thresholds.stage_a_top_n, stage_b_top_n=thresholds.stage_b_top_n)
            today_xml = render_today_table(top, date)
            archive_xml = render_archive_collapsible(top, date)
            await publisher.publish_today(today_xml=today_xml, archive_xml=archive_xml)
            LOG.info("published %s, %d symbols", date, len(top))
        except Exception:
            LOG.exception("daily report failed for %s", date)

async def main():
    logging.basicConfig(level=logging.INFO)
    thresholds = load_thresholds(CONFIG / "thresholds.yaml")
    sources = load_sources(CONFIG / "sources.yaml")
    aliases = load_aliases(CONFIG / "aliases.csv")
    extractor = AhoCorasickExtractor(aliases)

    store = Store(DATA / "heatmap.db"); await store.init()
    publisher = LarkPublisher(state_file=DATA / "state.json", runner=LarkCliRunner())

    tasks = [asyncio.create_task(_daily_loop(store, thresholds, publisher))]

    if sources.telegram.channels:
        tasks.append(asyncio.create_task(
            TelegramCollector(store, extractor, sources.telegram.channels).run()
        ))
    if sources.discord.guilds:
        watch = {int(cid) for g in sources.discord.guilds for cid in g.channel_ids}
        tasks.append(asyncio.create_task(
            DiscordCollector(store, extractor, watch).run()
        ))

    await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 5：跑集成测试通过 + 提交**

```bash
pytest tests/integration/test_end_to_end.py -v
git add heatmap/scheduler.py tests/integration/ tests/fixtures/
git commit -m "feat: scheduler glue + end-to-end integration test"
```

---

## Task 14：别名进化离线脚本 + README

**Files:**
- Create: `scripts/suggest_aliases.py`
- Create: `README.md`（覆盖根目录现有的空 README）

- [ ] **Step 1：实现 `scripts/suggest_aliases.py`**

```python
"""扫描近 30 天 raw_messages，对未命中任何 symbol 的高频词产出别名候选。
v1 仅产出 data/alias_suggestions.csv，等待人工审核。
"""
import asyncio
import csv
import re
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

import aiosqlite

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "heatmap.db"
OUT = ROOT / "data" / "alias_suggestions.csv"

WORD_RE = re.compile(r"[A-Za-z]{3,15}|[\u4e00-\u9fa5]{2,6}")

async def main():
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    counter: Counter[str] = Counter()
    async with aiosqlite.connect(DB) as db:
        async with db.execute(
            "SELECT r.content FROM raw_messages r "
            "LEFT JOIN mentions m ON m.message_id = r.id "
            "WHERE m.id IS NULL AND r.posted_at >= ?", (cutoff,)
        ) as cur:
            async for (content,) in cur:
                for w in WORD_RE.findall(content or ""):
                    counter[w.lower()] += 1
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["candidate", "frequency"])
        for word, freq in counter.most_common(200):
            w.writerow([word, freq])
    print(f"wrote {OUT}")

if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2：写 `README.md`**

```markdown
# Crypto Heatmap MVP

币圈社媒（Telegram + Discord）热度采集 → 双闸门打分 → 飞书日报。

## 安装

\`\`\`bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
\`\`\`

## 配置

- `config/sources.yaml`：填入要监听的 Telegram 频道、Discord 服务器/频道。
- `config/aliases.csv`：维护标的与俚称的映射，`is_ambiguous=true` 标记歧义词。
- `config/thresholds.yaml`：α/β 阈值。
- 环境变量：`TELEGRAM_API_ID`、`TELEGRAM_API_HASH`、`DISCORD_BOT_TOKEN`。
- 飞书：先在另一个 shell 跑 `lark-cli config init` 与 `lark-cli auth login --scope ...` 完成授权（参考 lark-shared skill）。

## 运行

\`\`\`bash
python -m heatmap.scheduler
\`\`\`

## 测试

\`\`\`bash
pytest -v
\`\`\`

## 文档

- 设计稿：[docs/superpowers/specs/2026-04-30-crypto-heatmap-design.md](docs/superpowers/specs/2026-04-30-crypto-heatmap-design.md)
- 实现计划：[docs/superpowers/plans/2026-04-30-crypto-heatmap-plan.md](docs/superpowers/plans/2026-04-30-crypto-heatmap-plan.md)
```

- [ ] **Step 3：提交**

```bash
git add scripts/suggest_aliases.py README.md
git commit -m "docs: add README and alias suggestion script"
```

---

## Self-Review 结论

- **Spec 覆盖**：第 2–10 节每节都有对应任务（Task 2=配置、3=存储、4–5=抽取、6–8=聚合、9–10=报告、11–12=采集、13=调度、14=别名脚本/README）。第 9 节测试要求散在每个 Task 内。第 11 节"开放问题"明确属 v1.1，本计划不覆盖，符合范围。
- **类型一致性**：`Candidate`、`Hit`、`AliasEntry`、`RawMessage`、`Mention` 在所有引用任务中签名一致；`weighted_score(mention, interactions)` 与 `compute_alpha_beta(today, yesterday, market_avg)` 签名贯穿 Task 6/7/8。
- **Placeholder 扫描**：无 TBD/TODO；每段 code 都给出可落地实现。
- **已知风险（已说明应对）**：Task 10 中 `lark-cli docs +update --command block_replace --target` 的实际 flag 形式需在实施时按 lark-doc skill 文档复核——已在该任务下方加了"调整不影响其他模块"的隔离说明。

---

## Execution Handoff

**Plan complete and saved to [docs/superpowers/plans/2026-04-30-crypto-heatmap-plan.md](2026-04-30-crypto-heatmap-plan.md). Two execution options:**

**1. Subagent-Driven（推荐）** — 每个 Task 派一个 fresh subagent，任务间审核，迭代快。

**2. Inline Execution** — 在当前会话用 executing-plans 串行跑，带检查点。

**选哪种？**
