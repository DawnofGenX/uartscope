import { useState, useEffect, useRef, useCallback } from 'react'
import { SessionSummary, SessionPacket, SessionMetric, SessionEvent, getSessionPackets, getSessionMetrics, getSessionEvents, getSessionInfo } from '../api/sessions'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'
import './SessionDetail.css'

interface Props {
  sessionId: string
  onBack: () => void
}

interface TimelinePoint {
  time: string
  timestamp: number
  type: 'packet' | 'metric' | 'event'
  content: string
  metric_name?: string
  value?: number
  severity?: string
}

const COLORS = ['#7170ff', '#10b981', '#f5a623', '#e5484d', '#3b82f6', '#ff6bff']

export default function SessionDetail({ sessionId, onBack }: Props) {
  const [packets, setPackets] = useState<SessionPacket[]>([])
  const [metrics, setMetrics] = useState<SessionMetric[]>([])
  const [events, setEvents] = useState<SessionEvent[]>([])
  const [info, setInfo] = useState<SessionSummary | null>(null)
  const [loading, setLoading] = useState(true)

  // Replay state
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(1)
  const [replayIndex, setReplayIndex] = useState(0)
  const [replayPackets, setReplayPackets] = useState<SessionPacket[]>([])
  const replayRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Active tab
  const [activeTab, setActiveTab] = useState<'timeline' | 'metrics' | 'export'>('timeline')

  useEffect(() => {
    async function fetchSession() {
      try {
        const [infoRes, packetsRes, metricsRes, eventsRes] = await Promise.all([
          getSessionInfo(sessionId),
          getSessionPackets(sessionId, 5000),
          getSessionMetrics(sessionId, 5000),
          getSessionEvents(sessionId, 5000),
        ])
        setInfo(infoRes)
        setPackets(packetsRes)
        setMetrics(metricsRes)
        setEvents(eventsRes)
        setReplayPackets(packetsRes)
      } catch {
        // silent
      } finally {
        setLoading(false)
      }
    }
    fetchSession()
  }, [sessionId])

  // Replay controls
  const startReplay = useCallback(() => {
    setPlaying(true)
    setReplayIndex(0)
    setReplayPackets([])
  }, [])

  const stopReplay = useCallback(() => {
    setPlaying(false)
    if (replayRef.current) clearInterval(replayRef.current)
  }, [])

  useEffect(() => {
    if (playing) {
      if (replayIndex >= packets.length) {
        setPlaying(false)
        return
      }
      replayRef.current = setInterval(() => {
        setReplayIndex((prev) => {
          if (prev >= packets.length) {
            setPlaying(false)
            if (replayRef.current) clearInterval(replayRef.current)
            return prev
          }
          setReplayPackets((r) => [...r, packets[prev]])
          return prev + 1
        })
      }, Math.max(16, 100 / speed))
    }
    return () => {
      if (replayRef.current) clearInterval(replayRef.current)
    }
  }, [playing, speed, packets, replayIndex])

  const handleExportJSON = () => {
    const data = { info, packets, metrics, events }
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `session-${sessionId.slice(0, 8)}.json`
    a.click()
    URL.revokeObjectURL(url)
  }

  const handleExportCSV = () => {
    const headers = ['timestamp', 'metric_name', 'value', 'unit']
    const rows = metrics.map(m => [m.ts, m.metric_name, m.value, m.unit || ''])
    const csv = [headers.join(','), ...rows.map(r => r.join(','))].join('\n')
    const blob = new Blob([csv], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `session-${sessionId.slice(0, 8)}-metrics.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  if (loading) {
    return (
      <div className="session-detail">
        <div className="loading-state">
          <div className="loading-spinner" />
          <span>Loading session...</span>
        </div>
      </div>
    )
  }

  if (!info) {
    return (
      <div className="session-detail">
        <div className="empty-state">
          <h3>Session not found</h3>
          <button className="btn btn-ghost" onClick={onBack}>← Back to sessions</button>
        </div>
      </div>
    )
  }

  // Prepare chart data from metrics
  const chartData = metrics.map(m => ({
    time: new Date(m.ts).toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' }),
    [m.metric_name]: m.value,
  }))

  const uniqueMetrics = [...new Set(metrics.map(m => m.metric_name))]

  return (
    <div className="session-detail">
      {/* Header */}
      <div className="session-detail-header">
        <button className="back-btn" onClick={onBack}>←</button>
        <div className="session-detail-info">
          <h2>{info.name}</h2>
          <span className="session-detail-meta">
            {info.status === 'recording' && <span className="session-live">● Recording</span>}
            {info.status !== 'recording' && <span>Completed</span>}
            {' · '}
            Started {new Date(info.started_at).toLocaleString([], {
              month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
            })}
            {' · '}
            {info.packet_count.toLocaleString()} packets
            {' · '}
            {info.metric_count.toLocaleString()} metrics
          </span>
        </div>
      </div>

      {/* Tabs */}
      <div className="session-tabs">
        <button
          className={`session-tab ${activeTab === 'timeline' ? 'active' : ''}`}
          onClick={() => setActiveTab('timeline')}
        >
          Timeline Replay
        </button>
        <button
          className={`session-tab ${activeTab === 'metrics' ? 'active' : ''}`}
          onClick={() => setActiveTab('metrics')}
        >
          Metrics Chart
        </button>
        <button
          className={`session-tab ${activeTab === 'export' ? 'active' : ''}`}
          onClick={() => setActiveTab('export')}
        >
          Export
        </button>
      </div>

      {/* Tab Content */}
      <div className="session-tab-content">
        {activeTab === 'timeline' && (
          <div className="timeline-view">
            {/* Replay Controls */}
            <div className="replay-controls">
              <div className="replay-btns">
                {!playing ? (
                  <button className="btn btn-primary btn-sm" onClick={startReplay}>
                    ▶ Replay
                  </button>
                ) : (
                  <button className="btn btn-ghost btn-sm" onClick={stopReplay}>
                    ❚❚ Pause
                  </button>
                )}
                <div className="speed-control">
                  <span className="speed-label">Speed</span>
                  {[0.5, 1, 2, 5, 10].map(s => (
                    <button
                      key={s}
                      className={`speed-btn ${speed === s ? 'active' : ''}`}
                      onClick={() => setSpeed(s)}
                    >
                      {s}x
                    </button>
                  ))}
                </div>
              </div>
              <div className="replay-progress">
                <div className="progress-bar">
                  <div
                    className="progress-fill"
                    style={{
                      width: `${packets.length > 0 ? (replayIndex / packets.length) * 100 : 0}%`
                    }}
                  />
                </div>
                <span className="progress-text">
                  {replayIndex} / {packets.length} packets
                </span>
              </div>
            </div>

            {/* Timeline Events */}
            <div className="timeline-container">
              {replayPackets.length === 0 && !playing && (
                <div className="timeline-empty">
                  Click ▶ Replay to replay recorded packets
                </div>
              )}
              {replayPackets.map((packet, i) => (
                <div key={i} className="timeline-row animate-slide-in">
                  <span className="timeline-time">
                    {new Date(packet.ts).toLocaleTimeString([], {
                      hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit',
                      fractionalSecondDigits: 3,
                    } as any)}
                  </span>
                  <span className="timeline-type packet">PKT</span>
                  <span className="timeline-content">{packet.raw}</span>
                </div>
              ))}
              {events.map((event, i) => (
                <div key={`e-${i}`} className="timeline-row event">
                  <span className="timeline-time">
                    {new Date(event.ts).toLocaleTimeString([], {
                      hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit',
                    })}
                  </span>
                  <span className={`timeline-type ${event.type}`}>{event.type.toUpperCase()}</span>
                  <span className="timeline-content">{event.message || event.type}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {activeTab === 'metrics' && (
          <div className="metrics-view">
            {metrics.length === 0 ? (
              <div className="empty-state">
                <h3>No metrics data</h3>
                <p>This session didn't record any telemetry metrics</p>
              </div>
            ) : (
              <>
                <div className="metrics-legend">
                  {uniqueMetrics.map((m, i) => (
                    <span key={m} className="legend-item">
                      <span className="legend-dot" style={{ background: COLORS[i % COLORS.length] }} />
                      <span className="legend-label">{m}</span>
                    </span>
                  ))}
                </div>
                <div className="metrics-chart">
                  <ResponsiveContainer width="100%" height={300}>
                    <LineChart data={chartData} margin={{ top: 10, right: 20, left: 10, bottom: 5 }}>
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
                      />
                      {uniqueMetrics.map((m, i) => (
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
                </div>
              </>
            )}
          </div>
        )}

        {activeTab === 'export' && (
          <div className="export-view">
            <div className="export-grid">
              <div className="export-card">
                <div className="export-icon">{ }</div>
                <h3>JSON Export</h3>
                <p>Full session data including all packets, metrics, and events</p>
                <button className="btn btn-primary" onClick={handleExportJSON}>
                  Download JSON
                </button>
              </div>
              <div className="export-card">
                <div className="export-icon">CSV</div>
                <h3>CSV Export</h3>
                <p>Metrics data in CSV format for spreadsheet analysis</p>
                <button className="btn btn-primary" onClick={handleExportCSV}>
                  Download CSV
                </button>
              </div>
            </div>
            <div className="export-stats">
              <h4>Session Statistics</h4>
              <div className="export-stats-grid">
                <div className="export-stat">
                  <span className="export-stat-value">{info.packet_count.toLocaleString()}</span>
                  <span className="export-stat-label">Total Packets</span>
                </div>
                <div className="export-stat">
                  <span className="export-stat-value">{info.metric_count.toLocaleString()}</span>
                  <span className="export-stat-label">Metric Points</span>
                </div>
                <div className="export-stat">
                  <span className="export-stat-value">{info.event_count.toLocaleString()}</span>
                  <span className="export-stat-label">Events</span>
                </div>
                <div className="export-stat">
                  <span className="export-stat-value">{uniqueMetrics.length}</span>
                  <span className="export-stat-label">Unique Metrics</span>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
