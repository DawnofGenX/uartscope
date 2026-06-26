"""UARTScope Pro — Main FastAPI application."""
import asyncio
import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import init_db
from app.api.routes.devices import router as devices_router
from app.api.routes.telemetry import router as telemetry_router
from app.api.routes.sessions import router as sessions_router
from app.api.routes.alerts import router as alerts_router
from app.api.routes.export import router as export_router
from app.api.routes.protocols import router as protocols_router
from app.api.routes.websocket import router as ws_router, setup_telemetry_pipeline
from app.api.routes.performance import router as performance_router
from app.core.device_manager import device_manager
from app.core.serial_reader import serial_reader
from app.core.telemetry_engine import telemetry_engine
from app.core.session_recorder import session_recorder
from app.core.performance_tracker import performance_tracker
from app.core.mqtt_client import mqtt_client
from app.core.websocket_hub import ws_manager
from app.core.alert_engine import alert_engine

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Global state
_active_sessions: dict = {}  # device_id -> session_id
_data_callbacks: dict = {}  # device_id -> callback (for cleanup tracking)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown."""
    logger.info(f"Starting {settings.app_name} v{settings.app_version}")

    # Initialize database
    await init_db()
    logger.info("Database initialized")

    # Setup telemetry pipeline (returns the on_data callback factory)
    on_data_factory = await setup_telemetry_pipeline()

    # Register MQTT callback
    async def on_mqtt_data(data):
        logger.info(f"MQTT data received: {data.get('topic')}")
    mqtt_client.register_callback(on_mqtt_data)

    # Start heartbeat monitor for auto-reconnect
    await device_manager.start_heartbeat_monitor()

    # Start performance tracker
    await performance_tracker.start()
    logger.info("Performance tracker started")

    # Register alert callback for WebSocket broadcasting
    async def on_alert(alert):
        """Broadcast alert events to all connected WebSocket clients."""
        await ws_manager.broadcast_to_all({
            "type": "alert",
            "alert": alert,
        })

    alert_engine.register_callback(on_alert)

    # Auto-connect to first available device (optional)
    if settings.mqtt_enabled:
        await mqtt_client.connect()

    logger.info("Application ready")
    yield

    # Shutdown
    logger.info("Shutting down...")
    await device_manager.stop_heartbeat_monitor()
    await performance_tracker.stop()
    await serial_reader.stop_all()
    await mqtt_client.disconnect()
    logger.info("Shutdown complete")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Open-source embedded telemetry and debugging platform — the Wireshark of microcontrollers",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routes
app.include_router(devices_router, prefix="/api")
app.include_router(telemetry_router, prefix="/api")
app.include_router(sessions_router, prefix="/api")
app.include_router(alerts_router, prefix="/api")
app.include_router(export_router, prefix="/api")
app.include_router(protocols_router, prefix="/api")
app.include_router(ws_router, prefix="/api")
app.include_router(performance_router, prefix="/api")


@app.get("/api/health")
async def health():
    stats = device_manager.get_stats()
    return {
        "status": "healthy",
        "version": settings.app_version,
        "devices": stats,
        "active_sessions": len(_active_sessions),
        "websocket_clients": ws_manager.count,
    }


@app.get("/api/protocols")
async def list_protocols():
    """List available protocol decoders."""
    from app.core.protocol_decoder import protocol_manager
    return {"decoders": protocol_manager.list_decoders()}


@app.post("/api/devices/{device_id}/start")
async def start_device_stream(device_id: str):
    """Start streaming data from a device.

    Creates an isolated session and data pipeline per device.
    Multiple devices can stream simultaneously.
    """
    device = device_manager.get_device(device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    # Check if already streaming
    if device.session_id and device_id in _active_sessions:
        return {
            "status": "already_streaming",
            "device_id": device_id,
            "session_id": device.session_id,
        }

    # Connect if not already
    if device.status != "connected":
        connected = await device_manager.connect(device_id)
        if not connected:
            raise HTTPException(status_code=400, detail="Failed to connect to device")

    # Create isolated session for this device
    session_id = str(uuid.uuid4())
    await session_recorder.start_session(
        session_id, device_id, f"Session {device.name}"
    )
    device.session_id = session_id
    device.status = "streaming"
    _active_sessions[device_id] = session_id

    # Create a dedicated data callback for this device
    # This callback broadcasts only to clients subscribed to this device
    async def on_data(dev_id=device_id, sess_id=session_id, line: str = ""):
        import time as _time
        _recv_start = _time.time()
        await telemetry_engine.process_line(dev_id, sess_id, line)
        await session_recorder.record_packet(sess_id, {
            "device_id": dev_id,
            "raw": line,
        })

        # Record performance metrics
        latency_ms = (_time.time() - _recv_start) * 1000
        await performance_tracker.on_packet_received(dev_id, len(line.encode()), latency_ms)

        # Get latest metrics and broadcast per-device
        latest = telemetry_engine.get_latest_values(dev_id)
        for metric_name, value in latest.items():
            await ws_manager.broadcast(
                {
                    "type": "metric",
                    "device_id": dev_id,
                    "metric_name": metric_name,
                    "value": value,
                },
                device_id=dev_id,
            )

        # Broadcast raw serial data to device-subscribed clients
        await ws_manager.broadcast(
            {
                "type": "serial_data",
                "device_id": dev_id,
                "session_id": sess_id,
                "data": line,
            },
            device_id=dev_id,
        )

    # Track the callback for cleanup
    _data_callbacks[device_id] = on_data

    # Start serial reader for this device
    await serial_reader.start_device(device, session_id, on_data)

    logger.info(f"Started streaming from {device.name} (session: {session_id})")
    return {
        "status": "streaming",
        "device_id": device_id,
        "session_id": session_id,
        "device_name": device.name,
    }


@app.post("/api/devices/{device_id}/stop")
async def stop_device_stream(device_id: str):
    """Stop streaming from a specific device.

    Other devices continue streaming unaffected.
    """
    await serial_reader.stop_device(device_id)

    session_id = _active_sessions.pop(device_id, None)
    if session_id:
        await session_recorder.stop_session(session_id)

    device = device_manager.get_device(device_id)
    if device:
        device.session_id = None
        device.status = "connected" if device.serial_conn else "disconnected"

    # Clean up callback
    _data_callbacks.pop(device_id, None)

    logger.info(f"Stopped streaming from device {device_id}")
    return {
        "status": "stopped",
        "device_id": device_id,
        "session_id": session_id,
    }


@app.get("/api/devices/{device_id}/stats")
async def get_device_stats(device_id: str):
    """Get statistics for a specific device."""
    device = device_manager.get_device(device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    latest_metrics = telemetry_engine.get_latest_values(device_id)
    all_metrics = telemetry_engine.get_all_metrics(device_id)

    return {
        "device_id": device_id,
        "name": device.name,
        "status": device.status,
        "bytes_received": device.bytes_received,
        "packets_received": device.packet_count,
        "errors": device.error_count,
        "last_seen": device.last_seen.isoformat() if device.last_seen else None,
        "session_id": device.session_id,
        "latest_metrics": latest_metrics,
        "metric_count": len(all_metrics),
        "metric_history_sizes": {
            name: len(history) for name, history in all_metrics.items()
        },
    }


@app.post("/api/devices/{device_id}/auto-reconnect")
async def toggle_auto_reconnect(device_id: str, enabled: bool = True):
    """Enable or disable auto-reconnect for a device."""
    device = device_manager.get_device(device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    device.auto_reconnect = enabled
    return {
        "device_id": device_id,
        "auto_reconnect": enabled,
    }


# Need HTTPException import
from fastapi import HTTPException
