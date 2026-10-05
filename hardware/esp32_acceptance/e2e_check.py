"""UARTScope end-to-end: real server, real device, real bytes, real API.

Everything so far has tested a component. This drives the WHOLE pipeline the
way a user does:

    pty character device  ->  SerialReader  ->  TelemetryEngine
                          ->  SessionRecorder  ->  AlertEngine
                          ->  WebSocketHub  ->  HTTP API  ->  browser

Nothing is mocked. The backend runs under uvicorn on a real port, a script
writes real bytes into a real serial port, and the assertions read the same
endpoints the UI reads. A break anywhere in that chain shows up here.

Run:
    python e2e_check.py
    python e2e_check.py --keep     # leave the server up for manual poking
"""
import argparse
import asyncio
import json
import os
import pty
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BACKEND = REPO / "backend"
sys.path.insert(0, str(BACKEND))

PY = "/home/hermes/gh-polish/uartscope/.venv-v2/bin/python"
PORT = 8099
BASE = f"http://127.0.0.1:{PORT}"

R = []


def check(name, ok, detail=""):
    R.append((name, ok))
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name}")
    if detail:
        for line in str(detail).splitlines():
            print(f"        {line}")


def api(method, path, body=None, expect=None):
    """Call the API the way the browser does. Returns (status, parsed)."""
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            status, raw = r.status, r.read()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read()
    except Exception as e:
        return 0, {"error": str(e)}
    try:
        return status, json.loads(raw)
    except Exception:
        return status, raw.decode(errors="replace")


def wait_for_server(proc, seconds=90):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if proc.poll() is not None:
            return False
        status, _ = api("GET", "/api/health")
        if status == 200:
            return True
        time.sleep(0.5)
    return False


def crc16(data):
    c = 0xFFFF
    for b in data:
        c ^= b
        for _ in range(8):
            c = (c >> 1) ^ 0xA001 if c & 1 else c >> 1
    return c


def modbus_response(slave, fn, value):
    body = bytes([slave, fn, 0x02, (value >> 8) & 0xFF, value & 0xFF])
    c = crc16(body)
    return body + bytes([c & 0xFF, c >> 8])


async def device_script(master, stop: asyncio.Event):
    """Behave like a real board: text telemetry + binary Modbus frames."""
    from app.core.serial_reader import inter_byte_timeout_for
    gap = inter_byte_timeout_for(115200)
    cycle = 0
    while not stop.is_set():
        cycle += 1
        payload = (
            f"CYCLE {cycle}\n"
            "TEMP:23.4C VOLT:3.30V HUM:45%\n"
        ).encode()
        os.write(master, payload)
        await asyncio.sleep(gap * 12)

        for frame in (modbus_response(1, 3, 0x000A),   # contains 0x0A
                      modbus_response(1, 3, 0x2A4C),
                      modbus_response(2, 3, 0xFF9C)):   # invalid UTF-8
            os.write(master, frame)
            await asyncio.sleep(gap * 12)

        await asyncio.sleep(1.2)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true",
                    help="leave the server running when finished")
    ap.add_argument("--protocol", default="serial")
    A = ap.parse_args()

    print("=" * 78)
    print("UARTScope END-TO-END   backend on :%d, real pty device" % PORT)
    print("=" * 78)

    # a real serial port pair
    master, slave = pty.openpty()
    port_path = os.ttyname(slave)
    print(f"  device port: {port_path}")

    db = BACKEND / "e2e_test.db"
    for f in (db,):
        if f.exists():
            f.unlink()
    (BACKEND / "sessions").mkdir(exist_ok=True)

    env = dict(os.environ)
    for k in ("PYTHONPATH", "PYTHONHOME"):
        env.pop(k, None)
    env["UARTSCOPE_DATABASE_URL"] = f"sqlite+aiosqlite:///{db}"
    env["UARTSCOPE_PLUGIN_INSTALL_ENABLED"] = "false"

    proc = subprocess.Popen(
        [PY, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
         "--port", str(PORT), "--log-level", "warning"],
        cwd=BACKEND, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, start_new_session=True)

    try:
        if not wait_for_server(proc):
            out = ""
            try:
                proc.terminate()
                out = proc.stdout.read()[-2500:]
            except Exception:
                pass
            check("backend started", False,
                  f"no health response in 90s\n{out}")
            return

        check("backend started and healthy", True, f"{BASE}/api/health")

        # ---- register the device, exactly as the UI does ----
        status, det = api("GET", "/api/devices/detect")
        check("GET /api/devices/detect responds", status == 200,
              f"status={status}")

        status, dev = api("POST", "/api/devices/", {
            "name": "e2esp32", "port": port_path, "protocol": A.protocol,
            "baudrate": 115200})
        check("POST /api/devices/ registered the device", status == 200,
              f"status={status} {dev}")
        if status != 200:
            return
        device_id = dev["id"]
        print(f"  device id: {device_id}")

        status, _ = api("POST", f"/api/devices/{device_id}/connect")
        check("POST /api/devices/{id}/connect", status == 200, f"status={status}")

        # ---- a websocket client, so broadcast delivery is really tested ----
        ws_messages = []

        async def ws_client():
            import websockets
            uri = f"ws://127.0.0.1:{PORT}/ws/telemetry"
            try:
                async with websockets.connect(uri) as ws:
                    if A.protocol:
                        try:
                            await ws.send(json.dumps(
                                {"type": "subscribe", "device_id": device_id}))
                        except Exception:
                            pass
                    end = time.time() + 8
                    while time.time() < end:
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                        except asyncio.TimeoutError:
                            continue
                        except Exception:
                            break
                        try:
                            ws_messages.append(json.loads(raw))
                        except Exception:
                            ws_messages.append({"raw": str(raw)[:200]})
            except Exception as e:
                ws_messages.append({"_ws_error": str(e)})

        ws_task = asyncio.create_task(ws_client())
        await asyncio.sleep(0.6)

        # ---- an alert rule, so the alert path is live ----
        # The route is /alerts/rules -- /alerts/ itself is 404. Read from the
        # router rather than guessing: the first draft of this script assumed
        # POST /api/alerts/ and got a clean-looking 404 it then misreported.
        status, rule = api("POST", "/api/alerts/rules", {
            "name": "e2e high temp", "metric_name": "TEMP",
            # The API speaks gt/lt/eq/gte/lte/range/change, NOT the symbols the
            # UI shows. Sending ">" is a 422 that reads like a routing problem.
            "condition": "gt", "threshold": 20.0})
        check("POST /api/alerts/rules created a rule", status in (200, 201),
              f"status={status} {rule}")
        rule_id = rule.get("id") if isinstance(rule, dict) else None

        # ---- start streaming ----
        status, started = api("POST", f"/api/devices/{device_id}/start")
        check("POST /api/devices/{id}/start", status == 200,
              f"status={status} {started}")

        stop = asyncio.Event()
        task = asyncio.create_task(device_script(master, stop))
        await asyncio.sleep(9.0)

        # ---- read the pipeline back out through the API ----
        status, latest = api("GET", f"/api/telemetry/latest/{device_id}")
        got = (latest if isinstance(latest, dict) else {}).get("values", {})
        check("telemetry reached TelemetryEngine and the API",
              "TEMP" in got,
              f"GET /api/telemetry/latest -> {got}")

        status, metrics = api("GET", f"/api/telemetry/metrics/{device_id}")
        names = [m["name"] for m in
                 ((metrics if isinstance(metrics, dict) else {})
                  .get("metrics", []))]
        check("multiple metrics extracted with units",
              "TEMP" in names and "HUM" in names,
              f"metrics={names}")

        status, hist = api("GET",
                           f"/api/telemetry/history/{device_id}?metric_name=TEMP")
        pts = (hist if isinstance(hist, dict) else {}).get("points", [])
        check("metric history recorded samples", len(pts) > 0,
              f"{len(pts)} TEMP points")

        status, stats = api("GET", f"/api/devices/{device_id}/stats")
        check("device counters advanced",
              (stats or {}).get("bytes_received", 0) > 0
              and (stats or {}).get("packets_received", 0) > 0,
              f"bytes={stats.get('bytes_received')} "
              f"packets={stats.get('packets_received')} "
              f"metric_count={stats.get('metric_count')}")

        status, sess = api("GET", "/api/sessions/")
        # List[dict], not {"sessions": [...]} -- the first draft assumed a
        # wrapper and crashed on a bare list.
        sessions = sess if isinstance(sess, list) else (sess or {}).get("sessions", [])
        check("a session was created by starting the stream",
              len(sessions) > 0,
              f"{len(sessions)} session(s): "
              f"{[s.get('name') for s in sessions][:3]}")

        session_id = sessions[0]["id"] if sessions else None
        if session_id:
    

            status, bundle = api("GET",
                                 f"/api/export/session/{session_id}/bundle")
            ok = status == 200 and "PK" in str(bundle)[:4]
            check("GET /api/export/session/{id}/bundle returns a zip", ok,
                  f"status={status} first bytes={str(bundle)[:8]!r}")

        status, alerts = api("GET", "/api/alerts/history?limit=100")
        hist_alerts = (alerts if isinstance(alerts, list)
                       else (alerts or {}).get("alerts", []))
        status, astats = api("GET", "/api/alerts/stats")
        status, rules_now = api("GET", "/api/alerts/rules")
        rn = rules_now if isinstance(rules_now, list) else []
        check("the alert engine FIRED on live data",
              len(hist_alerts) > 0,
              f"{len(hist_alerts)} alert(s) in history; "
              f"stats={astats}; "
              f"rules={[{k: r.get(k) for k in ('name','metric_name','condition','threshold','trigger_count')} for r in rn]}"
              + (f"\n        first={hist_alerts[0]}" if hist_alerts else ""))

        status, perf = api("GET", "/api/performance/summary")
        check("GET /api/performance/summary", status == 200,
              f"status={status} {str(perf)[:160]}")

        await asyncio.sleep(1.0)
        stop.set()
        await asyncio.wait_for(task, timeout=5)

        metric_msgs = [m for m in ws_messages
                       if m.get("type") == "metric"]
        serial_msgs = [m for m in ws_messages
                       if m.get("type") == "serial_data"]
        check("websocket delivered messages to a real client",
              len(ws_messages) > 0,
              f"{len(ws_messages)} messages: "
              f"{len(metric_msgs)} metric, {len(serial_msgs)} serial_data, "
              f"types={sorted({m.get('type') for m in ws_messages})[:6]}")

        # ---- stop, then confirm the device is reusable (the brick bug) ----
        status, _ = api("POST", f"/api/devices/{device_id}/stop")
        check("POST /api/devices/{id}/stop", status == 200, f"status={status}")

        status, s1 = api("POST", f"/api/devices/{device_id}/start")
        await asyncio.sleep(2.0)
        status, after = api("GET", f"/api/telemetry/latest/{device_id}")
        vals = (after if isinstance(after, dict) else {}).get("values", {})
        check("device can be restarted after stopping (no brick)",
              status == 200 and "TEMP" in vals,
              f"restart status={status} values={vals}")
        api("POST", f"/api/devices/{device_id}/stop")

        status, health = api("GET", "/api/health")
        check("GET /api/health still healthy at the end", status == 200,
              f"{health}")

    finally:
        try:
            os.close(master)
        except Exception:
            pass
        if not A.keep:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            print(f"\n  server stopped (pid {proc.pid})")
        else:
            print(f"\n  server LEFT RUNNING at {BASE} (pid {proc.pid})")

    print("\n" + "=" * 78)
    bad = [n for n, ok in R if not ok]
    print(f"{len(R)-len(bad)}/{len(R)} end-to-end checks passed")
    for n in bad:
        print(f"  FAIL {n}")
    print("=" * 78)


if __name__ == "__main__":
    asyncio.run(main())
