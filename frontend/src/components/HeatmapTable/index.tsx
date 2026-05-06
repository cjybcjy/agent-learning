interface HeatmapItem {
  symbol: string
  rank: number
  mention_count: number
  weighted_score: number
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

export default function HeatmapTable({ items, loading, cursor, onLoadMore, onSelectSymbol, onAskAI }: Props) {
  const getAlphaColor = (alpha?: string) => {
    if (!alpha) return '#666'
    const val = parseFloat(alpha)
    if (val > 0) return '#2e7d32'
    if (val < 0) return '#c62828'
    return '#666'
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
            <th style={{ padding: '8px 12px' }}>即时α</th>
            <th style={{ padding: '8px 12px' }}>AI</th>
            <th style={{ padding: '8px 12px' }}>操作</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr
              key={item.symbol}
              style={{ borderBottom: '1px solid #f0f0f0', cursor: 'pointer' }}
              onClick={() => onSelectSymbol(item.symbol)}
            >
              <td style={{ padding: '8px 12px' }}>{item.rank}</td>
              <td style={{ padding: '8px 12px', fontWeight: 600 }}>{item.symbol}</td>
              <td style={{ padding: '8px 12px' }}>{item.mention_count}</td>
              <td style={{ padding: '8px 12px', color: getAlphaColor(item.instant_alpha), fontWeight: 600 }}>
                {item.instant_alpha || '-'}
              </td>
              <td style={{ padding: '8px 12px' }}>
                {item.anomaly_score !== undefined && item.anomaly_score !== null ? (
                  <span style={{
                    padding: '2px 8px',
                    borderRadius: 12,
                    background: item.anomaly_score > 0.8 ? '#ffebee' : '#fff3e0',
                    color: item.anomaly_score > 0.8 ? '#c62828' : '#e65100',
                    fontSize: 12,
                    fontWeight: 600,
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
                    onAskAI(item.symbol, { instant_alpha: item.instant_alpha, mention_count: item.mention_count })
                  }}
                  style={{
                    padding: '2px 10px',
                    fontSize: 12,
                    border: '1px solid #1976d2',
                    background: '#fff',
                    color: '#1976d2',
                    borderRadius: 4,
                    cursor: 'pointer',
                  }}
                >
                  为什么?
                </button>
              </td>
            </tr>
          ))}
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
