"""Protocol Decoder — extensible plugin-based protocol decoding framework."""
import logging
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

    def can_decode(self, raw_data: bytes) -> float:
        try:
            text = raw_data.decode("utf-8")
            # Check for common UART patterns
            if text.startswith("AT+") or text.startswith("$G"):
                return 0.9
            if any(c.isalpha() for c in text) and text.strip().endswith("\n"):
                return 0.5
        except (UnicodeDecodeError, AttributeError):
            pass
        return 0.0

    def decode(self, raw_data: bytes) -> Dict[str, Any]:
        text = raw_data.decode("utf-8", errors="replace").strip()
        result = {"type": "text", "content": text}

        # AT command response
        if text.startswith("AT+") or text.startswith("AT"):
            result["subtype"] = "at_command"
            result["command"] = text.split("\r")[0]
        # NMEA sentence
        elif text.startswith("$G"):
            result["subtype"] = "nmea"
            parts = text.split(",")
            result["sentence_type"] = parts[0] if parts else "unknown"

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

    def can_decode(self, raw_data: bytes) -> float:
        if len(raw_data) < 4:
            return 0.0
        # Modbus RTU: [addr][func][data...][crc16]
        addr = raw_data[0]
        func = raw_data[1]
        if addr == 0 or addr > 247:
            return 0.0
        if func in [0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x0F, 0x10]:
            return 0.7
        return 0.0

    def decode(self, raw_data: bytes) -> Dict[str, Any]:
        return {
            "type": "modbus_rtu",
            "device_addr": raw_data[0],
            "function_code": raw_data[1],
            "data": raw_data[2:-2].hex() if len(raw_data) > 4 else "",
            "crc": raw_data[-2:].hex() if len(raw_data) >= 2 else "",
        }

    def encode(self, data: Dict[str, Any]) -> bytes:
        # Simplified encoding
        addr = data.get("device_addr", 1)
        func = data.get("function_code", 3)
        return bytes([addr, func, 0, 0])


class ProtocolManager:
    """Manages protocol decoders and auto-detection."""

    def __init__(self):
        self._decoders: Dict[str, ProtocolDecoder] = {}
        self._register_defaults()

    def _register_defaults(self):
        """Register built-in decoders."""
        self.register(UARTTextDecoder())
        self.register(ModbusRTUDecoder())

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
            {"id": d.protocol_id, "name": d.name}
            for d in self._decoders.values()
        ]


# Singleton
protocol_manager = ProtocolManager()
