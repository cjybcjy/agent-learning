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
  const optionsRef = useRef(options)
  const marketsRef = useRef(markets)
  optionsRef.current = options
  marketsRef.current = markets

  const connect = useCallback(() => {
    const socket = new WebSocket(url)
    ws.current = socket

    socket.onopen = () => {
      setConnected(true)
      reconnectDelay.current = 1000
      // Subscribe with current markets array (from ref, not closure)
      socket.send(JSON.stringify({
        action: 'subscribe',
        markets: marketsRef.current,
      }))

      if (wasConnected.current && optionsRef.current?.onReconnect) {
        optionsRef.current.onReconnect()
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
  }, [url])

  useEffect(() => {
    // When markets change, reconnect to re-subscribe with new markets
    connect()
    return () => {
      ws.current?.close()
    }
  }, [connect])

  return { messages, connected }
}
