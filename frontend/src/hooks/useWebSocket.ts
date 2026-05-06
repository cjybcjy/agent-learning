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

  const connect = useCallback(() => {
    const socket = new WebSocket(url)
    ws.current = socket

    socket.onopen = () => {
      setConnected(true)
      reconnectDelay.current = 1000
      socket.send(JSON.stringify({ action: 'subscribe', markets }))

      // Trigger reconnect callback if this is a reconnection
      if (wasConnected.current && options?.onReconnect) {
        options.onReconnect()
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
  }, [url, markets, options])

  useEffect(() => {
    connect()
    return () => ws.current?.close()
  }, [connect])

  return { messages, connected }
}
