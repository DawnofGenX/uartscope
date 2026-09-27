# UARTScope Pro — backend

The FastAPI service: device management, the telemetry engine, the alert engine,
the session recorder, the protocol decoders, and the WebSocket stream that the
desktop app subscribes to.

For the project as a whole, see the [root README](../README.md).

## Install

```bash
pip install -e ".[dev]"
```

`sqlalchemy[asyncio]` is deliberate. Plain `sqlalchemy` does not pull in
`greenlet`, and the async engine raises on import without it, so a clean
virtualenv cannot boot the backend. This was fixed in v2.0.0; see the
changelog.

## Run

```bash
uvicorn app.main:app --reload --port 8080
```

## Layout

| Path | What it is |
| --- | --- |
| `app/main.py` | FastAPI app, routers, static mounts |
| `app/config.py` | Settings (`app_version`, dirs, limits) |
| `app/api/` | HTTP routes, one module per domain |
| `app/core/device_manager.py` | Serial port enumeration, connect/disconnect |
| `app/core/serial_reader.py` | Read loops, one per streaming device |
| `app/core/telemetry_engine.py` | Line parsing, metric history, unit inference |
| `app/core/alert_engine.py` | Threshold rules and the alert queue |
| `app/core/session_recorder.py` | Capture, persist, replay, export |
| `app/core/protocol_decoder.py` | UART/Modbus/I²C/SPI/CAN decoders |
| `app/core/performance_tracker.py` | Throughput and latency counters |

## Tests

```bash
pytest tests/ -v
```

Five files there are plain scripts rather than pytest files — each prints a
pass count and exits non-zero on failure, so they run in CI unchanged:

| File | What it locks down |
| --- | --- |
| `test_metric_units.py` | Unit inference on both parse paths |
| `test_alert_conditions.py` | Every condition the UI offers actually fires |
| `test_session_metrics_recorded.py` | A recorded session contains its metrics |
| `test_protocol_autodetect.py` | Printable ASCII is never decoded as binary |
| `test_samples.py` | Every claim in `samples/payloads.json` is true |

`test_samples.py` reads `../../samples/payloads.json`, so the documented samples
cannot drift away from the code.

## Known sharp edges

- `AlertRule.condition` is stored as the symbol the UI sends (`>`, `<`, `>=`,
  `<=`). `check()` normalises to its internal names before comparing. Adding a
  condition means adding it to `_CONDITION_ALIASES` *and* to the UI picker —
  a symbol in neither is logged as unrecognised and never fires.
- `process_line()` returns the `ParsedMessage`. Callers that need the metrics
  from the line they just processed should use it rather than re-parsing.
- `session_recorder.load_session()` is a coroutine and the desktop page builder
  is synchronous. It runs on a private thread with its own loop; do not call
  `run_until_complete` on the running loop.
