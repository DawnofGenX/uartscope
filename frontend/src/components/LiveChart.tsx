import { useMemo } from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import { BarChart3 } from 'lucide-react';

interface LiveChartProps {
  metrics: Record<string, { x: number; y: number }[]>;
  fullHeight?: boolean;
}

const COLORS = ['#10b981', '#3b82f6', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899', '#06b6d4', '#f97316'];

export function LiveChart({ metrics, fullHeight }: LiveChartProps) {
  const metricNames = Object.keys(metrics);

  const chartData = useMemo(() => {
    if (metricNames.length === 0) return [];
    // Merge all metrics into a single dataset for the chart
    const allPoints: Record<string, any>[] = [];
    const maxLength = Math.max(...metricNames.map(n => metrics[n].length));
    for (let i = 0; i < maxLength; i++) {
      const point: Record<string, any> = { time: metrics[metricNames[0]]?.[i]?.x || Date.now() };
      metricNames.forEach(name => {
        point[name] = metrics[name]?.[i]?.y ?? null;
      });
      allPoints.push(point);
    }
    return allPoints;
  }, [metrics, metricNames]);

  if (metricNames.length === 0) {
    return (
      <div className={`flex h-full flex-col items-center justify-center bg-slate-900 ${fullHeight ? 'rounded-lg' : ''}`}>
        <BarChart3 className="mb-2 h-8 w-8 text-slate-600" />
        <p className="text-sm text-slate-500">No telemetry data yet</p>
        <p className="text-xs text-slate-600">Connect a device to start seeing live charts</p>
      </div>
    );
  }

  return (
    <div className={`flex h-full flex-col bg-slate-900 ${fullHeight ? 'rounded-lg' : ''}`}>
      <div className="flex items-center justify-between border-b border-slate-700 px-3 py-2">
        <div className="flex items-center gap-2">
          <BarChart3 className="h-4 w-4 text-emerald-400" />
          <span className="text-xs font-medium text-slate-300">Live Telemetry</span>
        </div>
        <div className="flex gap-2">
          {metricNames.map((name, i) => (
            <span key={name} className="flex items-center gap-1 text-[10px] text-slate-400">
              <span className="h-2 w-2 rounded-full" style={{ backgroundColor: COLORS[i % COLORS.length] }} />
              {name}
            </span>
          ))}
        </div>
      </div>
      <div className="flex-1 p-2">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
            <XAxis
              dataKey="time"
              tickFormatter={(t) => new Date(t).toLocaleTimeString()}
              stroke="#64748b"
              fontSize={10}
            />
            <YAxis stroke="#64748b" fontSize={10} />
            <Tooltip
              contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: 8 }}
              labelFormatter={(t) => new Date(t).toLocaleTimeString()}
            />
            {metricNames.map((name, i) => (
              <Line
                key={name}
                type="monotone"
                dataKey={name}
                stroke={COLORS[i % COLORS.length]}
                dot={false}
                strokeWidth={2}
                isAnimationActive={false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
