"""UARTScope Pro configuration."""
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    app_name: str = "UARTScope Pro"
    app_version: str = "2.0.1"
    debug: bool = False

    # Database
    database_url: str = "sqlite+aiosqlite:///./uartscope.db"
    # For PostgreSQL: postgresql+asyncpg://user:pass@localhost/uartscope

    # Serial defaults
    # Not yet wired: DeviceCreate in app/models/__init__.py hardcodes
    # baudrate=115200. A future change should read this as the default.
    default_baudrate: int = 115200
    serial_timeout: float = 1.0

    # Telemetry
    max_history_per_metric: int = 10000

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
    # sandbox, so this is OFF by default. The install route enforces this;
    # it is not advisory.
    plugin_install_enabled: bool = False

    # MQTT
    mqtt_enabled: bool = False
    mqtt_broker: str = "localhost"
    mqtt_port: int = 1883
    mqtt_topic_prefix: str = "uartscope"

    class Config:
        env_prefix = "UARTSCOPE_"


settings = Settings()
