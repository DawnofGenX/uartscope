"""Device Manager — detects, tracks, and manages connected embedded devices."""
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
    """Manages device lifecycle: detection, connection, tracking."""

    def __init__(self):
        self._devices: Dict[str, DeviceInfo] = {}  # id -> DeviceInfo
        self._port_map: Dict[str, str] = {}  # port -> device_id
        self._lock = asyncio.Lock()

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
        """Register a new device and attempt initial connection."""
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

    async def connect(self, device_id: str) -> bool:
        """Open serial connection to a device."""
        device = self._devices.get(device_id)
        if not device:
            return False

        try:
            device.serial_conn = serial.Serial(
                port=device.port,
                baudrate=device.baudrate,
                timeout=settings.serial_timeout,
                write_timeout=settings.serial_timeout,
            )
            device.status = "connected"
            device.last_seen = datetime.utcnow()
            logger.info(f"Connected to {device.name} @ {device.baudrate} baud")
            return True
        except serial.SerialException as e:
            device.status = "error"
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

    def get_device(self, device_id: str) -> Optional[DeviceInfo]:
        return self._devices.get(device_id)

    def get_all_devices(self) -> List[DeviceInfo]:
        return list(self._devices.values())

    def get_connected_device(self) -> Optional[DeviceInfo]:
        """Get first connected device (for single-device mode)."""
        for device in self._devices.values():
            if device.status == "connected":
                return device
        return None

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


# Singleton
device_manager = DeviceManager()
