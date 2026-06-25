import { useState, useEffect, useCallback } from 'react'
import { SessionSummary, listSessions, startSession, stopSession, renameSession } from '../api/sessions'
import { Device, listDevices } from '../api/devices'
import './SessionsPanel.css'

interface Props {
  onSessionSelect: (id: string) => void
}

function formatDuration(startedAt: string, endedAt: string | null): string {
  const start = new Date(startedAt)
  const end = endedAt ? new Date(endedAt) : new Date()
  const diff = Math.floor((end.getTime() - start.getTime()) / 1000)
  if (diff < 60) return `${diff}s`
  if (diff < 3600) return `${Math.floor(diff / 60)}m ${diff % 60}s`
  const h = Math.floor(diff / 3600)
  const m = Math.floor((diff % 3600) / 60)
  return `${h}h ${m}m`
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString([], { month: 'short', day: 'numeric' })
}

export default function SessionsPanel({ onSessionSelect }: Props) {
  const [sessions, setSessions] = useState<SessionSummary[]>([])
  const [devices, setDevices] = useState<Device[]>([])
  const [loading, setLoading] = useState(true)
  const [starting, setStarting] = useState(false)
  const [filter, setFilter] = useState<'all' | 'recording' | 'completed'>('all')

  const fetchData = useCallback(async () => {
    try {
      const [sessRes, devRes] = await Promise.all([listSessions(), listDevices()])
      setSessions(sessRes.sessions || [])
      setDevices(devRes.devices || [])
    } catch {
      // silent
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchData()
    const interval = setInterval(fetchData, 5000)
    return () => clearInterval(interval)
  }, [fetchData])

  const handleStartSession = async (deviceId: string) => {
    setStarting(true)
    try {
      const device = devices.find(d => d.id === deviceId)
      await startSession(deviceId, `${device?.name || 'Device'} Session`)
      await fetchData()
    } catch {
      // silent
    } finally {
      setStarting(false)
    }
  }

  const handleStopSession = async (id: string) => {
    try {
      await stopSession(id)
      await fetchData()
    } catch {
      // silent
    }
  }

  const handleRename = async (id: string, currentName: string) => {
    const newName = prompt('Session name:', currentName)
    if (newName && newName !== currentName) {
      try {
        await renameSession(id, newName)
        await fetchData()
      } catch {
        // silent
      }
    }
  }

  const filteredSessions = sessions.filter(s => {
    if (filter === 'all') return true
    return s.status === filter
  })

  const recordingCount = sessions.filter(s => s.status === 'recording').length

  if (loading) {
    return (
      <div className="sessions-panel">
        <div className="loading-state">
          <div className="loading-spinner" />
          <span>Loading sessions...</span>
        </div>
      </div>
    )
  }

  return (
    <div className="sessions-panel">
      {/* Header */}
      <div className="sessions-header">
        <div className="sessions-filters">
          <button
            className={`filter-chip ${filter === 'all' ? 'active' : ''}`}
            onClick={() => setFilter('all')}
          >
            All <span className="chip-count">{sessions.length}</span>
          </button>
          <button
            className={`filter-chip ${filter === 'recording' ? 'active' : ''}`}
            onClick={() => setFilter('recording')}
          >
            <span className="chip-dot live" /> Recording <span className="chip-count">{recordingCount}</span>
          </button>
          <button
            className={`filter-chip ${filter === 'completed' ? 'active' : ''}`}
            onClick={() => setFilter('completed')}
          >
            Completed <span className="chip-count">{sessions.length - recordingCount}</span>
          </button>
        </div>
        <div className="sessions-actions">
          <select
            className="device-select"
            onChange={(e) => e.target.value && handleStartSession(e.target.value)}
            defaultValue=""
            disabled={starting}
          >
            <option value="" disabled>+ Start from device...</option>
            {devices.map(d => (
              <option key={d.id} value={d.id}>{d.name} ({d.port})</option>
            ))}
          </select>
        </div>
      </div>

      {/* Session List */}
      {filteredSessions.length === 0 ? (
        <div className="sessions-empty">
          <div className="empty-icon">⟳</div>
          <h3>No sessions yet</h3>
          <p>Start streaming from a device to create your first recording session</p>
        </div>
      ) : (
        <div className="sessions-list">
          {filteredSessions.map((session) => (
            <div
              key={session.id}
              className="session-card animate-fade-in"
              onClick={() => onSessionSelect(session.id)}
            >
              <div className="session-card-left">
                <span className={`session-status-dot ${session.status}`} />
                <div className="session-info">
                  <span className="session-name">{session.name}</span>
                  <span className="session-meta">
                    {formatDate(session.started_at)} · {formatTime(session.started_at)}
                    {session.status === 'recording' && (
                      <> · <span className="session-live">● LIVE</span></>
                    )}
                  </span>
                </div>
              </div>

              <div className="session-card-center">
                <div className="session-stat">
                  <span className="session-stat-value">{session.packet_count.toLocaleString()}</span>
                  <span className="session-stat-label">Packets</span>
                </div>
                <div className="session-stat">
                  <span className="session-stat-value">{session.metric_count.toLocaleString()}</span>
                  <span className="session-stat-label">Metrics</span>
                </div>
                <div className="session-stat">
                  <span className="session-stat-value">{session.event_count.toLocaleString()}</span>
                  <span className="session-stat-label">Events</span>
                </div>
                <div className="session-stat">
                  <span className="session-stat-value">{formatDuration(session.started_at, session.ended_at)}</span>
                  <span className="session-stat-label">Duration</span>
                </div>
              </div>

              <div className="session-card-right" onClick={(e) => e.stopPropagation()}>
                {session.status === 'recording' ? (
                  <button
                    className="btn btn-ghost btn-sm"
                    onClick={() => handleStopSession(session.id)}
                    title="Stop recording"
                  >
                    ■ Stop
                  </button>
                ) : (
                  <button
                    className="btn btn-ghost btn-sm"
                    onClick={() => handleRename(session.id, session.name)}
                    title="Rename session"
                  >
                    ✎ Rename
                  </button>
                )}
                <button className="btn btn-primary btn-sm">
                  View →
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
