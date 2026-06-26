"""Performance Analytics — packet rate, throughput, latency, error tracking, uptime."""
import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class DevicePerformance:
    """Real-time performance metrics for a single device."""
    device_id: str
    device_name: str = ""
    connected_at: Optional[datetime] = None
    disconnected_at: Optional[datetime] = None
    total_bytes: int = 0
    total_packets: int = 0
    error_count: int = 0
    checksum_errors: int = 0
    parse_errors: int = 0
    timeout_errors: int = 0
    latencies: List[float] = field(default_factory=list)  # last 100 latency samples (ms)
    packet_rate_history: List[tuple] = field(default_factory=list)  # (timestamp, rate_pps)
    throughput_history: List[tuple] = field(default_factory=list)  # (timestamp, bytes_per_sec)
    _last_packet_time: Optional[float] = None
    _window_start: Optional[float] = None
    _window_bytes: int = 0
    _window_packets: int = 0

    @property
    def uptime_seconds(self) -> float:
        if not self.connected_at:
            return 0
        end = self.disconnected_at or datetime.utcnow()
        return (end - self.connected_at).total_seconds()

    @property
    def avg_latency_ms(self) -> float:
        if not self.latencies:
            return 0
        return sum(self.latencies) / len(self.latencies)

    @property
    def max_latency_ms(self) -> float:
        return max(self.latencies) if self.latencies else 0

    @property
    def min_latency_ms(self) -> float:
        return min(self.latencies) if self.latencies else 0

    @property
    def current_packet_rate(self) -> float:
        """Packets per second (last 10s window)."""
        if not self._window_start:
            return 0
        elapsed = time.time() - self._window_start
        if elapsed < 0.1:
            return 0
        return self._window_packets / elapsed

    @property
    def current_throughput(self) -> float:
        """Bytes per second (last 10s window)."""
        if not self._window_start:
            return 0
        elapsed = time.time() - self._window_start
        if elapsed < 0.1:
            return 0
        return self._window_bytes / elapsed

    @property
    def avg_packet_rate(self) -> float:
        """Average packets per second over entire session."""
        uptime = self.uptime_seconds
        if uptime < 1:
            return 0
        return self.total_packets / uptime

    @property
    def avg_throughput(self) -> float:
        """Average bytes per second over entire session."""
        uptime = self.uptime_seconds
        if uptime < 1:
            return 0
        return self.total_bytes / uptime

    @property
    def error_rate(self) -> float:
        """Errors per minute."""
        uptime = self.uptime_seconds
        if uptime < 1:
            return 0
        return (self.error_count / uptime) * 60

    @property
    def packet_loss_estimate(self) -> float:
        """Estimate packet loss based on sequence gaps (if available). Placeholder."""
        return 0.0


class PerformanceTracker:
    """Tracks performance metrics across all devices."""

    def __init__(self):
        self._device_perf: Dict[str, DevicePerformance] = {}
        self._global_history: List[Dict] = []  # aggregated snapshots
        self._lock = asyncio.Lock()
        self._snapshot_interval = 5.0  # seconds
        self._max_history = 720  # 1 hour at 5s intervals
        self._running = False

    async def start(self):
        """Start background snapshot collection."""
        if not self._running:
            self._running = True
            asyncio.create_task(self._snapshot_loop())
            logger.info("Performance tracker started")

    async def stop(self):
        self._running = False

    async def _snapshot_loop(self):
        """Periodically capture global performance snapshots."""
        while self._running:
            await asyncio.sleep(self._snapshot_interval)
            snapshot = self.get_global_snapshot()
            async with self._lock:
                self._global_history.append(snapshot)
                if len(self._global_history) > self._max_history:
                    self._global_history = self._global_history[-self._max_history:]

    async def on_device_connected(self, device_id: str, device_name: str = ""):
        async with self._lock:
            if device_id not in self._device_perf:
                self._device_perf[device_id] = DevicePerformance(
                    device_id=device_id,
                    device_name=device_name,
                    connected_at=datetime.utcnow(),
                )
            else:
                self._device_perf[device_id].connected_at = datetime.utcnow()
                self._device_perf[device_id].disconnected_at = None
                self._device_perf[device_id].device_name = device_name

    async def on_device_disconnected(self, device_id: str):
        async with self._lock:
            perf = self._device_perf.get(device_id)
            if perf:
                perf.disconnected_at = datetime.utcnow()

    async def on_packet_received(self, device_id: str, byte_count: int, latency_ms: Optional[float] = None):
        async with self._lock:
            perf = self._device_perf.get(device_id)
            if not perf:
                return

            now = time.time()
            perf.total_bytes += byte_count
            perf.total_packets += 1

            # Sliding window (10s)
            if perf._window_start is None or (now - perf._window_start) > 10:
                perf._window_start = now
                perf._window_bytes = 0
                perf._window_packets = 0
            perf._window_bytes += byte_count
            perf._window_packets += 1

            # Latency
            if latency_ms is not None:
                perf.latencies.append(latency_ms)
                if len(perf.latencies) > 100:
                    perf.latencies = perf.latencies[-100:]

            # Record packet rate snapshot
            perf.packet_rate_history.append((now, perf.current_packet_rate))
            if len(perf.packet_rate_history) > 200:
                perf.packet_rate_history = perf.packet_rate_history[-200:]

            # Record throughput snapshot
            perf.throughput_history.append((now, perf.current_throughput))
            if len(perf.throughput_history) > 200:
                perf.throughput_history = perf.throughput_history[-200:]

            perf._last_packet_time = now

    async def on_error(self, device_id: str, error_type: str = "generic"):
        async with self._lock:
            perf = self._device_perf.get(device_id)
            if not perf:
                return
            perf.error_count += 1
            if error_type == "checksum":
                perf.checksum_errors += 1
            elif error_type == "parse":
                perf.parse_errors += 1
            elif error_type == "timeout":
                perf.timeout_errors += 1

    def get_device_perf(self, device_id: str) -> Optional[DevicePerformance]:
        return self._device_perf.get(device_id)

    def get_all_perf(self) -> Dict[str, DevicePerformance]:
        return dict(self._device_perf)

    def get_global_snapshot(self) -> Dict:
        """Get a global aggregated snapshot."""
        total_bytes = sum(p.total_bytes for p in self._device_perf.values())
        total_packets = sum(p.total_packets for p in self._device_perf.values())
        total_errors = sum(p.error_count for p in self._device_perf.values())
        connected_count = sum(1 for p in self._device_perf.values() if p.connected_at and not p.disconnected_at)

        all_latencies = []
        for p in self._device_perf.values():
            all_latencies.extend(p.latencies)

        avg_latency = sum(all_latencies) / len(all_latencies) if all_latencies else 0

        current_pps = sum(p.current_packet_rate for p in self._device_perf.values())
        current_bps = sum(p.current_throughput for p in self._device_perf.values())

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "connected_devices": connected_count,
            "total_bytes": total_bytes,
            "total_packets": total_packets,
            "total_errors": total_errors,
            "current_packet_rate": round(current_pps, 2),
            "current_throughput": round(current_bps, 2),
            "avg_latency_ms": round(avg_latency, 2),
        }

    def get_history(self) -> List[Dict]:
        return list(self._global_history)

    def get_summary(self) -> Dict:
        """Get comprehensive performance summary."""
        all_perf = self._device_perf
        if not all_perf:
            return {
                "total_bytes": 0, "total_packets": 0, "total_errors": 0,
                "avg_latency_ms": 0, "avg_packet_rate": 0, "avg_throughput": 0,
                "error_rate_per_min": 0, "devices": {},
            }

        total_bytes = sum(p.total_bytes for p in all_perf.values())
        total_packets = sum(p.total_packets for p in all_perf.values())
        total_errors = sum(p.error_count for p in all_perf.values())
        total_uptime = sum(p.uptime_seconds for p in all_perf.values())

        all_latencies = []
        for p in all_perf.values():
            all_latencies.extend(p.latencies)

        avg_latency = sum(all_latencies) / len(all_latencies) if all_latencies else 0
        avg_pps = total_packets / max(total_uptime, 1)
        avg_bps = total_bytes / max(total_uptime, 1)
        error_rate = (total_errors / max(total_uptime, 1)) * 60

        devices_summary = {}
        for dev_id, p in all_perf.items():
            devices_summary[dev_id] = {
                "name": p.device_name,
                "uptime_seconds": round(p.uptime_seconds, 1),
                "total_bytes": p.total_bytes,
                "total_packets": p.total_packets,
                "error_count": p.error_count,
                "avg_latency_ms": round(p.avg_latency_ms, 2),
                "current_packet_rate": round(p.current_packet_rate, 2),
                "current_throughput": round(p.current_throughput, 2),
                "avg_packet_rate": round(p.avg_packet_rate, 2),
                "avg_throughput": round(p.avg_throughput, 2),
                "error_rate_per_min": round(p.error_rate, 2),
                "checksum_errors": p.checksum_errors,
                "parse_errors": p.parse_errors,
                "timeout_errors": p.timeout_errors,
            }

        return {
            "total_bytes": total_bytes,
            "total_packets": total_packets,
            "total_errors": total_errors,
            "avg_latency_ms": round(avg_latency, 2),
            "avg_packet_rate": round(avg_pps, 2),
            "avg_throughput": round(avg_bps, 2),
            "error_rate_per_min": round(error_rate, 2),
            "total_uptime_seconds": round(total_uptime, 1),
            "devices": devices_summary,
        }


# Singleton
performance_tracker = PerformanceTracker()
