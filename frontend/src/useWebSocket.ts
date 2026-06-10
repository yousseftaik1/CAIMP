import { useEffect, useRef, useState } from 'react'
import { getOrgId, getToken } from './auth'
import type { WsEvent } from './types'

export function useWebSocket(onEvent: (event: WsEvent) => void) {
  const wsRef = useRef<WebSocket | null>(null)
  const [connected, setConnected] = useState(false)

  useEffect(() => {
    const orgId = getOrgId()
    if (!orgId) return

    const protocol = location.protocol === 'https:' ? 'wss' : 'ws'

    const connect = () => {
      const token = getToken()
      if (!token) { setTimeout(connect, 3000); return }
      const url = `${protocol}://${location.host}/ws/${orgId}?token=${token}`
      const ws = new WebSocket(url)
      wsRef.current = ws

      ws.onopen = () => setConnected(true)
      ws.onclose = () => {
        setConnected(false)
        // Reconnect after 3 seconds
        setTimeout(connect, 3000)
      }
      ws.onerror = () => ws.close()
      ws.onmessage = (ev) => {
        try {
          const data = JSON.parse(ev.data) as WsEvent
          onEvent(data)
        } catch {
          // ignore parse errors
        }
      }
    }

    connect()
    return () => {
      wsRef.current?.close()
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const send = (data: string) => wsRef.current?.send(data)
  return { connected, send }
}
