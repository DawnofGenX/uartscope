"""Pydantic models for API schemas."""
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, List, Dict, Any


# Device schemas
class DeviceCreate(BaseModel):
    name: Optional[str] = None
    port: str
    protocol: str = "serial"
    baudrate: int = 115200
    board_type: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


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
