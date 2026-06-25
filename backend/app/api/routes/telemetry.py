"""Telemetry API routes."""
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List
from datetime import datetime

from app.database import get_db
from app.core.telemetry_engine import telemetry_engine

router = APIRouter(prefix="/telemetry", tags=["telemetry"])


@router.get("/history/{device_id}")
async def get_history(
    device_id: str,
    metric_name: Optional[str] = None,
    limit: int = Query(default=1000, le=10000),
):
    """Get telemetry history for a device."""
    if metric_name:
        history = telemetry_engine.get_history(device_id, metric_name, limit)
    else:
        all_metrics = telemetry_engine.get_all_metrics(device_id)
        history = []
        for name, metrics in all_metrics.items():
            history.extend(metrics)
        history.sort(key=lambda m: m.timestamp)
        history = history[-limit:]

    return {
        "device_id": device_id,
        "metric_name": metric_name,
        "points": [
            {
                "timestamp": m.timestamp.isoformat(),
                "metric_name": m.name,
                "value": m.value,
                "unit": m.unit,
            }
            for m in history
        ],
        "count": len(history),
    }


@router.get("/latest/{device_id}")
async def get_latest_values(device_id: str):
    """Get the most recent value for each metric."""
    values = telemetry_engine.get_latest_values(device_id)
    return {"device_id": device_id, "values": values}


@router.get("/metrics/{device_id}")
async def list_metrics(device_id: str):
    """List all available metrics for a device."""
    all_metrics = telemetry_engine.get_all_metrics(device_id)
    return {
        "device_id": device_id,
        "metrics": [
            {"name": name, "count": len(history), "latest": history[-1].value if history else None}
            for name, history in all_metrics.items()
        ],
    }


@router.delete("/{device_id}")
async def clear_telemetry(device_id: str):
    """Clear telemetry history for a device."""
    telemetry_engine.clear_history(device_id)
    return {"status": "cleared", "device_id": device_id}
