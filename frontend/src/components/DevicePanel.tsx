import { useState, useEffect, useCallback } from 'react'
import { Device, listDevices, startStream, stopStream, toggleAutoReconnect, getDeviceStats } from '../api/devices'
import './DevicePanel.css'

interface Props {
  onDeviceSelect: (id: string) => void
  onStatsUpdate: (stats: { total_devices: number; connected_devices: number; streaming_devices: number; total_bytes: number; total_packets: number; uptime_seconds: number; ws_clients: number }) => void
}

export default function DevicePanel({ onDeviceSelect, onStatsUpdate }: Props) {
  const [devices, setDevices] = useState<Device[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [startingId, setStartingId] = useState<string | null>(null)

  const fetchDevices = useCallback(async () => {
    try {
      const data = await listDevices()
      setDevices(data.devices || [])
      if (data.stats) {
        onStatsUpdate(data.stats)
      }
      setError(null)
    } catch {
      setError('Failed to load devices')
    } finally {
      setLoading(false)
    }
  }, [onStatsUpdate])

  useEffect(() => {
    fetchDevices()
    const interval = setInterval(fetchDevices, 5000)
    return () => clearInterval(interval)
  }, [fetchDevices])

  const handleStart = async (id: string) => {
    setStartingId(id)
    try {
      await startStream(id)
      await fetchDevices()
    } catch {
      // silent
    } finally {
      setStartingId(null)
    }
  }

  const handleStop = async (id: string) => {
    try {
      await stopStream(id)
      await fetchDevices()
    } catch {
      // silent
    }
  }

  const handleAutoReconnect = async (id: string, enabled: boolean) => {
    try {
      await toggleAutoReconnect(id, enabled)
      await fetchDevices()
    } catch {
      // silent
    }
  }

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'streaming': return 'var(--status-green)'
      case 'connected': return 'var(--status-blue)'
      case 'disconnected': return 'var(--text-quaternary)'
      default: return 'var(--text-quaternary)'
    }
  }

  const getStatusLabel = (status: string) => {
    switch (status) {
      case 'streaming': return 'Streaming'
      case 'connected': return 'Connected'
      case 'disconnected': return 'Disconnected'
      default: return status
    }
  }

  if (loading) {
    return (
      <div className="device-panel">
        <div className="loading-state">
          <div className="loading-spinner" />
          <span>Loading devices...</span>
        </div>
      </div>
    )
  }

  return (
    <div className="device-panel">
      {error && (
        <div className="error-banner">
          <span>⚠</span>
          <span>{error}</span>
          <button onClick={fetchDevices}>Retry</button>
        </div>
      )}

      <div className="device-grid">
        {devices.length === 0 ? (
          <div className="empty-state">
            <div className="empty-icon">◈</div>
            <h3>No devices registered</h3>
            <p>Connect a serial device to get started</p>
          </div>
        ) : (
          devices.map((device) => (
            <div key={device.id} className="device-card animate-fade-in">
              <div className="device-card-header">
                <div className="device-info">
                  <div className="device-status-row">
                    <span
                      className={`device-status-dot ${device.status === 'streaming' ? 'live' : ''}`}
                      style={{ background: getStatusColor(device.status) }}
                    />
                    <span className="device-name truncate">{device.name}</span>
                  </div>
                  <span className="device-port">{device.port}</span>
                </div>
                <span
                  className={`device-status-badge ${device.status}`}
                  style={{ color: getStatusColor(device.status) }}
                >
                  {getStatusLabel(device.status)}
                </span>
              </div>

              <div className="device-meta">
                <span className="meta-item">{device.baud_rate} baud</span>
                <span className="meta-sep">·</span>
                <span className="meta-item">{device.board_type || 'Unknown'}</span>
                <span className="meta-sep">·</span>
                <span className="meta-item">ID: {device.id.slice(0, 8)}</span>
              </div>

              <div className="device-card-actions">
                {device.status === 'streaming' ? (
                  <>
                    <button
                      className="btn btn-ghost"
                      onClick={() => handleStop(device.id)}
                    >
                      Stop
                    </button>
                    <button
                      className="btn btn-primary"
                      onClick={() => onDeviceSelect(device.id)}
                    >
                      Open Terminal →
                    </button>
                  </>
                ) : (
                  <>
                    <button
                      className="btn btn-ghost btn-sm"
                      onClick={() => handleAutoReconnect(device.id, !device.auto_reconnect)}
                      title={device.auto_reconnect ? 'Disable auto-reconnect' : 'Enable auto-reconnect'}
                    >
                      {device.auto_reconnect ? '⟳ Auto' : '⟳ Manual'}
                    </button>
                    <button
                      className="btn btn-primary"
                      onClick={() => handleStart(device.id)}
                      disabled={startingId === device.id}
                    >
                      {startingId === device.id ? 'Starting...' : 'Start Stream'}
                    </button>
                  </>
                )}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  )
}
