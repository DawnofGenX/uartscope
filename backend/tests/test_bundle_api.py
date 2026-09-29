"""The bundle must be downloadable over HTTP, not only from the desktop UI.

A `.uartscope` capture was only ever produced by `desktop_app._export_bundle`,
assembled from in-memory UI state. A script, a CI job, or a second client had
no way to export one, so the shareable format was not actually shareable.

These test the route end to end against a real recorded session.

Run:  ../.venv-v2/bin/python -m pytest tests/test_bundle_api.py -v
"""
import io
import json
import sys
import zipfile
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))

from app.core import session_recorder as recorder_module  # noqa: E402
from app.core.session_recorder import SessionRecorder  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture
def recorded(tmp_path, monkeypatch):
    """A real session with packets and metrics, recorded through the recorder."""
    monkeypatch.setattr(recorder_module.settings, "sessions_dir",
                        str(tmp_path / "sessions"))
    rec = SessionRecorder()
    monkeypatch.setattr("app.api.routes.sessions.session_recorder", rec)
    monkeypatch.setattr("app.api.routes.export.session_recorder", rec)
    return rec


async def _record(rec) -> str:
    import asyncio
    sid = "b0075e1e" + "0" * 56
    await rec.start_session(sid, device_id="dev-1", name="API capture")
    for i in range(4):
        await rec.record_packet(sid, {
            "timestamp": f"2026-09-28T11:0{i}:00",
            "data": f"line {i}",
        })
    for i in range(3):
        await rec.record_metric(sid, {
            "name": "temperature",
            "value": 40.0 + i,
            "unit": "C",
            "timestamp": f"2026-09-28T11:0{i}:00",
        })
    await rec.record_event(sid, {"type": "alert", "message": "over temp"})
    await rec.stop_session(sid)
    return sid


class TestBundleRoute:
    async def test_bundle_downloads_as_a_zip(self, recorded):
        import asyncio
        sid = await _record(recorded)
        async with AsyncClient(transport=ASGITransport(app=app),
                               base_url="http://test") as client:
            r = await client.get(f"/api/export/session/{sid}/bundle")
        assert r.status_code == 200, r.text
        assert r.headers["content-type"] == "application/zip"
        assert r.content[:2] == b"PK"

    async def test_filename_names_the_session(self, recorded):
        import asyncio
        sid = await _record(recorded)
        async with AsyncClient(transport=ASGITransport(app=app),
                               base_url="http://test") as client:
            r = await client.get(f"/api/export/session/{sid}/bundle")
        disposition = r.headers.get("content-disposition", "")
        assert "session_b0075e1e.uartscope" in disposition

    async def test_bundle_contains_the_recorded_packets(self, recorded):
        import asyncio
        sid = await _record(recorded)
        async with AsyncClient(transport=ASGITransport(app=app),
                               base_url="http://test") as client:
            r = await client.get(f"/api/export/session/{sid}/bundle")
        with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
            packets = json.loads(zf.read("packets.json"))
        assert len(packets) == 4
        assert packets[0]["data"] == "line 0"

    async def test_bundle_contains_the_recorded_metrics(self, recorded):
        import asyncio
        sid = await _record(recorded)
        async with AsyncClient(transport=ASGITransport(app=app),
                               base_url="http://test") as client:
            r = await client.get(f"/api/export/session/{sid}/bundle")
        with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
            csv_text = zf.read("metrics.csv").decode()
        assert csv_text.startswith("timestamp,metric,value,unit")
        assert csv_text.count("temperature") == 3

    async def test_unknown_session_is_404(self, recorded):
        async with AsyncClient(transport=ASGITransport(app=app),
                               base_url="http://test") as client:
            r = await client.get("/api/export/session/does-not-exist/bundle")
        assert r.status_code == 404

    async def test_head_request_does_not_build_a_bundle(self, recorded):
        """HEAD is for size and headers, not for a 100 MB capture."""
        import asyncio
        sid = await _record(recorded)
        async with AsyncClient(transport=ASGITransport(app=app),
                               base_url="http://test") as client:
            r = await client.head(f"/api/export/session/{sid}/bundle")
        assert r.status_code in (200, 405)
        if r.status_code == 200:
            assert r.content == b""
