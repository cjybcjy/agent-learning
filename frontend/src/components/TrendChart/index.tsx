import { useEffect, useState } from 'react'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'

interface DataPoint {
  window_start: string
  mention_count: number
  weighted_score: number
}

interface Props {
  symbol: string
  granularity: string
}

export default function TrendChart({ symbol, granularity }: Props) {
  const [data, setData] = useState<DataPoint[]>([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!symbol) return
    setLoading(true)
    fetch(`/api/heatmap/${encodeURIComponent(symbol)}/trend?granularity=${granularity}`)
      .then(r => r.json())
      .then(res => {
        setData((res.data || []).map((d: any) => ({
          ...d,
          label: d.window_start?.slice(5, 16) || '',
        })))
      })
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [symbol, granularity])

  if (!symbol) return null

  return (
    <div style={{ padding: '16px 20px', borderTop: '1px solid #eee' }}>
      <h3 style={{ margin: '0 0 12px' }}>
        {symbol} 趋势图
        {loading && <span style={{ fontSize: 12, color: '#999', marginLeft: 8 }}>加载中...</span>}
      </h3>
      <ResponsiveContainer width="100%" height={200}>
        <LineChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
          <XAxis dataKey="label" tick={{ fontSize: 11 }} />
          <YAxis tick={{ fontSize: 11 }} />
          <Tooltip />
          <Line type="monotone" dataKey="mention_count" stroke="#1976d2" strokeWidth={2} dot={false} />
          <Line type="monotone" dataKey="weighted_score" stroke="#2e7d32" strokeWidth={2} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
