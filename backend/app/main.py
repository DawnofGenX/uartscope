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
from app.api.routes.websocket import router as ws_router, setup_telemetry_pipeline
from app.core.device_manager import device_manager
from app.core.serial_reader import serial_reader
from app.core.telemetry_engine import telemetry_engine
from app.core.session_recorder import session_recorder
from app.core.mqtt_client import mqtt_client
from app.core.websocket_hub import ws_manager

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Global state
_active_sessions: dict = {}  # device_id -> session_id


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown."""
    logger.info(f"Starting {settings.app_name} v{settings.app_version}")

    # Initialize database
    await init_db()
    logger.info("Database initialized")

    # Setup telemetry pipeline
    on_data = await setup_telemetry_pipeline()

    # Register MQTT callback
    async def on_mqtt_data(data):
        logger.info(f"MQTT data received: {data.get('topic')}")
    mqtt_client.register_callback(on_mqtt_data)

    # Auto-connect to first available device (optional)
    if settings.mqtt_enabled:
        await mqtt_client.connect()

    logger.info("Application ready")
    yield

    # Shutdown
    logger.info("Shutting down...")
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
app.include_router(ws_router, prefix="/api")


@app.get("/api/health")
async def health():
    return {
        "status": "healthy",
        "version": settings.app_version,
        "devices": len(device_manager.get_all_devices()),
        "active_sessions": len(_active_sessions),
    }


@app.get("/api/protocols")
async def list_protocols():
    """List available protocol decoders."""
    from app.core.protocol_decoder import protocol_manager
    return {"decoders": protocol_manager.list_decoders()}


@app.post("/api/devices/{device_id}/start")
async def start_device_stream(device_id: str):
    """Start streaming data from a device."""
    device = device_manager.get_device(device_id)
    if not device:
        return {"error": "Device not found"}, 404

    # Connect if not already
    if device.status != "connected":
        connected = await device_manager.connect(device_id)
        if not connected:
            return {"error": "Failed to connect"}, 400

    # Create session
    session_id = str(uuid.uuid4())
    await session_recorder.start_session(session_id, device_id, f"Session {device.name}")
    _active_sessions[device_id] = session_id

    # Start reading
    async def on_data(dev_id, sess_id, line):
        await telemetry_engine.process_line(dev_id, sess_id, line)
        await session_recorder.record_packet(sess_id, {"device_id": dev_id, "raw": line})

        # Broadcast to WebSocket clients
        await ws_manager.broadcast({
            "type": "serial_data",
            "device_id": dev_id,
            "session_id": sess_id,
            "data": line,
        })

        # Check alerts
        for metric in telemetry_engine.get_all_metrics(dev_id):
            pass  # Alerts handled by callback

    await serial_reader.start_device(device, session_id, on_data)

    return {
        "status": "streaming",
        "device_id": device_id,
        "session_id": session_id,
    }


@app.post("/api/devices/{device_id}/stop")
async def stop_device_stream(device_id: str):
    """Stop streaming from a device."""
    await serial_reader.stop_device(device_id)
    session_id = _active_sessions.pop(device_id, None)
    if session_id:
        await session_recorder.stop_session(session_id)
    return {"status": "stopped", "device_id": device_id}
