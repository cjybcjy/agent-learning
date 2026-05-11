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
