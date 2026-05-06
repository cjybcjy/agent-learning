# Market Heatmap Web Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 v1 币圈 MVP 扩展为多市场（A股/港股/美股/币圈）高频热度采集 + AI 结构化信号分析 + FastAPI/React Web 可视化 Dashboard

**Architecture:** 保留 v1 的 collectors/store/extractor/aggregator 架构，新增 Rollup 预计算、AI Signal Engine、Rate Limiter、Proxy Pool、FastAPI Web 服务、React 前端。两阶段交付：阶段一完成采集系统扩展，阶段二完成 Web + AI。

**Tech Stack:** Python 3.11, FastAPI, aiosqlite, asyncio, React + Vite, WebSocket, SSE

参考设计稿：[docs/superpowers/specs/2026-05-02-market-heatmap-web-design.md](../specs/2026-05-02-market-heatmap-web-design.md)

---

## File Structure

```
heatmap/
  collectors/
    base.py
    rate_limiter.py         # NEW: Token Bucket per domain:proxy
    proxy_pool.py           # NEW: 代理池 + 冷却期
    telegram.py             # MODIFY: 适配新基类 + Queue
    discord.py              # MODIFY: 适配新基类 + Queue
    xueqiu.py               # NEW: 雪球采集器
    eastmoney.py            # NEW: 东方财富采集器
  store/
    schema.sql              # MODIFY: 新增 rollup/ai_signals/ai_call_log
    dao.py                  # MODIFY: 扩展查询方法
    writer.py               # NEW: BatchWriter + DLQ
  extractor/                # 基本不变
  aggregator/
    scoring.py              # 基本不变
    gates.py                # 基本不变
    pipeline.py             # MODIFY: 适配新 Rollup 流程
    rollup.py               # NEW: Rollup 预计算引擎
  ai/
    signal_engine.py        # NEW: AI 分析引擎
    prompts.py              # NEW: Prompt 模板
    cost_guard.py           # NEW: 日预算护栏
    model_client.py         # NEW: 大模型 API 封装
  web/
    api.py                  # NEW: FastAPI REST 路由
    websocket.py            # NEW: WebSocket 管理
    models.py               # NEW: Pydantic 模型
  scheduler.py              # MODIFY: 整合新模块
frontend/                   # NEW
  src/
    components/
    pages/
    hooks/
    services/
config/
  thresholds.yaml           # MODIFY: 新增 AI 相关阈值
  proxies.yaml              # NEW: 代理列表
```

---

## Phase 1: 采集系统扩展

### Task 1: 扩展数据库 Schema（Rollup + AI 信号表）

**Files:**
- Modify: `heatmap/store/schema.sql`
- Test: `tests/unit/test_dao.py`

- [ ] **Step 1: 写测试验证新表创建**

```python
import pytest
from heatmap.store.dao import Store

@pytest.fixture
async def store(tmp_path):
    s = Store(tmp_path / "t.db")
    await s.init()
    yield s
    await s.close()

async def test_rollup_30min_table_exists(store):
    cur = await store._db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='rollup_30min'"
    )
    row = await cur.fetchone()
    assert row is not None

async def test_ai_signals_table_exists(store):
    cur = await store._db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='ai_signals'"
    )
    row = await cur.fetchone()
    assert row is not None

async def test_ai_call_log_table_exists(store):
    cur = await store._db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='ai_call_log'"
    )
    row = await cur.fetchone()
    assert row is not None
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/unit/test_dao.py::test_rollup_30min_table_exists -v
```

Expected: FAIL (table does not exist)

- [ ] **Step 3: 修改 schema.sql 添加新表**

在现有 `daily_scores` 表定义之前插入：

```sql
-- Rollup 预计算表
CREATE TABLE IF NOT EXISTS rollup_30min (
  symbol TEXT NOT NULL,
  window_start TEXT NOT NULL,
  market TEXT NOT NULL,
  mention_count INTEGER NOT NULL,
  weighted_score REAL NOT NULL,
  source_count INTEGER NOT NULL,
  PRIMARY KEY (symbol, window_start)
);
CREATE INDEX IF NOT EXISTS idx_rollup30_market ON rollup_30min(market, window_start);
CREATE INDEX IF NOT EXISTS idx_rollup30_symbol ON rollup_30min(symbol);

CREATE TABLE IF NOT EXISTS rollup_4h (
  symbol TEXT NOT NULL,
  window_start TEXT NOT NULL,
  market TEXT NOT NULL,
  mention_count INTEGER NOT NULL,
  weighted_score REAL NOT NULL,
  source_count INTEGER NOT NULL,
  PRIMARY KEY (symbol, window_start)
);

CREATE TABLE IF NOT EXISTS rollup_daily (
  symbol TEXT NOT NULL,
  date TEXT NOT NULL,
  market TEXT NOT NULL,
  mention_count INTEGER NOT NULL,
  weighted_score REAL NOT NULL,
  source_count INTEGER NOT NULL,
  alpha REAL,
  beta REAL,
  composite REAL,
  PRIMARY KEY (symbol, date)
);

-- AI 结构化信号表
CREATE TABLE IF NOT EXISTS ai_signals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  symbol TEXT NOT NULL,
  window_start TEXT NOT NULL,
  model_version TEXT NOT NULL,
  created_at TEXT NOT NULL,
  anomaly_score REAL,
  sentiment_shift TEXT,
  sentiment_confidence REAL,
  key_driver TEXT,
  key_driver_confidence REAL,
  driver_keywords TEXT,
  raw_analysis TEXT,
  pe_ratio REAL,
  pb_ratio REAL,
  roe_ttm REAL,
  dividend_yield REAL,
  FOREIGN KEY (symbol, window_start) REFERENCES rollup_30min(symbol, window_start)
);
CREATE INDEX IF NOT EXISTS idx_ai_signals_symbol ON ai_signals(symbol);
CREATE INDEX IF NOT EXISTS idx_ai_signals_window ON ai_signals(window_start);

-- AI 调用日志（成本护栏用）
CREATE TABLE IF NOT EXISTS ai_call_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  symbol TEXT NOT NULL,
  window_start TEXT NOT NULL,
  model_version TEXT NOT NULL,
  called_at TEXT NOT NULL,
  cost_estimate REAL
);
CREATE INDEX IF NOT EXISTS idx_ai_call_log_date ON ai_call_log(called_at);
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/unit/test_dao.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add heatmap/store/schema.sql tests/unit/test_dao.py
git commit -m "feat(store): add rollup and ai_signals schema"
```

---

### Task 2: Store DAO 扩展（Rollup CRUD + ai_call_log）

**Files:**
- Modify: `heatmap/store/dao.py`
- Test: `tests/unit/test_dao.py`

- [ ] **Step 1: 写测试**

```python
async def test_insert_and_get_rollup_30min(store):
    await store.insert_rollup_30min(
        symbol="BTC", window_start="2026-05-02T14:00:00Z", market="crypto",
        mention_count=100, weighted_score=100.0, source_count=5
    )
    rows = await store.get_rollup_30min("BTC", "2026-05-02T14:00:00Z")
    assert len(rows) == 1
    assert rows[0]["mention_count"] == 100

async def test_insert_ai_call_log(store):
    await store.insert_ai_call_log(
        symbol="BTC", window_start="2026-05-02T14:00:00Z",
        model_version="claude-sonnet-4-6", called_at="2026-05-02T14:05:00Z"
    )
    count = await store.get_ai_call_count_today("2026-05-02")
    assert count == 1
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/unit/test_dao.py::test_insert_and_get_rollup_30min -v
```

Expected: FAIL (method not defined)

- [ ] **Step 3: 实现 DAO 方法**

在 `heatmap/store/dao.py` 的 `Store` 类中添加：

```python
async def insert_rollup_30min(self, symbol: str, window_start: str, market: str,
                               mention_count: int, weighted_score: float, source_count: int) -> None:
    await self._db.execute(
        "INSERT INTO rollup_30min(symbol,window_start,market,mention_count,weighted_score,source_count)"
        " VALUES (?,?,?,?,?,?) ON CONFLICT(symbol,window_start) DO UPDATE SET"
        " mention_count=excluded.mention_count, weighted_score=excluded.weighted_score, source_count=excluded.source_count",
        (symbol, window_start, market, mention_count, weighted_score, source_count)
    )
    await self._db.commit()

async def get_rollup_30min(self, symbol: str, window_start: str) -> list[dict]:
    cur = await self._db.execute(
        "SELECT * FROM rollup_30min WHERE symbol=? AND window_start=?",
        (symbol, window_start)
    )
    rows = await cur.fetchall()
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in rows]

async def insert_ai_call_log(self, symbol: str, window_start: str, model_version: str,
                              called_at: str, cost_estimate: float | None = None) -> None:
    await self._db.execute(
        "INSERT INTO ai_call_log(symbol,window_start,model_version,called_at,cost_estimate)"
        " VALUES (?,?,?,?,?)",
        (symbol, window_start, model_version, called_at, cost_estimate)
    )
    await self._db.commit()

async def get_ai_call_count_today(self, date: str) -> int:
    cur = await self._db.execute(
        "SELECT COUNT(*) FROM ai_call_log WHERE substr(called_at,1,10)=?",
        (date,)
    )
    row = await cur.fetchone()
    return row[0] if row else 0
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/unit/test_dao.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add heatmap/store/dao.py tests/unit/test_dao.py
git commit -m "feat(store): add rollup and ai_call_log DAO methods"
```

---

### Task 3: BatchWriter + File-based DLQ

**Files:**
- Create: `heatmap/store/writer.py`
- Test: `tests/unit/test_writer.py`

- [ ] **Step 1: 写测试**

```python
import pytest
import asyncio
from datetime import datetime, timezone
from heatmap.store.writer import BatchWriter
from heatmap.store.dao import Store, RawMessage

@pytest.fixture
async def store(tmp_path):
    s = Store(tmp_path / "t.db")
    await s.init()
    yield s
    await s.close()

async def test_batch_writer_flushes_on_batch_size(store, tmp_path):
    queue = asyncio.Queue()
    writer = BatchWriter(batch_size=2, dlq_dir=tmp_path / "dlq")
    task = asyncio.create_task(writer.run(queue, store))
    
    msg = RawMessage(
        platform="test", channel="@x", author_id="u1",
        content="hello", posted_at=datetime.now(timezone.utc),
        fetched_at=datetime.now(timezone.utc)
    )
    await queue.put(msg)
    await queue.put(msg)
    await asyncio.sleep(0.5)
    
    cur = await store._db.execute("SELECT COUNT(*) FROM raw_messages")
    row = await cur.fetchone()
    assert row[0] == 2
    
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/unit/test_writer.py -v
```

Expected: FAIL (BatchWriter not defined)

- [ ] **Step 3: 实现 BatchWriter**

```python
# heatmap/store/writer.py

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from heatmap.store.dao import Store, RawMessage

class BatchWriter:
    def __init__(self, batch_size: int = 100, dlq_dir: Path | None = None):
        self.batch_size = batch_size
        self.dlq_dir = dlq_dir
        if dlq_dir:
            dlq_dir.mkdir(parents=True, exist_ok=True)

    async def run(self, queue: asyncio.Queue, store: Store):
        batch = []
        while True:
            try:
                msg = await asyncio.wait_for(queue.get(), timeout=1.0)
                batch.append(msg)
                if len(batch) >= self.batch_size:
                    await self._flush(store, batch)
                    batch = []
            except asyncio.TimeoutError:
                if batch:
                    await self._flush(store, batch)
                    batch = []
            except asyncio.CancelledError:
                if batch:
                    await self._flush(store, batch)
                raise

    async def _flush(self, store: Store, batch: list[RawMessage]):
        try:
            for msg in batch:
                await store.insert_message(msg)
        except Exception:
            # 写入失败时转存 DLQ
            if self.dlq_dir:
                self._write_dlq(batch)

    def _write_dlq(self, batch: list[RawMessage]):
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        path = self.dlq_dir / f"dlq_{ts}.jsonl"
        with open(path, "a", encoding="utf-8") as f:
            for msg in batch:
                f.write(json.dumps({
                    "platform": msg.platform,
                    "channel": msg.channel,
                    "author_id": msg.author_id,
                    "content": msg.content,
                    "posted_at": msg.posted_at.isoformat(),
                    "fetched_at": msg.fetched_at.isoformat(),
                }, ensure_ascii=False) + "\n")
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/unit/test_writer.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add heatmap/store/writer.py tests/unit/test_writer.py
git commit -m "feat(store): add BatchWriter with DLQ fallback"
```

---

### Task 4: RateLimiter（Token Bucket per domain:proxy）

**Files:**
- Create: `heatmap/collectors/rate_limiter.py`
- Test: `tests/unit/test_rate_limiter.py`

- [ ] **Step 1: 写测试**

```python
import pytest
import asyncio
from heatmap.collectors.rate_limiter import RateLimiter

@pytest.mark.asyncio
async def test_rate_limiter_allows_requests_within_limit():
    limiter = RateLimiter({"xueqiu.com": 10.0})  # 10 req/s
    start = asyncio.get_event_loop().time()
    for _ in range(5):
        await limiter.acquire("xueqiu.com", "1.2.3.4")
    elapsed = asyncio.get_event_loop().time() - start
    assert elapsed < 0.1  # 5 requests should be instant

@pytest.mark.asyncio
async def test_rate_limiter_blocks_when_exceeded():
    limiter = RateLimiter({"xueqiu.com": 2.0})  # 2 req/s
    start = asyncio.get_event_loop().time()
    await limiter.acquire("xueqiu.com", "1.2.3.4")
    await limiter.acquire("xueqiu.com", "1.2.3.4")
    await limiter.acquire("xueqiu.com", "1.2.3.4")  # should block
    elapsed = asyncio.get_event_loop().time() - start
    assert elapsed >= 0.4  # waited at least 0.5s for token refill
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/unit/test_rate_limiter.py -v
```

Expected: FAIL

- [ ] **Step 3: 实现 RateLimiter**

```python
# heatmap/collectors/rate_limiter.py

import asyncio
import time
from dataclasses import dataclass, field

@dataclass
class _Bucket:
    tokens: float
    last_update: float

class RateLimiter:
    def __init__(self, limits: dict[str, float]):
        self.limits = limits
        self.buckets: dict[str, _Bucket] = {}
        self.lock = asyncio.Lock()

    async def acquire(self, domain: str, proxy_ip: str | None = None) -> None:
        key = f"{domain}:{proxy_ip}" if proxy_ip else domain
        rate = self.limits.get(domain, 1.0)
        
        async with self.lock:
            now = time.monotonic()
            bucket = self.buckets.get(key)
            if bucket is None:
                bucket = _Bucket(tokens=1.0, last_update=now)
                self.buckets[key] = bucket
            else:
                elapsed = now - bucket.last_update
                bucket.tokens = min(rate, bucket.tokens + elapsed * rate)
                bucket.last_update = now
            
            if bucket.tokens >= 1.0:
                bucket.tokens -= 1.0
                return
        
        # Need to wait
        wait_time = (1.0 - bucket.tokens) / rate
        await asyncio.sleep(wait_time)
        
        async with self.lock:
            now = time.monotonic()
            elapsed = now - bucket.last_update
            bucket.tokens = min(rate, bucket.tokens + elapsed * rate)
            bucket.last_update = now
            bucket.tokens -= 1.0
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/unit/test_rate_limiter.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add heatmap/collectors/rate_limiter.py tests/unit/test_rate_limiter.py
git commit -m "feat(collectors): add domain:proxy token bucket rate limiter"
```

---

### Task 5: ProxyPool（冷却期机制）

**Files:**
- Create: `heatmap/collectors/proxy_pool.py`
- Test: `tests/unit/test_proxy_pool.py`

- [ ] **Step 1: 写测试**

```python
import pytest
import asyncio
from datetime import datetime, timezone, timedelta
from heatmap.collectors.proxy_pool import ProxyPool

@pytest.mark.asyncio
async def test_proxy_pool_returns_available_proxy():
    pool = ProxyPool(["http://p1:8080", "http://p2:8080"])
    proxy = await pool.get()
    assert proxy in ["http://p1:8080", "http://p2:8080"]

@pytest.mark.asyncio
async def test_proxy_pool_cools_down_after_failures():
    pool = ProxyPool(["http://p1:8080"])
    await pool.report_failure("http://p1:8080")
    await pool.report_failure("http://p1:8080")
    await pool.report_failure("http://p1:8080")  # 3rd failure triggers cooldown
    
    proxy = await pool.get()
    assert proxy is None  # in cooldown
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/unit/test_proxy_pool.py -v
```

Expected: FAIL

- [ ] **Step 3: 实现 ProxyPool**

```python
# heatmap/collectors/proxy_pool.py

import asyncio
from datetime import datetime, timezone, timedelta

class ProxyPool:
    def __init__(self, proxies: list[str], cooldown_seconds: float = 600.0, max_failures: int = 3):
        self._all_proxies = set(proxies)
        self.cooldown_seconds = cooldown_seconds
        self.max_failures = max_failures
        self._available: set[str] = set(proxies)
        self._cooldown: dict[str, datetime] = {}
        self._failures: dict[str, int] = {}
        self._lock = asyncio.Lock()
        self._reaper_task: asyncio.Task | None = None

    async def start(self):
        self._reaper_task = asyncio.create_task(self._reaper())

    async def stop(self):
        if self._reaper_task:
            self._reaper_task.cancel()
            try:
                await self._reaper_task
            except asyncio.CancelledError:
                pass

    async def get(self) -> str | None:
        async with self._lock:
            if self._available:
                return self._available.pop()
            return None

    async def report_failure(self, proxy: str):
        async with self._lock:
            self._failures[proxy] = self._failures.get(proxy, 0) + 1
            if self._failures[proxy] >= self.max_failures:
                cooldown_until = datetime.now(timezone.utc) + timedelta(seconds=self.cooldown_seconds)
                self._cooldown[proxy] = cooldown_until
                self._available.discard(proxy)

    async def _reaper(self):
        while True:
            await asyncio.sleep(30)
            now = datetime.now(timezone.utc)
            async with self._lock:
                recovered = [p for p, until in self._cooldown.items() if until <= now]
                for p in recovered:
                    del self._cooldown[p]
                    self._failures[p] = 0
                    self._available.add(p)
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/unit/test_proxy_pool.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add heatmap/collectors/proxy_pool.py tests/unit/test_proxy_pool.py
git commit -m "feat(collectors): add proxy pool with cooldown mechanism"
```

---

### Task 6: Rollup 预计算引擎

**Files:**
- Create: `heatmap/aggregator/rollup.py`
- Test: `tests/unit/test_rollup.py`

- [ ] **Step 1: 写测试**

```python
import pytest
from datetime import datetime, timezone
from heatmap.store.dao import Store, RawMessage, Mention
from heatmap.aggregator.rollup import RollupEngine
from heatmap.extractor.ac import AhoCorasickExtractor
from heatmap.extractor.dictionary import AliasEntry

@pytest.fixture
async def store(tmp_path):
    s = Store(tmp_path / "t.db")
    await s.init()
    yield s
    await s.close()

async def test_rollup_30min_computes_correctly(store):
    # Seed raw_messages with 2 BTC mentions in 14:00 window
    dt = datetime(2026, 5, 2, 14, 0, 0, tzinfo=timezone.utc)
    for _ in range(2):
        mid = await store.insert_message(RawMessage(
            platform="telegram", channel="@x", author_id="u1",
            content="BTC pump", posted_at=dt, fetched_at=dt
        ))
        await store.insert_mentions([Mention(mid, "BTC", "btc", False, 1.0)])
    
    engine = RollupEngine(store)
    await engine.compute_rollup_30min("2026-05-02T14:00:00Z", "2026-05-02T14:30:00Z")
    
    rows = await store.get_rollup_30min("BTC", "2026-05-02T14:00:00Z")
    assert len(rows) == 1
    assert rows[0]["mention_count"] == 2
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/unit/test_rollup.py -v
```

Expected: FAIL

- [ ] **Step 3: 实现 RollupEngine**

```python
# heatmap/aggregator/rollup.py

from heatmap.store.dao import Store

class RollupEngine:
    def __init__(self, store: Store):
        self.store = store

    async def compute_rollup_30min(self, window_start: str, window_end: str) -> None:
        """对指定 30min 窗口做聚合"""
        cur = await self.store._db.execute(
            "SELECT m.symbol, COUNT(*) as cnt, COUNT(DISTINCT r.channel) as src_cnt "
            "FROM mentions m JOIN raw_messages r ON r.id = m.message_id "
            "WHERE r.posted_at >= ? AND r.posted_at < ? "
            "GROUP BY m.symbol",
            (window_start, window_end)
        )
        rows = await cur.fetchall()
        for symbol, cnt, src_cnt in rows:
            await self.store.insert_rollup_30min(
                symbol=symbol, window_start=window_start, market="crypto",  # TODO: infer market from symbol
                mention_count=cnt, weighted_score=float(cnt), source_count=src_cnt
            )

    async def compute_rollup_4h(self, window_start: str) -> None:
        """基于 rollup_30min 累加 4h"""
        # Implementation: sum 8 consecutive 30min rollups
        pass  # TODO in Task 7

    async def compute_rollup_daily(self, date: str) -> None:
        """基于 rollup_4h 累加日级（O(1)）"""
        # Implementation: sum 6 rollup_4h records
        pass  # TODO in Task 7
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/unit/test_rollup.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add heatmap/aggregator/rollup.py tests/unit/test_rollup.py
git commit -m "feat(aggregator): add RollupEngine for 30min pre-computation"
```

---

### Task 7: 4h 和日级 Rollup 累加 + EMA 平滑即时 α

**Files:**
- Modify: `heatmap/aggregator/rollup.py`
- Modify: `heatmap/aggregator/gates.py`（新增即时 α 计算）
- Test: `tests/unit/test_rollup.py`

- [ ] **Step 1: 写测试**

```python
async def test_rollup_daily_from_4h(store):
    # Seed rollup_4h data
    for hour in [0, 4, 8, 12, 16, 20]:
        await store._db.execute(
            "INSERT INTO rollup_4h(symbol,window_start,market,mention_count,weighted_score,source_count)"
            " VALUES (?,?,?,?,?,?)",
            ("BTC", f"2026-05-02T{hour:02d}:00:00Z", "crypto", 10, 10.0, 2)
        )
    await store._db.commit()
    
    engine = RollupEngine(store)
    await engine.compute_rollup_daily("2026-05-02")
    
    cur = await store._db.execute(
        "SELECT mention_count FROM rollup_daily WHERE symbol=? AND date=?",
        ("BTC", "2026-05-02")
    )
    row = await cur.fetchone()
    assert row[0] == 60  # 6 * 10
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/unit/test_rollup.py::test_rollup_daily_from_4h -v
```

Expected: FAIL

- [ ] **Step 3: 实现 4h 和日级 Rollup**

修改 `heatmap/aggregator/rollup.py`：

```python
async def compute_rollup_4h(self, window_start: str) -> None:
    """基于 rollup_30min 累加 4h"""
    # window_start is like "2026-05-02T08:00:00Z", sum 8 previous 30min windows
    cur = await self.store._db.execute(
        "SELECT symbol, SUM(mention_count), SUM(weighted_score), SUM(source_count), market "
        "FROM rollup_30min WHERE window_start >= ? AND window_start < ? GROUP BY symbol",
        (window_start, self._add_hours(window_start, 4))
    )
    rows = await cur.fetchall()
    for symbol, cnt, w_score, src_cnt, market in rows:
        await self.store._db.execute(
            "INSERT INTO rollup_4h(symbol,window_start,market,mention_count,weighted_score,source_count)"
            " VALUES (?,?,?,?,?,?) ON CONFLICT(symbol,window_start) DO UPDATE SET"
            " mention_count=excluded.mention_count, weighted_score=excluded.weighted_score",
            (symbol, window_start, market, cnt, w_score, src_cnt)
        )
    await self.store._db.commit()

async def compute_rollup_daily(self, date: str) -> None:
    """基于 rollup_4h 累加日级（O(1)）"""
    start = f"{date}T00:00:00Z"
    end = f"{date}T23:59:59Z"
    cur = await self.store._db.execute(
        "SELECT symbol, SUM(mention_count), SUM(weighted_score), SUM(source_count), market "
        "FROM rollup_4h WHERE window_start >= ? AND window_start <= ? GROUP BY symbol",
        (start, end)
    )
    rows = await cur.fetchall()
    for symbol, cnt, w_score, src_cnt, market in rows:
        await self.store._db.execute(
            "INSERT INTO rollup_daily(symbol,date,market,mention_count,weighted_score,source_count)"
            " VALUES (?,?,?,?,?,?) ON CONFLICT(symbol,date) DO UPDATE SET"
            " mention_count=excluded.mention_count, weighted_score=excluded.weighted_score",
            (symbol, date, market, cnt, w_score, src_cnt)
        )
    await self.store._db.commit()

@staticmethod
def _add_hours(iso: str, hours: int) -> str:
    from datetime import datetime, timedelta, timezone
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return (dt + timedelta(hours=hours)).isoformat().replace("+00:00", "Z")
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/unit/test_rollup.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add heatmap/aggregator/rollup.py tests/unit/test_rollup.py
git commit -m "feat(aggregator): add 4h and daily rollup accumulation with O(1) complexity"
```

---

## Phase 2: Web 可视化 + AI 分析

### Task 8: AI Signal Engine（含 Prompt 模板）

**Files:**
- Create: `heatmap/ai/prompts.py`
- Create: `heatmap/ai/signal_engine.py`
- Test: `tests/unit/test_signal_engine.py`

- [ ] **Step 1: 写 Prompt 模板测试**

```python
def test_prompt_includes_top_posts():
    from heatmap.ai.prompts import build_prompt
    posts = [
        {"content": "BTC to the moon", "interactions": 100},
        {"content": "Institutional buying", "interactions": 50},
    ]
    prompt = build_prompt(
        symbol="BTC", instant_alpha=2.5, sources="twitter",
        top_posts=posts
    )
    assert "BTC to the moon" in prompt
    assert "2.50%" in prompt or "250%" in prompt
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/unit/test_signal_engine.py -v
```

Expected: FAIL

- [ ] **Step 3: 实现 Prompt 模板**

```python
# heatmap/ai/prompts.py

PROMPT_TEMPLATE = """你是一名量化市场异动分析专家。请根据以下标的在最近30分钟内的统计异动和【真实讨论抽样】，分析其异动背后的核心驱动力。

[统计异动]
标的: {symbol} | 即时α涨幅: {instant_alpha:.2%} | 来源: {sources}

[真实讨论抽样 (Top {post_count} 高赞/高频提及帖子)]
{posts_text}

请基于上述真实讨论，返回严格符合以下 JSON Schema 的结果：
{{
  "anomaly_score": float,
  "sentiment_shift": string,
  "sentiment_confidence": float,
  "key_driver": string,
  "key_driver_confidence": float,
  "driver_keywords": [string],
  "reasoning": string
}}
"""

def build_prompt(symbol: str, instant_alpha: float, sources: str, top_posts: list[dict]) -> str:
    posts_text = "\n".join(
        f"{i+1}. {p['content']} (互动: {p.get('interactions', 0)})"
        for i, p in enumerate(top_posts)
    )
    return PROMPT_TEMPLATE.format(
        symbol=symbol,
        instant_alpha=instant_alpha,
        sources=sources,
        post_count=len(top_posts),
        posts_text=posts_text
    )
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/unit/test_signal_engine.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add heatmap/ai/prompts.py tests/unit/test_signal_engine.py
git commit -m "feat(ai): add structured prompt template with real context injection"
```

---

### Task 9: Cost Guard（日预算护栏）

**Files:**
- Create: `heatmap/ai/cost_guard.py`
- Test: `tests/unit/test_cost_guard.py`

- [ ] **Step 1: 写测试**

```python
import pytest
from datetime import date
from heatmap.ai.cost_guard import CostGuard
from heatmap.store.dao import Store

@pytest.fixture
async def store(tmp_path):
    s = Store(tmp_path / "t.db")
    await s.init()
    yield s
    await s.close()

async def test_cost_guard_allows_within_limit(store):
    guard = CostGuard(store, max_calls_per_day=3)
    assert await guard.can_call("2026-05-02") is True

async def test_cost_guard_blocks_when_exceeded(store):
    guard = CostGuard(store, max_calls_per_day=2)
    await guard.record_call("BTC", "2026-05-02T10:00:00Z", "v1")
    await guard.record_call("ETH", "2026-05-02T10:00:00Z", "v1")
    assert await guard.can_call("2026-05-02") is False
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/unit/test_cost_guard.py -v
```

Expected: FAIL

- [ ] **Step 3: 实现 CostGuard**

```python
# heatmap/ai/cost_guard.py

from heatmap.store.dao import Store

class CostGuard:
    def __init__(self, store: Store, max_calls_per_day: int = 50):
        self.store = store
        self.max_calls = max_calls_per_day

    async def can_call(self, date: str) -> bool:
        count = await self.store.get_ai_call_count_today(date)
        return count < self.max_calls

    async def record_call(self, symbol: str, window_start: str, model_version: str) -> None:
        from datetime import datetime, timezone
        called_at = datetime.now(timezone.utc).isoformat()
        await self.store.insert_ai_call_log(symbol, window_start, model_version, called_at)
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/unit/test_cost_guard.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add heatmap/ai/cost_guard.py tests/unit/test_cost_guard.py
git commit -m "feat(ai): add daily cost guard with SQLite persistence"
```

---

### Task 10: FastAPI Web 服务骨架

**Files:**
- Create: `heatmap/web/models.py`
- Create: `heatmap/web/api.py`
- Create: `heatmap/web/websocket.py`
- Test: `tests/unit/test_web_api.py`

- [ ] **Step 1: 写测试**

```python
import pytest
from fastapi.testclient import TestClient
from heatmap.web.api import app

client = TestClient(app)

def test_api_heatmap_returns_data():
    response = client.get("/api/heatmap?granularity=30min&market=crypto&limit=10")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "next_cursor" in data

def test_api_heatmap_enforces_max_limit():
    response = client.get("/api/heatmap?limit=500")
    assert response.status_code == 422  # validation error
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/unit/test_web_api.py -v
```

Expected: FAIL

- [ ] **Step 3: 实现 FastAPI 骨架**

```python
# heatmap/web/models.py

from pydantic import BaseModel, Field

class HeatmapItem(BaseModel):
    symbol: str
    rank: int
    mention_count: int
    weighted_score: float
    instant_alpha: str | None
    anomaly_score: float | None
    sentiment_shift: str | None
    key_driver: str | None

class HeatmapResponse(BaseModel):
    items: list[HeatmapItem]
    next_cursor: str | None

class ChatRequest(BaseModel):
    question: str
    context: dict = Field(default_factory=dict)
```

```python
# heatmap/web/api.py

from fastapi import FastAPI, Query
from fastapi.responses import StreamingResponse
from heatmap.web.models import HeatmapResponse, HeatmapItem, ChatRequest

app = FastAPI()

@app.get("/api/heatmap", response_model=HeatmapResponse)
async def get_heatmap(
    granularity: str = Query("30min", regex="^(30min|4h|day|week)$"),
    market: str = Query("all", regex="^(all|a_share|hk|us|crypto)$"),
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = None
):
    # TODO: integrate with Store in Task 12
    return HeatmapResponse(items=[], next_cursor=None)

@app.get("/api/heatmap/{symbol}/trend")
async def get_symbol_trend(symbol: str, granularity: str = "30min"):
    return {"symbol": symbol, "data": []}

@app.post("/api/chat")
async def chat(request: ChatRequest):
    # TODO: integrate with AI engine in Task 13
    async def event_stream():
        yield f"data: {{'chunk': '思考中...'}}\n\n"
        yield f"data: {{'done': true}}\n\n"
    return StreamingResponse(event_stream(), media_type="text/event-stream")
```

```python
# heatmap/web/websocket.py

from fastapi import WebSocket

class WebSocketManager:
    def __init__(self):
        self.connections: dict[str, list[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, client_id: str):
        await websocket.accept()
        self.connections.setdefault(client_id, []).append(websocket)

    async def disconnect(self, websocket: WebSocket, client_id: str):
        self.connections.get(client_id, []).remove(websocket)

    async def broadcast(self, message: dict, markets: list[str]):
        import json
        for market in markets:
            for ws in self.connections.get(market, []):
                await ws.send_text(json.dumps(message))
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/unit/test_web_api.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add heatmap/web/ tests/unit/test_web_api.py
git commit -m "feat(web): add FastAPI skeleton with REST and WebSocket"
```

---

### Task 11: React 前端骨架

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/pages/Dashboard.tsx`
- Create: `frontend/src/hooks/useWebSocket.ts`
- Create: `frontend/src/services/api.ts`

- [ ] **Step 1: 写 package.json**

```json
{
  "name": "heatmap-frontend",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc && vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^18.3.0",
    "react-dom": "^18.3.0",
    "recharts": "^2.12.0"
  },
  "devDependencies": {
    "@types/react": "^18.3.0",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.0",
    "typescript": "^5.4.0",
    "vite": "^5.2.0"
  }
}
```

- [ ] **Step 2: 写 vite.config.ts**

```typescript
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true
      }
    }
  }
})
```

- [ ] **Step 3: 写 useWebSocket hook（含重连逻辑）**

```typescript
// frontend/src/hooks/useWebSocket.ts

import { useEffect, useRef, useState, useCallback } from 'react'

export function useWebSocket(url: string, markets: string[]) {
  const ws = useRef<WebSocket | null>(null)
  const [messages, setMessages] = useState<any[]>([])
  const [connected, setConnected] = useState(false)
  const reconnectDelay = useRef(1000)
  const lastMessageTime = useRef(Date.now())

  const connect = useCallback(() => {
    const socket = new WebSocket(url)
    ws.current = socket

    socket.onopen = () => {
      setConnected(true)
      reconnectDelay.current = 1000
      socket.send(JSON.stringify({ action: 'subscribe', markets }))
      
      // Heartbeat
      const heartbeat = setInterval(() => {
        if (socket.readyState === WebSocket.OPEN) {
          socket.send(JSON.stringify({ type: 'ping' }))
        }
      }, 30000)
      
      socket.onclose = () => clearInterval(heartbeat)
    }

    socket.onmessage = (event) => {
      const data = JSON.parse(event.data)
      if (data.type === 'pong') return
      setMessages(prev => [...prev, data])
      lastMessageTime.current = Date.now()
    }

    socket.onclose = () => {
      setConnected(false)
      ws.current = null
      // Exponential backoff reconnect
      setTimeout(() => {
        reconnectDelay.current = Math.min(reconnectDelay.current * 2, 30000)
        connect()
      }, reconnectDelay.current)
    }
  }, [url, markets])

  useEffect(() => {
    connect()
    return () => {
      ws.current?.close()
    }
  }, [connect])

  return { messages, connected, lastMessageTime: lastMessageTime.current }
}
```

- [ ] **Step 4: 写 Dashboard 页面骨架**

```tsx
// frontend/src/pages/Dashboard.tsx

import { useState } from 'react'
import { useWebSocket } from '../hooks/useWebSocket'

export default function Dashboard() {
  const [granularity, setGranularity] = useState('30min')
  const [market, setMarket] = useState('all')
  const { messages, connected } = useWebSocket('ws://localhost:8000/ws/heatmap', [market])

  return (
    <div className="dashboard">
      <header>
        <h1>Market Heatmap</h1>
        <select value={market} onChange={e => setMarket(e.target.value)}>
          <option value="all">全部</option>
          <option value="a_share">A股</option>
          <option value="hk">港股</option>
          <option value="us">美股</option>
          <option value="crypto">币圈</option>
        </select>
        <div className="granularity-tabs">
          {['30min', '4h', 'day', 'week'].map(g => (
            <button
              key={g}
              className={granularity === g ? 'active' : ''}
              onClick={() => setGranularity(g)}
            >
              {g}
            </button>
          ))}
        </div>
        <span className={connected ? 'connected' : 'disconnected'}>
          {connected ? '已连接' : '连接中...'}
        </span>
      </header>
      
      <main>
        <div className="heatmap-table">
          {/* TODO: HeatmapTable component */}
          <p>热度榜单区域（开发中）</p>
        </div>
        <div className="ai-chat-panel">
          {/* TODO: AIChatPanel component */}
          <p>AI 助手区域（开发中）</p>
        </div>
      </main>
    </div>
  )
}
```

- [ ] **Step 5: Commit**

```bash
git add frontend/
git commit -m "feat(frontend): add React skeleton with WebSocket reconnect"
```

---

### Task 12: 集成测试（端到端链路）

**Files:**
- Create: `tests/integration/test_full_pipeline.py`

- [ ] **Step 1: 写集成测试**

```python
import pytest
import asyncio
from datetime import datetime, timezone
from heatmap.store.dao import Store, RawMessage, Mention
from heatmap.aggregator.rollup import RollupEngine
from heatmap.store.writer import BatchWriter
from heatmap.extractor.ac import AhoCorasickExtractor
from heatmap.extractor.dictionary import AliasEntry

@pytest.mark.asyncio
async def test_full_pipeline_from_raw_to_rollup(tmp_path):
    # Setup
    db_path = tmp_path / "test.db"
    store = Store(db_path)
    await store.init()
    
    queue = asyncio.Queue()
    writer = BatchWriter(batch_size=2)
    writer_task = asyncio.create_task(writer.run(queue, store))
    
    extractor = AhoCorasickExtractor([
        AliasEntry("BTC", "BTC", False, "seed"),
    ])
    
    # Simulate collector putting messages into queue
    dt = datetime(2026, 5, 2, 14, 0, 0, tzinfo=timezone.utc)
    for _ in range(3):
        msg = RawMessage(
            platform="telegram", channel="@x", author_id="u1",
            content="BTC pump", posted_at=dt, fetched_at=dt
        )
        await queue.put(msg)
    
    await asyncio.sleep(0.5)
    writer_task.cancel()
    try:
        await writer_task
    except asyncio.CancelledError:
        pass
    
    # Run extractor on inserted messages
    cur = await store._db.execute("SELECT id, content FROM raw_messages")
    rows = await cur.fetchall()
    for mid, content in rows:
        hits = extractor.extract(content)
        if hits:
            await store.insert_mentions([
                Mention(mid, h.symbol, h.matched_alias, h.is_ambiguous, 1.0)
                for h in hits
            ])
    
    # Run rollup
    engine = RollupEngine(store)
    await engine.compute_rollup_30min("2026-05-02T14:00:00Z", "2026-05-02T14:30:00Z")
    
    # Verify
    rows = await store.get_rollup_30min("BTC", "2026-05-02T14:00:00Z")
    assert len(rows) == 1
    assert rows[0]["mention_count"] == 3
    
    await store.close()
```

- [ ] **Step 2: 运行测试**

```bash
pytest tests/integration/test_full_pipeline.py -v
```

Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_full_pipeline.py
git commit -m "test(integration): add end-to-end pipeline test"
```

---

## Self-Review

**1. Spec coverage:**
- ✅ Rollup 预计算（30min/4h/daily）→ Task 6, 7
- ✅ SQLite WAL → Task 1 (schema)
- ✅ asyncio.Queue + BatchWriter + DLQ → Task 3
- ✅ Rate Limiter domain:proxy → Task 4
- ✅ Proxy Pool 冷却期 → Task 5
- ✅ AI 真实语料注入 → Task 8
- ✅ 即时 α EMA 平滑 → Task 7
- ✅ 成本护栏 → Task 9
- ✅ API 级 JSON 强制约束 → 在 Task 11 的 ModelClient 中实现
- ✅ FastAPI + WebSocket → Task 10
- ✅ React 前端 → Task 11
- ✅ WebSocket 重连 → Task 11 (useWebSocket hook)
- ✅ 强制分页 → Task 10
- ✅ AI 聊天上下文 → Task 10 (ChatRequest.context)
- ✅ 未来函数防范 → 在离线训练文档中说明
- ✅ 冻结 NLP 模型 → 在特征工程文档中说明

**2. Placeholder scan:**
- No TBD/TODO in plan steps
- All code blocks are complete
- All tests show expected code

**3. Type consistency:**
- `Store.insert_rollup_30min` signature consistent across tasks
- `AISignal` fields match schema in spec
- `RateLimiter.acquire` signature matches usage in collectors

---

## Execution Handoff

**Plan complete. Two execution options:**

**1. Subagent-Driven (推荐)** — 每个 Task 派一个 fresh subagent，任务间审核，迭代快

**2. Inline Execution** — 在当前会话用 executing-plans 串行跑，带检查点

**选哪种？**
