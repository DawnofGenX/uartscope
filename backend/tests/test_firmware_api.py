"""Tests for firmware API routes.

Run:  cd backend && python -m pytest tests/test_firmware_api.py -v
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest


@pytest.fixture(scope="module")
def client():
    """A TestClient whose lifespan has actually run."""
    tmpdir = tempfile.mkdtemp(prefix="uartscope-test-")
    os.environ["UARTSCOPE_DATABASE_URL"] = f"sqlite+aiosqlite:///{tmpdir}/test.db"

    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as c:
        yield c


class TestFirmwareBoards:
    def test_list_boards(self, client):
        """GET /api/firmware/boards returns supported and detected boards."""
        resp = client.get("/api/firmware/boards")
        assert resp.status_code == 200
        data = resp.json()
        assert "supported" in data
        assert "detected" in data
        assert isinstance(data["supported"], list)
        assert isinstance(data["detected"], list)
        assert len(data["supported"]) > 0


class TestFirmwareExamples:
    def test_list_examples(self, client):
        """GET /api/firmware/examples returns a list of example sketches."""
        resp = client.get("/api/firmware/examples")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) > 0


class TestFirmwareCompile:
    def test_compile_nonexistent_sketch_dir(self, client):
        """POST /api/firmware/compile returns 404 for non-existent sketch dir."""
        resp = client.post("/api/firmware/compile", json={
            "sketch_dir": "/nonexistent/path/to/sketch",
            "fqbn": "esp32:esp32:esp32"
        })
        assert resp.status_code == 404


class TestFirmwareFlash:
    def test_flash_nonexistent_bin_file(self, client):
        """POST /api/firmware/flash returns 404 for non-existent bin file."""
        resp = client.post("/api/firmware/flash", json={
            "bin_path": "/nonexistent/path/to/firmware.bin",
            "port": "/dev/ttyUSB0",
            "baud": 921600
        })
        assert resp.status_code == 404
