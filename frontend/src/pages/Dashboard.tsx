import { useState, useMemo, useEffect, useCallback, useReducer, useRef } from 'react'
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
    // Abort previous request on non-append loads
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
          title="设置">{'⚙️'}</button>
      </header>

      {/* L1: Overview bar */}
      {currentMarketStat && (
        <div style={{
          padding: '8px 20px', background: '#f8f9fa', borderBottom: '1px solid #eee',
          display: 'flex', gap: 20, fontSize: 13, color: '#555',
        }}>
          <span>{'标的'}: <strong>{currentMarketStat.symbol_count}</strong></span>
          <span>{'消息'}: <strong>{currentMarketStat.total_mentions}</strong></span>
          <span>{'来源'}: <strong>{currentMarketStat.source_count}</strong> ({currentMarketStat.sources.join(', ') || '无'})</span>
          {currentMarketStat.last_updated && (
            <span style={{ color: '#888' }}>{'更新于'} {new Date(currentMarketStat.last_updated).toLocaleString()}</span>
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
            <p style={{ color: '#c62828', padding: 20 }}>{'加载失败'}: {state.message}</p>
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
