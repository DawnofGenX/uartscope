"""Telemetry Engine — parses incoming data, classifies messages, extracts metrics."""
import asyncio
import logging
import re
from datetime import datetime
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass, field

from app.config import settings

logger = logging.getLogger(__name__)

# Pattern to extract metrics like TEMP:25, VOLTAGE:3.3, HUMIDITY:60
METRIC_PATTERN = re.compile(
    r'([A-Z][A-Z0-9_]+)\s*[:=]\s*(-?\d+\.?\d*)\s*([A-Za-z%°]*)'
)

# Pattern for JSON-like structured data: {"temp": 25.5, "humidity": 60}
JSON_METRIC_KEYS = {"temp", "temperature", "humidity", "voltage", "current",
                    "power", "pressure", "altitude", "speed", "rpm",
                    "adc", "pwm", "freq", "frequency", "rssi", "snr"}


@dataclass
class Metric:
    name: str
    value: float
    unit: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ParsedMessage:
    raw: str
    timestamp: datetime
    message_type: str  # "metric", "log", "packet", "json"
    metrics: List[Metric] = field(default_factory=list)
    log_level: Optional[str] = None
    decoded: Optional[Dict[str, Any]] = None


class TelemetryEngine:
    """Parses incoming serial data streams and extracts telemetry."""

    def __init__(self):
        self._callbacks: List[Callable[[ParsedMessage], None]] = []
        self._buffer: Dict[str, str] = {}  # device_id -> line buffer
        self._metrics_history: Dict[str, List[Metric]] = {}  # metric_name -> history
        self._lock = asyncio.Lock()

    def register_callback(self, fn: Callable[[ParsedMessage], None]):
        """Register a callback for parsed messages."""
        self._callbacks.append(fn)

    async def process_line(self, device_id: str, session_id: str, raw_line: str):
        """Process a single line of data from a device."""
        raw_line = raw_line.strip()
        if not raw_line:
            return

        msg = self._parse(raw_line)
        device_key = f"{device_id}:{msg.timestamp.isoformat()}"

        # Store metrics in history
        async with self._lock:
            for metric in msg.metrics:
                key = f"{device_id}:{metric.name}"
                if key not in self._metrics_history:
                    self._metrics_history[key] = []
                self._metrics_history[key].append(metric)
                # Trim to max size
                if len(self._metrics_history[key]) > settings.max_history_per_metric:
                    self._metrics_history[key] = self._metrics_history[key][-settings.max_history_per_metric:]

        # Notify callbacks
        for cb in self._callbacks:
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(msg)
                else:
                    cb(msg)
            except Exception as e:
                logger.error(f"Callback error: {e}")

    def _parse(self, line: str) -> ParsedMessage:
        """Parse a line into structured data."""
        msg = ParsedMessage(raw=line, timestamp=datetime.utcnow(), message_type="log")

        # Try JSON parsing first
        if line.startswith("{") and line.endswith("}"):
            try:
                import json
                data = json.loads(line)
                msg.message_type = "json"
                msg.decoded = data
                for key, val in data.items():
                    if isinstance(val, (int, float)) and key.lower() in JSON_METRIC_KEYS:
                        metric = Metric(
                            name=key.upper(),
                            value=float(val),
                            unit=self._infer_unit(key),
                            timestamp=msg.timestamp,
                        )
                        msg.metrics.append(metric)
                if msg.metrics:
                    return msg
            except (json.JSONDecodeError, ValueError):
                pass

        # Try KEY:VALUE pattern
        matches = METRIC_PATTERN.findall(line)
        if matches:
            msg.message_type = "metric"
            for name, value_str, unit in matches:
                try:
                    value = float(value_str)
                    metric = Metric(
                        name=name,
                        value=value,
                        unit=unit if unit else None,
                        timestamp=msg.timestamp,
                    )
                    msg.metrics.append(metric)
                except ValueError:
                    continue
            return msg

        # Detect log levels
        line_upper = line.upper()
        for level in ["ERROR", "WARN", "WARNING", "INFO", "DEBUG", "TRACE"]:
            if level in line_upper:
                msg.log_level = level
                break

        return msg

    def _infer_unit(self, key: str) -> Optional[str]:
        """Infer unit from metric name."""
        key_lower = key.lower()
        unit_map = {
            "temp": "°C", "temperature": "°C",
            "humidity": "%",
            "voltage": "V", "current": "A", "power": "W",
            "pressure": "hPa", "altitude": "m",
            "speed": "m/s", "rpm": "RPM",
            "rssi": "dBm", "snr": "dB",
            "freq": "Hz", "frequency": "Hz",
        }
        return unit_map.get(key_lower)

    def get_history(self, device_id: str, metric_name: str, limit: int = 1000) -> List[Metric]:
        """Get historical metrics for a device."""
        key = f"{device_id}:{metric_name}"
        history = self._metrics_history.get(key, [])
        return history[-limit:]

    def get_all_metrics(self, device_id: str) -> Dict[str, List[Metric]]:
        """Get all metric history for a device."""
        result = {}
        prefix = f"{device_id}:"
        for key, history in self._metrics_history.items():
            if key.startswith(prefix):
                metric_name = key[len(prefix):]
                result[metric_name] = history
        return result

    def get_latest_values(self, device_id: str) -> Dict[str, float]:
        """Get the most recent value for each metric."""
        result = {}
        prefix = f"{device_id}:"
        for key, history in self._metrics_history.items():
            if key.startswith(prefix) and history:
                metric_name = key[len(prefix):]
                result[metric_name] = history[-1].value
        return result

    def clear_history(self, device_id: Optional[str] = None):
        """Clear metric history."""
        if device_id:
            prefix = f"{device_id}:"
            keys_to_remove = [k for k in self._metrics_history if k.startswith(prefix)]
            for k in keys_to_remove:
                del self._metrics_history[k]
        else:
            self._metrics_history.clear()


# Singleton
telemetry_engine = TelemetryEngine()
