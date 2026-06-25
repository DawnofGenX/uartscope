import { useEffect, useRef, useState, useCallback } from 'react'

interface UseWebSocketOptions {
  url: string
  subscribeTo?: string
  onMessage?: (data: any) => void
  onConnect?: () => void
  onDisconnect?: () => void
  reconnect?: boolean
}

export function useWebSocket({
  url,
  subscribeTo = 'all',
  onMessage,
  onConnect,
  onDisconnect,
  reconnect = true,
}: UseWebSocketOptions) {
  const [connected, setConnected] = useState(false)
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return

    const ws = new WebSocket(url)
    wsRef.current = ws

    ws.onopen = () => {
      setConnected(true)
      onConnect?.()
      // Subscribe after connection
      if (subscribeTo !== 'all') {
        ws.send(JSON.stringify({
          type: 'subscribe',
          target: subscribeTo,
        }))
      }
    }

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        onMessage?.(data)
      } catch {
        // ignore
      }
    }

    ws.onclose = () => {
      setConnected(false)
      onDisconnect?.()
      if (reconnect) {
        reconnectTimeoutRef.current = setTimeout(connect, 3000)
      }
    }

    ws.onerror = () => {
      ws.close()
    }
  }, [url, subscribeTo, onMessage, onConnect, onDisconnect, reconnect])

  useEffect(() => {
    connect()
    return () => {
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current)
      wsRef.current?.close()
    }
  }, [connect])

  const send = useCallback((data: any) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(data))
    }
  }, [])

  const subscribe = useCallback((target: string) => {
    send({ type: 'subscribe', target })
  }, [send])

  return { connected, send, subscribe }
}
