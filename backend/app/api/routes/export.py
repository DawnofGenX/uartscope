"""Export API routes — CSV, JSON, and other formats."""
import csv
import io
import json
from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from typing import Optional

from app.core.telemetry_engine import telemetry_engine
from app.core.session_recorder import session_recorder

router = APIRouter(prefix="/export", tags=["export"])


@router.get("/csv/{device_id}")
async def export_csv(
    device_id: str,
    metric_name: Optional[str] = None,
    session_id: Optional[str] = None,
):
    """Export telemetry data as CSV."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["timestamp", "device_id", "metric_name", "value", "unit", "session_id"])

    if session_id:
        session = await session_recorder.load_session(session_id)
        if session:
            for m in session.get("metrics", []):
                if not metric_name or m.get("metric_name", "").upper() == metric_name.upper():
                    writer.writerow([
                        m.get("ts", ""),
                        device_id,
                        m.get("metric_name", ""),
                        m.get("value", ""),
                        m.get("unit", ""),
                        session_id,
                    ])
    else:
        all_metrics = telemetry_engine.get_all_metrics(device_id)
        for name, metrics in all_metrics.items():
            if metric_name and name.upper() != metric_name.upper():
                continue
            for m in metrics:
                writer.writerow([
                    m.timestamp.isoformat(),
                    device_id,
                    m.name,
                    m.value,
                    m.unit or "",
                    "",
                ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=uartscope_{device_id}.csv"},
    )


@router.get("/json/{device_id}")
async def export_json(
    device_id: str,
    metric_name: Optional[str] = None,
    limit: int = Query(default=10000, le=50000),
):
    """Export telemetry data as JSON."""
    all_metrics = telemetry_engine.get_all_metrics(device_id)
    data = {
        "device_id": device_id,
        "exported_at": __import__("datetime").datetime.utcnow().isoformat(),
        "metrics": {},
    }
    for name, metrics in all_metrics.items():
        if metric_name and name.upper() != metric_name.upper():
            continue
        data["metrics"][name] = [
            {"timestamp": m.timestamp.isoformat(), "value": m.value, "unit": m.unit}
            for m in metrics[-limit:]
        ]

    return data


@router.get("/session/{session_id}")
async def export_session_json(session_id: str):
    """Export a complete session as JSON."""
    session = await session_recorder.load_session(session_id)
    if not session:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Session not found")
    return session
