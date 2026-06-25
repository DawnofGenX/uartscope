"""WebSocket broadcast hub for real-time data distribution."""
import asyncio
import json
import logging
from datetime import datetime
from typing import Set, Dict, Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages WebSocket connections for real-time telemetry streaming."""

    def __init__(self):
        self._connections: Set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)
        logger.info(f"WebSocket connected. Total: {len(self._connections)}")

    async def disconnect(self, websocket: WebSocket):
        async with self._lock:
            self._connections.discard(websocket)
        logger.info(f"WebSocket disconnected. Total: {len(self._connections)}")

    async def broadcast(self, message: Dict[str, Any]):
        """Broadcast a message to all connected clients."""
        message.setdefault("timestamp", datetime.utcnow().isoformat())
        disconnected = []
        for ws in self._connections:
            try:
                await ws.send_json(message)
            except Exception:
                disconnected.append(ws)
        # Clean up failed connections
        for ws in disconnected:
            await self.disconnect(ws)

    async def send_to(self, websocket: WebSocket, message: Dict[str, Any]):
        """Send a message to a specific client."""
        try:
            await ws.send_json(message)
        except Exception:
            await self.disconnect(websocket)


ws_manager = ConnectionManager()
