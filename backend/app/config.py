"""UARTScope Pro configuration."""
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    app_name: str = "UARTScope Pro"
    app_version: str = "2.0.1"
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

    # Plugin marketplace
    # Where the registry manifest lives. A path or http(s) URL; a path is
    # resolved against the packaged `registry/` directory by default. Empty
    # disables the marketplace, and the API says so rather than showing an
    # empty list that looks like a broken registry.
    plugin_registry: str = ""
    plugin_install_dir: str = "./plugins"
    # Installing a plugin runs third-party Python in this process. There is no
    # sandbox, so this stays off unless the operator turns it on deliberately.
    plugin_install_enabled: bool = True

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
