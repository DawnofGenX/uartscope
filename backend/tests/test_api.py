import pytest
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


@pytest.fixture(scope="module")
def client():
    """A TestClient whose lifespan has actually run.

    The module previously did `client = TestClient(app)` at import time and used
    that object directly. A TestClient only runs the ASGI lifespan -- which is
    what calls init_db() -- when it is entered as a context manager or used as a
    context manager. Without that, no tables are ever created and every test
    that touches the database fails with "no such table: devices".

    This never failed locally because a uartscope.db from an earlier manual run
    was sitting in backend/ and the tables already existed. On a clean CI
    checkout there is no such file, so the same tests failed. That is the whole
    class of bug this fixture exists to remove: a test that only passes because
    of untracked state on one machine.

    The database URL is set to a temp file *before* app.database is imported, so
    the engine binds to it rather than to whatever is in the working directory.
    """
    tmpdir = tempfile.mkdtemp(prefix="uartscope-test-")
    os.environ["UARTSCOPE_DATABASE_URL"] = f"sqlite+aiosqlite:///{tmpdir}/test.db"

    # Import after the env var is set: the engine is built at module import.
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as c:
        yield c


# ─── Health ────────────────────────────────────────────────────────────────────

class TestHealth:
    def test_health_check(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert "devices" in data

    def test_list_protocols(self, client):
        resp = client.get("/api/protocols")
        assert resp.status_code == 200
        data = resp.json()
        assert "decoders" in data
        assert len(data["decoders"]) >= 5


# ─── Devices ──────────────────────────────────────────────────────────────────

class TestDevices:
    def test_detect_ports(self, client):
        resp = client.get("/api/devices/detect")
        assert resp.status_code == 200
        data = resp.json()
        # Returns {"devices": [...], "count": N}
        assert isinstance(data, dict)
        assert "devices" in data

    def test_create_device(self, client):
        resp = client.post("/api/devices/", json={
            "name": "Test Device",
            "port": "/dev/ttyTEST",
            "protocol": "uart",
            "baudrate": 115200
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Test Device"
        assert data["id"] is not None
        return data["id"]

    def test_create_device_duplicate_port(self, client):
        resp1 = client.post("/api/devices/", json={
            "name": "Dev1", "port": "/dev/ttyDUP", "protocol": "uart", "baudrate": 115200
        })
        assert resp1.status_code == 200
        resp2 = client.post("/api/devices/", json={
            "name": "Dev2", "port": "/dev/ttyDUP", "protocol": "uart", "baudrate": 115200
        })
        # Should return 409 Conflict for duplicate port
        assert resp2.status_code == 409

    def test_get_devices(self, client):
        resp = client.get("/api/devices/")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


# ─── Telemetry ────────────────────────────────────────────────────────────────

class TestTelemetry:
    def test_get_latest_not_found(self, client):
        resp = client.get("/api/telemetry/latest/nonexistent")
        # Should return empty device response or 404
        assert resp.status_code in [200, 404]

    def test_get_history_not_found(self, client):
        resp = client.get("/api/telemetry/history/nonexistent")
        assert resp.status_code in [200, 404]

    def test_clear_telemetry(self, client):
        resp = client.delete("/api/telemetry/nonexistent")
        assert resp.status_code == 200


# ─── Sessions ────────────────────────────────────────────────────────────────

class TestSessions:
    def test_list_sessions(self, client):
        resp = client.get("/api/sessions/")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_create_session(self, client):
        resp = client.post("/api/sessions/", json={
            "device_id": "test_dev",
            "name": "Test Session"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "recording"


# ─── Alerts ──────────────────────────────────────────────────────────────────

class TestAlerts:
    def test_list_rules_empty(self, client):
        resp = client.get("/api/alerts/rules")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_create_rule(self, client):
        resp = client.post("/api/alerts/rules", json={
            "name": "High Temp",
            "metric_name": "TEMP",
            "condition": "gt",
            "threshold": 40,
            "cooldown": 10
        })
        assert resp.status_code == 200
        data = resp.json()
        # API returns: {"id": "...", "created": true}
        assert "id" in data
        assert data.get("created") == True

    def test_delete_rule(self, client):
        create = client.post("/api/alerts/rules", json={
            "name": "To Delete",
            "metric_name": "VOLTAGE",
            "condition": "lt",
            "threshold": 2.0,
            "cooldown": 5
        })
        rule_id = create.json()["id"]
        assert rule_id is not None
        delete = client.delete(f"/api/alerts/rules/{rule_id}")
        assert delete.status_code == 200

    def test_get_alert_stats(self, client):
        resp = client.get("/api/alerts/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_alerts" in data or "total" in data
        assert "active_rules" in data


# ─── Protocols ────────────────────────────────────────────────────────────────

class TestProtocols:
    def test_list_protocols(self, client):
        resp = client.get("/api/protocols")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["decoders"]) >= 5




# ─── Performance ──────────────────────────────────────────────────────────────

class TestPerformance:
    def test_get_summary(self, client):
        resp = client.get("/api/performance/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_bytes" in data
        assert "total_packets" in data
        assert "devices" in data

    def test_get_snapshot(self, client):
        resp = client.get("/api/performance/snapshot")
        assert resp.status_code == 200
        data = resp.json()
        assert "current_packet_rate" in data
        assert "current_throughput" in data

    def test_get_history(self, client):
        resp = client.get("/api/performance/history")
        assert resp.status_code == 200
        data = resp.json()
        assert "history" in data


# ─── MQTT ─────────────────────────────────────────────────────────────────────

class TestMQTT:
    def test_get_stats(self, client):
        resp = client.get("/api/mqtt/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_connections" in data
        assert "connected" in data

    def test_get_profiles_empty(self, client):
        resp = client.get("/api/mqtt/profiles")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["profiles"], list)

    def test_create_profile(self, client):
        resp = client.post("/api/mqtt/profiles", json={
            "name": "Test Broker",
            "broker": "broker.hivemq.com",
            "port": 1883,
            "topic_prefix": "uartscope/test"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "id" in data
        return data["id"]

    def test_delete_profile(self, client):
        create = client.post("/api/mqtt/profiles", json={
            "name": "To Delete",
            "broker": "localhost",
            "port": 1883
        })
        pid = create.json()["id"]
        resp = client.delete(f"/api/mqtt/profiles/{pid}")
        assert resp.status_code == 200

    def test_get_messages_empty(self, client):
        resp = client.get("/api/mqtt/messages")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["messages"], list)
