import { useState, useEffect, useRef } from 'react'
import { TerminalLine, connectTerminal, fetchHistory } from '../api/terminal'
import './TerminalView.css'

interface Props {
  deviceId: string | null
}

export default function TerminalView({ deviceId }: Props) {
  const [lines, setLines] = useState<TerminalLine[]>([])
  const [connected, setConnected] = useState(false)
  const termRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!deviceId) return

    setLines([])
    
    const cleanup = connectTerminal(deviceId, (line) => {
      setLines((prev) => {
        const updated = [...prev, line]
        // Keep last 500 lines for performance
        if (updated.length > 500) return updated.slice(-500)
        return updated
      })
    })

    setConnected(true)

    return () => {
      cleanup()
      setConnected(false)
    }
  }, [deviceId])

  useEffect(() => {
    if (termRef.current) {
      termRef.current.scrollTop = termRef.current.scrollHeight
    }
  }, [lines])

  if (!deviceId) {
    return (
      <div className="terminal-view">
        <div className="empty-state">
          <div className="empty-icon">▸</div>
          <h3>No device selected</h3>
          <p>Select a device from the Devices view to see its output</p>
        </div>
      </div>
    )
  }

  return (
    <div className="terminal-view">
      <div className="terminal-toolbar">
        <div className="terminal-toolbar-left">
          <span className={`terminal-dot ${connected ? 'live' : ''}`} />
          <span className="terminal-device-id">Device {deviceId.slice(0, 8)}</span>
          <span className="terminal-sep">·</span>
          <span className="terminal-status">
            {connected ? `${lines.length} lines` : 'Disconnected'}
          </span>
        </div>
        <div className="terminal-toolbar-right">
          <button
            className="terminal-btn"
            onClick={() => setLines([])}
            title="Clear terminal"
          >
            Clear
          </button>
          <button
            className="terminal-btn"
            onClick={() => {
              if (termRef.current) {
                termRef.current.scrollTop = termRef.current.scrollHeight
              }
            }}
            title="Scroll to bottom"
          >
            Bottom ↓
          </button>
        </div>
      </div>

      <div className="terminal-container" ref={termRef}>
        {lines.length === 0 && connected && (
          <div className="terminal-waiting">
            <div className="loading-spinner" />
            <span>Waiting for data...</span>
          </div>
        )}
        
        {lines.map((line, i) => (
          <div key={i} className={`terminal-line ${line.type}`}>
            <span className="terminal-time">{line.timestamp}</span>
            <span className="terminal-content">{line.content}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
