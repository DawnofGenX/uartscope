# UARTScope API Reference

The REST and WebSocket surface of the UARTScope backend. Request and response
bodies follow the Pydantic schemas in `backend/app/models/__init__.py`.

- Base URL: `http://<host>:8080`. All routers are mounted with prefix
  `/api` in `backend/app/main.py` (9 routers).
- **Authentication: none.** The API has no keys, tokens, or sessions. Do not
  expose it to an untrusted network.
- The desktop app does **not** use this API — it imports the backend modules
  in-process. See [explanation-architecture.md](explanation-architecture.md).
  The HTTP surface exists for Docker deployments and external clients.
- Run the backend with:
  `cd backend && python -m uvicorn app.main:app --port 8080`

All examples below were sent against a live instance; responses are verbatim.

## Devices

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/devices/detect` | List serial ports found on the host |
| POST | `/api/devices/` | Register a device (body: `DeviceCreate`) |
| GET | `/api/devices/` | List all registered devices |
| GET | `/api/devices/{id}` | One device; 404 `{"detail":"Device not found"}` for unknown id |
| POST | `/api/devices/{id}/connect` | Open the port; 400 `{"detail":"Failed to connect"}` if the port won't open |
| POST | `/api/devices/{id}/disconnect` | Close the port |
| POST | `/api/devices/{id}/send` | Write a line to the device |
| DELETE | `/api/devices/{id}` | Remove the device |

Device verbs are `connect` / `disconnect`. There is no `start`, `stop`, or
`stats` device route — `/start` 404s, and `/{id}/stats` does not exist.

**POST `/api/devices/`** — body is `DeviceCreate`: `port` (required str),
`name` (optional, defaults to the port), `protocol` (default `"serial"`),
`baudrate` (default `115200`), `board_type` (optional), `metadata` (optional
dict). Re-registering an existing port returns 409 with
`{"detail":"Device on /dev/ttyUSB9 already registered"}`.

```bash
curl -X POST http://localhost:8080/api/devices/ \
  -H 'Content-Type: application/json' \
  -d '{"port":"/dev/ttyUSB9","name":"Doc example","baudrate":115200}'
```

```json
{
  "id": "64e0adc6-f9cb-4e87-ad7a-f0027bb2654d",
  "name": "Doc example",
  "port": "/dev/ttyUSB9",
  "protocol": "serial",
  "baudrate": 115200,
  "status": "detected",
  "board_type": null,
  "metadata_json": {},
  "created_at": "2026-09-28T20:17:31.031953",
  "last_seen": null
}
```

**GET `/api/devices/detect`** returns `{"devices": [...], "count": N}`; each
entry has `port`, `description`, `manufacturer`, `serial_number`, `vid`,
`pid`, `board_type`. There is no baud-rate auto-detection — set `baudrate`
yourself.

## Telemetry

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/telemetry/history/{device_id}` | Time series; optional query params `metric_name`, `start_time`, `end_time`, `limit` |
| GET | `/api/telemetry/latest/{device_id}` | Latest value per metric |
| GET | `/api/telemetry/metrics/{device_id}` | Metric names seen for the device |
| DELETE | `/api/telemetry/{device_id}` | Discard stored telemetry for the device |

```json
// GET /api/telemetry/history/{device_id}?limit=2  (device with no data yet)
{"device_id": "64e0adc6-...", "metric_name": null, "points": [], "count": 0}

// GET /api/telemetry/latest/{device_id}
{"device_id": "64e0adc6-...", "values": {}}

// GET /api/telemetry/metrics/{device_id}
{"device_id": "64e0adc6-...", "metrics": []}
```

## Sessions

Sessions are recorded captures: packets, metrics, and events, persisted as
JSON under `sessions_dir`. A session is created **only when you ask** —
streaming telemetry alone never creates one.

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/sessions/` | Start recording; body `SessionCreate`: `device_id?`, `name?` |
| GET | `/api/sessions/` | List sessions |
| GET | `/api/sessions/{id}` | Full session: packets, metrics, events |
| GET | `/api/sessions/{id}/info` | Summary counts and status |
| GET | `/api/sessions/{id}/packets` | Packet list; query param `limit` (default 1000) |
| GET | `/api/sessions/{id}/metrics` | Metric list; `limit` as above |
| GET | `/api/sessions/{id}/events` | Event list; `limit` as above |
| PUT | `/api/sessions/{id}/rename` | JSON body `{"name": "..."}` |
| POST | `/api/sessions/{id}/stop` | Stop recording |

The `{id}` in every path is the **server-generated UUID returned by the create
call**, not the session's display name.

```bash
curl -X POST http://localhost:8080/api/sessions/ \
  -H 'Content-Type: application/json' -d '{"name":"Doc session"}'
```

```json
{"id": "41f96516-2986-42e3-bb47-819998bc49d3", "status": "recording"}
```

```json
// GET /api/sessions/41f96516-2986-42e3-bb47-819998bc49d3/info
{
  "id": "41f96516-2986-42e3-bb47-819998bc49d3",
  "name": "Doc session",
  "device_id": null,
  "started_at": "2026-09-28T20:17:31.740952",
  "ended_at": null,
  "status": "recording",
  "packet_count": 0,
  "metric_count": 0,
  "event_count": 0
}

// POST /api/sessions/41f96516-2986-42e3-bb47-819998bc49d3/rename
// body: {"name":"Renamed session"}
{"id": "41f96516-2986-42e3-bb47-819998bc49d3", "name": "Renamed session", "status": "renamed"}

// POST /api/sessions/41f96516-.../stop
{"id": "41f96516-...", "status": "stopped"}
```

## Alerts

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/alerts/rules` | Create a rule (body: `AlertRuleCreate`) |
| GET | `/api/alerts/rules` | List rules |
| DELETE | `/api/alerts/rules/{rule_id}` | Delete a rule |
| PUT | `/api/alerts/rules/{rule_id}/enable?enabled=true\|false` | Enable/disable |
| GET | `/api/alerts/history` | Fired alerts; query params `limit` (100), `unacknowledged_only` |
| POST | `/api/alerts/acknowledge/{alert_id}` | Acknowledge one alert |
| POST | `/api/alerts/acknowledge/all` | Acknowledge all |
| GET | `/api/alerts/stats` | Counts by severity, rule totals |
| POST | `/api/alerts/test` | Evaluate a candidate rule shape |

`AlertRuleCreate`: `name`, `metric_name`, `condition`, `threshold`,
`secondary_threshold?`, `cooldown_seconds` (default 60), `severity`
(default `"warning"`). Over REST, `condition` is validated by a Pydantic
pattern and must be one of the internal names: `gt`, `lt`, `gte`, `lte`,
`eq`, `range`, `change`. Sending a symbol returns 422:

```json
{"detail": [{"type": "string_pattern_mismatch",
  "loc": ["body", "condition"],
  "msg": "String should match pattern '^(gt|lt|eq|gte|lte|range|change)$'",
  "input": ">", "ctx": {"pattern": "^(gt|lt|eq|gte|lte|range|change)$"}}]}
```

The engine itself (`backend/app/core/alert_engine.py`, `_CONDITION_ALIASES`)
also accepts the symbol spellings `>`, `<`, `>=`, `<=`, `=`, `==` and
normalizes them to those names — that is how the desktop UI's symbol picker
works. `range` uses `threshold` as the low bound and `secondary_threshold`
as the high; `change` fires when `|value − last_value| > threshold`.

```bash
curl -X POST http://localhost:8080/api/alerts/rules \
  -H 'Content-Type: application/json' \
  -d '{"name":"Temp too high","metric_name":"temperature","condition":"gt","threshold":80,"cooldown_seconds":30,"severity":"warning"}'
```

```json
{"id": "038afaf1-e725-4be6-b102-93855272026b", "created": true}

// GET /api/alerts/rules
[{
  "id": "038afaf1-e725-4be6-b102-93855272026b",
  "name": "Temp too high",
  "metric_name": "temperature",
  "condition": "gt",
  "threshold": 80.0,
  "secondary_threshold": null,
  "cooldown": 30,
  "severity": "warning",
  "enabled": true,
  "trigger_count": 0
}]

// GET /api/alerts/stats
{"total_alerts": 0, "unacknowledged": 0, "by_severity": {}, "active_rules": 0, "total_rules": 1}
```

## Export

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/export/csv/{device_id}` | Telemetry as CSV |
| GET | `/api/export/json/{device_id}` | Telemetry as JSON |
| GET | `/api/export/session/{session_id}` | Full session as JSON (same shape as `GET /api/sessions/{id}`) |

```
timestamp,device_id,metric_name,value,unit,session_id
```
(the CSV header line; a device with no data has no rows)

```json
// GET /api/export/json/64e0adc6-...
{"device_id": "64e0adc6-...", "exported_at": "2026-09-28T20:17:46.856080", "metrics": {}}
```

The `.uartscope` shareable bundle is **desktop-only** (the Sessions Export tab
writes a zip of `session.json`, `packets.json`, `metrics.csv`). No API route
produces it.

## Protocols

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/protocols/` | List built-in decoders |
| POST | `/api/protocols/decode` | Decode `raw_hex` with `protocol_id` (default `"auto"`) |
| POST | `/api/protocols/encode` | Encode `data` with `protocol_id` |
| POST | `/api/protocols/dbc/load` | Load a DBC file: `{"content": "...", "filename": "x.dbc"}` |
| GET | `/api/protocols/dbc/loaded` | What DBC data is currently loaded |

Decoder details live in [reference-protocols.md](reference-protocols.md).

```json
// GET /api/protocols/
{"decoders": [
  {"id": "uart_text",  "name": "UART Text",  "description": "AT commands, NMEA GPS, debug print, CSV/key-value text"},
  {"id": "modbus_rtu", "name": "Modbus RTU", "description": "Industrial Modbus RTU (function codes 1-6, 15, 16)"},
  {"id": "i2c",        "name": "I2C",        "description": "I2C bus — 7/10-bit addressing, read/write, ACK/NACK"},
  {"id": "spi",        "name": "SPI",        "description": "SPI bus — MOSI/MISO, CS polarity, clock modes"},
  {"id": "can",        "name": "CAN Bus",    "description": "CAN 2.0A/B — 11/29-bit ID, data bytes, CRC"},
  {"id": "can_dbc",    "name": "CAN DBC",    "description": "CAN bus protocol with .dbc database file for signal decoding"}
]}

// POST /api/protocols/decode  {"raw_hex": "010300000001840A"}  (auto-detect)
{"success": true, "protocol_id": "modbus_rtu", "protocol_name": "Modbus RTU",
 "decoded": {"type": "modbus_rtu", "device_addr": 1, "function_code": 3,
             "function_name": "Read Holding Registers", "data": "00000001",
             "crc": "840a", "length": 8}}

// POST /api/protocols/encode  {"protocol_id": "modbus_rtu",
//   "data": {"slave_address": 1, "function_code": 3, "register_address": 0, "quantity": 1}}
{"protocol_id": "modbus_rtu", "raw_hex": "01030000", "length": 4}

// POST /api/protocols/dbc/load with empty content -> 400
{"detail": "File content required"}

// GET /api/protocols/dbc/loaded (nothing loaded)
{"loaded": false, "messages": 0, "signals": 0}
```

Invalid hex in a decode request returns 400 `{"detail":"Invalid hex data"}`;
auto-detect below its confidence floor returns
`{"success": false, "message": "No protocol detected with sufficient confidence", "raw_hex": "..."}`.

## Performance

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/performance/summary` | Cumulative totals and averages |
| GET | `/api/performance/snapshot` | Current-rate snapshot |
| GET | `/api/performance/history` | Ring buffer of snapshots |
| GET | `/api/performance/device/{device_id}` | Per-device stats; 404 for unknown id |

```json
// GET /api/performance/summary
{"total_bytes": 0, "total_packets": 0, "total_errors": 0, "avg_latency_ms": 0,
 "avg_packet_rate": 0, "avg_throughput": 0, "error_rate_per_min": 0, "devices": {}}

// GET /api/performance/snapshot
{"timestamp": "2026-09-28T20:17:47.134881", "connected_devices": 0,
 "total_bytes": 0, "total_packets": 0, "total_errors": 0,
 "current_packet_rate": 0, "current_throughput": 0, "avg_latency_ms": 0}
```

## MQTT

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/mqtt/profiles` | List broker profiles |
| POST | `/api/mqtt/profiles` | Create a profile |
| DELETE | `/api/mqtt/profiles/{profile_id}` | Delete a profile |
| POST | `/api/mqtt/profiles/{id}/connect` | Connect to the broker |
| POST | `/api/mqtt/profiles/{id}/disconnect` | Disconnect |
| POST | `/api/mqtt/profiles/{id}/subscribe` | Subscribe to a topic |
| POST | `/api/mqtt/profiles/{id}/unsubscribe` | Unsubscribe |
| POST | `/api/mqtt/profiles/{id}/publish` | Publish a message |
| GET | `/api/mqtt/profiles/{profile_id}/stats` | Per-profile counters |
| GET | `/api/mqtt/messages` | Recent MQTT messages |
| GET | `/api/mqtt/stats` | Global counters |

```json
// POST /api/mqtt/profiles  {"name":"local broker","broker":"localhost","port":1883,"topic_prefix":"uartscope"}
{"id": "b5fd7412", "name": "local broker"}

// GET /api/mqtt/stats
{"total_connections": 0, "connected": 0, "total_messages": 0, "total_bytes": 0, "history_size": 0}
```

MQTT support is off by default (`UARTSCOPE_MQTT_ENABLED=false`).

## WebSocket

**`WS /api/ws/telemetry`** — the real-time stream. The client sends JSON
messages; the hub (`backend/app/core/websocket_hub.py`) replies:

| Client sends | Server replies |
|---|---|
| `{"type":"ping"}` | `{"type":"pong"}` |
| `{"type":"subscribe_device","device_id":"<uuid>"}` | `{"type":"subscribed","device_id":...,"device_name":...}` or `{"type":"error","message":...}` |
| `{"type":"subscribe_all"}` | `{"type":"subscribed","mode":"all"}` |
| `{"type":"unsubscribe"}` | `{"type":"unsubscribed"}` |
| `{"type":"send_data",...}` | writes through to the device |

Broadcast frames carry `type` of `telemetry`, `packet`, `alert`, or
`device_status` with a `data` dict and `timestamp` (see `WSMessage` in
`backend/app/models/__init__.py`).

**GET `/api/ws/subscriptions`** reports current hub subscriptions:

```json
{"total": 0, "devices": {}}
```

## Health

**GET `/api/health`** — liveness plus device/session/WS counters:

```json
{"status": "healthy", "version": "2.0.0",
 "devices": {"total": 0, "connected": 0, "streaming": 0, "errors": 0,
             "total_bytes_received": 0, "total_packets": 0},
 "active_sessions": 0, "websocket_clients": 0}
```

Device totals live here, not on a device-stats endpoint.

## Related documents

- [reference-configuration.md](reference-configuration.md) — every setting
- [reference-protocols.md](reference-protocols.md) — decoder details
- [how-to-alerts.md](how-to-alerts.md) — rules from the UI
- [how-to-sessions-and-export.md](how-to-sessions-and-export.md) — captures and exports
