export interface TerminalLine {
  content: string
  timestamp: string
  type: 'info' | 'data' | 'error' | 'warn'
  device_id: string
}

export function connectTerminal(
  deviceId: string,
  onLine: (line: TerminalLine) => void
): () => void {
  const ws = new WebSocket(
    `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws/terminal/${deviceId}`
  )

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data)
      if (data.type === 'line') {
        onLine(data.line as TerminalLine)
      }
    } catch {
      // ignore malformed messages
    }
  }

  return () => {
    ws.close()
  }
}

export async function fetchHistory(deviceId: string): Promise<TerminalLine[]> {
  try {
    const res = await fetch(`/api/telemetry/${deviceId}/history?limit=200`)
    if (!res.ok) return []
    return await res.json()
  } catch {
    return []
  }
}
