"""Device Manager — detects, tracks, and manages multiple connected embedded devices."""
import asyncio
import logging
from typing import Dict, List, Optional
from datetime import datetime

import serial.tools.list_ports
import serial

from app.config import settings
from app.models import DeviceCreate, DeviceResponse

logger = logging.getLogger(__name__)


class DeviceInfo:
    """Runtime state of a connected device."""
    def __init__(self, create: DeviceCreate):
        self.id: Optional[str] = None
        self.name = create.name or create.port
        self.port = create.port
        self.protocol = create.protocol
        self.baudrate = create.baudrate
        self.board_type = create.board_type
        self.metadata = create.metadata or {}
        self.status = "disconnected"
        self.serial_conn: Optional[serial.Serial] = None
        self.created_at = datetime.utcnow()
        self.last_seen: Optional[datetime] = None
        self.bytes_received = 0
        self.packet_count = 0
        self.error_count = 0
        self.session_id: Optional[str] = None
        self.auto_reconnect = True
        self._reconnect_task: Optional[asyncio.Task] = None

    def to_response(self) -> DeviceResponse:
        return DeviceResponse(
            id=self.id or "",
            name=self.name,
            port=self.port,
            protocol=self.protocol,
            baudrate=self.baudrate,
            status=self.status,
            board_type=self.board_type,
            metadata_json=self.metadata,
            created_at=self.created_at,
            last_seen=self.last_seen,
        )


class DeviceManager:
    """Manages device lifecycle: detection, connection, tracking, heartbeat, auto-reconnect."""

    def __init__(self):
        self._devices: Dict[str, DeviceInfo] = {}  # id -> DeviceInfo
        self._port_map: Dict[str, str] = {}  # port -> device_id
        self._lock = asyncio.Lock()
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._heartbeat_interval = 5.0  # seconds
        self._stale_threshold = 30.0  # seconds before marking stale

    async def start_heartbeat_monitor(self):
        """Start background task to monitor device health."""
        if self._heartbeat_task is None:
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
            logger.info("Heartbeat monitor started")

    async def stop_heartbeat_monitor(self):
        """Stop heartbeat monitor."""
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            self._heartbeat_task = None

    async def _heartbeat_loop(self):
        """Periodically check device health and trigger auto-reconnect."""
        while True:
            try:
                await asyncio.sleep(self._heartbeat_interval)
                now = datetime.utcnow()
                for device in list(self._devices.values()):
                    # Check for stale connections (no data received recently)
                    if device.status == "connected" and device.last_seen:
                        elapsed = (now - device.last_seen).total_seconds()
                        if elapsed > self._stale_threshold:
                            logger.warning(
                                f"Device {device.name} stale for {elapsed:.0f}s, "
                                f"last seen {device.last_seen.isoformat()}"
                            )

                    # Auto-reconnect logic
                    if (
                        device.auto_reconnect
                        and device.status in ("disconnected", "error")
                        and device.serial_conn is None
                    ):
                        logger.info(f"Auto-reconnecting {device.name}...")
                        await self.connect(device.id)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Heartbeat error: {e}")

    async def detect_ports(self) -> List[Dict]:
        """Auto-detect connected serial devices."""
        ports = serial.tools.list_ports.comports()
        detected = []
        for port in ports:
            detected.append({
                "port": port.device,
                "description": port.description,
                "manufacturer": port.manufacturer,
                "serial_number": port.serial_number,
                "vid": port.vid,
                "pid": port.pid,
                "board_type": self._guess_board(port),
            })
        return detected

    def _guess_board(self, port) -> str:
        """Heuristic to identify board type from USB descriptors."""
        desc = (port.description or "").lower()
        manufacturer = (port.manufacturer or "").lower()
        if "ch340" in desc or "ch340" in manufacturer:
            return "Arduino (CH340)"
        if "cp210" in desc or "cp210" in manufacturer:
            return "ESP32 (CP210x)"
        if "ftdi" in desc or "ftdi" in manufacturer:
            return "FTDI Device"
        if "stm32" in desc or "stm" in desc:
            return "STM32 Bootloader"
        if "pico" in desc or "rp2040" in desc or "rp2040" in manufacturer:
            return "Raspberry Pi Pico"
        if "arduino" in desc or "arduino" in manufacturer:
            return "Arduino"
        if "usb serial" in desc:
            return "USB-Serial Adapter"
        return "Unknown"

    async def add_device(self, create: DeviceCreate) -> DeviceInfo:
        """Register a new device with auto-generated ID."""
        async with self._lock:
            if create.port in self._port_map:
                device_id = self._port_map[create.port]
                return self._devices[device_id]

            device = DeviceInfo(create)
            device.id = f"dev_{len(self._devices):04x}"
            device.status = "detected"
            self._devices[device.id] = device
            self._port_map[create.port] = device.id

            logger.info(f"Device added: {device.name} on {device.port} ({device.board_type})")
            return device

    def register_device_from_db(self, device_id: str, create: DeviceCreate) -> DeviceInfo:
        """Register a device from database (synchronous, for startup/refresh)."""
        if device_id in self._devices:
            return self._devices[device_id]
        if create.port in self._port_map:
            existing_id = self._port_map[create.port]
            if existing_id != device_id:
                return self._devices[existing_id]

        device = DeviceInfo(create)
        device.id = device_id
        device.status = "disconnected"
        self._devices[device.id] = device
        self._port_map[create.port] = device.id
        return device

    async def add_device_with_id(self, device_id: str, create: DeviceCreate) -> DeviceInfo:
        """Register a new device with a specific ID (e.g., from database UUID)."""
        async with self._lock:
            if create.port in self._port_map:
                existing_id = self._port_map[create.port]
                return self._devices[existing_id]

            # Remove any existing device with this ID
            if device_id in self._devices:
                old = self._devices.pop(device_id)
                self._port_map.pop(old.port, None)

            device = DeviceInfo(create)
            device.id = device_id
            device.status = "detected"
            self._devices[device.id] = device
            self._port_map[create.port] = device.id

            logger.info(f"Device added: {device.name} on {device.port} (id={device.id})")
            return device

    async def connect(self, device_id: str) -> bool:
        """Open serial connection to a device."""
        device = self._devices.get(device_id)
        if not device:
            return False

        # Close existing connection if any
        if device.serial_conn and device.serial_conn.is_open:
            try:
                device.serial_conn.close()
            except Exception:
                pass

        try:
            device.serial_conn = serial.Serial(
                port=device.port,
                baudrate=device.baudrate,
                timeout=settings.serial_timeout,
                write_timeout=settings.serial_timeout,
            )
            device.status = "connected"
            device.last_seen = datetime.utcnow()
            device.error_count = 0
            logger.info(f"Connected to {device.name} @ {device.baudrate} baud")
            return True
        except serial.SerialException as e:
            device.status = "error"
            device.serial_conn = None
            device.error_count += 1
            logger.error(f"Failed to connect to {device.name}: {e}")
            return False

    async def disconnect(self, device_id: str) -> bool:
        """Close serial connection."""
        device = self._devices.get(device_id)
        if not device or not device.serial_conn:
            return False

        try:
            device.serial_conn.close()
            device.status = "disconnected"
            device.serial_conn = None
            logger.info(f"Disconnected {device.name}")
            return True
        except Exception as e:
            logger.error(f"Error disconnecting {device.name}: {e}")
            return False

    async def remove_device(self, device_id: str):
        """Remove a device from management."""
        async with self._lock:
            device = self._devices.pop(device_id, None)
            if device:
                self._port_map.pop(device.port, None)
                if device.serial_conn:
                    try:
                        device.serial_conn.close()
                    except Exception:
                        pass
                if device._reconnect_task:
                    device._reconnect_task.cancel()

    def get_device(self, device_id: str) -> Optional[DeviceInfo]:
        return self._devices.get(device_id)

    def get_all_devices(self) -> List[DeviceInfo]:
        return list(self._devices.values())

    def get_connected_devices(self) -> List[DeviceInfo]:
        """Get all currently connected devices."""
        return [d for d in self._devices.values() if d.status == "connected"]

    def get_streaming_devices(self) -> List[DeviceInfo]:
        """Get all devices currently streaming."""
        return [d for d in self._devices.values() if d.session_id is not None]

    async def write(self, device_id: str, data: bytes) -> bool:
        """Send data to a device."""
        device = self._devices.get(device_id)
        if not device or not device.serial_conn:
            return False
        try:
            device.serial_conn.write(data)
            return True
        except serial.SerialException:
            return False

    def get_stats(self) -> Dict:
        """Get aggregate device statistics."""
        total = len(self._devices)
        connected = sum(1 for d in self._devices.values() if d.status == "connected")
        streaming = sum(1 for d in self._devices.values() if d.session_id)
        errors = sum(1 for d in self._devices.values() if d.status == "error")
        total_bytes = sum(d.bytes_received for d in self._devices.values())
        total_packets = sum(d.packet_count for d in self._devices.values())
        return {
            "total": total,
            "connected": connected,
            "streaming": streaming,
            "errors": errors,
            "total_bytes_received": total_bytes,
            "total_packets": total_packets,
        }


# Singleton
device_manager = DeviceManager()
