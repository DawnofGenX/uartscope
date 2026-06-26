"""Performance Analytics API routes."""
from fastapi import APIRouter

from app.core.performance_tracker import performance_tracker

router = APIRouter(prefix="/performance", tags=["performance"])


@router.get("/summary")
async def get_performance_summary():
    """Get comprehensive performance summary across all devices."""
    return performance_tracker.get_summary()


@router.get("/snapshot")
async def get_current_snapshot():
    """Get current real-time snapshot."""
    return performance_tracker.get_global_snapshot()


@router.get("/history")
async def get_history():
    """Get historical performance snapshots."""
    return {"history": performance_tracker.get_history()}


@router.get("/device/{device_id}")
async def get_device_performance(device_id: str):
    """Get performance metrics for a specific device."""
    perf = performance_tracker.get_device_perf(device_id)
    if not perf:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Device not found")
    return {
        "device_id": perf.device_id,
        "device_name": perf.device_name,
        "connected_at": perf.connected_at.isoformat() if perf.connected_at else None,
        "uptime_seconds": perf.uptime_seconds,
        "total_bytes": perf.total_bytes,
        "total_packets": perf.total_packets,
        "error_count": perf.error_count,
        "checksum_errors": perf.checksum_errors,
        "parse_errors": perf.parse_errors,
        "timeout_errors": perf.timeout_errors,
        "avg_latency_ms": perf.avg_latency_ms,
        "min_latency_ms": perf.min_latency_ms,
        "max_latency_ms": perf.max_latency_ms,
        "current_packet_rate": perf.current_packet_rate,
        "current_throughput": perf.current_throughput,
        "avg_packet_rate": perf.avg_packet_rate,
        "avg_throughput": perf.avg_throughput,
        "error_rate_per_min": perf.error_rate,
        "packet_rate_history": [
            {"ts": ts, "rate": round(rate, 2)}
            for ts, rate in perf.packet_rate_history[-60:]
        ],
        "throughput_history": [
            {"ts": ts, "rate": round(rate, 2)}
            for ts, rate in perf.throughput_history[-60:]
        ],
    }
