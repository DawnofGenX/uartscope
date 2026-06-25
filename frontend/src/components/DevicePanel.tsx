import { useState, useEffect } from 'react';
import { apiGet, apiPost } from '../api/client';
import type { Device } from '../types';
import { Usb, Play, Square, Trash2, RefreshCw } from 'lucide-react';

export function DevicePanel() {
  const [devices, setDevices] = useState<Device[]>([]);
  const [detected, setDetected] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);

  const fetchDevices = async () => {
    try {
      const data = await apiGet<Device[]>('/api/devices/');
      setDevices(data);
    } catch (e) {
      console.error('Failed to fetch devices:', e);
    }
  };

  const fetchDetected = async () => {
    setLoading(true);
    try {
      const data = await apiGet<{ devices: any[] }>('/api/devices/detect');
      setDetected(data.devices);
    } catch (e) {
      console.error('Failed to detect devices:', e);
    }
    setLoading(false);
  };

  const addDevice = async (port: string, name?: string) => {
    try {
      await apiPost('/api/devices/', { port, name: name || port, baudrate: 115200 });
      fetchDevices();
    } catch (e) {
      console.error('Failed to add device:', e);
    }
  };

  const connectDevice = async (id: string) => {
    try {
      await apiPost(`/api/devices/${id}/start`, {});
      fetchDevices();
    } catch (e) {
      console.error('Failed to connect:', e);
    }
  };

  const disconnectDevice = async (id: string) => {
    try {
      await apiPost(`/api/devices/${id}/stop`, {});
      fetchDevices();
    } catch (e) {
      console.error('Failed to disconnect:', e);
    }
  };

  const removeDevice = async (id: string) => {
    try {
      await fetch(`/api/devices/${id}`, { method: 'DELETE' });
      fetchDevices();
    } catch (e) {
      console.error('Failed to remove:', e);
    }
  };

  useEffect(() => {
    fetchDevices();
    fetchDetected();
  }, []);

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-slate-700 p-3">
        <h2 className="text-sm font-semibold text-white">Devices</h2>
        <button onClick={fetchDetected} disabled={loading} className="rounded p-1 text-slate-400 hover:bg-slate-700 hover:text-white disabled:opacity-50">
          <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {/* Detected Ports */}
      {detected.length > 0 && (
        <div className="border-b border-slate-700 p-3">
          <h3 className="mb-2 text-xs font-medium uppercase text-slate-500">Auto-Detected</h3>
          <div className="space-y-1">
            {detected.map((d) => (
              <div key={d.port} className="flex items-center justify-between rounded bg-slate-800 px-2 py-1.5">
                <div className="flex items-center gap-2 overflow-hidden">
                  <Usb className="h-3 w-3 text-emerald-400 shrink-0" />
                  <div className="truncate">
                    <div className="truncate text-xs text-white">{d.port}</div>
                    <div className="truncate text-[10px] text-slate-400">{d.board_type}</div>
                  </div>
                </div>
                <button onClick={() => addDevice(d.port, d.board_type)} className="shrink-0 rounded bg-emerald-600 px-2 py-0.5 text-[10px] text-white hover:bg-emerald-500">
                  Add
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Registered Devices */}
      <div className="flex-1 overflow-y-auto p-3">
        {devices.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-8 text-center text-slate-500">
            <Usb className="mb-2 h-8 w-8 opacity-50" />
            <p className="text-xs">No devices registered</p>
            <p className="text-[10px]">Click refresh to auto-detect</p>
          </div>
        ) : (
          <div className="space-y-2">
            {devices.map((device) => (
              <div key={device.id} className="rounded-lg bg-slate-800 p-3">
                <div className="mb-2 flex items-center justify-between">
                  <span className="text-xs font-medium text-white truncate">{device.name || device.port}</span>
                  <span className={`h-2 w-2 rounded-full ${
                    device.status === 'connected' || device.status === 'streaming' ? 'bg-emerald-400' :
                    device.status === 'error' ? 'bg-red-400' : 'bg-slate-500'
                  }`} />
                </div>
                <div className="mb-2 text-[10px] text-slate-400">
                  {device.port} @ {device.baudrate} baud • {device.board_type || 'Unknown'}
                </div>
                <div className="flex gap-1">
                  {device.status !== 'connected' && device.status !== 'streaming' ? (
                    <button onClick={() => connectDevice(device.id)} className="flex items-center gap-1 rounded bg-emerald-600 px-2 py-1 text-[10px] text-white hover:bg-emerald-500">
                      <Play className="h-3 w-3" /> Start
                    </button>
                  ) : (
                    <button onClick={() => disconnectDevice(device.id)} className="flex items-center gap-1 rounded bg-red-600 px-2 py-1 text-[10px] text-white hover:bg-red-500">
                      <Square className="h-3 w-3" /> Stop
                    </button>
                  )}
                  <button onClick={() => removeDevice(device.id)} className="flex items-center gap-1 rounded bg-slate-700 px-2 py-1 text-[10px] text-slate-300 hover:bg-slate-600">
                    <Trash2 className="h-3 w-3" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
