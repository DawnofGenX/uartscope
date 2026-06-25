"""Session management API routes."""
from fastapi import APIRouter, HTTPException
from typing import Optional, List

from app.core.session_recorder import session_recorder
from app.models import SessionCreate, SessionResponse

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("/", response_model=dict)
async def create_session(create: SessionCreate):
    """Start a new recording session."""
    import uuid
    session_id = str(uuid.uuid4())
    await session_recorder.start_session(
        session_id,
        device_id=create.device_id,
        name=create.name,
    )
    return {"id": session_id, "status": "recording"}


@router.post("/{session_id}/stop")
async def stop_session(session_id: str):
    """Stop a recording session."""
    await session_recorder.stop_session(session_id)
    return {"id": session_id, "status": "stopped"}


@router.get("/{session_id}")
async def get_session(session_id: str):
    """Get session details."""
    session = await session_recorder.load_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.get("/{session_id}/info")
async def get_session_info(session_id: str):
    """Get session metadata."""
    info = session_recorder.get_session_info(session_id)
    if not info:
        raise HTTPException(status_code=404, detail="Session not found")
    return info


@router.get("/", response_model=List[dict])
async def list_sessions():
    """List all sessions."""
    return session_recorder.list_sessions()


@router.get("/{session_id}/packets")
async def get_session_packets(session_id: str, limit: int = 1000):
    """Get packets from a session."""
    session = await session_recorder.load_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session.get("packets", [])[-limit:]


@router.get("/{session_id}/metrics")
async def get_session_metrics(session_id: str, limit: int = 1000):
    """Get metrics from a session."""
    session = await session_recorder.load_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session.get("metrics", [])[-limit:]
