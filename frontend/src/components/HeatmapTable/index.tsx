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
  return item.source_count === 1 && item.mention_count > 0 && item.rank <= 10
}

function getRelativeTime(isoStr?: string): string {
  if (!isoStr) return '--'
  try {
    const dt = new Date(isoStr.replace('Z', '+00:00'))
    const diffMin = Math.floor((Date.now() - dt.getTime()) / 60000)
    if (diffMin < 1) return '刚刚'
    if (diffMin < 60) return `${diffMin}分钟前`
    const diffHour = Math.floor(diffMin / 60)
    if (diffHour < 24) return `${diffHour}小时前`
    const diffDay = Math.floor(diffHour / 24)
    return `${diffDay}天前`
  } catch {
    return '--'
  }
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
            <th style={{ padding: '8px 12px' }}>更新时间</th>
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
                <td style={{ padding: '8px 12px', color: '#888', fontSize: 12 }}>
                  {getRelativeTime(item.last_updated)}
                </td>
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
