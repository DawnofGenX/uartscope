import { apiGet, apiPost, apiPut, apiDelete } from './client'

export interface Device {
  id: string
  name: string
  port: string
  baud_rate: number
  status: 'connected' | 'disconnected' | 'streaming'
  board_type: string | null
  auto_reconnect: boolean
  created_at: string
}

export interface DeviceListResponse {
  devices: Device[]
  stats?: {
    total_devices: number
    connected_devices: number
    streaming_devices: number
    total_bytes: number
    total_packets: number
    uptime_seconds: number
    ws_clients: number
  }
}

export async function listDevices(): Promise<DeviceListResponse> {
  return apiGet<DeviceListResponse>('/api/devices/')
}

export async function getDevice(id: string): Promise<Device> {
  return apiGet<Device>(`/api/devices/${id}`)
}

export async function startStream(id: string): Promise<any> {
  return apiPost(`/api/devices/${id}/stream`, {})
}

export async function stopStream(id: string): Promise<any> {
  return apiPost(`/api/devices/${id}/stop`, {})
}

export async function toggleAutoReconnect(id: string, enabled: boolean): Promise<any> {
  return apiPut(`/api/devices/${id}/auto-reconnect`, { enabled })
}

export async function getDeviceStats(id: string): Promise<any> {
  return apiGet(`/api/devices/${id}/stats`)
}
