interface Props {
  alerts: { symbol: string; message: string; severity: 'high' | 'medium' | 'low' }[]
}

export default function AlertBanner({ alerts }: Props) {
  if (!alerts.length) return null

  const bgColors = {
    high: '#ffebee',
    medium: '#fff3e0',
    low: '#e8f5e9',
  }

  return (
    <div style={{ padding: '8px 20px', display: 'flex', gap: 8, flexWrap: 'wrap' }}>
      {alerts.map((a, i) => (
        <div
          key={i}
          style={{
            padding: '6px 12px',
            borderRadius: 4,
            background: bgColors[a.severity],
            fontSize: 12,
            fontWeight: 500,
          }}
        >
          {a.severity === 'high' ? '🔥' : a.severity === 'medium' ? '⚠️' : '•'} {a.symbol}: {a.message}
        </div>
      ))}
    </div>
  )
}
