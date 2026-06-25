import type { TelemetryPoint } from '../types'

export function connectTelemetry(
  deviceId: string,
  onPoint: (point: TelemetryPoint) => void
): () => void {
  const ws = new WebSocket(
    `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws/telemetry/${deviceId}`
  )

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data)
      if (data.type === 'telemetry') {
        onPoint(data.point as TelemetryPoint)
      }
    } catch {
      // ignore
    }
  }

  return () => {
    ws.close()
  }
}
