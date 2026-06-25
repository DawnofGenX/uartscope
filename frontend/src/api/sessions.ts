import { apiGet, apiPost, apiPut } from './client'

export interface SessionSummary {
  id: string
  name: string
  device_id: string | null
  started_at: string
  ended_at: string | null
  status: 'recording' | 'completed'
  packet_count: number
  metric_count: number
  event_count: number
}

export interface SessionPacket {
  device_id: string
  raw: string
  ts: string
}

export interface SessionMetric {
  metric_name: string
  value: number
  unit?: string
  ts: string
}

export interface SessionEvent {
  type: string
  message?: string
  ts: string
}

export interface SessionDetail {
  id: string
  device_id: string | null
  name: string
  started_at: string
  ended_at: string | null
  packets: SessionPacket[]
  metrics: SessionMetric[]
  events: SessionEvent[]
}

export async function listSessions(): Promise<{ sessions: SessionSummary[] }> {
  return apiGet<{ sessions: SessionSummary[] }>('/api/sessions/')
}

export async function getSession(id: string): Promise<SessionDetail> {
  return apiGet<SessionDetail>(`/api/sessions/${id}`)
}

export async function getSessionInfo(id: string): Promise<SessionSummary> {
  return apiGet<SessionSummary>(`/api/sessions/${id}/info`)
}

export async function startSession(deviceId: string | null, name?: string): Promise<{ id: string; status: string }> {
  return apiPost('/api/sessions/', { device_id: deviceId, name })
}

export async function stopSession(id: string): Promise<{ id: string; status: string }> {
  return apiPost(`/api/sessions/${id}/stop`, {})
}

export async function renameSession(id: string, name: string): Promise<any> {
  return apiPut(`/api/sessions/${id}/rename`, { name })
}

export async function getSessionPackets(id: string, limit = 1000): Promise<SessionPacket[]> {
  return apiGet<SessionPacket[]>(`/api/sessions/${id}/packets?limit=${limit}`)
}

export async function getSessionMetrics(id: string, limit = 1000): Promise<SessionMetric[]> {
  return apiGet<SessionMetric[]>(`/api/sessions/${id}/metrics?limit=${limit}`)
}

export async function getSessionEvents(id: string, limit = 1000): Promise<SessionEvent[]> {
  return apiGet<SessionEvent[]>(`/api/sessions/${id}/events?limit=${limit}`)
}
