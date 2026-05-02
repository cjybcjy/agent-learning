const API_BASE = '/api'

export async function fetchHeatmap(params: {
  granularity?: string
  market?: string
  limit?: number
  cursor?: string
}) {
  const query = new URLSearchParams(params as any).toString()
  const res = await fetch(`${API_BASE}/heatmap?${query}`)
  return res.json()
}

export async function fetchMarkets() {
  const res = await fetch(`${API_BASE}/markets`)
  return res.json()
}
