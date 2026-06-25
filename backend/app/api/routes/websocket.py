"""WebSocket real-time telemetry stream."""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import asyncio
import json
import logging

from app.core.device_manager import device_manager
from app.core.telemetry_engine import telemetry_engine
from app.core.serial_reader import serial_reader
from app.core.alert_engine import alert_engine
from app.core.protocol_decoder import protocol_manager
from app.core.session_recorder import session_recorder
from app.core.websocket_hub import ws_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ws", tags=["websocket"])


async def handle_websocket(websocket: WebSocket):
    """Handle a WebSocket connection for real-time telemetry."""
    await ws_manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")

            if msg_type == "ping":
                await ws_manager.send_to(websocket, {"type": "pong"})

            elif msg_type == "subscribe_device":
                device_id = data.get("device_id")
                # Start telemetry stream for this device
                await ws_manager.send_to(websocket, {
                    "type": "subscribed",
                    "device_id": device_id,
                })

            elif msg_type == "send_data":
                device_id = data.get("device_id")
                payload = data.get("data", "")
                if device_id and payload:
                    await device_manager.write(device_id, payload.encode() + b"\n")

            elif msg_type == "set_session":
                session_id = data.get("session_id")
                device_id = data.get("device_id")
                await session_recorder.start_session(session_id, device_id)
                await ws_manager.send_to(websocket, {
                    "type": "session_started",
                    "session_id": session_id,
                })

    except WebSocketDisconnect:
        await ws_manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        await ws_manager.disconnect(websocket)


@router.websocket("/telemetry")
async def websocket_telemetry(websocket: WebSocket):
    """Main WebSocket endpoint for real-time telemetry data."""
    await handle_websocket(websocket)


async def setup_telemetry_pipeline():
    """Wire up the components: serial -> telemetry engine -> alerts + broadcast."""

    async def on_data(device_id: str, session_id: str, line: str):
        # Parse through telemetry engine
        await telemetry_engine.process_line(device_id, session_id, line)

        # Store in session recorder
        await session_recorder.record_packet(session_id, {
            "device_id": device_id,
            "raw": line,
        })

        # Get parsed metrics and check alerts
        for msg_callback in telemetry_engine._callbacks:
            pass  # Callbacks already triggered in process_line

        # Broadcast raw line
        await ws_manager.broadcast({
            "type": "serial_data",
            "device_id": device_id,
            "session_id": session_id,
            "data": line,
        })

    # Register telemetry engine callback for alerts
    async def on_parsed_message(msg):
        for metric in msg.metrics:
            await alert_engine.evaluate("", "", metric)
            await session_recorder.record_metric("", {
                "metric_name": metric.name,
                "value": metric.value,
                "unit": metric.unit,
            })
            # Broadcast metric
            await ws_manager.broadcast({
                "type": "metric",
                "metric_name": metric.name,
                "value": metric.value,
                "unit": metric.unit,
            })

    telemetry_engine.register_callback(on_parsed_message)
    return on_data
