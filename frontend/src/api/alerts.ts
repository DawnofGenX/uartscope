import { apiGet, apiPost, apiDelete } from './client'

export interface AlertRule {
  id: string
  name: string
  metric: string
  condition: 'gt' | 'lt' | 'eq' | 'range'
  threshold: number
  threshold_max: number
  device_id: string | null
  severity: 'info' | 'warning' | 'critical'
  cooldown: number
  enabled: boolean
  created_at: string
}

export interface AlertEvent {
  id: string
  rule_id: string
  message: string
  severity: 'info' | 'warning' | 'critical'
  timestamp: string
  acknowledged: boolean
}

export async function listAlertRules(): Promise<{ rules: AlertRule[] }> {
  return apiGet<{ rules: AlertRule[] }>('/api/alerts/rules')
}

export async function listAlertEvents(): Promise<{ events: AlertEvent[] }> {
  return apiGet<{ events: AlertEvent[] }>('/api/alerts/events')
}

export async function createAlertRule(data: {
  name: string
  metric: string
  condition: string
  threshold: number
  threshold_max: number
  device_id: string
  cooldown: number
}): Promise<AlertRule> {
  return apiPost<AlertRule>('/api/alerts/rules', data)
}

export async function deleteAlertRule(id: string): Promise<any> {
  return apiDelete(`/api/alerts/rules/${id}`)
}
