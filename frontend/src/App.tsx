import { useState, useCallback } from 'react'
import DevicePanel from './components/DevicePanel'
import TerminalView from './components/TerminalView'
import LiveChart from './components/LiveChart'
import AlertPanel from './components/AlertPanel'
import './styles/app.css'

type View = 'devices' | 'terminal' | 'charts' | 'alerts'

interface Stats {
  total_devices: number
  connected_devices: number
  streaming_devices: number
  total_bytes: number
  total_packets: number
  uptime_seconds: number
  ws_clients: number
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function formatUptime(seconds: number): string {
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = seconds % 60
  if (h > 0) return `${h}h ${m}m`
  if (m > 0) return `${m}m ${s}s`
  return `${s}s`
}

export default function App() {
  const [view, setView] = useState<View>('devices')
  const [selectedDeviceId, setSelectedDeviceId] = useState<string | null>(null)
  const [stats, setStats] = useState<Stats>({
    total_devices: 0,
    connected_devices: 0,
    streaming_devices: 0,
    total_bytes: 0,
    total_packets: 0,
    uptime_seconds: 0,
    ws_clients: 0,
  })

  const handleStatsUpdate = useCallback((newStats: Stats) => {
    setStats(newStats)
  }, [])

  const navItems: { id: View; label: string; icon: string }[] = [
    { id: 'devices', label: 'Devices', icon: '◈' },
    { id: 'terminal', label: 'Terminal', icon: '▸' },
    { id: 'charts', label: 'Charts', icon: '◇' },
    { id: 'alerts', label: 'Alerts', icon: '◉' },
  ]

  return (
    <div className="app">
      {/* Sidebar */}
      <aside className="sidebar">
        <div className="sidebar-header">
          <div className="logo">
            <span className="logo-icon">◈</span>
            <span className="logo-text">UARTScope</span>
          </div>
        </div>

        <nav className="sidebar-nav">
          {navItems.map((item) => (
            <button
              key={item.id}
              className={`nav-item ${view === item.id ? 'active' : ''}`}
              onClick={() => setView(item.id)}
            >
              <span className="nav-icon">{item.icon}</span>
              <span className="nav-label">{item.label}</span>
              {item.id === 'alerts' && (
                <span className="nav-badge">3</span>
              )}
            </button>
          ))}
        </nav>

        <div className="sidebar-footer">
          <div className="stats-grid">
            <div className="stat-item">
              <span className="stat-value">{stats.connected_devices}/{stats.total_devices}</span>
              <span className="stat-label">Devices</span>
            </div>
            <div className="stat-item">
              <span className="stat-value">{formatBytes(stats.total_bytes)}</span>
              <span className="stat-label">Data</span>
            </div>
            <div className="stat-item">
              <span className="stat-value">{stats.ws_clients}</span>
              <span className="stat-label">Clients</span>
            </div>
            <div className="stat-item">
              <span className="stat-value">{formatUptime(stats.uptime_seconds)}</span>
              <span className="stat-label">Uptime</span>
            </div>
          </div>
        </div>
      </aside>

      {/* Main Content */}
      <main className="main-content">
        {/* Top Bar */}
        <header className="top-bar">
          <div className="top-bar-left">
            <h1 className="page-title">
              {navItems.find(n => n.id === view)?.label}
            </h1>
            <span className="page-subtitle">
              {view === 'devices' && `${stats.total_devices} registered`}
              {view === 'terminal' && (selectedDeviceId ? `Device ${selectedDeviceId.slice(0, 8)}` : 'Select a device')}
              {view === 'charts' && 'Real-time telemetry'}
              {view === 'alerts' && 'Rule-based monitoring'}
            </span>
          </div>
          <div className="top-bar-right">
            <div className="status-indicator">
              <span className={`status-dot ${stats.connected_devices > 0 ? 'live' : ''}`} />
              <span className="status-text">
                {stats.connected_devices > 0 ? `${stats.streaming_devices} streaming` : 'No devices'}
              </span>
            </div>
          </div>
        </header>

        {/* View Content */}
        <div className="content-area animate-fade-in">
          {view === 'devices' && (
            <DevicePanel
              onDeviceSelect={(id) => {
                setSelectedDeviceId(id)
                setView('terminal')
              }}
              onStatsUpdate={handleStatsUpdate}
            />
          )}
          {view === 'terminal' && (
            <TerminalView deviceId={selectedDeviceId} />
          )}
          {view === 'charts' && (
            <LiveChart deviceId={selectedDeviceId} />
          )}
          {view === 'alerts' && (
            <AlertPanel />
          )}
        </div>
      </main>
    </div>
  )
}
