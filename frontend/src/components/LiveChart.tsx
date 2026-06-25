import { useState, useEffect } from 'react'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'
import type { TelemetryPoint } from '../types'
import { connectTelemetry } from '../api/telemetry'
import './LiveChart.css'

interface Props {
  deviceId: string | null
}

interface DataPoint {
  time: string
  [key: string]: number | string
}

const COLORS = ['#7170ff', '#10b981', '#f5a623', '#e5484d', '#3b82f6', '#ff6bff']

export default function LiveChart({ deviceId }: Props) {
  const [data, setData] = useState<DataPoint[]>([])
  const [metrics, setMetrics] = useState<string[]>([])
  const [connected, setConnected] = useState(false)
  const maxPoints = 100

  useEffect(() => {
    if (!deviceId) return

    setData([])
    setMetrics([])

    const cleanup = connectTelemetry(deviceId, (point) => {
      setConnected(true)
      
      // Track new metrics
      const keys = Object.keys(point.values)
      setMetrics((prev) => {
        const newMetrics = [...prev]
        keys.forEach(k => {
          if (!newMetrics.includes(k)) newMetrics.push(k)
        })
        return newMetrics
      })

      setData((prev) => {
        const newPoint: DataPoint = {
          time: new Date(point.timestamp).toLocaleTimeString([], { 
            hour12: false, 
            hour: '2-digit', 
            minute: '2-digit', 
            second: '2-digit' 
          }),
          ...point.values,
        }
        const updated = [...prev, newPoint]
        if (updated.length > maxPoints) return updated.slice(-maxPoints)
        return updated
      })
    })

    return () => {
      cleanup()
      setConnected(false)
    }
  }, [deviceId])

  if (!deviceId) {
    return (
      <div className="chart-view">
        <div className="empty-state">
          <div className="empty-icon">◇</div>
          <h3>No device selected</h3>
          <p>Select a device to view live telemetry charts</p>
        </div>
      </div>
    )
  }

  return (
    <div className="chart-view">
      <div className="chart-toolbar">
        <div className="chart-toolbar-left">
          <span className={`terminal-dot ${connected ? 'live' : ''}`} />
          <span className="chart-device-id">{deviceId.slice(0, 8)}</span>
          <span className="chart-sep">·</span>
          <span className="chart-info">
            {metrics.length} metric{metrics.length !== 1 ? 's' : ''} · {data.length} points
          </span>
        </div>
        <div className="chart-legend">
          {metrics.map((m, i) => (
            <span key={m} className="legend-item">
              <span className="legend-dot" style={{ background: COLORS[i % COLORS.length] }} />
              <span className="legend-label">{m}</span>
            </span>
          ))}
        </div>
      </div>

      <div className="chart-container">
        {data.length === 0 && connected ? (
          <div className="chart-waiting">
            <div className="loading-spinner" />
            <span>Waiting for telemetry data...</span>
          </div>
        ) : data.length > 0 ? (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 10, right: 20, left: 10, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.03)" />
              <XAxis 
                dataKey="time" 
                tick={{ fontSize: 10, fill: '#62666d' }}
                axisLine={{ stroke: 'rgba(255,255,255,0.05)' }}
                tickLine={false}
                interval="preserveStartEnd"
              />
              <YAxis 
                tick={{ fontSize: 10, fill: '#62666d' }}
                axisLine={false}
                tickLine={false}
                width={50}
              />
              <Tooltip
                contentStyle={{
                  background: '#191a1b',
                  border: '1px solid rgba(255,255,255,0.08)',
                  borderRadius: '8px',
                  fontSize: '12px',
                  color: '#d0d6e0',
                  fontFamily: 'JetBrains Mono, monospace',
                }}
                labelStyle={{ color: '#8a8f98' }}
              />
              {metrics.map((m, i) => (
                <Line
                  key={m}
                  type="monotone"
                  dataKey={m}
                  stroke={COLORS[i % COLORS.length]}
                  strokeWidth={2}
                  dot={false}
                  isAnimationActive={false}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        ) : (
          <div className="chart-empty">
            <span>No data available</span>
          </div>
        )}
      </div>
    </div>
  )
}
