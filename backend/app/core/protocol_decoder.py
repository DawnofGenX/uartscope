"""Protocol Decoder — extensible plugin-based protocol decoding framework."""
import logging
import struct
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)


class ProtocolDecoder(ABC):
    """Base class for protocol decoders."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Decoder name."""
        pass

    @property
    @abstractmethod
    def protocol_id(self) -> str:
        """Unique protocol identifier."""
        pass

    @property
    def description(self) -> str:
        """Human-readable description."""
        return ""

    @abstractmethod
    def can_decode(self, raw_data: bytes) -> float:
        """Return confidence 0.0-1.0 that this data matches the protocol."""
        pass

    @abstractmethod
    def decode(self, raw_data: bytes) -> Dict[str, Any]:
        """Decode raw data into structured format."""
        pass

    @abstractmethod
    def encode(self, data: Dict[str, Any]) -> bytes:
        """Encode structured data back to raw bytes."""
        pass


class UARTTextDecoder(ProtocolDecoder):
    """Decoder for common UART text protocols (AT commands, NMEA, etc.)."""

    @property
    def name(self) -> str:
        return "UART Text"

    @property
    def protocol_id(self) -> str:
        return "uart_text"

    @property
    def description(self) -> str:
        return "AT commands, NMEA GPS, debug print, CSV/key-value text"

    def can_decode(self, raw_data: bytes) -> float:
        try:
            text = raw_data.decode("utf-8")
            if text.startswith("AT+") or text.startswith("AT"):
                return 0.9
            if text.startswith("$G"):
                return 0.95
            if any(c.isalpha() for c in text) and text.strip().endswith("\n"):
                return 0.5
        except (UnicodeDecodeError, AttributeError):
            pass
        return 0.0

    def decode(self, raw_data: bytes) -> Dict[str, Any]:
        text = raw_data.decode("utf-8", errors="replace").strip()
        result = {"type": "text", "content": text}

        if text.startswith("AT+") or text.startswith("AT"):
            result["subtype"] = "at_command"
            result["command"] = text.split("\r")[0]
        elif text.startswith("$G"):
            result["subtype"] = "nmea"
            parts = text.split(",")
            result["sentence_type"] = parts[0] if parts else "unknown"
        elif ":" in text and "=" not in text:
            result["subtype"] = "key_value"
            kv_pairs = {}
            for part in text.split(","):
                if ":" in part:
                    k, v = part.split(":", 1)
                    kv_pairs[k.strip()] = v.strip()
            result["values"] = kv_pairs

        return result

    def encode(self, data: Dict[str, Any]) -> bytes:
        return data.get("content", "").encode("utf-8")


class ModbusRTUDecoder(ProtocolDecoder):
    """Decoder for Modbus RTU protocol."""

    @property
    def name(self) -> str:
        return "Modbus RTU"

    @property
    def protocol_id(self) -> str:
        return "modbus_rtu"

    @property
    def description(self) -> str:
        return "Industrial Modbus RTU (function codes 1-6, 15, 16)"

    FUNCTION_NAMES = {
        0x01: "Read Coils",
        0x02: "Read Discrete Inputs",
        0x03: "Read Holding Registers",
        0x04: "Read Input Registers",
        0x05: "Write Single Coil",
        0x06: "Write Single Register",
        0x0F: "Write Multiple Coils",
        0x10: "Write Multiple Registers",
    }

    def can_decode(self, raw_data: bytes) -> float:
        if len(raw_data) < 4:
            return 0.0
        addr = raw_data[0]
        func = raw_data[1]
        if addr == 0 or addr > 247:
            return 0.0
        if func in self.FUNCTION_NAMES:
            return 0.75
        return 0.0

    def decode(self, raw_data: bytes) -> Dict[str, Any]:
        func = raw_data[1]
        result = {
            "type": "modbus_rtu",
            "device_addr": raw_data[0],
            "function_code": func,
            "function_name": self.FUNCTION_NAMES.get(func, f"Unknown (0x{func:02X})"),
            "data": raw_data[2:-2].hex() if len(raw_data) > 4 else "",
            "crc": raw_data[-2:].hex() if len(raw_data) >= 2 else "",
            "length": len(raw_data),
        }
        return result

    def encode(self, data: Dict[str, Any]) -> bytes:
        addr = data.get("device_addr", 1)
        func = data.get("function_code", 3)
        return bytes([addr, func, 0, 0])


class I2CDecoder(ProtocolDecoder):
    """Decoder for I2C protocol (7-bit and 10-bit addressing)."""

    @property
    def name(self) -> str:
        return "I2C"

    @property
    def protocol_id(self) -> str:
        return "i2c"

    @property
    def description(self) -> str:
        return "I2C bus — 7/10-bit addressing, read/write, ACK/NACK"

    # Common I2C address ranges for detection
    KNOWN_ADDRESSES = set(range(0x08, 0x78))  # Valid 7-bit addresses

    def can_decode(self, raw_data: bytes) -> float:
        if len(raw_data) < 3:
            return 0.0
        # I2C packet format: [addr_w/r][data...][ack]
        addr_byte = raw_data[0]
        addr_7bit = addr_byte >> 1
        rw = addr_byte & 0x01

        if addr_7bit in self.KNOWN_ADDRESSES and rw in (0, 1):
            return 0.6
        return 0.0

    def decode(self, raw_data: bytes) -> Dict[str, Any]:
        addr_byte = raw_data[0]
        addr_7bit = addr_byte >> 1
        read_write = "Read" if addr_byte & 0x01 else "Write"
        ack = "ACK" if len(raw_data) > 1 and raw_data[-1] == 0 else "NACK"

        result = {
            "type": "i2c",
            "address_7bit": f"0x{addr_7bit:02X}",
            "address_raw": f"0x{addr_byte:02X}",
            "rw": read_write,
            "ack": ack,
            "data": raw_data[1:-1].hex() if len(raw_data) > 2 else "",
            "data_length": max(0, len(raw_data) - 2),
            "raw_hex": raw_data.hex(),
        }

        # Try to identify common devices
        if 0x3C <= addr_7bit <= 0x3D:
            result["device_hint"] = "SSD1306 OLED display"
        elif 0x68 <= addr_7bit <= 0x69:
            result["device_hint"] = "MPU6050/DS3231/RTC"
        elif 0x48 <= addr_7bit <= 0x4B:
            result["device_hint"] = "ADS1115/ADS1015 ADC"
        elif 0x50 <= addr_7bit <= 0x57:
            result["device_hint"] = "EEPROM"
        elif 0x76 <= addr_7bit <= 0x77:
            result["device_hint"] = "BME280/BMP280 pressure sensor"

        return result

    def encode(self, data: Dict[str, Any]) -> bytes:
        addr = int(data.get("address_7bit", "0x3C"), 16)
        rw = 0 if data.get("rw", "Write") == "Write" else 1
        payload = bytes.fromhex(data.get("data", ""))
        return bytes([addr << 1 | rw]) + payload + bytes([0])  # ACK


class SPIDecoder(ProtocolDecoder):
    """Decoder for SPI (Serial Peripheral Interface) protocol."""

    @property
    def name(self) -> str:
        return "SPI"

    @property
    def protocol_id(self) -> str:
        return "spi"

    @property
    def description(self) -> str:
        return "SPI bus — MOSI/MISO, CS polarity, clock modes"

    def can_decode(self, raw_data: bytes) -> float:
        if len(raw_data) < 2:
            return 0.0
        # SPI typically has start marker or consistent length
        # Heuristic: even-length packets >= 4 bytes with printable or structured data
        if len(raw_data) >= 4 and len(raw_data) % 2 == 0:
            return 0.4
        return 0.0

    def decode(self, raw_data: bytes) -> Dict[str, Any]:
        # SPI frame: [cmd/register][data...]  (simplified)
        cmd_byte = raw_data[0]
        result = {
            "type": "spi",
            "command": f"0x{cmd_byte:02X}",
            "cmd_mosi": cmd_byte > 0,
            "data_mosi": raw_data[1:].hex() if len(raw_data) > 1 else "",
            "data_length": len(raw_data) - 1,
            "raw_hex": raw_data.hex(),
            "bits": len(raw_data) * 8,
        }

        # Common SPI flash commands
        spi_commands = {
            0x06: "Write Enable",
            0x04: "Write Disable",
            0x05: "Read Status Register-1",
            0x9F: "Read JEDEC ID",
            0x03: "Read Data",
            0x02: "Page Program",
            0x20: "Sector Erase",
            0xD8: "Block Erase 64KB",
            0xC7: "Chip Erase",
            0xAB: "Release Power Down",
            0xB9: "Power Down",
        }
        if cmd_byte in spi_commands:
            result["spi_command"] = spi_commands[cmd_byte]
            result["peripheral_hint"] = "SPI Flash"

        return result

    def encode(self, data: Dict[str, Any]) -> bytes:
        cmd = int(data.get("command", "0x03"), 16)
        payload = bytes.fromhex(data.get("data_mosi", ""))
        return bytes([cmd]) + payload


class CANDecoder(ProtocolDecoder):
    """Decoder for CAN bus (Controller Area Network) protocol."""

    @property
    def name(self) -> str:
        return "CAN Bus"

    @property
    def protocol_id(self) -> str:
        return "can"

    @property
    def description(self) -> str:
        return "CAN 2.0A/B — 11/29-bit ID, data bytes, CRC"

    def can_decode(self, raw_data: bytes) -> float:
        if len(raw_data) < 5:
            return 0.0
        # CAN frame format: [id_hi][id_lo][dlc][data...][crc]
        dlc = raw_data[2]
        if dlc <= 8 and len(raw_data) >= 3 + dlc + 1:
            return 0.65
        return 0.0

    def decode(self, raw_data: bytes) -> Dict[str, Any]:
        id_hi = raw_data[0]
        id_lo = raw_data[1]
        can_id = (id_hi << 8) | id_lo
        dlc = raw_data[2]
        data_bytes = raw_data[3:3 + dlc] if dlc <= 8 else raw_data[3:11]
        crc = raw_data[3 + dlc:3 + dlc + 2] if len(raw_data) >= 3 + dlc + 2 else b""

        result = {
            "type": "can",
            "can_id": f"0x{can_id:03X}",
            "can_id_decimal": can_id,
            "dlc": dlc,
            "data": data_bytes.hex(),
            "data_bytes": list(data_bytes),
            "crc": crc.hex() if crc else "",
            "raw_hex": raw_data.hex(),
            "extended": can_id > 0x7FF,
        }

        # Common CAN IDs
        known_ids = {
            0x100: "Engine RPM",
            0x120: "Vehicle Speed",
            0x180: "Coolant Temp",
            0x200: "Throttle Position",
            0x300: "OBD-II Request",
            0x7DF: "OBD-II Functional Request",
            0x7E0: "OBD-II ECU Response",
        }
        if can_id in known_ids:
            result["id_hint"] = known_ids[can_id]

        return result

    def encode(self, data: Dict[str, Any]) -> bytes:
        can_id = int(data.get("can_id", "0x100"), 16)
        dlc = data.get("dlc", len(data.get("data_bytes", [])))
        data_bytes = data.get("data_bytes", [0] * dlc)
        return bytes([(can_id >> 8) & 0xFF, can_id & 0xFF, dlc]) + bytes(data_bytes[:8])


class ProtocolManager:
    """Manages protocol decoders and auto-detection."""

    def __init__(self):
        self._decoders: Dict[str, ProtocolDecoder] = {}
        self._register_defaults()

    def _register_defaults(self):
        """Register built-in decoders."""
        self.register(UARTTextDecoder())
        self.register(ModbusRTUDecoder())
        self.register(I2CDecoder())
        self.register(SPIDecoder())
        self.register(CANDecoder())

    def register(self, decoder: ProtocolDecoder):
        """Register a protocol decoder."""
        self._decoders[decoder.protocol_id] = decoder
        logger.info(f"Protocol decoder registered: {decoder.name} ({decoder.protocol_id})")

    def unregister(self, protocol_id: str):
        self._decoders.pop(protocol_id, None)

    def get_decoder(self, protocol_id: str) -> Optional[ProtocolDecoder]:
        return self._decoders.get(protocol_id)

    def auto_detect(self, raw_data: bytes) -> Optional[ProtocolDecoder]:
        """Auto-detect protocol from raw data."""
        best_decoder = None
        best_confidence = 0.0

        for decoder in self._decoders.values():
            try:
                confidence = decoder.can_decode(raw_data)
                if confidence > best_confidence:
                    best_confidence = confidence
                    best_decoder = decoder
            except Exception:
                continue

        if best_confidence > 0.3:
            return best_decoder
        return None

    def decode(self, protocol_id: str, raw_data: bytes) -> Dict[str, Any]:
        decoder = self._decoders.get(protocol_id)
        if decoder:
            return decoder.decode(raw_data)
        return {"type": "unknown", "raw": raw_data.hex()}

    def list_decoders(self) -> List[Dict[str, str]]:
        return [
            {
                "id": d.protocol_id,
                "name": d.name,
                "description": d.description,
            }
            for d in self._decoders.values()
        ]


# Singleton
protocol_manager = ProtocolManager()
