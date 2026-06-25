import { useState } from 'react';
import { useWebSocket } from './api/websocket';
import { DevicePanel } from './components/DevicePanel';
import { TerminalView } from './components/TerminalView';
import { LiveChart } from './components/LiveChart';
import { AlertPanel } from './components/AlertPanel';
import type { WsMessage } from './types';
import { Activity, Cpu, AlertTriangle, Terminal, BarChart3, Settings } from 'lucide-react';

type Tab = 'dashboard' | 'terminal' | 'charts' | 'alerts';

export default function App() {
  const [activeTab, setActiveTab] = useState<Tab>('dashboard');
  const [messages, setMessages] = useState<string[]>([]);
  const [metrics, setMetrics] = useState<Record<string, { x: number; y: number }[]>>({});
  const [alerts, setAlerts] = useState<any[]>([]);
  const [connected, setConnected] = useState(false);

  const handleMessage = (msg: WsMessage) => {
    if (msg.type === 'serial_data' || msg.type === 'test_data') {
      setMessages(prev => [...prev.slice(-500), msg.data as string]);
    } else if (msg.type === 'metric' && msg.metric_name !== undefined) {
      const name = msg.metric_name;
      const point = { x: Date.now(), y: msg.value! };
      setMetrics(prev => ({
        ...prev,
        [name]: [...(prev[name] || []).slice(-500), point],
      }));
    } else if (msg.type === 'alert') {
      setAlerts(prev => [msg, ...prev].slice(0, 100));
    }
  };

  const { connected: wsConnected, send } = useWebSocket(handleMessage);

  return (
    <div className="flex h-screen flex-col">
      {/* Header */}
      <header className="flex items-center justify-between border-b border-slate-700 bg-slate-900 px-4 py-3">
        <div className="flex items-center gap-2">
          <Activity className="h-6 w-6 text-emerald-400" />
          <h1 className="text-lg font-bold text-white">UARTScope Pro</h1>
          <span className="rounded bg-slate-700 px-2 py-0.5 text-xs text-slate-300">v0.1.0</span>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5">
            <div className={`h-2 w-2 rounded-full ${wsConnected ? 'bg-emerald-400' : 'bg-red-400'}`} />
            <span className="text-xs text-slate-400">{wsConnected ? 'Connected' : 'Disconnected'}</span>
          </div>
          <Settings className="h-5 w-5 cursor-pointer text-slate-400 hover:text-white" />
        </div>
      </header>

      {/* Main Content */}
      <div className="flex flex-1 overflow-hidden">
        {/* Sidebar */}
        <aside className="flex w-16 flex-col items-center gap-2 border-r border-slate-700 bg-slate-900 py-4">
          <TabButton icon={<Cpu />} label="Devices" active={activeTab === 'dashboard'} onClick={() => setActiveTab('dashboard')} />
          <TabButton icon={<Terminal />} label="Terminal" active={activeTab === 'terminal'} onClick={() => setActiveTab('terminal')} />
          <TabButton icon={<BarChart3 />} label="Charts" active={activeTab === 'charts'} onClick={() => setActiveTab('charts')} />
          <TabButton icon={<AlertTriangle />} label="Alerts" active={activeTab === 'alerts'} onClick={() => setActiveTab('alerts')} badge={alerts.length} />
        </aside>

        {/* Content Area */}
        <main className="flex flex-1 overflow-hidden">
          {activeTab === 'dashboard' && (
            <div className="flex flex-1 overflow-hidden">
              <div className="w-72 border-r border-slate-700 overflow-y-auto">
                <DevicePanel />
              </div>
              <div className="flex flex-1 flex-col overflow-hidden">
              <div className="flex-1 border-b border-slate-700 overflow-hidden">
                <TerminalView messages={messages} />
              </div>
              <div className="h-64 overflow-hidden">
                <LiveChart metrics={metrics} />
              </div>
            </div>
          </div>
          )}

          {activeTab === 'terminal' && (
            <div className="flex-1 overflow-hidden p-4">
              <TerminalView messages={messages} fullHeight />
            </div>
          )}

          {activeTab === 'charts' && (
            <div className="flex-1 overflow-hidden p-4">
              <LiveChart metrics={metrics} fullHeight />
            </div>
          )}

          {activeTab === 'alerts' && (
            <div className="flex-1 overflow-hidden p-4">
              <AlertPanel alerts={alerts} />
            </div>
          )}
        </main>
      </div>
    </div>
  );
}

function TabButton({ icon, label, active, onClick, badge }: { icon: React.ReactNode; label: string; active: boolean; onClick: () => void; badge?: number }) {
  return (
    <button
      onClick={onClick}
      className={`relative flex w-12 flex-col items-center gap-1 rounded-lg px-2 py-2 transition-colors ${
        active ? 'bg-emerald-600/20 text-emerald-400' : 'text-slate-400 hover:bg-slate-800 hover:text-white'
      }`}
      title={label}
    >
      {icon}
      <span className="text-[10px]">{label}</span>
      {badge ? (
        <span className="absolute -right-1 -top-1 flex h-4 w-4 items-center justify-center rounded-full bg-red-500 text-[9px] text-white">
          {badge > 9 ? '9+' : badge}
        </span>
      ) : null}
    </button>
  );
}
