import { useState, useEffect, useCallback } from 'react'
import { ProtocolInfo, DecodedResult, listProtocols, decodeData } from '../api/protocols'
import './ProtocolDecoder.css'

interface Props {
  onDecoded?: (result: DecodedResult) => void
}

export default function ProtocolDecoder({ onDecoded }: Props) {
  const [protocols, setProtocols] = useState<ProtocolInfo[]>([])
  const [selectedProtocol, setSelectedProtocol] = useState('auto')
  const [rawInput, setRawInput] = useState('')
  const [result, setResult] = useState<DecodedResult | null>(null)
  const [decoding, setDecoding] = useState(false)
  const [history, setHistory] = useState<DecodedResult[]>([])

  useEffect(() => {
    listProtocols().then(res => setProtocols(res.decoders)).catch(() => {})
  }, [])

  const handleDecode = useCallback(async () => {
    if (!rawInput.trim()) return
    setDecoding(true)
    try {
      const res = await decodeData(rawInput.trim(), selectedProtocol)
      setResult(res)
      if (res.success) {
        setHistory(prev => [res, ...prev].slice(0, 20))
        onDecoded?.(res)
      }
    } catch {
      setResult({ success: false, protocol_id: '', protocol_name: '', decoded: {}, message: 'Decode failed' })
    } finally {
      setDecoding(false)
    }
  }, [rawInput, selectedProtocol, onDecoded])

  const formatDecoded = (obj: Record<string, any>, depth = 0): JSX.Element[] => {
    return Object.entries(obj).map(([key, value]) => {
      if (typeof value === 'object' && value !== null && !Array.isArray(value)) {
        return (
          <div key={key} className="decoded-nested" style={{ paddingLeft: depth * 16 }}>
            <span className="decoded-key">{key}</span>
            {formatDecoded(value, depth + 1)}
          </div>
        )
      }
      return (
        <div key={key} className="decoded-field" style={{ paddingLeft: depth * 16 }}>
          <span className="decoded-key">{key}</span>
          <span className="decoded-value">
            {Array.isArray(value) ? `[${value.join(', ')}]` : String(value)}
          </span>
        </div>
      )
    })
  }

  return (
    <div className="decoder-view">
      {/* Toolbar */}
      <div className="decoder-toolbar">
        <div className="decoder-controls">
          <select
            className="decoder-select"
            value={selectedProtocol}
            onChange={(e) => setSelectedProtocol(e.target.value)}
          >
            <option value="auto">Auto-detect</option>
            {protocols.map(p => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
          <div className="decoder-input-group">
            <input
              className="decoder-input"
              type="text"
              placeholder="Enter hex data (e.g. 48656C6C6F or 01 03 00 01)"
              value={rawInput}
              onChange={(e) => setRawInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleDecode()}
            />
            <button
              className="btn btn-primary"
              onClick={handleDecode}
              disabled={decoding || !rawInput.trim()}
            >
              {decoding ? 'Decoding...' : 'Decode'}
            </button>
          </div>
        </div>
      </div>

      {/* Result */}
      {result && (
        <div className={`decoder-result ${result.success ? 'success' : 'error'} animate-fade-in`}>
          {result.success ? (
            <>
              <div className="decoder-result-header">
                <span className="decoder-protocol-badge">{result.protocol_name}</span>
                <span className="decoder-protocol-id">{result.protocol_id}</span>
              </div>
              <div className="decoder-fields">
                {formatDecoded(result.decoded)}
              </div>
            </>
          ) : (
            <div className="decoder-error">
              <span className="decoder-error-icon">⚠</span>
              <span>{result.message || 'Failed to decode'}</span>
            </div>
          )}
        </div>
      )}

      {/* History */}
      {history.length > 0 && (
        <div className="decoder-history">
          <div className="decoder-history-header">
            <h3>Recent Decodes</h3>
            <button
              className="btn btn-ghost btn-sm"
              onClick={() => setHistory([])}
            >
              Clear
            </button>
          </div>
          <div className="decoder-history-list">
            {history.map((item, i) => (
              <div
                key={i}
                className="history-row"
                onClick={() => setResult(item)}
              >
                <span className="history-protocol">{item.protocol_name}</span>
                <span className="history-preview">
                  {Object.entries(item.decoded)
                    .slice(0, 2)
                    .map(([k, v]) => `${k}=${typeof v === 'object' ? '{...}' : v}`)
                    .join(', ')}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Protocol Reference */}
      <div className="decoder-reference">
        <h3>Available Protocols</h3>
        <div className="protocol-cards">
          {protocols.map(p => (
            <div
              key={p.id}
              className={`protocol-card ${selectedProtocol === p.id ? 'active' : ''}`}
              onClick={() => setSelectedProtocol(p.id)}
            >
              <span className="protocol-card-name">{p.name}</span>
              <span className="protocol-card-desc">{p.description}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
