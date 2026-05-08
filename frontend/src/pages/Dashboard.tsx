import { useState, useMemo, useEffect, useCallback } from 'react'
import { useWebSocket } from '../hooks/useWebSocket'
import { fetchHeatmap } from '../services/api'
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
  instant_alpha?: string
  anomaly_score?: number
  sentiment_shift?: string
  key_driver?: string
}

export default function Dashboard() {
  const [granularity, setGranularity] = useState('30min')
  const [market, setMarket] = useState('all')
  const [items, setItems] = useState<HeatmapItem[]>([])
  const [cursor, setCursor] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null)
  const [chatContext, setChatContext] = useState<any>(null)
  const [settingsOpen, setSettingsOpen] = useState(false)

  const loadData = useCallback(async (append = false) => {
    setLoading(true)
    try {
      const res = await fetchHeatmap({ granularity, market, limit: 50, cursor: append ? cursor || undefined : undefined })
      const newItems: HeatmapItem[] = (res.items || []).map((r: any, idx: number) => ({
        symbol: r.symbol,
        rank: append ? (items.length + idx + 1) : (idx + 1),
        mention_count: r.mention_count,
        weighted_score: r.weighted_score,
        instant_alpha: r.instant_alpha,
        anomaly_score: r.anomaly_score,
        sentiment_shift: r.sentiment_shift,
        key_driver: r.key_driver,
      }))
      setItems(prev => append ? [...prev, ...newItems] : newItems)
      setCursor(res.next_cursor)
    } catch (e) {
      console.error('fetchHeatmap failed', e)
    } finally {
      setLoading(false)
    }
  }, [granularity, market, cursor, items.length])

  useEffect(() => {
    loadData(false)
  }, [granularity, market])

  const handleReconnect = useCallback(() => {
    // Re-fetch data on WebSocket reconnect to catch up missed updates
    loadData(false)
  }, [loadData])

  const { messages, connected } = useWebSocket('ws://localhost:8000/ws/heatmap', [market], {
    onReconnect: handleReconnect,
  })

  // Merge real-time WebSocket messages into items
  useEffect(() => {
    if (!messages.length) return
    const latest = messages[messages.length - 1]
    if (latest.type === 'rollup_update') {
      setItems(prev => {
        const idx = prev.findIndex(i => i.symbol === latest.symbol)
        if (idx >= 0) {
          const updated = [...prev]
          updated[idx] = { ...updated[idx], mention_count: latest.mention_count, weighted_score: latest.weighted_score }
          return updated
        }
        return prev
      })
    } else if (latest.type === 'ai_signal') {
      setItems(prev => {
        const idx = prev.findIndex(i => i.symbol === latest.symbol)
        if (idx >= 0) {
          const updated = [...prev]
          updated[idx] = { ...updated[idx], anomaly_score: latest.anomaly_score, sentiment_shift: latest.sentiment_shift, key_driver: latest.key_driver }
          return updated
        }
        return prev
      })
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

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh' }}>
      <header style={{ padding: '12px 20px', borderBottom: '1px solid #eee', display: 'flex', alignItems: 'center', gap: 16 }}>
        <h1 style={{ margin: 0, fontSize: 20 }}>Market Heatmap</h1>

        <select value={market} onChange={e => setMarket(e.target.value)} style={{ padding: '4px 8px' }}>
          {MARKETS.map(m => (
            <option key={m.key} value={m.key}>{m.label}</option>
          ))}
        </select>

        <div>
          {GRANULARITIES.map(g => (
            <button
              key={g}
              onClick={() => setGranularity(g)}
              style={{
                marginRight: 4,
                padding: '4px 12px',
                background: granularity === g ? '#1976d2' : '#f5f5f5',
                color: granularity === g ? '#fff' : '#333',
                border: 'none',
                borderRadius: 4,
                cursor: 'pointer'
              }}
            >
              {g}
            </button>
          ))}
        </div>

        <span style={{
          marginLeft: 'auto',
          padding: '4px 12px',
          borderRadius: 4,
          background: connected ? '#e8f5e9' : '#ffebee',
          color: connected ? '#2e7d32' : '#c62828'
        }}>
          {connected ? '已连接' : '连接中...'}
        </span>

        <button
          onClick={() => setSettingsOpen(true)}
          style={{
            padding: '4px 12px',
            border: '1px solid #ddd',
            background: '#fff',
            borderRadius: 4,
            cursor: 'pointer',
            fontSize: 13,
          }}
          title="设置"
        >
          ⚙️
        </button>
      </header>

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
