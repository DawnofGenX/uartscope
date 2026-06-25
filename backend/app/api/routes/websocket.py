"""WebSocket real-time telemetry stream with per-device subscription support."""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException
import asyncio
import logging

from app.core.device_manager import device_manager
from app.core.telemetry_engine import telemetry_engine
from app.core.serial_reader import serial_reader
from app.core.alert_engine import alert_engine
from app.core.session_recorder import session_recorder
from app.core.websocket_hub import ws_manager, SubscriptionMode

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
                if device_id:
                    # Verify device exists
                    device = device_manager.get_device(device_id)
                    if not device:
                        await ws_manager.send_to(websocket, {
                            "type": "error",
                            "message": f"Device {device_id} not found",
                        })
                        continue
                    await ws_manager.set_subscription(
                        websocket, SubscriptionMode.DEVICE, device_id
                    )
                    await ws_manager.send_to(websocket, {
                        "type": "subscribed",
                        "device_id": device_id,
                        "device_name": device.name,
                    })

            elif msg_type == "subscribe_all":
                await ws_manager.set_subscription(websocket, SubscriptionMode.ALL)
                await ws_manager.send_to(websocket, {
                    "type": "subscribed",
                    "mode": "all",
                })

            elif msg_type == "unsubscribe":
                await ws_manager.set_subscription(websocket, SubscriptionMode.NONE)
                await ws_manager.send_to(websocket, {"type": "unsubscribed"})

            elif msg_type == "send_data":
                device_id = data.get("device_id")
                payload = data.get("data", "")
                if device_id and payload:
                    success = await device_manager.write(
                        device_id, payload.encode() + b"\n"
                    )
                    await ws_manager.send_to(websocket, {
                        "type": "data_sent",
                        "device_id": device_id,
                        "success": success,
                    })

            elif msg_type == "set_session":
                session_id = data.get("session_id")
                device_id = data.get("device_id")
                await session_recorder.start_session(session_id, device_id)
                await ws_manager.send_to(websocket, {
                    "type": "session_started",
                    "session_id": session_id,
                })

            elif msg_type == "get_subscriptions":
                info = ws_manager.get_subscription_info()
                await ws_manager.send_to(websocket, {
                    "type": "subscriptions",
                    "data": info,
                })

    except WebSocketDisconnect:
        await ws_manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        await ws_manager.disconnect(websocket)


@router.websocket("/telemetry")
async def websocket_telemetry(websocket: WebSocket):
    """Main WebSocket endpoint for real-time telemetry data.

    Supports per-device subscriptions:
    - {"type": "subscribe_device", "device_id": "dev_0001"} — single device
    - {"type": "subscribe_all"} — all devices
    - {"type": "unsubscribe"} — stop receiving data
    """
    await handle_websocket(websocket)


@router.get("/subscriptions")
async def get_active_subscriptions():
    """Get current WebSocket subscription info."""
    return ws_manager.get_subscription_info()


async def setup_telemetry_pipeline():
    """Wire up the components: serial -> telemetry engine -> alerts + broadcast.

    Each device gets its own on_data callback that broadcasts only to
    clients subscribed to that device.
    """

    async def on_data(device_id: str, session_id: str, line: str):
        # Parse through telemetry engine
        await telemetry_engine.process_line(device_id, session_id, line)

        # Store in session recorder
        await session_recorder.record_packet(session_id, {
            "device_id": device_id,
            "raw": line,
        })

        # Broadcast raw line to device-subscribed clients
        await ws_manager.broadcast(
            {
                "type": "serial_data",
                "device_id": device_id,
                "session_id": session_id,
                "data": line,
            },
            device_id=device_id,
        )

    # Register telemetry engine callback for alerts + metric broadcast
    async def on_parsed_message(msg):
        # The telemetry engine calls this with parsed messages
        # We need to broadcast metrics to subscribed clients
        # Note: device_id is not directly available here, so we use a workaround
        pass

    # Instead of using the global callback, we handle metric broadcast
    # in the on_data callback above by accessing the engine's latest values
    # For alerts, we check after each line
    async def on_data_with_alerts(device_id: str, session_id: str, line: str):
        await telemetry_engine.process_line(device_id, session_id, line)
        await session_recorder.record_packet(session_id, {
            "device_id": device_id,
            "raw": line,
        })

        # Get latest metrics and check alerts
        latest = telemetry_engine.get_latest_values(device_id)
        for metric_name, value in latest.items():
            # Broadcast metric to subscribed clients
            await ws_manager.broadcast(
                {
                    "type": "metric",
                    "device_id": device_id,
                    "metric_name": metric_name,
                    "value": value,
                },
                device_id=device_id,
            )

        # Broadcast raw line
        await ws_manager.broadcast(
            {
                "type": "serial_data",
                "device_id": device_id,
                "session_id": session_id,
                "data": line,
            },
            device_id=device_id,
        )

    return on_data_with_alerts
