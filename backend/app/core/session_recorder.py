"""Session Recorder — records complete debugging sessions for replay and analysis."""
import asyncio
import json
import logging
import os
from datetime import datetime
from typing import List, Optional, Dict, Any

from app.config import settings

logger = logging.getLogger(__name__)


class SessionRecorder:
    """Records and replays debugging sessions."""

    def __init__(self):
        self._sessions: Dict[str, Dict[str, Any]] = {}  # session_id -> session data
        self._active_sessions: Dict[str, bool] = {}

    def _ensure_dir(self):
        os.makedirs(settings.sessions_dir, exist_ok=True)

    async def start_session(self, session_id: str, device_id: Optional[str] = None, name: Optional[str] = None):
        """Initialize a new recording session."""
        self._ensure_dir()
        self._sessions[session_id] = {
            "id": session_id,
            "device_id": device_id,
            "name": name or f"Session {session_id[:8]}",
            "started_at": datetime.utcnow().isoformat(),
            "packets": [],
            "metrics": [],
            "events": [],
        }
        self._active_sessions[session_id] = True
        logger.info(f"Session recording started: {session_id}")

    async def stop_session(self, session_id: str):
        """Stop recording a session."""
        self._active_sessions.pop(session_id, None)
        session = self._sessions.get(session_id)
        if session:
            session["ended_at"] = datetime.utcnow().isoformat()
            # Persist to disk
            await self._save_session(session_id)
            logger.info(f"Session recording stopped: {session_id}")

    async def record_packet(self, session_id: str, packet: Dict[str, Any]):
        """Record a data packet."""
        if not self._active_sessions.get(session_id):
            return
        session = self._sessions.get(session_id)
        if session:
            # Keep in-memory buffer limited
            if len(session["packets"]) < settings.max_session_size_mb * 2000:
                session["packets"].append({**packet, "ts": datetime.utcnow().isoformat()})

    async def record_metric(self, session_id: str, metric: Dict[str, Any]):
        """Record a telemetry metric."""
        if not self._active_sessions.get(session_id):
            return
        session = self._sessions.get(session_id)
        if session:
            if len(session["metrics"]) < settings.max_session_size_mb * 2000:
                session["metrics"].append({**metric, "ts": datetime.utcnow().isoformat()})

    async def record_event(self, session_id: str, event: Dict[str, Any]):
        """Record a session event (connect, disconnect, error, etc.)."""
        if not self._active_sessions.get(session_id):
            return
        session = self._sessions.get(session_id)
        if session:
            session["events"].append({**event, "ts": datetime.utcnow().isoformat()})

    async def _save_session(self, session_id: str):
        """Persist session to disk."""
        session = self._sessions.get(session_id)
        if not session:
            return
        filepath = os.path.join(settings.sessions_dir, f"{session_id}.json")
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: json.dump(session, open(filepath, "w"), indent=2, default=str)
        )
        logger.info(f"Session saved to {filepath}")

    async def load_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Load a session from disk."""
        filepath = os.path.join(settings.sessions_dir, f"{session_id}.json")
        if not os.path.exists(filepath):
            return self._sessions.get(session_id)
        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(
            None,
            lambda: json.load(open(filepath))
        )
        return data

    def get_session_info(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get session metadata without full data."""
        session = self._sessions.get(session_id)
        if session:
            return {
                "id": session["id"],
                "name": session["name"],
                "device_id": session["device_id"],
                "started_at": session["started_at"],
                "ended_at": session.get("ended_at"),
                "status": "recording" if self._active_sessions.get(session_id) else "completed",
                "packet_count": len(session["packets"]),
                "metric_count": len(session["metrics"]),
                "event_count": len(session["events"]),
            }
        # Check disk
        if os.path.exists(settings.sessions_dir):
            filepath = os.path.join(settings.sessions_dir, f"{session_id}.json")
            if os.path.exists(filepath):
                try:
                    data = json.load(open(filepath))
                    return {
                        "id": data["id"],
                        "name": data.get("name", f"Session {session_id[:8]}"),
                        "device_id": data.get("device_id"),
                        "started_at": data.get("started_at"),
                        "ended_at": data.get("ended_at"),
                        "status": "completed",
                        "packet_count": len(data.get("packets", [])),
                        "metric_count": len(data.get("metrics", [])),
                        "event_count": len(data.get("events", [])),
                    }
                except Exception:
                    pass
        return None

    def rename_session(self, session_id: str, name: str) -> bool:
        """Rename a session."""
        session = self._sessions.get(session_id)
        if session:
            session["name"] = name
            return True
        # Check disk
        if os.path.exists(settings.sessions_dir):
            filepath = os.path.join(settings.sessions_dir, f"{session_id}.json")
            if os.path.exists(filepath):
                try:
                    data = json.load(open(filepath))
                    data["name"] = name
                    json.dump(data, open(filepath, "w"), indent=2, default=str)
                    return True
                except Exception:
                    pass
        return False

    def list_sessions(self) -> List[Dict[str, Any]]:
        """List all sessions."""
        sessions = []
        for sid, session in self._sessions.items():
            sessions.append({
                "id": sid,
                "name": session["name"],
                "device_id": session["device_id"],
                "started_at": session["started_at"],
                "ended_at": session.get("ended_at"),
                "status": "recording" if self._active_sessions.get(sid) else "completed",
                "packet_count": len(session["packets"]),
                "metric_count": len(session["metrics"]),
                "event_count": len(session["events"]),
            })
        # Also scan disk
        if os.path.exists(settings.sessions_dir):
            for f in os.listdir(settings.sessions_dir):
                if f.endswith(".json") and f[:-5] not in self._sessions:
                    sid = f[:-5]
                    filepath = os.path.join(settings.sessions_dir, f)
                    try:
                        data = json.load(open(filepath))
                        sessions.append({
                            "id": sid,
                            "name": data.get("name", f"Session {sid[:8]}"),
                            "device_id": data.get("device_id"),
                            "started_at": data.get("started_at"),
                            "ended_at": data.get("ended_at"),
                            "status": "completed",
                            "packet_count": len(data.get("packets", [])),
                            "metric_count": len(data.get("metrics", [])),
                            "event_count": len(data.get("events", [])),
                        })
                    except Exception:
                        pass
        return sessions


# Singleton
session_recorder = SessionRecorder()
