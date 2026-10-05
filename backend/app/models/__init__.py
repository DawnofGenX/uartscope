"""Pydantic models for API schemas."""
from pydantic import BaseModel, Field, field_validator, model_validator
from datetime import datetime
from typing import Optional, List, Dict, Any


# Valid pyserial parity values
VALID_PARITY = {"N", "E", "O", "M", "S"}
# Valid pyserial stopbits values
VALID_STOPBITS = {1.0, 1.5, 2.0}


# Device schemas
class DeviceCreate(BaseModel):
    name: Optional[str] = None
    port: str
    protocol: str = "serial"
    baudrate: int = 115200
    board_type: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    parity: str = "N"
    stopbits: float = 1.0

    @model_validator(mode="before")
    @classmethod
    def extract_serial_config_from_metadata(cls, data):
        """Read parity/stopbits from metadata if not explicitly provided.

        When a device is loaded from the DB, devices.py constructs
        DeviceCreate without parity/stopbits. The values are in
        metadata_json (injected at create time). This validator pulls
        them back out so the device reconnects with the same settings.
        """
        if isinstance(data, dict):
            metadata = data.get("metadata") or {}
            if "parity" not in data and "parity" in metadata:
                data["parity"] = metadata["parity"]
            if "stopbits" not in data and "stopbits" in metadata:
                data["stopbits"] = metadata["stopbits"]
        return data

    @field_validator("parity")
    @classmethod
    def validate_parity(cls, v: str) -> str:
        if v not in VALID_PARITY:
            raise ValueError(f"parity must be one of {VALID_PARITY}, got {v!r}")
        return v

    @field_validator("stopbits")
    @classmethod
    def validate_stopbits(cls, v: float) -> float:
        if v not in VALID_STOPBITS:
            raise ValueError(f"stopbits must be one of {VALID_STOPBITS}, got {v!r}")
        return v

    @model_validator(mode="after")
    def inject_serial_config_into_metadata(self):
        """Ensure parity/stopbits are persisted in metadata_json.

        The DB has no dedicated columns for serial line settings (and no
        migration path to add them). Storing them in metadata_json means
        they survive a DB round-trip without any schema change.
        """
        if self.metadata is None:
            self.metadata = {}
        self.metadata["parity"] = self.parity
        self.metadata["stopbits"] = self.stopbits
        return self


class DeviceResponse(BaseModel):
    id: str
    name: Optional[str]
    port: str
    protocol: str
    baudrate: int
    status: str
    board_type: Optional[str]
    metadata_json: Optional[Dict[str, Any]]
    created_at: datetime
    last_seen: Optional[datetime]
    parity: str = "N"
    stopbits: float = 1.0

    class Config:
        from_attributes = True


class DeviceStatus(BaseModel):
    status: str


# Telemetry schemas
class TelemetryPoint(BaseModel):
    timestamp: datetime
    metric_name: str
    value: float
    unit: Optional[str] = None
    message_type: str = "metric"


class TelemetryBatch(BaseModel):
    device_id: str
    session_id: str
    points: List[TelemetryPoint]


class TelemetryQuery(BaseModel):
    device_id: str
    metric_name: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    limit: int = 1000


# Session schemas
class SessionCreate(BaseModel):
    device_id: Optional[str] = None
    name: Optional[str] = None


class SessionResponse(BaseModel):
    id: str
    device_id: Optional[str]
    name: Optional[str]
    started_at: datetime
    ended_at: Optional[datetime]
    status: str
    packet_count: int
    bytes_received: int

    class Config:
        from_attributes = True


# Alert schemas
class AlertRuleCreate(BaseModel):
    name: str
    metric_name: str
    condition: str = Field(..., pattern="^(gt|lt|eq|gte|lte|range|change)$")
    threshold: float
    secondary_threshold: Optional[float] = None
    cooldown_seconds: int = 60
    severity: str = "warning"


class AlertRuleResponse(AlertRuleCreate):
    id: str
    enabled: bool
    created_at: datetime

    class Config:
        from_attributes = True


class AlertEvent(BaseModel):
    id: int
    rule_id: str
    device_id: str
    session_id: str
    timestamp: datetime
    metric_name: str
    value: float
    message: str
    severity: str
    acknowledged: bool


# Packet schemas
class PacketResponse(BaseModel):
    id: int
    device_id: str
    session_id: str
    timestamp: datetime
    direction: str
    raw_data: str
    decoded_data: Optional[Dict[str, Any]]
    protocol: Optional[str]
    size_bytes: int


# WebSocket messages
class WSMessage(BaseModel):
    type: str  # telemetry, packet, alert, device_status
    data: Dict[str, Any]
    timestamp: datetime = Field(default_factory=datetime.utcnow)
