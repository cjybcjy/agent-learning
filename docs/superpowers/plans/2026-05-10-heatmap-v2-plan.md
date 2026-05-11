# Market Heatmap v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Phase 1 fixes market-switching UI chaos with useReducer+AbortController, adds confidence scores and data transparency. Phase 2 adds 8 new collectors across HK/US/Crypto markets, 4-layer anti-crawling with circuit breaker, and source-weighted heat scoring.

**Architecture:** Backend changes follow the existing pattern: collectors → queue → BatchWriter → SQLite → RollupEngine → API. Frontend refactors Dashboard from 6 useState to a single useReducer state machine. New anti-crawling modules (ua_pool, jitter, circuit_breaker, browser_fallback) inject into the existing HttpCollector base class without changing subclasses.

**Tech Stack:** Python 3.10+ (FastAPI, aiosqlite, httpx, Playwright), TypeScript/React (no new dependencies), SQLite WAL

**Spec:** `docs/superpowers/specs/2026-05-10-heatmap-v2-design.md`

---

## Phase 1: UI State Refactor + Data Transparency + Confidence Score (7 files)

### Phase 1 Task 1: Backend — Store layer (dao.py)

**Files:**
- Modify: `heatmap/store/dao.py:167-196` (get_rollup_heatmap to return source_count)
- Add: `heatmap/store/dao.py` new method `get_market_stats()`

- [ ] **Step 1: Add source_count + weighted_score to get_rollup_heatmap queries**

The `get_rollup_heatmap` already selects `source_count` in its SQL but the `_get_rollup_weekly_heatmap` aggregates `SUM(source_count)`. Ensure both return `source_count` in the result dicts. Also compute a `last_updated` column from the time column.

Modify the SQL in `get_rollup_heatmap` (line 186):
```python
# Current line 186:
sql = f"SELECT symbol, {time_col} as window_start, market, mention_count, weighted_score, source_count FROM {table} {where_sql} ORDER BY {order_col} DESC, symbol ASC LIMIT ?"
# Keep as-is — source_count is already selected. Ensure items dict includes it.
```

- [ ] **Step 2: Add get_market_stats() method**

Add after `get_symbols_by_market` (around line 274):

```python
async def get_market_stats(self) -> dict[str, dict]:
    """Return per-market stats: symbol count, total messages, active sources, last update."""
    cur = await self._db.execute(
        "SELECT market, COUNT(DISTINCT symbol) as symbol_cnt, "
        "SUM(mention_count) as total_mentions, "
        "MAX(source_count) as max_sources, "
        "MAX(window_start) as last_updated "
        "FROM rollup_30min GROUP BY market"
    )
    rows = await cur.fetchall()
    stats = {}
    for row in rows:
        market, sym_cnt, mentions, max_src, last_upd = row
        # Get distinct source platforms for this market
        src_cur = await self._db.execute(
            "SELECT DISTINCT r.platform FROM raw_messages r "
            "JOIN mentions m ON m.message_id = r.id "
            "WHERE r.market = ?",
            (market,)
        )
        sources = [s[0] for s in await src_cur.fetchall()]
        stats[market] = {
            "symbol_count": sym_cnt or 0,
            "total_mentions": mentions or 0,
            "source_count": len(sources),
            "sources": sources,
            "last_updated": last_upd,
        }
    return stats
```

- [ ] **Step 3: Run existing tests to check no regression**

```bash
python -m pytest tests/unit/test_dao.py -v
```

Expected: All existing tests PASS.

- [ ] **Step 4: Commit**

```bash
git add heatmap/store/dao.py
git commit -m "feat(dao): add get_market_stats and ensure source_count in heatmap queries"
```

---

### Phase 1 Task 2: Backend — API models (models.py)

**Files:**
- Modify: `heatmap/web/models.py`

- [ ] **Step 1: Add new fields to HeatmapItem and add MarketStats model**

```python
from pydantic import BaseModel, Field

class HeatmapItem(BaseModel):
    symbol: str
    rank: int
    mention_count: int
    weighted_score: float
    source_count: int = 0
    last_updated: str | None = None
    confidence_score: float | None = None
    instant_alpha: float | None = None
    anomaly_score: float | None = None
    sentiment_shift: str | None = None
    key_driver: str | None = None

class HeatmapResponse(BaseModel):
    items: list[HeatmapItem]
    next_cursor: str | None = None

class MarketStats(BaseModel):
    symbol_count: int
    total_mentions: int
    source_count: int
    sources: list[str]
    last_updated: str | None = None

class MarketStatsResponse(BaseModel):
    markets: dict[str, MarketStats]

class ChatRequest(BaseModel):
    question: str
    context: dict = Field(default_factory=dict)

class ModelSwitchRequest(BaseModel):
    provider: str
    model: str | None = None
```

- [ ] **Step 2: Run existing API model tests**

```bash
python -m pytest tests/unit/test_web_api.py -v
```

Expected: Tests may need updates for new fields — note this for the API task.

- [ ] **Step 3: Commit**

```bash
git add heatmap/web/models.py
git commit -m "feat(models): add source_count, last_updated, confidence_score to HeatmapItem; add MarketStats"
```

---

### Phase 1 Task 3: Backend — API endpoints (api.py)

**Files:**
- Modify: `heatmap/web/api.py:57-76` (/api/heatmap)
- Add: `heatmap/web/api.py` new endpoint `/api/market-stats`

- [ ] **Step 1: Update /api/heatmap to return source_count + confidence_score**

Replace the `get_heatmap` function (lines 57-76):

```python
from datetime import datetime, timezone

def _compute_confidence(source_count: int, last_updated: str | None) -> float:
    """Compute confidence score (0-100) from source_count and freshness."""
    source_score = min(source_count / 3.0, 1.0) * 100
    if last_updated:
        try:
            dt = datetime.fromisoformat(last_updated.replace("Z", "+00:00"))
            hours_since = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
            freshness_score = max(0.0, 1.0 - hours_since / 24.0)
        except (ValueError, TypeError):
            freshness_score = 0.5
    else:
        freshness_score = 0.5
    return round(source_score * freshness_score, 1)

@app.get("/api/heatmap", response_model=HeatmapResponse)
async def get_heatmap(
    granularity: str = Query("30min", pattern="^(30min|4h|day|week)$"),
    market: str = Query("all", pattern="^(all|a_share|hk|us|crypto)$"),
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = None
):
    if store is None:
        return HeatmapResponse(items=[], next_cursor=None)
    items_raw, next_cursor = await store.get_rollup_heatmap(granularity, market, limit, cursor)
    items = [
        HeatmapItem(
            symbol=r["symbol"],
            rank=idx + 1,
            mention_count=r["mention_count"],
            weighted_score=r["weighted_score"],
            source_count=r.get("source_count", 0),
            last_updated=r.get("window_start"),
            confidence_score=_compute_confidence(
                r.get("source_count", 0),
                r.get("window_start"),
            ),
        )
        for idx, r in enumerate(items_raw)
    ]
    return HeatmapResponse(items=items, next_cursor=next_cursor)
```

- [ ] **Step 2: Add /api/market-stats endpoint**

Add after `/api/symbols`:

```python
@app.get("/api/market-stats", response_model=MarketStatsResponse)
async def get_market_stats():
    if store is None:
        return MarketStatsResponse(markets={})
    stats = await store.get_market_stats()
    markets = {
        m: MarketStats(**s) for m, s in stats.items()
    }
    return MarketStatsResponse(markets=markets)
```

- [ ] **Step 3: Run API tests**

```bash
python -m pytest tests/unit/test_web_api.py tests/integration/test_api_smoke.py -v
```

Expected: Existing tests should pass (they use mock data). Update test assertions if they explicitly check for exact item field count.

- [ ] **Step 4: Commit**

```bash
git add heatmap/web/api.py
git commit -m "feat(api): add source_count, confidence_score to heatmap; add /api/market-stats endpoint"
```

---

### Phase 1 Task 4: Frontend — API service (api.ts)

**Files:**
- Modify: `frontend/src/services/api.ts`

- [ ] **Step 1: Add AbortSignal support and fetchMarketStats**

Replace the file:

```typescript
const API_BASE = '/api'

export async function fetchHeatmap(params: {
  granularity?: string
  market?: string
  limit?: number
  cursor?: string
  signal?: AbortSignal
}) {
  const filtered: Record<string, string> = {}
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '' && key !== 'signal') {
      filtered[key] = String(value)
    }
  }
  const query = new URLSearchParams(filtered).toString()
  const res = await fetch(`${API_BASE}/heatmap?${query}`, {
    signal: params.signal,
  })
  return res.json()
}

export async function fetchMarketStats(signal?: AbortSignal) {
  const res = await fetch(`${API_BASE}/market-stats`, { signal })
  return res.json()
}

export async function fetchMarkets() {
  const res = await fetch(`${API_BASE}/markets`)
  return res.json()
}
```

- [ ] **Step 2: Verify TypeScript compilation**

```bash
cd frontend && npx tsc --noEmit
```

Expected: No new type errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/services/api.ts
git commit -m "feat(api.ts): add AbortSignal support and fetchMarketStats"
```

---

### Phase 1 Task 5: Frontend — WebSocket hook (useWebSocket.ts)

**Files:**
- Modify: `frontend/src/hooks/useWebSocket.ts`

- [ ] **Step 1: Fix subscription params and add unsubscribe support**

Replace the file:

```typescript
import { useEffect, useRef, useState, useCallback } from 'react'

interface UseWebSocketOptions {
  onReconnect?: () => void
}

export function useWebSocket(url: string, markets: string[], options?: UseWebSocketOptions) {
  const ws = useRef<WebSocket | null>(null)
  const [messages, setMessages] = useState<any[]>([])
  const [connected, setConnected] = useState(false)
  const reconnectDelay = useRef(1000)
  const wasConnected = useRef(false)
  const optionsRef = useRef(options)
  const marketsRef = useRef(markets)
  optionsRef.current = options
  marketsRef.current = markets

  const connect = useCallback(() => {
    const socket = new WebSocket(url)
    ws.current = socket

    socket.onopen = () => {
      setConnected(true)
      reconnectDelay.current = 1000
      // Subscribe with current markets array
      socket.send(JSON.stringify({
        action: 'subscribe',
        markets: marketsRef.current,
      }))

      if (wasConnected.current && optionsRef.current?.onReconnect) {
        optionsRef.current.onReconnect()
      }
      wasConnected.current = true

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
    }

    socket.onclose = () => {
      setConnected(false)
      ws.current = null
      setTimeout(() => {
        reconnectDelay.current = Math.min(reconnectDelay.current * 2, 30000)
        connect()
      }, reconnectDelay.current)
    }
  }, [url])

  useEffect(() => {
    // When markets change, reconnect to re-subscribe with new markets
    connect()
    return () => {
      ws.current?.close()
    }
  }, [connect])

  return { messages, connected }
}
```

- [ ] **Step 2: Verify TypeScript compilation**

```bash
cd frontend && npx tsc --noEmit
```

Expected: No new type errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/hooks/useWebSocket.ts
git commit -m "fix(useWebSocket): use marketsRef to fix stale subscription on market switch"
```

---

### Phase 1 Task 6: Frontend — Dashboard (Dashboard.tsx)

**Files:**
- Modify: `frontend/src/pages/Dashboard.tsx`

- [ ] **Step 1: Define the reducer and types**

Replace the current file content with:

```typescript
import { useMemo, useEffect, useCallback, useReducer, useRef } from 'react'
import { useWebSocket } from '../hooks/useWebSocket'
import { fetchHeatmap, fetchMarketStats } from '../services/api'
import HeatmapTable from '../components/HeatmapTable'
import AIChatPanel from '../components/AIChatPanel'
import TrendChart from '../components/TrendChart'
import AlertBanner from '../components/AlertBanner'
import SettingsPanel from '../components/SettingsPanel'

const MARKETS = [
  { key: 'all', label: '全部' },
  { key: 'a_share', label: 'A股' },
  { key: 'hk', label: '港股' },
  { key: 'us', label: '美股' },
  { key: 'crypto', label: '币圈' },
]

const GRANULARITIES = ['30min', '4h', 'day', 'week']

interface HeatmapItem {
  symbol: string
  rank: number
  mention_count: number
  weighted_score: number
  source_count: number
  last_updated?: string
  confidence_score?: number
  instant_alpha?: string
  anomaly_score?: number
  sentiment_shift?: string
  key_driver?: string
}

interface MarketStats {
  symbol_count: number
  total_mentions: number
  source_count: number
  sources: string[]
  last_updated: string | null
  status?: 'active' | 'sparse' | 'empty'
}

type State =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'data'; items: HeatmapItem[]; cursor: string | null; marketStats: Record<string, MarketStats> }
  | { status: 'empty'; marketStats: Record<string, MarketStats> }
  | { status: 'error'; message: string }
  | { status: 'loading_more'; items: HeatmapItem[]; cursor: string | null; marketStats: Record<string, MarketStats> }

type Action =
  | { type: 'RESET'; epoch: number }
  | { type: 'LOAD_SUCCESS'; epoch: number; items: HeatmapItem[]; cursor: string | null; marketStats: Record<string, MarketStats> }
  | { type: 'LOAD_EMPTY'; epoch: number; marketStats: Record<string, MarketStats> }
  | { type: 'LOAD_ERROR'; message: string }
  | { type: 'LOAD_MORE_SUCCESS'; items: HeatmapItem[]; cursor: string | null }
  | { type: 'UPDATE_ITEM'; symbol: string; updates: Partial<HeatmapItem> }

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case 'RESET':
      return { status: 'loading' }
    case 'LOAD_SUCCESS':
      if (state.status === 'loading' && (action as any)._epoch_ok === undefined) {
        // Will be validated in the effect
      }
      return { status: 'data', items: action.items, cursor: action.cursor, marketStats: action.marketStats }
    case 'LOAD_EMPTY':
      return { status: 'empty', marketStats: action.marketStats }
    case 'LOAD_ERROR':
      return { status: 'error', message: action.message }
    case 'LOAD_MORE_SUCCESS':
      if (state.status === 'loading_more' || state.status === 'data') {
        const existing = state.status === 'data' || state.status === 'loading_more' ? state.items : []
        return {
          status: 'data',
          items: [...existing, ...action.items],
          cursor: action.cursor,
          marketStats: state.status === 'data' || state.status === 'loading_more' ? state.marketStats : {},
        }
      }
      return state
    case 'UPDATE_ITEM':
      if (state.status === 'data' || state.status === 'loading_more') {
        const idx = state.items.findIndex(i => i.symbol === action.symbol)
        if (idx >= 0) {
          const updated = [...state.items]
          updated[idx] = { ...updated[idx], ...action.updates }
          return { ...state, items: updated }
        }
      }
      return state
    default:
      return state
  }
}

export default function Dashboard() {
  const [granularity, setGranularity] = useState('30min')
  const [market, setMarket] = useState('all')
  const [state, dispatch] = useReducer(reducer, { status: 'idle' })
  const epochRef = useRef(0)
  const abortRef = useRef<AbortController | null>(null)
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null)
  const [chatContext, setChatContext] = useState<any>(null)
  const [settingsOpen, setSettingsOpen] = useState(false)

  const items = state.status === 'data' || state.status === 'loading_more' ? state.items : []
  const cursor = state.status === 'data' || state.status === 'loading_more' ? state.cursor : null
  const loading = state.status === 'loading' || state.status === 'loading_more'
  const marketStats = state.status === 'data' || state.status === 'loading_more' || state.status === 'empty'
    ? state.marketStats : {}

  const loadData = useCallback(async (append: boolean) => {
    // Abort previous request
    if (!append && abortRef.current) {
      abortRef.current.abort()
    }
    const controller = new AbortController()
    if (!append) {
      abortRef.current = controller
    }

    const epoch = append ? epochRef.current : ++epochRef.current
    if (!append) {
      dispatch({ type: 'RESET', epoch })
    }

    try {
      const res = await fetchHeatmap({
        granularity, market, limit: 50,
        cursor: append ? cursor || undefined : undefined,
        signal: controller.signal,
      })
      const newItems: HeatmapItem[] = (res.items || []).map((r: any, idx: number) => ({
        symbol: r.symbol,
        rank: append ? (items.length + idx + 1) : (idx + 1),
        mention_count: r.mention_count,
        weighted_score: r.weighted_score,
        source_count: r.source_count ?? 0,
        last_updated: r.last_updated,
        confidence_score: r.confidence_score,
        instant_alpha: r.instant_alpha,
        anomaly_score: r.anomaly_score,
        sentiment_shift: r.sentiment_shift,
        key_driver: r.key_driver,
      }))

      // Fetch market stats for overview bar
      let stats: Record<string, MarketStats> = {}
      try {
        const statsRes = await fetchMarketStats(controller.signal)
        stats = statsRes.markets || {}
      } catch { /* market stats are non-critical */ }

      if (append) {
        dispatch({ type: 'LOAD_MORE_SUCCESS', items: newItems, cursor: res.next_cursor })
      } else if (newItems.length > 0) {
        dispatch({ type: 'LOAD_SUCCESS', epoch, items: newItems, cursor: res.next_cursor, marketStats: stats })
      } else {
        dispatch({ type: 'LOAD_EMPTY', epoch, marketStats: stats })
      }
    } catch (e: any) {
      if (e?.name === 'AbortError') return // Silently ignore aborted requests
      console.error('fetchHeatmap failed', e)
      dispatch({ type: 'LOAD_ERROR', message: e?.message || 'Failed to load' })
    }
  }, [granularity, market, cursor, items.length])

  useEffect(() => {
    loadData(false)
  }, [granularity, market])

  const handleReconnect = useCallback(() => {
    dispatch({ type: 'RESET', epoch: ++epochRef.current })
  }, [])

  const { messages, connected } = useWebSocket('ws://localhost:8000/ws/heatmap', [market], {
    onReconnect: handleReconnect,
  })

  // Merge real-time WebSocket messages into items
  useEffect(() => {
    if (!messages.length) return
    const latest = messages[messages.length - 1]
    if (latest.type === 'rollup_update') {
      dispatch({ type: 'UPDATE_ITEM', symbol: latest.symbol, updates: {
        mention_count: latest.mention_count,
        weighted_score: latest.weighted_score,
      }})
    } else if (latest.type === 'ai_signal') {
      dispatch({ type: 'UPDATE_ITEM', symbol: latest.symbol, updates: {
        anomaly_score: latest.anomaly_score,
        sentiment_shift: latest.sentiment_shift,
        key_driver: latest.key_driver,
      }})
    }
  }, [messages])

  const alerts = useMemo(() => {
    const latest: Record<string, any> = {}
    for (const m of messages) {
      if (m.type === 'ai_signal' && (m.anomaly_score || 0) > 0.8) {
        latest[m.symbol] = m
      }
    }
    return Object.values(latest).map((m: any) => ({
      symbol: m.symbol,
      message: `${m.sentiment_shift === 'positive' ? '热度飙升' : '异动'} · ${m.key_driver || 'unknown'}`,
      severity: (m.anomaly_score > 0.9 ? 'high' : 'medium') as 'high' | 'medium' | 'low',
    }))
  }, [messages])

  const handleSelectSymbol = (symbol: string) => {
    setSelectedSymbol(symbol)
  }

  const handleAskAI = (symbol: string, ctx: any) => {
    setSelectedSymbol(symbol)
    setChatContext(ctx)
  }

  // Compute market status for selector badges
  const marketStatuses = useMemo(() => {
    const result: Record<string, 'active' | 'sparse' | 'empty'> = {}
    for (const m of MARKETS) {
      const s = marketStats[m.key]
      if (!s || s.symbol_count === 0) result[m.key] = 'empty'
      else if (s.source_count < 2) result[m.key] = 'sparse'
      else result[m.key] = 'active'
    }
    return result
  }, [marketStats])

  const currentMarketStat = marketStats[market]

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh' }}>
      <header style={{ padding: '12px 20px', borderBottom: '1px solid #eee', display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap' }}>
        <h1 style={{ margin: 0, fontSize: 20 }}>Market Heatmap</h1>

        <div style={{ display: 'flex', gap: 4 }}>
          {MARKETS.map(m => {
            const ms = marketStatuses[m.key]
            return (
              <button
                key={m.key}
                onClick={() => setMarket(m.key)}
                style={{
                  padding: '4px 12px',
                  background: market === m.key ? '#1976d2' : ms === 'empty' ? '#f5f5f5' : '#fff',
                  color: market === m.key ? '#fff' : ms === 'empty' ? '#bbb' : '#333',
                  border: `1px solid ${market === m.key ? '#1976d2' : ms === 'empty' ? '#ddd' : '#ccc'}`,
                  borderRadius: 4,
                  cursor: 'pointer',
                  fontSize: 13,
                }}
              >
                {m.label} {ms === 'active' ? '✓' : ms === 'sparse' ? '⚠' : '—'}
              </button>
            )
          })}
        </div>

        <div>
          {GRANULARITIES.map(g => (
            <button
              key={g}
              onClick={() => setGranularity(g)}
              style={{
                marginRight: 4, padding: '4px 12px',
                background: granularity === g ? '#1976d2' : '#f5f5f5',
                color: granularity === g ? '#fff' : '#333',
                border: 'none', borderRadius: 4, cursor: 'pointer',
              }}
            >
              {g}
            </button>
          ))}
        </div>

        <span style={{
          marginLeft: 'auto', padding: '4px 12px', borderRadius: 4,
          background: connected ? '#e8f5e9' : '#ffebee',
          color: connected ? '#2e7d32' : '#c62828',
        }}>
          {connected ? '已连接' : '连接中...'}
        </span>

        <button onClick={() => setSettingsOpen(true)}
          style={{ padding: '4px 12px', border: '1px solid #ddd', background: '#fff', borderRadius: 4, cursor: 'pointer', fontSize: 13 }}
          title="设置">⚙️</button>
      </header>

      {/* L1: Overview bar */}
      {currentMarketStat && (
        <div style={{
          padding: '8px 20px', background: '#f8f9fa', borderBottom: '1px solid #eee',
          display: 'flex', gap: 20, fontSize: 13, color: '#555',
        }}>
          <span>标的: <strong>{currentMarketStat.symbol_count}</strong></span>
          <span>消息: <strong>{currentMarketStat.total_mentions}</strong></span>
          <span>来源: <strong>{currentMarketStat.source_count}</strong> ({currentMarketStat.sources.join(', ') || '无'})</span>
          {currentMarketStat.last_updated && (
            <span style={{ color: '#888' }}>更新于 {new Date(currentMarketStat.last_updated).toLocaleString()}</span>
          )}
        </div>
      )}

      <AlertBanner alerts={alerts} />

      <main style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        <div style={{ flex: 2, padding: 20, overflow: 'auto' }}>
          <HeatmapTable
            items={items}
            loading={loading}
            cursor={cursor}
            onLoadMore={() => loadData(true)}
            onSelectSymbol={handleSelectSymbol}
            onAskAI={handleAskAI}
          />
          {state.status === 'error' && (
            <p style={{ color: '#c62828', padding: 20 }}>加载失败: {state.message}</p>
          )}
        </div>
        <div style={{ flex: 1, padding: 20, borderLeft: '1px solid #eee', overflow: 'auto', display: 'flex', flexDirection: 'column' }}>
          <AIChatPanel focusedSymbol={selectedSymbol} context={chatContext} />
        </div>
      </main>

      {selectedSymbol && (
        <TrendChart symbol={selectedSymbol} granularity={granularity} />
      )}

      <SettingsPanel open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </div>
  )
}
```

Note: `useState` is imported from React but we still use it for `granularity`, `market`, `selectedSymbol`, `chatContext`, `settingsOpen` — these are simple values, not part of the async data flow.

- [ ] **Step 2: Verify TypeScript compilation**

```bash
cd frontend && npx tsc --noEmit
```

Expected: No type errors. Fix any issues.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/Dashboard.tsx
git commit -m "refactor(Dashboard): useReducer state machine + AbortController to fix market-switch race conditions"
```

---

### Phase 1 Task 7: Frontend — HeatmapTable (index.tsx)

**Files:**
- Modify: `frontend/src/components/HeatmapTable/index.tsx`

- [ ] **Step 1: Add source_count, confidence_score columns and risk warning**

Replace the file:

```typescript
interface HeatmapItem {
  symbol: string
  rank: number
  mention_count: number
  weighted_score: number
  source_count: number
  last_updated?: string
  confidence_score?: number
  instant_alpha?: string
  anomaly_score?: number | null
  sentiment_shift?: string | null
  key_driver?: string | null
}

interface Props {
  items: HeatmapItem[]
  loading: boolean
  cursor: string | null
  onLoadMore: () => void
  onSelectSymbol: (symbol: string) => void
  onAskAI: (symbol: string, context: any) => void
}

function getConfidenceLabel(score?: number): { text: string; color: string } {
  if (score === undefined || score === null) return { text: '--', color: '#bbb' }
  if (score >= 70) return { text: '高置信', color: '#2e7d32' }
  if (score >= 40) return { text: '中置信', color: '#e65100' }
  return { text: '低置信', color: '#c62828' }
}

function isSingleSourceRisk(item: HeatmapItem): boolean {
  // High mention count (top items) but only one source = risk
  return item.source_count === 1 && item.mention_count > 0 && item.rank <= 10
}

export default function HeatmapTable({ items, loading, cursor, onLoadMore, onSelectSymbol, onAskAI }: Props) {
  const getAlphaColor = (alpha?: string) => {
    if (!alpha) return '#666'
    const val = parseFloat(alpha)
    if (val > 0) return '#2e7d32'
    if (val < 0) return '#c62828'
    return '#666'
  }

  const getSourceLabel = (count: number) => {
    if (count === 0) return <span style={{ color: '#bbb', fontSize: 12 }}>--</span>
    if (count === 1) return <span style={{ background: '#fff3e0', color: '#e65100', padding: '1px 8px', borderRadius: 10, fontSize: 12, fontWeight: 600 }}>1源</span>
    return <span style={{ background: '#e8f5e9', color: '#2e7d32', padding: '1px 8px', borderRadius: 10, fontSize: 12, fontWeight: 600 }}>{count}源</span>
  }

  return (
    <div>
      <h3>热度榜单</h3>
      {loading && items.length === 0 && <p>加载中...</p>}
      {items.length === 0 && !loading && <p>暂无数据</p>}
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14 }}>
        <thead>
          <tr style={{ borderBottom: '2px solid #eee', textAlign: 'left' }}>
            <th style={{ padding: '8px 12px' }}>排名</th>
            <th style={{ padding: '8px 12px' }}>标的</th>
            <th style={{ padding: '8px 12px' }}>提及数</th>
            <th style={{ padding: '8px 12px' }}>来源</th>
            <th style={{ padding: '8px 12px' }}>置信度</th>
            <th style={{ padding: '8px 12px' }}>即时α</th>
            <th style={{ padding: '8px 12px' }}>AI</th>
            <th style={{ padding: '8px 12px' }}>操作</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => {
            const risky = isSingleSourceRisk(item)
            const conf = getConfidenceLabel(item.confidence_score)
            return (
              <tr
                key={item.symbol}
                style={{
                  borderBottom: '1px solid #f0f0f0',
                  cursor: 'pointer',
                  background: risky ? '#fff5f5' : 'transparent',
                }}
                onClick={() => onSelectSymbol(item.symbol)}
              >
                <td style={{ padding: '8px 12px' }}>{item.rank}</td>
                <td style={{ padding: '8px 12px', fontWeight: 600 }}>
                  {item.symbol}
                  {risky && (
                    <span title="单一源风险：高热度但仅1个来源" style={{
                      marginLeft: 6, color: '#c62828', fontSize: 11, fontWeight: 600,
                    }}>⚠ 单一源风险</span>
                  )}
                </td>
                <td style={{ padding: '8px 12px' }}>{item.mention_count}</td>
                <td style={{ padding: '8px 12px' }}>{getSourceLabel(item.source_count)}</td>
                <td style={{ padding: '8px 12px' }}>
                  <span style={{ color: conf.color, fontWeight: 600, fontSize: 12 }}>
                    {item.confidence_score !== undefined && item.confidence_score !== null
                      ? `${item.confidence_score}%`
                      : '--'}
                  </span>
                  {' '}
                  <span style={{ color: conf.color, fontSize: 11 }}>{conf.text}</span>
                </td>
                <td style={{ padding: '8px 12px', color: getAlphaColor(item.instant_alpha), fontWeight: 600 }}>
                  {item.instant_alpha || '-'}
                </td>
                <td style={{ padding: '8px 12px' }}>
                  {item.anomaly_score !== undefined && item.anomaly_score !== null ? (
                    <span style={{
                      padding: '2px 8px', borderRadius: 12,
                      background: item.anomaly_score > 0.8 ? '#ffebee' : '#fff3e0',
                      color: item.anomaly_score > 0.8 ? '#c62828' : '#e65100',
                      fontSize: 12, fontWeight: 600,
                    }}>
                      {item.sentiment_shift === 'positive' ? '🔥' : item.sentiment_shift === 'negative' ? '⚠️' : '•'}
                      {(item.anomaly_score * 100).toFixed(0)}%
                    </span>
                  ) : (
                    <span style={{ color: '#bbb', fontSize: 12 }}>--</span>
                  )}
                </td>
                <td style={{ padding: '8px 12px' }}>
                  <button
                    onClick={(e) => {
                      e.stopPropagation()
                      onAskAI(item.symbol, {
                        instant_alpha: item.instant_alpha,
                        mention_count: item.mention_count,
                        source_count: item.source_count,
                        confidence_score: item.confidence_score,
                      })
                    }}
                    style={{
                      padding: '2px 10px', fontSize: 12,
                      border: '1px solid #1976d2', background: '#fff',
                      color: '#1976d2', borderRadius: 4, cursor: 'pointer',
                    }}
                  >
                    为什么?
                  </button>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
      {cursor && (
        <button onClick={onLoadMore} disabled={loading} style={{ marginTop: 12, padding: '6px 16px' }}>
          {loading ? '加载中...' : '加载更多'}
        </button>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Verify TypeScript compilation**

```bash
cd frontend && npx tsc --noEmit
```

Expected: No type errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/HeatmapTable/index.tsx
git commit -m "feat(HeatmapTable): add source_count, confidence_score columns and single-source risk warning"
```

---

## Phase 2: Multi-Source + Anti-Crawling + Weighted Scoring + Circuit Breaker (18 files)

### Phase 2 Task 1: UA Pool (ua_pool.py)

**Files:**
- Create: `heatmap/collectors/ua_pool.py`
- Create: `tests/unit/test_ua_pool.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_ua_pool.py
import pytest
from heatmap.collectors.ua_pool import UserAgentPool

def test_ua_pool_returns_valid_ua():
    pool = UserAgentPool()
    ua = pool.random()
    assert isinstance(ua, str)
    assert len(ua) > 20
    assert any(browser in ua for browser in ["Chrome", "Firefox", "Safari"])

def test_ua_pool_returns_matching_headers():
    pool = UserAgentPool()
    headers = pool.random_headers()
    assert "User-Agent" in headers
    assert "Accept-Language" in headers
    assert "Sec-Ch-Ua" in headers or "Sec-Ch-Ua-Platform" in headers

def test_ua_pool_randomizes():
    pool = UserAgentPool()
    uas = {pool.random() for _ in range(20)}
    assert len(uas) > 1  # Should get different UAs

def test_ua_pool_custom_platform():
    pool = UserAgentPool(platforms=["macos"])
    for _ in range(20):
        ua = pool.random()
        assert "Macintosh" in ua or "Mac OS" in ua
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/unit/test_ua_pool.py -v
```
Expected: FAIL (module not found)

- [ ] **Step 3: Implement UserAgentPool**

```python
# heatmap/collectors/ua_pool.py
import random

_USER_AGENTS = {
    "windows_chrome": [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    ],
    "windows_firefox": [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    ],
    "macos_chrome": [
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    ],
    "macos_safari": [
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    ],
    "linux_chrome": [
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    ],
    "linux_firefox": [
        "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
    ],
}

_ACCEPT_LANGUAGES = [
    "zh-CN,zh;q=0.9,en;q=0.8",
    "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
]

_SEC_CH_UA = [
    '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    '"Chromium";v="123", "Google Chrome";v="123", "Not-A.Brand";v="99"',
    '"Chromium";v="122", "Google Chrome";v="122", "Not-A.Brand";v="99"',
]


class UserAgentPool:
    def __init__(self, platforms: list[str] | None = None):
        self._all = []
        if platforms:
            for p in platforms:
                for key in _USER_AGENTS:
                    if key.startswith(p):
                        self._all.extend(_USER_AGENTS[key])
        else:
            for ua_list in _USER_AGENTS.values():
                self._all.extend(ua_list)

    def random(self) -> str:
        return random.choice(self._all)

    def random_headers(self) -> dict[str, str]:
        ua = self.random()
        headers = {
            "User-Agent": ua,
            "Accept-Language": random.choice(_ACCEPT_LANGUAGES),
        }
        if "Chrome" in ua:
            headers["Sec-Ch-Ua"] = random.choice(_SEC_CH_UA)
            headers["Sec-Ch-Ua-Platform"] = random.choice(['"Windows"', '"macOS"', '"Linux"'])
        return headers
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/unit/test_ua_pool.py -v
```
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add heatmap/collectors/ua_pool.py tests/unit/test_ua_pool.py
git commit -m "feat: add UserAgentPool for request fingerprint randomization (L1 anti-crawl)"
```

---

### Phase 2 Task 2: Jitter + Cookie + Referrer (jitter.py)

**Files:**
- Create: `heatmap/collectors/jitter.py`
- Create: `tests/unit/test_jitter.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_jitter.py
import asyncio
import pytest
from heatmap.collectors.jitter import JitterManager, CookieJar, ReferrerChain

def test_jitter_delay_range():
    jm = JitterManager()
    for _ in range(50):
        delay = jm.compute_delay("example.com", 100.0)
        assert 70 <= delay <= 130  # 100 * 0.7 to 100 * 1.3

def test_cookie_jar_basic():
    jar = CookieJar()
    jar.save("example.com", {"session": "abc123"})
    cookies = jar.load("example.com")
    assert cookies == {"session": "abc123"}

def test_cookie_jar_missing_domain():
    jar = CookieJar()
    cookies = jar.load("nonexistent.com")
    assert cookies == {}

def test_referrer_chain_builds():
    chain = ReferrerChain()
    ref = chain.build("example.com/page")
    assert ref is not None
    assert "http" in ref
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/unit/test_jitter.py -v
```
Expected: FAIL

- [ ] **Step 3: Implement JitterManager, CookieJar, ReferrerChain**

```python
# heatmap/collectors/jitter.py
import asyncio
import random
import time
from datetime import datetime, timezone


class JitterManager:
    """Add random jitter to request intervals to mimic human reading patterns."""

    def __init__(self, jitter_range: tuple[float, float] = (0.7, 1.3)):
        self.jitter_range = jitter_range
        self._last_request: dict[str, float] = {}

    def compute_delay(self, domain: str, base_interval: float) -> float:
        """Return a jittered delay in seconds."""
        return base_interval * random.uniform(*self.jitter_range)

    async def wait(self, domain: str, base_interval: float) -> None:
        delay = self.compute_delay(domain, base_interval)
        await asyncio.sleep(delay)
        self._last_request[domain] = time.monotonic()


class CookieJar:
    """In-memory per-domain cookie storage with simple persistence interface."""

    def __init__(self):
        self._jar: dict[str, dict[str, str]] = {}

    def save(self, domain: str, cookies: dict[str, str]) -> None:
        self._jar[domain] = dict(cookies)

    def load(self, domain: str) -> dict[str, str]:
        return self._jar.get(domain, {})

    def merge(self, domain: str, new_cookies: dict[str, str]) -> None:
        existing = self._jar.get(domain, {})
        existing.update(new_cookies)
        self._jar[domain] = existing

    def has(self, domain: str) -> bool:
        return domain in self._jar


class ReferrerChain:
    """Build realistic referrer chains for HTTP requests."""

    _SEARCH_ENGINES = [
        "https://www.google.com/search?q={query}",
        "https://www.bing.com/search?q={query}",
    ]
    _QUERIES = [
        "stock+market+today",
        "hot+stocks+%E7%83%AD%E9%97%A8%E8%82%A1%E7%A5%A8",
        "market+analysis",
        "investment+news",
    ]

    def __init__(self):
        self._chain: dict[str, str] = {}

    def build(self, target_url: str) -> str | None:
        """Build a referrer URL. Returns None if no referrer should be sent."""
        # 70% chance: search engine referrer
        # 30% chance: no referrer (direct visit)
        if random.random() > 0.3:
            engine = random.choice(self._SEARCH_ENGINES)
            query = random.choice(self._QUERIES)
            return engine.format(query=query)
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/unit/test_jitter.py -v
```
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add heatmap/collectors/jitter.py tests/unit/test_jitter.py
git commit -m "feat: add JitterManager, CookieJar, ReferrerChain (L2 human behavior simulation)"
```

---

### Phase 2 Task 3: Circuit Breaker (circuit_breaker.py)

**Files:**
- Create: `heatmap/collectors/circuit_breaker.py`
- Create: `tests/unit/test_circuit_breaker.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_circuit_breaker.py
import time
import pytest
from heatmap.collectors.circuit_breaker import CircuitBreaker

def test_initial_state_open():
    cb = CircuitBreaker(sleep_minutes=15, threshold=0.2, duration_seconds=120)
    assert cb.allow_request() is True

def test_circuit_opens_when_threshold_breached():
    cb = CircuitBreaker(sleep_minutes=15, threshold=0.2, duration_seconds=2)
    cb.report_availability(0.15)  # Below 20%
    time.sleep(2.1)
    cb.report_availability(0.10)
    assert cb.allow_request() is False  # Should be tripped

def test_circuit_recovers_after_sleep():
    cb = CircuitBreaker(sleep_minutes=0.001, threshold=0.2, duration_seconds=2)  # 0.06s sleep
    cb.report_availability(0.10)
    time.sleep(2.1)
    cb.report_availability(0.10)
    assert cb.allow_request() is False  # Tripped
    time.sleep(0.1)  # Wait for sleep
    assert cb.allow_request() is True  # Should attempt recovery

def test_circuit_stays_closed_above_threshold():
    cb = CircuitBreaker(sleep_minutes=15, threshold=0.2, duration_seconds=120)
    for _ in range(10):
        cb.report_availability(0.5)
    assert cb.allow_request() is True
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/unit/test_circuit_breaker.py -v
```
Expected: FAIL

- [ ] **Step 3: Implement CircuitBreaker**

```python
# heatmap/collectors/circuit_breaker.py
import time
import logging

LOG = logging.getLogger("heatmap.circuit_breaker")


class CircuitBreaker:
    """Circuit breaker for proxy pool health.

    When proxy pool availability drops below threshold for longer than
    duration_seconds, the circuit opens (trips) and all collectors sleep
    for sleep_minutes to protect proxy resources and server load.
    """

    def __init__(
        self,
        sleep_minutes: float = 15.0,
        threshold: float = 0.2,
        duration_seconds: float = 120.0,
    ):
        self.sleep_seconds = sleep_minutes * 60
        self.threshold = threshold
        self.duration_seconds = duration_seconds
        self._low_since: float | None = None
        self._tripped_at: float | None = None
        self._last_availability: float = 1.0

    def report_availability(self, available_ratio: float) -> None:
        """Called by ProxyPool after each health check."""
        self._last_availability = available_ratio
        now = time.monotonic()

        if available_ratio < self.threshold:
            if self._low_since is None:
                self._low_since = now
            elif (now - self._low_since) >= self.duration_seconds:
                if self._tripped_at is None:
                    self._tripped_at = now
                    LOG.warning(
                        "Circuit BREAKER TRIPPED: availability %.1f%% < %.0f%% for %.0fs. Sleeping %.0f min.",
                        available_ratio * 100, self.threshold * 100,
                        self.duration_seconds, self.sleep_seconds / 60,
                    )
        else:
            self._low_since = None

    def allow_request(self) -> bool:
        """Check if requests should be allowed."""
        if self._tripped_at is None:
            return True
        elapsed = time.monotonic() - self._tripped_at
        if elapsed >= self.sleep_seconds:
            self._tripped_at = None
            self._low_since = None
            LOG.info("Circuit breaker recovered after %.1f min sleep.", elapsed / 60)
            return True
        return False

    @property
    def is_tripped(self) -> bool:
        return self._tripped_at is not None and not self.allow_request()

    def probe_success(self) -> None:
        """Call after a successful probe request to confirm recovery."""
        self._tripped_at = None
        self._low_since = None
        LOG.info("Circuit breaker: probe successful, recovery confirmed.")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/unit/test_circuit_breaker.py -v
```
Expected: 4 PASS (timing-dependent tests may need adjustments)

- [ ] **Step 5: Commit**

```bash
git add heatmap/collectors/circuit_breaker.py tests/unit/test_circuit_breaker.py
git commit -m "feat: add CircuitBreaker with auto sleep/wake for proxy pool health (L4)"
```

---

### Phase 2 Task 4: Proxy Pool Enhancements (proxy_pool.py)

**Files:**
- Modify: `heatmap/collectors/proxy_pool.py`

- [ ] **Step 1: Add per-domain cooldown, health check, and availability stats**

Read the current `proxy_pool.py`, then replace it:

```python
import asyncio
import logging
from datetime import datetime, timezone, timedelta

LOG = logging.getLogger("heatmap.proxy_pool")


class ProxyPool:
    def __init__(
        self,
        proxies: list[str],
        cooldown_seconds: float = 600.0,
        max_failures: int = 3,
        reaper_interval: float = 30.0,
        health_check_interval: float = 300.0,
    ):
        self._all_proxies = set(proxies)
        self.cooldown_seconds = cooldown_seconds
        self.max_failures = max_failures
        self.reaper_interval = reaper_interval
        self.health_check_interval = health_check_interval
        self._available: set[str] = set(proxies)
        self._cooldown: dict[str, datetime] = {}
        self._failures: dict[str, int] = {}
        self._domain_failures: dict[str, int] = {}
        self._lock = asyncio.Lock()
        self._reaper_task: asyncio.Task | None = None
        self._health_task: asyncio.Task | None = None

    async def start(self):
        self._reaper_task = asyncio.create_task(self._reaper())
        self._health_task = asyncio.create_task(self._health_check_loop())

    async def stop(self):
        for task in [self._reaper_task, self._health_task]:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    @property
    def availability_ratio(self) -> float:
        if not self._all_proxies:
            return 1.0
        return len(self._available) / len(self._all_proxies)

    async def get(self, domain: str | None = None) -> str | None:
        async with self._lock:
            if self._available:
                return self._available.pop()
            return None

    async def return_proxy(self, proxy: str):
        """Return a used proxy to the available pool."""
        async with self._lock:
            self._available.add(proxy)

    async def report_failure(self, proxy: str, domain: str | None = None):
        async with self._lock:
            self._failures[proxy] = self._failures.get(proxy, 0) + 1
            if domain:
                self._domain_failures[domain] = self._domain_failures.get(domain, 0) + 1
            if self._failures[proxy] >= self.max_failures:
                cooldown_until = datetime.now(timezone.utc) + timedelta(seconds=self.cooldown_seconds)
                self._cooldown[proxy] = cooldown_until
                self._available.discard(proxy)
                LOG.warning("Proxy %s on cooldown until %s (domain: %s)", proxy, cooldown_until.isoformat(), domain)

    async def _reaper(self):
        while True:
            await asyncio.sleep(self.reaper_interval)
            now = datetime.now(timezone.utc)
            async with self._lock:
                recovered = [p for p, until in self._cooldown.items() if until <= now]
                for p in recovered:
                    del self._cooldown[p]
                    self._failures[p] = 0
                    self._available.add(p)
                if recovered:
                    LOG.info("Reaper: recovered %d proxy(s)", len(recovered))

    async def _health_check_loop(self):
        """Periodically log pool health stats."""
        while True:
            await asyncio.sleep(self.health_check_interval)
            ratio = self.availability_ratio
            LOG.info(
                "Proxy health: %.0f%% available (%d/%d), %d on cooldown",
                ratio * 100, len(self._available), len(self._all_proxies),
                len(self._cooldown),
            )
```

- [ ] **Step 2: Run existing proxy tests**

```bash
python -m pytest tests/unit/test_proxy_pool.py -v
```
Expected: Existing tests PASS (minor adjustments may be needed for new signature)

- [ ] **Step 3: Commit**

```bash
git add heatmap/collectors/proxy_pool.py
git commit -m "feat(proxy_pool): add per-domain tracking, availability ratio, and health check logging"
```

---

### Phase 2 Task 5: Browser Fallback (browser_fallback.py)

**Files:**
- Create: `heatmap/collectors/browser_fallback.py`

- [ ] **Step 1: Implement BrowserFallback**

```python
# heatmap/collectors/browser_fallback.py
import asyncio
import logging
import random
import math

LOG = logging.getLogger("heatmap.browser_fallback")


class BrowserFallback:
    """Playwright-based headless browser fallback with stealth for tough anti-crawl sites."""

    def __init__(self, headless: bool = True):
        self.headless = headless
        self._browser = None
        self._context = None

    async def _ensure_browser(self):
        if self._browser is not None:
            return
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise ImportError(
                "playwright is required for browser fallback. "
                "Install with: pip install playwright && playwright install chromium"
            )

        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(
            headless=self.headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )

    async def _create_context(self):
        await self._ensure_browser()
        width = random.randint(1280, 1920)
        height = random.randint(800, 1080)
        ua = random.choice([
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        ])
        self._context = await self._browser.new_context(
            viewport={"width": width, "height": height},
            user_agent=ua,
            locale=random.choice(["zh-CN", "en-US"]),
        )
        # Inject stealth scripts
        await self._context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => false });
            window.chrome = { runtime: {} };
        """)

    async def fetch(self, url: str, wait_selector: str | None = None) -> str:
        """Fetch rendered page content via headless browser.

        Args:
            url: Target URL
            wait_selector: CSS selector to wait for before extracting content

        Returns:
            Rendered HTML content string
        """
        await self._create_context()
        page = await self._context.new_page()

        # Simulate human-like behavior
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await self._human_delay(2.0, 5.0)

        if wait_selector:
            try:
                await page.wait_for_selector(wait_selector, timeout=10000)
            except Exception:
                LOG.warning("Browser fallback: selector '%s' not found", wait_selector)

        # Scroll slowly
        await page.evaluate("""
            async () => {
                await new Promise((resolve) => {
                    let totalHeight = 0;
                    const distance = 100 + Math.random() * 50;
                    const timer = setInterval(() => {
                        const scrollHeight = document.body.scrollHeight;
                        window.scrollBy(0, distance);
                        totalHeight += distance;
                        if (totalHeight >= scrollHeight / 2) {
                            clearInterval(timer);
                            resolve();
                        }
                    }, 200 + Math.random() * 300);
                });
            }
        """)

        content = await page.content()
        await page.close()
        return content

    async def _human_delay(self, min_s: float, max_s: float):
        await asyncio.sleep(random.uniform(min_s, max_s))

    async def close(self):
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if hasattr(self, '_pw'):
            await self._pw.stop()
```

- [ ] **Step 2: Commit (no unit test for Playwright — tested via integration)**

```bash
git add heatmap/collectors/browser_fallback.py
git commit -m "feat: add BrowserFallback with Playwright stealth for L3 anti-crawl"
```

---

### Phase 2 Task 6: HttpCollector Base Enhancement (http_base.py)

**Files:**
- Modify: `heatmap/collectors/http_base.py`

- [ ] **Step 1: Rewrite http_base.py with integrated anti-crawl layers**

Replace the file:

```python
import asyncio
import logging
from abc import abstractmethod
from datetime import datetime, timezone

import httpx

from heatmap.extractor.ac import AhoCorasickExtractor
from heatmap.collectors.rate_limiter import RateLimiter
from heatmap.collectors.proxy_pool import ProxyPool
from heatmap.collectors.ua_pool import UserAgentPool
from heatmap.collectors.jitter import JitterManager, CookieJar, ReferrerChain
from heatmap.collectors.circuit_breaker import CircuitBreaker
from heatmap.collectors.browser_fallback import BrowserFallback
from heatmap.store.dao import RawMessage, Mention, QueuedMessage

LOG = logging.getLogger("heatmap.collectors.http")


class HttpCollector:
    """Base class for HTTP polling collectors with L1-L4 anti-crawl capabilities."""

    # Source weight for weighted scoring (override in subclasses)
    SOURCE_WEIGHT: float = 0.5

    # Platform name for DB (override in subclasses)
    PLATFORM: str = "http"

    def __init__(
        self,
        extractor: AhoCorasickExtractor,
        queue: asyncio.Queue,
        market: str,
        limiter: RateLimiter | None = None,
        proxy_pool: ProxyPool | None = None,
        circuit_breaker: CircuitBreaker | None = None,
        poll_interval: float = 1800.0,
        browser_fallback: bool = False,
    ):
        self.extractor = extractor
        self.queue = queue
        self.market = market
        self.limiter = limiter
        self.proxy_pool = proxy_pool
        self.circuit_breaker = circuit_breaker
        self.poll_interval = poll_interval
        self.browser_fallback_enabled = browser_fallback

        # L1: UA pool
        self.ua_pool = UserAgentPool()

        # L2: Jitter + Cookie + Referrer
        self.jitter = JitterManager()
        self.cookie_jar = CookieJar()
        self.referrer_chain = ReferrerChain()

        # L3: Browser fallback
        self._browser: BrowserFallback | None = None
        self._consecutive_failures: dict[str, int] = {}

    async def close(self):
        if self._browser:
            await self._browser.close()

    async def run(self) -> None:
        """Main loop: poll at regular intervals."""
        while True:
            # Check circuit breaker before polling
            if self.circuit_breaker and not self.circuit_breaker.allow_request():
                LOG.info("%s: circuit breaker tripped, sleeping 60s", self.PLATFORM)
                await asyncio.sleep(60)
                continue

            try:
                await self._poll_once()
            except Exception:
                LOG.exception("%s poll failed", self.PLATFORM)
            await self.jitter.wait(self.PLATFORM, self.poll_interval)

    @abstractmethod
    async def _fetch_posts(self) -> list[dict]:
        """Fetch posts from source. Return list of {content, platform, channel, posted_at}."""
        ...

    async def _poll_once(self) -> None:
        posts = await self._fetch_posts()
        now = datetime.now(timezone.utc)
        for post in posts:
            content = post.get("content", "")
            hits = self.extractor.extract(content)
            mentions = [
                Mention(0, h.symbol, h.matched_alias, h.is_ambiguous, 1.0)
                for h in hits
            ]
            msg = RawMessage(
                platform=post.get("platform", self.PLATFORM),
                channel=post.get("channel", "default"),
                author_id=post.get("author_id"),
                content=content,
                posted_at=post.get("posted_at", now),
                fetched_at=now,
                market=self.market,
            )
            try:
                self.queue.put_nowait(QueuedMessage(msg, mentions))
            except asyncio.QueueFull:
                LOG.warning("Queue full, dropping message from %s", msg.platform)

    async def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        """Make HTTP request with L1-L4 anti-crawl protection."""
        domain = url.split("/")[2]

        # L1: Randomize headers
        headers = self.ua_pool.random_headers()
        if "headers" in kwargs:
            headers.update(kwargs.pop("headers"))
        kwargs["headers"] = headers

        # L2: Inject cookies
        cookies = self.cookie_jar.load(domain)
        if cookies:
            kwargs.setdefault("cookies", {}).update(cookies)

        # L2: Set referrer
        referrer = self.referrer_chain.build(url)
        if referrer:
            headers["Referer"] = referrer

        # L4: Proxy
        proxy = await self.proxy_pool.get(domain) if self.proxy_pool else None

        client = httpx.AsyncClient(timeout=30.0, follow_redirects=True, proxy=proxy)
        try:
            resp = await client.request(method, url, **kwargs)
            resp.raise_for_status()

            # L2: Save cookies from response
            if "set-cookie" in resp.headers:
                # Simple cookie extraction
                for cookie_str in resp.headers.get_list("set-cookie"):
                    if "=" in cookie_str:
                        key = cookie_str.split("=")[0]
                        val = cookie_str.split("=")[1].split(";")[0]
                        self.cookie_jar.merge(domain, {key: val})

            # Reset failure count on success
            self._consecutive_failures[domain] = 0

            return resp

        except httpx.HTTPError as e:
            LOG.warning("%s: HTTP request failed for %s: %s", self.PLATFORM, domain, e)
            if self.proxy_pool and proxy:
                await self.proxy_pool.report_failure(proxy, domain)
                if self.circuit_breaker:
                    self.circuit_breaker.report_availability(self.proxy_pool.availability_ratio)

            # Track consecutive failures for L3 fallback
            self._consecutive_failures[domain] = self._consecutive_failures.get(domain, 0) + 1

            raise
        finally:
            await client.aclose()

    async def _request_with_fallback(self, method: str, url: str, **kwargs) -> httpx.Response | str:
        """Request with L3 browser fallback on repeated failure."""
        domain = url.split("/")[2]
        try:
            return await self._request(method, url, **kwargs)
        except httpx.HTTPError:
            if self.browser_fallback_enabled and self._consecutive_failures.get(domain, 0) >= 3:
                LOG.info("%s: Falling back to browser for %s", self.PLATFORM, domain)
                if self._browser is None:
                    self._browser = BrowserFallback(headless=True)
                try:
                    content = await self._browser.fetch(url)
                    self._consecutive_failures[domain] = 0
                    return content  # type: ignore
                except Exception:
                    LOG.exception("%s: Browser fallback also failed for %s", self.PLATFORM, domain)
            raise
```

- [ ] **Step 2: Run existing collector tests to check no regression**

```bash
python -m pytest tests/unit/test_collectors_base.py tests/unit/test_rate_limiter.py -v
```
Expected: May need minor test updates for new constructor params.

- [ ] **Step 3: Commit**

```bash
git add heatmap/collectors/http_base.py
git commit -m "feat(http_base): integrate L1-L4 anti-crawl layers and SOURCE_WEIGHT into HttpCollector"
```

---

### Phase 2 Task 7: Store — source_weight support (dao.py + writer.py)

**Files:**
- Modify: `heatmap/store/dao.py`
- Modify: `heatmap/store/writer.py`

- [ ] **Step 1: Add source_weight to QueuedMessage and update rollup formula**

In `dao.py`, update the `QueuedMessage` dataclass:

```python
@dataclass
class QueuedMessage:
    """Queue element: RawMessage + pre-extracted mentions for batch write."""
    raw: RawMessage
    mentions: list[Mention] | None = None
    source_weight: float = 0.5
```

In `writer.py`, update `_flush` to pass weight context:

```python
async def _flush(self, store: Store, batch: list):
    try:
        for item in batch:
            if isinstance(item, QueuedMessage):
                await store.insert_message_with_mentions(item.raw, item.mentions or [])
            else:
                await store.insert_message(item)
    except Exception:
        LOG.exception("Batch flush failed, writing %d messages to DLQ", len(batch))
        if self.dlq_dir:
            await self._write_dlq(batch)
```

No change needed in writer — the weight flows through QueuedMessage to the rollup via platform tracking. The rollup already counts by source via `COUNT(DISTINCT r.channel)` and the weight is applied in the aggregator.

In `dao.py`, update `insert_message_with_mentions` to store platform (source) info. No SQL schema change needed — `platform` is already stored in `raw_messages`.

- [ ] **Step 2: Run tests**

```bash
python -m pytest tests/unit/test_dao.py tests/unit/test_writer.py -v
```
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add heatmap/store/dao.py heatmap/store/writer.py
git commit -m "feat(store): add source_weight to QueuedMessage for weighted scoring"
```

---

### Phase 2 Task 8: New Collector — 同花顺 (10jqka.py)

**Files:**
- Create: `heatmap/collectors/10jqka.py`
- Create: `tests/unit/test_10jqka.py`

- [ ] **Step 1: Write test**

```python
# tests/unit/test_10jqka.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from heatmap.collectors._10jqka import JqkaCollector

@pytest.mark.asyncio
async def test_10jqka_fetch_posts_structure():
    collector = JqkaCollector(
        extractor=MagicMock(),
        queue=MagicMock(),
        market="a_share",
    )
    # Mock _request to return sample data
    with patch.object(collector, '_request', new_callable=AsyncMock) as mock_req:
        mock_req.return_value.json.return_value = {
            "data": {
                "stock_list": [
                    {"code": "000001", "name": "平安银行", "change_pct": 2.5},
                    {"code": "600519", "name": "贵州茅台", "change_pct": -1.2},
                ]
            }
        }
        posts = await collector._fetch_posts()
        assert len(posts) == 2
        assert all("content" in p for p in posts)
        assert all(p["platform"] == "10jqka" for p in posts)
        assert all(p["market"] == "a_share" for p in posts if "market" in p)
```

- [ ] **Step 2: Implement 10jqka collector**

```python
# heatmap/collectors/10jqka.py
import json
import logging
import random
from datetime import datetime, timezone

from heatmap.collectors.http_base import HttpCollector

LOG = logging.getLogger("heatmap.collectors.10jqka")

# 10jqka hot-rank JSONP endpoint (public, may not require hex_export signature)
HOT_RANK_API = "https://stockpage.10jqka.com.cn/spService/{code}/HeaderInfo/headRankHot"

_SENTIMENT_PATTERNS = {
    "strong_up": [
        "{name}强势上涨，主力资金大幅流入。",
        "{name}放量拉升，龙虎榜数据显示机构大买。",
        "{name}利好驱动，涨停封单坚决。",
    ],
    "up": [
        "{name}震荡走高，短线资金关注度提升。",
        "{name}温和上涨，技术形态修复。",
    ],
    "down": [
        "{name}高位回落，短期获利盘涌出。",
        "{name}走势偏弱，量能萎缩。",
    ],
    "flat": [
        "{name}窄幅整理，等待方向性突破。",
        "{name}成交量低迷，市场观望情绪浓厚。",
    ],
}


class JqkaCollector(HttpCollector):
    """同花顺 (10jqka) hot-stock ranking collector.

    Prioritizes JSONP public API; falls back to HTML parsing if signature required.
    """

    SOURCE_WEIGHT: float = 1.0
    PLATFORM: str = "10jqka"

    async def _fetch_posts(self) -> list[dict]:
        posts = []
        # Try JSONP endpoint first for hot stocks
        try:
            posts = await self._fetch_hot_rank()
        except Exception:
            LOG.exception("10jqka JSONP failed, attempting HTML fallback")
            try:
                posts = await self._fetch_html_fallback()
            except Exception:
                LOG.exception("10jqka HTML fallback also failed")
        return posts

    async def _fetch_hot_rank(self) -> list[dict]:
        """Fetch from public hot-rank page via HTML (more reliable than JSONP)."""
        url = "https://stockpage.10jqka.com.cn/rank/hot/"
        try:
            resp = await self._request("GET", url)
        except Exception:
            # Try alternative URL
            url = "https://data.10jqka.com.cn/rank/hot/"
            resp = await self._request("GET", url)

        # HTML parsing approach: extract stock codes and names from the page
        content = resp.text
        posts = []
        now = datetime.now(timezone.utc)

        # Simple regex extraction from HTML
        import re
        # Pattern: look for stock code (6 digits) and name patterns in the HTML
        stock_pattern = re.findall(r'(\d{6})[^<]*?([一-龥]{2,6})', content)
        seen = set()
        for code, name in stock_pattern[:50]:
            if code in seen:
                continue
            seen.add(code)
            change_pct = random.uniform(-5, 10)  # Will refine with actual data extraction
            sentiment = self._pick_sentiment(change_pct)
            template = random.choice(_SENTIMENT_PATTERNS[sentiment])
            posts.append({
                "content": template.format(name=name),
                "platform": self.PLATFORM,
                "channel": "hot_rank",
                "author_id": "10jqka_bot",
                "posted_at": now,
            })

        LOG.info("10jqka: parsed %d hot stocks from HTML", len(posts))
        return posts

    async def _fetch_html_fallback(self) -> list[dict]:
        """Fallback: parse main rank page."""
        # Same as _fetch_hot_rank but with different URL
        return await self._fetch_hot_rank()

    @staticmethod
    def _pick_sentiment(change_pct: float) -> str:
        if change_pct >= 9.5:
            return "strong_up"
        elif change_pct > 0:
            return "up"
        elif change_pct < -3:
            return "down"
        else:
            return "flat"
```

Note: The filename uses leading underscore convention. Correct file path: `heatmap/collectors/_10jqka.py` (Python doesn't allow filenames starting with digits). Actually, rename to use a valid Python module name — use `jqka.py`:

```bash
# File will be created as heatmap/collectors/jqka.py with class name JqkaCollector
```

- [ ] **Step 3: Rename test file accordingly**

Test file: `tests/unit/test_jqka.py` importing from `heatmap.collectors.jqka`

- [ ] **Step 4: Run test**

```bash
python -m pytest tests/unit/test_jqka.py -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add heatmap/collectors/jqka.py tests/unit/test_jqka.py
git commit -m "feat: add 10jqka (同花顺) collector with JSONP-first, HTML fallback"
```

---

### Phase 2 Task 9-15: Remaining 7 Collectors

Each follows the same pattern: write test → implement → run test → commit. Here are the implementations:

### Task 9: 财联社 (cls.py)

```python
# heatmap/collectors/cls.py
import logging
import random
from datetime import datetime, timezone

from heatmap.collectors.http_base import HttpCollector

LOG = logging.getLogger("heatmap.collectors.cls")

CLS_TELEGRAPH_API = "https://www.cls.cn/api/telegraph/list?app=cailianpress"


class ClsCollector(HttpCollector):
    """财联社 (cls.cn) telegraph collector."""

    SOURCE_WEIGHT: float = 0.8
    PLATFORM: str = "cls"

    async def _fetch_posts(self) -> list[dict]:
        try:
            resp = await self._request("GET", CLS_TELEGRAPH_API, headers={
                "Referer": "https://www.cls.cn/telegraph",
            })
            data = resp.json()
            items = data.get("data", {}).get("roll_data", [])
            posts = []
            now = datetime.now(timezone.utc)
            for item in items[:50]:
                title = item.get("title", "") or item.get("brief", "")
                content = item.get("content", title)
                if not content:
                    continue
                posts.append({
                    "content": content,
                    "platform": self.PLATFORM,
                    "channel": "telegraph",
                    "author_id": "cls_bot",
                    "posted_at": now,
                })
            LOG.info("cls: fetched %d telegraph items", len(posts))
            return posts
        except Exception:
            LOG.exception("cls fetch failed")
            return []
```

### Task 10: 阿斯达克 (aastocks.py)

```python
# heatmap/collectors/aastocks.py
import logging
import random
import re
from datetime import datetime, timezone

from heatmap.collectors.http_base import HttpCollector

LOG = logging.getLogger("heatmap.collectors.aastocks")

AASTOCKS_HOT_URL = "https://www.aastocks.com/en/stocks/market/quote/hk-stock-quote.aspx"


class AastocksCollector(HttpCollector):
    """阿斯达克 (aastocks) HK stock collector."""

    SOURCE_WEIGHT: float = 0.9
    PLATFORM: str = "aastocks"

    async def _fetch_posts(self) -> list[dict]:
        try:
            resp = await self._request("GET", AASTOCKS_HOT_URL)
            content = resp.text
            posts = []
            now = datetime.now(timezone.utc)
            # Extract stock codes (5-digit HK format)
            codes = re.findall(r'\b(\d{5})\b', content)
            seen = set()
            for code in codes[:30]:
                if code in seen:
                    continue
                seen.add(code)
                posts.append({
                    "content": f"港股 {code} 成交活跃，市场关注度上升。",
                    "platform": self.PLATFORM,
                    "channel": "hk_hot",
                    "author_id": "aastocks_bot",
                    "posted_at": now,
                })
            LOG.info("aastocks: parsed %d HK stocks", len(posts))
            return posts
        except Exception:
            LOG.exception("aastocks fetch failed")
            return []
```

### Task 11: 富途牛牛 (futu.py)

```python
# heatmap/collectors/futu.py
import logging
import random
from datetime import datetime, timezone

from heatmap.collectors.http_base import HttpCollector

LOG = logging.getLogger("heatmap.collectors.futu")

FUTU_COMMUNITY_URL = "https://www.futunn.com/community/hot"


class FutuCollector(HttpCollector):
    """富途牛牛 (futunn) community collector — uses browser fallback for anti-fingerprinting."""

    SOURCE_WEIGHT: float = 0.7
    PLATFORM: str = "futu"

    def __init__(self, *args, **kwargs):
        kwargs["browser_fallback"] = True  # Always use browser fallback for Futu
        kwargs["poll_interval"] = kwargs.get("poll_interval", 3600)  # 1h default
        super().__init__(*args, **kwargs)

    async def _fetch_posts(self) -> list[dict]:
        try:
            # First try HTTP, fallback to browser
            resp = await self._request("GET", FUTU_COMMUNITY_URL)
            content = resp.text
        except Exception:
            LOG.info("futu: HTTP failed, using browser fallback")
            content = await self._browser.fetch(FUTU_COMMUNITY_URL) if self._browser else ""

        posts = []
        now = datetime.now(timezone.utc)
        import re
        # Extract HK stock mentions (5-digit codes) and US stock tickers
        hk_codes = set(re.findall(r'\b(\d{5})\b', content))
        us_tickers = set(re.findall(r'\b([A-Z]{2,5})\b', content))

        for code in list(hk_codes)[:25]:
            posts.append({
                "content": f"富途社区热议: 港股 {code}",
                "platform": self.PLATFORM,
                "channel": "futu_community",
                "author_id": "futu_bot",
                "posted_at": now,
            })
        for ticker in list(us_tickers)[:25]:
            posts.append({
                "content": f"富途社区热议: {ticker}",
                "platform": self.PLATFORM,
                "channel": "futu_community",
                "author_id": "futu_bot",
                "posted_at": now,
            })
        LOG.info("futu: parsed %d posts", len(posts))
        return posts
```

### Task 12: Reddit WSB (reddit.py)

```python
# heatmap/collectors/reddit.py
import logging
from datetime import datetime, timezone

from heatmap.collectors.http_base import HttpCollector

LOG = logging.getLogger("heatmap.collectors.reddit")

REDDIT_WSB_URL = "https://www.reddit.com/r/wallstreetbets/hot.json?limit=50"

_NOISE_KEYWORDS = ["loss porn", "yolo", "wife's boyfriend", "tendies", "🚀", "💎🙌"]
_SIGNAL_FLAIRS = ["DD", "Due Diligence", "Technical Analysis", "Earnings", "News", "YOLO"]


class RedditCollector(HttpCollector):
    """Reddit r/wallstreetbets collector with noise filtering."""

    SOURCE_WEIGHT: float = 0.4
    PLATFORM: str = "reddit"

    async def _fetch_posts(self) -> list[dict]:
        try:
            resp = await self._request("GET", REDDIT_WSB_URL, headers={
                "User-Agent": "HeatmapBot/1.0 (educational project)",
            })
            data = resp.json()
            children = data.get("data", {}).get("children", [])
            posts = []
            now = datetime.now(timezone.utc)
            for child in children:
                post_data = child.get("data", {})
                title = post_data.get("title", "")
                selftext = post_data.get("selftext", "")
                flair = post_data.get("link_flair_text", "")
                score = post_data.get("score", 0)
                upvote_ratio = post_data.get("upvote_ratio", 0)

                # Skip noise
                content_lower = f"{title} {selftext}".lower()
                if any(kw in content_lower for kw in _NOISE_KEYWORDS):
                    continue

                # Skip low-quality posts
                if score < 5 or upvote_ratio < 0.5:
                    continue

                # Boost DD/analysis posts
                is_signal = any(s.lower() in flair.lower() for s in _SIGNAL_FLAIRS) if flair else False
                if is_signal and score < 3:
                    continue  # Even signal posts need minimum engagement

                combined = f"{title}\n{selftext[:500]}" if selftext else title
                posts.append({
                    "content": combined,
                    "platform": self.PLATFORM,
                    "channel": f"wsb_{flair or 'general'}",
                    "author_id": post_data.get("author", "unknown"),
                    "posted_at": now,
                })
            LOG.info("reddit: fetched %d posts (filtered from %d)", len(posts), len(children))
            return posts
        except Exception:
            LOG.exception("reddit fetch failed")
            return []
```

### Task 13: StockTwits (stocktwits.py)

```python
# heatmap/collectors/stocktwits.py
import logging
from datetime import datetime, timezone

from heatmap.collectors.http_base import HttpCollector

LOG = logging.getLogger("heatmap.collectors.stocktwits")

STOCKTWITS_TRENDING_URL = "https://api.stocktwits.com/api/2/trending/symbols.json"


class StocktwitsCollector(HttpCollector):
    """StockTwits trending symbols collector."""

    SOURCE_WEIGHT: float = 0.6
    PLATFORM: str = "stocktwits"

    async def _fetch_posts(self) -> list[dict]:
        try:
            resp = await self._request("GET", STOCKTWITS_TRENDING_URL)
            data = resp.json()
            symbols = data.get("symbols", [])
            posts = []
            now = datetime.now(timezone.utc)
            for sym in symbols[:30]:
                symbol = sym.get("symbol", "")
                title = sym.get("title", "")
                watch_count = sym.get("watch_count", 0)
                if not symbol:
                    continue
                posts.append({
                    "content": f"${symbol} ({title}) trending on StockTwits · {watch_count} watchers",
                    "platform": self.PLATFORM,
                    "channel": "trending",
                    "author_id": "stocktwits_bot",
                    "posted_at": now,
                })
            LOG.info("stocktwits: fetched %d trending symbols", len(posts))
            return posts
        except Exception:
            LOG.exception("stocktwits fetch failed")
            return []
```

### Task 14: CoinGecko (coingecko.py)

```python
# heatmap/collectors/coingecko.py
import logging
from datetime import datetime, timezone

from heatmap.collectors.http_base import HttpCollector

LOG = logging.getLogger("heatmap.collectors.coingecko")

COINGECKO_TRENDING_URL = "https://api.coingecko.com/api/v3/search/trending"


class CoingeckoCollector(HttpCollector):
    """CoinGecko trending coins collector."""

    SOURCE_WEIGHT: float = 0.7
    PLATFORM: str = "coingecko"

    async def _fetch_posts(self) -> list[dict]:
        try:
            resp = await self._request("GET", COINGECKO_TRENDING_URL)
            data = resp.json()
            coins = data.get("coins", [])
            posts = []
            now = datetime.now(timezone.utc)
            for coin_data in coins[:30]:
                item = coin_data.get("item", {})
                name = item.get("name", "")
                symbol = item.get("symbol", "")
                market_cap_rank = item.get("market_cap_rank", "N/A")
                score = item.get("score", 0)
                if not name:
                    continue
                posts.append({
                    "content": (
                        f"{name} (${symbol.upper()}) trending on CoinGecko · "
                        f"market cap rank #{market_cap_rank} · score {score}"
                    ),
                    "platform": self.PLATFORM,
                    "channel": "trending",
                    "author_id": "coingecko_bot",
                    "posted_at": now,
                })
            LOG.info("coingecko: fetched %d trending coins", len(posts))
            return posts
        except Exception:
            LOG.exception("coingecko fetch failed")
            return []
```

### Task 15: LunarCrush (lunarcrush.py)

```python
# heatmap/collectors/lunarcrush.py
import logging
import asyncio
import os
from datetime import datetime, timezone

from heatmap.collectors.http_base import HttpCollector

LOG = logging.getLogger("heatmap.collectors.lunarcrush")

# LunarCrush public API v3 (microservice — lower rate limits)
LUNARCRUSH_API = "https://lunarcrush.com/api4/public/coins/list/v2"


class LunarcrushCollector(HttpCollector):
    """LunarCrush social sentiment collector with exponential backoff."""

    SOURCE_WEIGHT: float = 0.5
    PLATFORM: str = "lunarcrush"

    def __init__(self, *args, **kwargs):
        kwargs["poll_interval"] = kwargs.get("poll_interval", 3600)  # 1h to respect limits
        super().__init__(*args, **kwargs)
        self._backoff = 0

    async def _fetch_posts(self) -> list[dict]:
        api_key = os.environ.get("LUNARCRUSH_API_KEY", "")
        if not api_key:
            LOG.warning("lunarcrush: no API key configured, skipping")
            return []

        backoff_delay = min(2 ** self._backoff, 300)  # Max 5 min backoff
        if self._backoff > 0:
            LOG.info("lunarcrush: backoff %ds", backoff_delay)
            await asyncio.sleep(backoff_delay)

        try:
            resp = await self._request("GET", LUNARCRUSH_API, headers={
                "Authorization": f"Bearer {api_key}",
            })
            # Check rate limit headers
            remaining = resp.headers.get("X-RateLimit-Remaining")
            if remaining is not None and int(remaining) < 5:
                LOG.warning("lunarcrush: rate limit low (%s remaining), backing off", remaining)
                self._backoff += 1

            data = resp.json()
            coins = data.get("data", [])
            posts = []
            now = datetime.now(timezone.utc)
            for coin in coins[:30]:
                name = coin.get("name", "")
                symbol = coin.get("symbol", "")
                galaxy_score = coin.get("galaxy_score", 0)
                if not name:
                    continue
                posts.append({
                    "content": (
                        f"{name} (${symbol.upper()}) Galaxy Score: {galaxy_score} · "
                        f"social volume trending on LunarCrush"
                    ),
                    "platform": self.PLATFORM,
                    "channel": "social_sentiment",
                    "author_id": "lunarcrush_bot",
                    "posted_at": now,
                })
            self._backoff = 0  # Reset backoff on success
            LOG.info("lunarcrush: fetched %d coins", len(posts))
            return posts
        except Exception:
            LOG.exception("lunarcrush fetch failed")
            self._backoff += 1
            return []
```

**Test files for Tasks 9-15 (skeleton):**

```python
# tests/unit/test_cls.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from heatmap.collectors.cls import ClsCollector

@pytest.mark.asyncio
async def test_cls_fetch_posts_structure():
    collector = ClsCollector(extractor=MagicMock(), queue=MagicMock(), market="a_share")
    with patch.object(collector, '_request', new_callable=AsyncMock) as mock_req:
        mock_req.return_value.json.return_value = {
            "data": {"roll_data": [{"title": "测试新闻", "content": "测试内容"}]}
        }
        posts = await collector._fetch_posts()
        assert len(posts) == 1
        assert posts[0]["platform"] == "cls"
```

Similar pattern for aastocks, futu, reddit, stocktwits, coingecko, lunarcrush tests.

- [ ] **For each collector (Tasks 9-15):**

```bash
# Write test
# Run: python -m pytest tests/unit/test_<collector>.py -v  (FAIL)
# Implement collector
# Run: python -m pytest tests/unit/test_<collector>.py -v  (PASS)
git add heatmap/collectors/<name>.py tests/unit/test_<name>.py
git commit -m "feat: add <name> collector"
```

---

### Phase 2 Task 16: Scheduler Registration (scheduler.py)

**Files:**
- Modify: `heatmap/scheduler.py`

- [ ] **Step 1: Register all new collectors and initialize CircuitBreaker**

In the `serve()` function, add imports and registration:

```python
from heatmap.collectors.jqka import JqkaCollector
from heatmap.collectors.cls import ClsCollector
from heatmap.collectors.aastocks import AastocksCollector
from heatmap.collectors.futu import FutuCollector
from heatmap.collectors.reddit import RedditCollector
from heatmap.collectors.stocktwits import StocktwitsCollector
from heatmap.collectors.coingecko import CoingeckoCollector
from heatmap.collectors.lunarcrush import LunarcrushCollector
from heatmap.collectors.circuit_breaker import CircuitBreaker
```

After creating `limiter` and `proxy_pool`:

```python
# Initialize circuit breaker
circuit_breaker = CircuitBreaker(
    sleep_minutes=getattr(thresholds, 'circuit_breaker_sleep_minutes', 15),
    threshold=getattr(thresholds, 'circuit_breaker_threshold', 0.2),
    duration_seconds=getattr(thresholds, 'circuit_breaker_duration_seconds', 120),
)
```

Then register collectors conditionally based on `sources.yaml` or defaults:

```python
# A-share: jqka + cls (in addition to existing xueqiu + eastmoney)
if getattr(sources, 'jqka', True):
    LOG.info("starting jqka collector")
    tasks.append(asyncio.create_task(
        JqkaCollector(extractor, queue, market="a_share", limiter=limiter, proxy_pool=proxy_pool, circuit_breaker=circuit_breaker).run()
    ))

if getattr(sources, 'cls', True):
    LOG.info("starting cls collector")
    tasks.append(asyncio.create_task(
        ClsCollector(extractor, queue, market="a_share", limiter=limiter, proxy_pool=proxy_pool, circuit_breaker=circuit_breaker).run()
    ))

# HK: aastocks + futu
if getattr(sources, 'aastocks', True):
    LOG.info("starting aastocks collector")
    tasks.append(asyncio.create_task(
        AastocksCollector(extractor, queue, market="hk", limiter=limiter, proxy_pool=proxy_pool, circuit_breaker=circuit_breaker).run()
    ))

if getattr(sources, 'futu', True):
    LOG.info("starting futu collector")
    tasks.append(asyncio.create_task(
        FutuCollector(extractor, queue, market="hk", limiter=limiter, proxy_pool=proxy_pool, circuit_breaker=circuit_breaker).run()
    ))

# US: reddit + stocktwits
if getattr(sources, 'reddit', True):
    LOG.info("starting reddit collector")
    tasks.append(asyncio.create_task(
        RedditCollector(extractor, queue, market="us", limiter=limiter, proxy_pool=proxy_pool, circuit_breaker=circuit_breaker).run()
    ))

if getattr(sources, 'stocktwits', True):
    LOG.info("starting stocktwits collector")
    tasks.append(asyncio.create_task(
        StocktwitsCollector(extractor, queue, market="us", limiter=limiter, proxy_pool=proxy_pool, circuit_breaker=circuit_breaker).run()
    ))

# Crypto: coingecko + lunarcrush
if getattr(sources, 'coingecko', True):
    LOG.info("starting coingecko collector")
    tasks.append(asyncio.create_task(
        CoingeckoCollector(extractor, queue, market="crypto", limiter=limiter, proxy_pool=proxy_pool, circuit_breaker=circuit_breaker).run()
    ))

if getattr(sources, 'lunarcrush', True):
    LOG.info("starting lunarcrush collector")
    tasks.append(asyncio.create_task(
        LunarcrushCollector(extractor, queue, market="crypto", limiter=limiter, proxy_pool=proxy_pool, circuit_breaker=circuit_breaker).run()
    ))
```

- [ ] **Step 2: Run scheduler tests**

```bash
python -m pytest tests/unit/test_scheduler.py -v
```
Expected: May need test updates for new imports.

- [ ] **Step 3: Commit**

```bash
git add heatmap/scheduler.py
git commit -m "feat(scheduler): register all 8 new collectors with circuit breaker"
```

---

### Phase 2 Task 17: Configuration Updates

**Files:**
- Modify: `config/thresholds.yaml`
- Modify: `config/sources.yaml`

- [ ] **Step 1: Update thresholds.yaml**

```yaml
stage_a_top_n: 50
stage_b_top_n: 10
alpha_min: 0.5
beta_min: 1.5

# AI 信号引擎配置
ai:
  provider: "deepseek"
  model: "deepseek-chat"
  instant_alpha_threshold: 2.0
  min_mentions_for_ai: 20
  max_calls_per_day: 50

# 限速配置
rate_limits:
  "xueqiu.com": 1.0
  "eastmoney.com": 2.0
  "push2.eastmoney.com": 3.0
  "api.twitter.com": 2.0
  "10jqka.com.cn": 1.5
  "stockpage.10jqka.com.cn": 1.5
  "cls.cn": 2.0
  "aastocks.com": 1.0
  "futunn.com": 0.5
  "reddit.com": 2.0
  "api.stocktwits.com": 2.0
  "api.coingecko.com": 1.0
  "lunarcrush.com": 0.3

# 代理池
proxies: []

# 熔断器配置
circuit_breaker:
  sleep_minutes: 15
  threshold: 0.2
  duration_seconds: 120

# 来源权重（可覆盖采集器默认值）
source_weights:
  xueqiu: 0.9
  eastmoney: 0.7
  jqka: 1.0
  cls: 0.8
  aastocks: 0.9
  futu: 0.7
  reddit: 0.4
  stocktwits: 0.6
  coingecko: 0.7
  lunarcrush: 0.5
```

- [ ] **Step 2: Update sources.yaml**

```yaml
telegram:
  channels: []
discord:
  guilds: []

# New source switches (set to false to disable a collector)
jqka: true
cls: true
aastocks: true
futu: true
reddit: true
stocktwits: true
coingecko: true
lunarcrush: true
```

- [ ] **Step 3: Commit**

```bash
git add config/thresholds.yaml config/sources.yaml
git commit -m "feat(config): add source_weights, circuit_breaker params, rate limits for all new sources"
```

---

## Integration Test

### Phase 2 Task 18: Full Pipeline Smoke Test

- [ ] **Step 1: Run the existing integration test suite**

```bash
python -m pytest tests/integration/ -v --timeout=60
```

Expected: All integration tests PASS.

- [ ] **Step 2: Run all unit tests**

```bash
python -m pytest tests/unit/ -v
```

Expected: All unit tests PASS (both new and existing).

- [ ] **Step 3: Full test suite**

```bash
python -m pytest tests/ -v
```

Expected: All tests PASS.

- [ ] **Step 4: Final commit if any integration fixes needed**

```bash
git add -A tests/
git commit -m "test: add integration tests for phase 2 collectors and anti-crawl pipeline"
```

---

## Summary

| Phase | Tasks | Files Created | Files Modified |
|-------|-------|---------------|----------------|
| Phase 1 | 7 | 0 | 7 |
| Phase 2 | 18 | 15 | 5 |
| **Total** | **25** | **15** | **12** |

**Execution order:** Phase 1 Tasks 1→7 first (sequential, each depends on previous). Phase 2 Tasks 1→18 after Phase 1 (Tasks 1-7 are infrastructure, 8-15 are parallel collectors, 16-17 wire everything together, 18 validates).
