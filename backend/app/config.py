"""UARTScope Pro configuration."""
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    app_name: str = "UARTScope Pro"
    app_version: str = "0.1.0"
    debug: bool = False

    # Server
    host: str = "0.0.0.0"
    port: int = 8080

    # Database
    database_url: str = "sqlite+aiosqlite:///./uartscope.db"
    # For PostgreSQL: postgresql+asyncpg://user:pass@localhost/uartscope

    # Serial defaults
    default_baudrate: int = 115200
    serial_timeout: float = 1.0

    # Telemetry
    max_history_per_metric: int = 10000
    telemetry_buffer_size: int = 500

    # Sessions
    sessions_dir: str = "./sessions"
    max_session_size_mb: int = 500

    # MQTT
    mqtt_enabled: bool = False
    mqtt_broker: str = "localhost"
    mqtt_port: int = 1883
    mqtt_topic_prefix: str = "uartscope"

    # Alerts
    alert_check_interval: float = 2.0

    class Config:
        env_prefix = "UARTSCOPE_"


settings = Settings()
