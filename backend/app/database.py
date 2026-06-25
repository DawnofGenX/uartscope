"""Database setup and models for UARTScope Pro."""
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Float, Integer, DateTime, Text, JSON, Boolean
from datetime import datetime
from typing import Optional
import uuid

from app.config import settings


engine = create_async_engine(settings.database_url, echo=settings.debug)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class DeviceModel(Base):
    __tablename__ = "devices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    port: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    protocol: Mapped[str] = mapped_column(String(50), default="serial")
    baudrate: Mapped[int] = mapped_column(Integer, default=115200)
    status: Mapped[str] = mapped_column(String(20), default="disconnected")
    board_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    metadata_json: Mapped[Optional[str]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_seen: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class TelemetryModel(Base):
    __tablename__ = "telemetry"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[str] = mapped_column(String(36), index=True)
    session_id: Mapped[str] = mapped_column(String(36), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    metric_name: Mapped[str] = mapped_column(String(100), index=True)
    value: Mapped[float] = mapped_column(Float)
    unit: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    raw_line: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    message_type: Mapped[str] = mapped_column(String(20), default="metric")  # metric, log, packet


class SessionModel(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    device_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active")
    packet_count: Mapped[int] = mapped_column(Integer, default=0)
    bytes_received: Mapped[int] = mapped_column(Integer, default=0)
    metadata_json: Mapped[Optional[str]] = mapped_column(JSON, nullable=True)


class AlertRuleModel(Base):
    __tablename__ = "alert_rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255))
    metric_name: Mapped[str] = mapped_column(String(100))
    condition: Mapped[str] = mapped_column(String(20))  # gt, lt, eq, gte, lte, range, change
    threshold: Mapped[float] = mapped_column(Float)
    secondary_threshold: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    cooldown_seconds: Mapped[int] = mapped_column(Integer, default=60)
    severity: Mapped[str] = mapped_column(String(20), default="warning")  # info, warning, critical
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AlertModel(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rule_id: Mapped[str] = mapped_column(String(36))
    device_id: Mapped[str] = mapped_column(String(36))
    session_id: Mapped[str] = mapped_column(String(36))
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    metric_name: Mapped[str] = mapped_column(String(100))
    value: Mapped[float] = mapped_column(Float)
    message: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(20))
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)


class PacketModel(Base):
    __tablename__ = "packets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[str] = mapped_column(String(36), index=True)
    session_id: Mapped[str] = mapped_column(String(36), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    direction: Mapped[str] = mapped_column(String(10), default="rx")  # rx, tx
    raw_data: Mapped[str] = mapped_column(Text)
    decoded_data: Mapped[Optional[str]] = mapped_column(JSON, nullable=True)
    protocol: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db() -> AsyncSession:
    async with async_session() as session:
        yield session
