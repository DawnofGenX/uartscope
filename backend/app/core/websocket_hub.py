"""WebSocket broadcast hub for real-time data distribution.

Supports:
- Global broadcast (all clients)
- Per-device subscriptions (only receive data from specific device)
- Per-client targeted messages
"""
import asyncio
import json
import logging
from datetime import datetime
from typing import Set, Dict, Optional
from enum import Enum

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class SubscriptionMode(str, Enum):
    ALL = "all"           # Receive data from all devices
    DEVICE = "device"     # Receive data from specific device
    NONE = "none"         # Receive only control messages


class ClientState:
    """Track per-client subscription state."""
    def __init__(self, websocket: WebSocket):
        self.websocket = websocket
        self.mode = SubscriptionMode.ALL
        self.device_id: Optional[str] = None

    def matches(self, device_id: str) -> bool:
        """Check if this client should receive data from a given device."""
        if self.mode == SubscriptionMode.NONE:
            return False
        if self.mode == SubscriptionMode.ALL:
            return True
        return self.device_id == device_id


class ConnectionManager:
    """Manages WebSocket connections for real-time telemetry streaming."""

    def __init__(self):
        self._connections: Dict[WebSocket, ClientState] = {}
        self._lock = asyncio.Lock()

    @property
    def count(self) -> int:
        return len(self._connections)

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        async with self._lock:
            self._connections[websocket] = ClientState(websocket)
        logger.info(f"WebSocket connected. Total: {len(self._connections)}")

    async def disconnect(self, websocket: WebSocket):
        async with self._lock:
            self._connections.pop(websocket, None)
        logger.info(f"WebSocket disconnected. Total: {len(self._connections)}")

    async def set_subscription(
        self,
        websocket: WebSocket,
        mode: SubscriptionMode,
        device_id: Optional[str] = None,
    ):
        """Set a client's subscription mode."""
        async with self._lock:
            state = self._connections.get(websocket)
            if state:
                state.mode = mode
                state.device_id = device_id

    async def broadcast(self, message: Dict, device_id: Optional[str] = None):
        """Broadcast a message to relevant clients based on subscription."""
        message.setdefault("timestamp", datetime.utcnow().isoformat())
        disconnected = []

        for ws, state in self._connections.items():
            # If device_id is provided, filter by subscription
            if device_id and not state.matches(device_id):
                continue

            try:
                await ws.send_json(message)
            except Exception:
                disconnected.append(ws)

        # Clean up failed connections
        for ws in disconnected:
            await self.disconnect(ws)

    async def broadcast_to_all(self, message: Dict):
        """Broadcast to ALL connected clients regardless of subscription."""
        message.setdefault("timestamp", datetime.utcnow().isoformat())
        disconnected = []

        for ws in list(self._connections.keys()):
            try:
                await ws.send_json(message)
            except Exception:
                disconnected.append(ws)

        for ws in disconnected:
            await self.disconnect(ws)

    async def send_to(self, websocket: WebSocket, message: Dict):
        """Send a message to a specific client."""
        try:
            await websocket.send_json(message)
        except Exception:
            await self.disconnect(websocket)

    def get_client_state(self, websocket: WebSocket) -> Optional[ClientState]:
        return self._connections.get(websocket)

    def get_subscription_info(self) -> Dict:
        """Get summary of current subscriptions."""
        info = {"total": len(self._connections), "devices": {}}
        for state in self._connections.values():
            if state.mode == SubscriptionMode.DEVICE and state.device_id:
                info["devices"][state.device_id] = (
                    info["devices"].get(state.device_id, 0) + 1
                )
        return info


ws_manager = ConnectionManager()
