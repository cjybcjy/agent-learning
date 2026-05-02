import { useState } from 'react'
import { useWebSocket } from '../hooks/useWebSocket'

const MARKETS = [
  { key: 'all', label: '全部' },
  { key: 'a_share', label: 'A股' },
  { key: 'hk', label: '港股' },
  { key: 'us', label: '美股' },
  { key: 'crypto', label: '币圈' },
]

const GRANULARITIES = ['30min', '4h', 'day', 'week']

export default function Dashboard() {
  const [granularity, setGranularity] = useState('30min')
  const [market, setMarket] = useState('all')
  const { messages, connected } = useWebSocket('ws://localhost:8000/ws/heatmap', [market])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh' }}>
      <header style={{ padding: '12px 20px', borderBottom: '1px solid #eee', display: 'flex', alignItems: 'center', gap: 16 }}>
        <h1 style={{ margin: 0, fontSize: 20 }}>Market Heatmap</h1>

        <select value={market} onChange={e => setMarket(e.target.value)}>
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
      </header>

      <main style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        <div style={{ flex: 2, padding: 20, overflow: 'auto' }}>
          <h2>热度榜单</h2>
          <p>数据加载中...（{messages.length} 条实时消息）</p>
        </div>
        <div style={{ flex: 1, padding: 20, borderLeft: '1px solid #eee', overflow: 'auto' }}>
          <h2>AI 助手</h2>
          <p>AI 聊天面板（开发中）</p>
        </div>
      </main>
    </div>
  )
}
