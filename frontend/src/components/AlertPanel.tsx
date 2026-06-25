import { useState, useEffect, useCallback } from 'react'
import { AlertRule, AlertEvent, listAlertRules, listAlertEvents, createAlertRule, deleteAlertRule } from '../api/alerts'
import './AlertPanel.css'

interface Props {}

export default function AlertPanel({}: Props) {
  const [rules, setRules] = useState<AlertRule[]>([])
  const [events, setEvents] = useState<AlertEvent[]>([])
  const [loading, setLoading] = useState(true)
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState({
    name: '',
    metric: '',
    condition: 'gt' as 'gt' | 'lt' | 'eq' | 'range',
    threshold: 0,
    threshold_max: 0,
    device_id: '',
    cooldown: 60,
  })

  const fetchData = useCallback(async () => {
    try {
      const [rulesRes, eventsRes] = await Promise.all([
        listAlertRules(),
        listAlertEvents(),
      ])
      setRules(rulesRes.rules || [])
      setEvents(eventsRes.events || [])
    } catch {
      // silent
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchData()
    const interval = setInterval(fetchData, 10000)
    return () => clearInterval(interval)
  }, [fetchData])

  const handleCreateRule = async (e: React.FormEvent) => {
    e.preventDefault()
    try {
      await createAlertRule(form)
      setShowForm(false)
      setForm({ name: '', metric: '', condition: 'gt', threshold: 0, threshold_max: 0, device_id: '', cooldown: 60 })
      await fetchData()
    } catch {
      // silent
    }
  }

  const handleDeleteRule = async (id: string) => {
    try {
      await deleteAlertRule(id)
      await fetchData()
    } catch {
      // silent
    }
  }

  const getConditionLabel = (condition: string) => {
    switch (condition) {
      case 'gt': return '>'
      case 'lt': return '<'
      case 'eq': return '='
      case 'range': return '∈'
      default: return condition
    }
  }

  const getSeverityColor = (severity: string) => {
    switch (severity) {
      case 'critical': return 'var(--status-red)'
      case 'warning': return 'var(--status-yellow)'
      case 'info': return 'var(--status-blue)'
      default: return 'var(--text-tertiary)'
    }
  }

  if (loading) {
    return (
      <div className="alert-panel">
        <div className="loading-state">
          <div className="loading-spinner" />
          <span>Loading alerts...</span>
        </div>
      </div>
    )
  }

  return (
    <div className="alert-panel">
      {/* Rules Section */}
      <div className="alert-section">
        <div className="alert-section-header">
          <div>
            <h3 className="alert-section-title">Alert Rules</h3>
            <span className="alert-section-count">{rules.length} rule{rules.length !== 1 ? 's' : ''}</span>
          </div>
          <button
            className="btn btn-primary btn-sm"
            onClick={() => setShowForm(!showForm)}
          >
            {showForm ? 'Cancel' : '+ New Rule'}
          </button>
        </div>

        {showForm && (
          <form className="alert-form animate-fade-in" onSubmit={handleCreateRule}>
            <div className="form-row">
              <div className="form-group">
                <label className="form-label">Name</label>
                <input
                  className="form-input"
                  type="text"
                  placeholder="High temperature alert"
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  required
                />
              </div>
              <div className="form-group">
                <label className="form-label">Metric</label>
                <input
                  className="form-input"
                  type="text"
                  placeholder="TEMP"
                  value={form.metric}
                  onChange={(e) => setForm({ ...form, metric: e.target.value })}
                  required
                />
              </div>
            </div>
            <div className="form-row">
              <div className="form-group">
                <label className="form-label">Condition</label>
                <select
                  className="form-select"
                  value={form.condition}
                  onChange={(e) => setForm({ ...form, condition: e.target.value as any })}
                >
                  <option value="gt">Greater than (&gt;)</option>
                  <option value="lt">Less than (&lt;)</option>
                  <option value="eq">Equals (=)</option>
                  <option value="range">In range</option>
                </select>
              </div>
              <div className="form-group">
                <label className="form-label">Threshold</label>
                <input
                  className="form-input"
                  type="number"
                  step="any"
                  value={form.threshold}
                  onChange={(e) => setForm({ ...form, threshold: parseFloat(e.target.value) })}
                  required
                />
              </div>
              {form.condition === 'range' && (
                <div className="form-group">
                  <label className="form-label">Max</label>
                  <input
                    className="form-input"
                    type="number"
                    step="any"
                    value={form.threshold_max}
                    onChange={(e) => setForm({ ...form, threshold_max: parseFloat(e.target.value) })}
                    required
                  />
                </div>
              )}
              <div className="form-group">
                <label className="form-label">Cooldown (s)</label>
                <input
                  className="form-input"
                  type="number"
                  min="0"
                  value={form.cooldown}
                  onChange={(e) => setForm({ ...form, cooldown: parseInt(e.target.value) })}
                />
              </div>
            </div>
            <button type="submit" className="btn btn-primary">Create Rule</button>
          </form>
        )}

        {rules.length === 0 ? (
          <div className="alert-empty">
            <p>No alert rules configured</p>
            <span>Create a rule to get notified when metrics cross thresholds</span>
          </div>
        ) : (
          <div className="alert-rules-list">
            {rules.map((rule) => (
              <div key={rule.id} className="rule-card animate-fade-in">
                <div className="rule-card-left">
                  <span
                    className="rule-severity"
                    style={{ background: getSeverityColor(rule.severity || 'info') }}
                  />
                  <div className="rule-info">
                    <span className="rule-name">{rule.name}</span>
                    <span className="rule-expression">
                      {rule.metric} {getConditionLabel(rule.condition)}
                      {rule.condition === 'range'
                        ? ` ${rule.threshold} – ${rule.threshold_max}`
                        : ` ${rule.threshold}`}
                    </span>
                  </div>
                </div>
                <div className="rule-card-right">
                  <span className="rule-cooldown">{rule.cooldown}s cooldown</span>
                  <button
                    className="btn btn-ghost btn-icon"
                    onClick={() => handleDeleteRule(rule.id)}
                    title="Delete rule"
                  >
                    ✕
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Events Section */}
      <div className="alert-section">
        <div className="alert-section-header">
          <div>
            <h3 className="alert-section-title">Recent Events</h3>
            <span className="alert-section-count">{events.length} event{events.length !== 1 ? 's' : ''}</span>
          </div>
        </div>

        {events.length === 0 ? (
          <div className="alert-empty">
            <p>No events yet</p>
            <span>Alert events will appear here when rules are triggered</span>
          </div>
        ) : (
          <div className="alert-events-list">
            {events.slice(0, 20).map((event, i) => (
              <div key={i} className="event-row animate-slide-in">
                <span
                  className="event-severity-dot"
                  style={{ background: getSeverityColor(event.severity) }}
                />
                <span className="event-time">
                  {new Date(event.timestamp).toLocaleTimeString([], {
                    hour12: false,
                    hour: '2-digit',
                    minute: '2-digit',
                    second: '2-digit',
                  })}
                </span>
                <span className="event-message">{event.message}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
