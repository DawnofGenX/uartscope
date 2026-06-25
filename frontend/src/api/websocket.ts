import { useEffect, useRef, useState, useCallback } from 'react';
import type { WsMessage } from '../types';

interface UseWebSocketOptions {
  onMessage: (msg: WsMessage) => void;
  subscribeTo?: string | 'all' | null;  // device_id or 'all'
}

export function useWebSocket({ onMessage, subscribeTo }: UseWebSocketOptions) {
  const wsRef = useRef<WebSocket | null>(null);
  const [connected, setConnected] = useState(false);
  const onMessageRef = useRef(onMessage);
  const subscribeToRef = useRef(subscribeTo);
  onMessageRef.current = onMessage;
  subscribeToRef.current = subscribeTo;

  const connect = useCallback(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(`${protocol}//${window.location.host}/api/ws/telemetry`);

    ws.onopen = () => {
      setConnected(true);
      console.log('WebSocket connected');
      // Subscribe after connection
      if (subscribeToRef.current === 'all') {
        ws.send(JSON.stringify({ type: 'subscribe_all' }));
      } else if (subscribeToRef.current) {
        ws.send(JSON.stringify({ type: 'subscribe_device', device_id: subscribeToRef.current }));
      }
    };

    ws.onclose = () => {
      setConnected(false);
      console.log('WebSocket disconnected');
      // Reconnect after 3s
      setTimeout(() => connect(), 3000);
    };

    ws.onerror = (err) => {
      console.error('WebSocket error:', err);
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data) as WsMessage;
        onMessageRef.current(msg);
      } catch (e) {
        console.error('Failed to parse WS message:', e);
      }
    };

    wsRef.current = ws;
  }, []);

  const send = useCallback((data: any) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(data));
    }
  }, []);

  const subscribe = useCallback((deviceId: string | 'all') => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      if (deviceId === 'all') {
        wsRef.current.send(JSON.stringify({ type: 'subscribe_all' }));
      } else {
        wsRef.current.send(JSON.stringify({ type: 'subscribe_device', device_id: deviceId }));
      }
    }
  }, []);

  useEffect(() => {
    connect();
    return () => {
      wsRef.current?.close();
    };
  }, [connect]);

  // Re-subscribe when subscribeTo changes
  useEffect(() => {
    if (connected && wsRef.current?.readyState === WebSocket.OPEN) {
      if (subscribeTo === 'all') {
        wsRef.current.send(JSON.stringify({ type: 'subscribe_all' }));
      } else if (subscribeTo) {
        wsRef.current.send(JSON.stringify({ type: 'subscribe_device', device_id: subscribeTo }));
      }
    }
  }, [subscribeTo, connected]);

  return { connected, send, subscribe };
}
