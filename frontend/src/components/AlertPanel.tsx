import { useEffect, useState } from 'react';
import { apiGet, apiPost } from '../api/client';
import type { AlertRule } from '../types';
import { AlertTriangle, Bell, Plus, Trash2 } from 'lucide-react';

interface AlertPanelProps {
  alerts: any[];
}

export function AlertPanel({ alerts }: AlertPanelProps) {
  const [rules, setRules] = useState<AlertRule[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ name: '', metric_name: 'TEMP', condition: 'gt', threshold: 0, severity: 'warning' });

  const fetchRules = async () => {
    try {
      const data = await apiGet<AlertRule[]>('/api/alerts/rules');
      setRules(data);
    } catch (e) {
      console.error('Failed to fetch rules:', e);
    }
  };

  const createRule = async () => {
    try {
      await apiPost('/api/alerts/rules', form);
      setShowForm(false);
      setForm({ name: '', metric_name: 'TEMP', condition: 'gt', threshold: 0, severity: 'warning' });
      fetchRules();
    } catch (e) {
      console.error('Failed to create rule:', e);
    }
  };

  const deleteRule = async (id: string) => {
    try {
      await fetch(`/api/alerts/rules/${id}`, { method: 'DELETE' });
      fetchRules();
    } catch (e) {
      console.error('Failed to delete rule:', e);
    }
  };

  useEffect(() => { fetchRules(); }, []);

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="flex items-center justify-between border-b border-slate-700 p-3">
        <h2 className="text-sm font-semibold text-white">Alerts & Rules</h2>
        <button onClick={() => setShowForm(!showForm)} className="flex items-center gap-1 rounded bg-emerald-600 px-2 py-1 text-xs text-white hover:bg-emerald-500">
          <Plus className="h-3 w-3" /> Add Rule
        </button>
      </div>

      {showForm && (
        <div className="border-b border-slate-700 bg-slate-800 p-3">
          <div className="grid grid-cols-2 gap-2">
            <input
              type="text"
              placeholder="Rule name"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              className="rounded bg-slate-700 px-2 py-1 text-xs text-white placeholder-slate-400 outline-none"
            />
            <input
              type="text"
              placeholder="Metric (e.g. TEMP)"
              value={form.metric_name}
              onChange={(e) => setForm({ ...form, metric_name: e.target.value })}
              className="rounded bg-slate-700 px-2 py-1 text-xs text-white placeholder-slate-400 outline-none"
            />
            <select
              value={form.condition}
              onChange={(e) => setForm({ ...form, condition: e.target.value })}
              className="rounded bg-slate-700 px-2 py-1 text-xs text-white outline-none"
            >
              <option value="gt">Greater than (&gt;)</option>
              <option value="lt">Less than (&lt;)</option>
              <option value="gte">≥</option>
              <option value="lte">≤</option>
              <option value="range">Outside range</option>
            </select>
            <input
              type="number"
              placeholder="Threshold"
              value={form.threshold}
              onChange={(e) => setForm({ ...form, threshold: parseFloat(e.target.value) || 0 })}
              className="rounded bg-slate-700 px-2 py-1 text-xs text-white placeholder-slate-400 outline-none"
            />
            <select
              value={form.severity}
              onChange={(e) => setForm({ ...form, severity: e.target.value })}
              className="rounded bg-slate-700 px-2 py-1 text-xs text-white outline-none"
            >
              <option value="info">Info</option>
              <option value="warning">Warning</option>
              <option value="critical">Critical</option>
            </select>
            <button onClick={createRule} className="rounded bg-emerald-600 px-3 py-1 text-xs text-white hover:bg-emerald-500">
              Create
            </button>
          </div>
        </div>
      )}

      <div className="flex-1 overflow-y-auto p-3">
        {/* Active Rules */}
        <div className="mb-4">
          <h3 className="mb-2 text-xs font-medium uppercase text-slate-500">Alert Rules ({rules.length})</h3>
          {rules.length === 0 ? (
            <p className="text-xs text-slate-500">No rules configured</p>
          ) : (
            <div className="space-y-1">
              {rules.map((rule) => (
                <div key={rule.id} className="flex items-center justify-between rounded bg-slate-800 px-3 py-2">
                  <div>
                    <div className="text-xs text-white">{rule.name}</div>
                    <div className="text-[10px] text-slate-400">
                      {rule.metric_name} {rule.condition} {rule.threshold} • {rule.severity}
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    {rule.trigger_count ? (
                      <span className="rounded bg-amber-600 px-1.5 py-0.5 text-[9px] text-white">{rule.trigger_count} triggers</span>
                    ) : null}
                    <button onClick={() => deleteRule(rule.id)} className="text-slate-400 hover:text-red-400">
                      <Trash2 className="h-3 w-3" />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Recent Alerts */}
        <div>
          <h3 className="mb-2 text-xs font-medium uppercase text-slate-500">Recent Alerts ({alerts.length})</h3>
          {alerts.length === 0 ? (
            <div className="flex flex-col items-center py-6 text-slate-500">
              <Bell className="mb-2 h-6 w-6 opacity-50" />
              <p className="text-xs">No alerts triggered</p>
            </div>
          ) : (
            <div className="space-y-1">
              {alerts.slice(0, 20).map((alert, i) => (
                <div key={i} className={`rounded px-3 py-2 text-xs ${
                  alert.severity === 'critical' ? 'bg-red-900/30 border border-red-800' :
                  alert.severity === 'warning' ? 'bg-amber-900/30 border border-amber-800' :
                  'bg-blue-900/30 border border-blue-800'
                }`}>
                  <div className="flex items-center gap-2">
                    <AlertTriangle className={`h-3 w-3 ${
                      alert.severity === 'critical' ? 'text-red-400' :
                      alert.severity === 'warning' ? 'text-amber-400' : 'text-blue-400'
                    }`} />
                    <span className="font-medium text-white">{alert.rule_name || alert.message}</span>
                  </div>
                  <div className="mt-1 text-[10px] text-slate-400">
                    {alert.metric_name}: {alert.value} • {new Date(alert.timestamp).toLocaleTimeString()}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
