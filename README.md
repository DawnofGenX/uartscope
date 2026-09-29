# UARTScope Pro

**Open-source embedded telemetry, debugging, and protocol analysis — the Wireshark of microcontrollers.**

![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![CI](https://github.com/DawnofGenX/uartscope/actions/workflows/ci.yml/badge.svg)

UARTScope connects to a serial port, parses the telemetry your board emits
(`KEY:VALUE` lines and JSON), charts it live, alerts you on thresholds, records
replayable sessions, and decodes raw bus traffic (UART text, Modbus RTU, I2C,
SPI, CAN, CAN with a DBC file). The desktop app is pure Python (NiceGUI) — no
Node.js, no build step, no browser install.

![Live charts with five telemetry series grouped by unit](docs/images/04-charts.png)

## What it does

| Area | Detail |
|---|---|
| Serial monitoring | Connect, disconnect, and send on any serial port; terminal view of the raw stream |
| Live telemetry | Automatic `KEY:VALUE` and JSON parsing into per-metric charts grouped by unit |
| Alerts | Rule-based conditions (`>`, `<`, `>=`, `<=`, `==`, range, rate-of-change) with per-rule cooldown and an alert history with acknowledgment |
| Sessions | Record, replay, diff against a golden baseline, and export JSON/CSV; share as `.uartscope` bundles from the desktop app or `GET /api/export/session/{id}/bundle` |
| Protocol decoders | Six built-ins — UART Text, Modbus RTU, I2C, SPI, CAN Bus, CAN DBC — all with encode as well as decode |
| Plugin marketplace | Install real third-party decoders from a registry manifest; `registry/registry.json` ships LIN, J1939 and DALI. Validation, persistence and uninstall are implemented |
| MQTT | Multi-broker profiles, pub/sub, message history (backend API is live; the MQTT screen is still on the v1 UI — see below) |
| REST + WebSocket API | FastAPI backend on :8080 with ~50 verified routes; the OpenAPI schema at `/docs` lists them all |

### What to know before you trust the screenshots

- Installing a **plugin** runs third-party Python inside the app process and is
  **not sandboxed**. A plugin that is registered gets its `can_decode` called
  against live traffic. The marketplace validates and records what it installs,
  but it cannot make untrusted code safe — read the source first. The screen
  says this on the page.
- The registry ships as a local manifest, not a hosted service. Set
  `UARTSCOPE_PLUGIN_REGISTRY` to an `http(s)` URL to point at a remote one;
  the manifest format is the same either way.
- Every screen has been rebuilt to the v2 design treatment, so no screen
  carries a "Not yet v2" marker. The Performance and MQTT screenshots are
  taken against seeded demo data — a fixed seed, so the numbers in the image
  are reproducible but are not measurements of your hardware.
- There is **no baudrate auto-detection**. You set the baudrate; the app uses it.
- Sessions are **not** created automatically when you start streaming. You
  create a session when you want one recorded.

## Quick start (5 minutes)

```bash
git clone https://github.com/DawnofGenX/uartscope.git
cd uartscope
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r backend/requirements.txt
python desktop_app.py
```

Open **http://localhost:3000**. That is the whole app: `desktop_app.py` imports
the backend modules in-process and serves the UI itself. You do **not** need to
run uvicorn separately for local use.

No board handy? Simulate one in a second terminal:

```bash
python scripts/simulate_device.py /dev/ttyUSB0 115200 --virtual
```

```text
Virtual serial port: /dev/pts/5
Connect UARTScope to: /dev/pts/5
```

Add the printed `/dev/pts/…` port as a device in the UI, press **Start**, and
watch live charts. The steps above are the whole path; the removed tutorial
walked through the same thing in more detail.

### Backend API only

```bash
cd backend
python -m uvicorn app.main:app --port 8080
curl http://127.0.0.1:8080/api/health
```

```json
{"status":"healthy","version":"2.0.1","devices":{"total":0,"connected":0,"streaming":0,"errors":0,"total_bytes_received":0,"total_packets":0},"active_sessions":0,"websocket_clients":0}
```

### Docker

```bash
docker compose up -d
```

Docker is the one case where the HTTP backend matters: the desktop container is
given `API_URL=http://backend:8080` and the browser talks to the FastAPI
service on :8080, while the UI is served on :3000.

## Documentation

The long-form guides have been removed. What remains here:

- **Quick start** (above) — the five-minute setup, including the no-hardware path
- **What to know before you trust the screenshots** (above) — what the screens
  do and do not show
- **Development** (below) — running the tests and the static gates

The full guides are recoverable from the v2.0.1 tag if you want them:
https://github.com/DawnofGenX/uartscope/tree/v2.0.1/docs

## Development

Python 3.11–3.13 (CI matrix). From the repo root, with a venv active:

```bash
.venv/bin/python -m pytest backend/tests/ -q    # 75 tests
python check_handler_order.py
python check_dict_keys.py
python smoke_pages.py --boot --wait 60          # renders every screen headless
```

Lint is `ruff check app/ --line-length=120 --select E9,F63,F7,F82` from
`backend/`, enforced in CI.

## License

MIT. See [LICENSE](LICENSE).
