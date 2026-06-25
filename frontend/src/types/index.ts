export interface Device {
  id: string;
  name?: string;
  port: string;
  protocol: string;
  baudrate: number;
  status: 'disconnected' | 'connected' | 'detected' | 'error' | 'streaming';
  board_type?: string;
  metadata_json?: Record<string, any>;
  created_at: string;
  last_seen?: string;
}

export interface TelemetryPoint {
  timestamp: string;
  metric_name: string;
  value: number;
  unit?: string;
  message_type: string;
}

export interface AlertRule {
  id: string;
  name: string;
  metric_name: string;
  condition: string;
  threshold: number;
  secondary_threshold?: number;
  cooldown: number;
  severity: string;
  enabled: boolean;
  trigger_count?: number;
}

export interface Session {
  id: string;
  name?: string;
  device_id?: string;
  started_at: string;
  ended_at?: string;
  status: string;
  packet_count: number;
}

export interface WsMessage {
  type: string;
  data?: any;
  timestamp?: string;
  device_id?: string;
  metric_name?: string;
  value?: number;
  unit?: string;
}
