# Architecture

This page explains why UARTScope is shaped the way it is. For the endpoint
list see [reference-api.md](reference-api.md); for settings see
[reference-configuration.md](reference-configuration.md).

## The one idea that explains everything else

**The desktop app imports the backend modules in-process. It is not an HTTP
client of them.** `desktop_app.py` begins with:

```python
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))
from app.core.device_manager import device_manager
# ... 11 more in-process imports
```

There is no `API_URL`, no httpx/requests/aiohttp import, and no HTTP call to
:8080 anywhere in `desktop_app.py`. The consequence: `python desktop_app.py`
alone is the whole product. This was verified by killing the uvicorn backend
and reloading the desktop UI — it served HTTP 200 on :3000 with the backend
dead.

So why does the FastAPI backend exist at all? Two consumers:

1. **Docker.** The compose desktop container gets
   `API_URL=http://backend:8080`, and the browser served by it talks to the
   FastAPI service — there, the HTTP hop is real and necessary.
2. **External clients.** Anything scripting UARTScope (the endpoint list in
   the API reference) uses the same surface.

The old README's "Option A" quick start — terminal one runs uvicorn, terminal
two runs desktop_app — was two terminals of ceremony for a backend the UI
never calls. The honest local workflow is one command.

## Layering

```
desktop_app.py            NiceGUI shell: pages, charts, follow-mode terminal,
   |                      demo seeding. Imports the core engines directly.
   v
backend/app/
  core/                   the engines (framework-free, importable standalone):
    device_manager.py     registry, connect/disconnect, write
    serial_reader.py      async serial read loop
    telemetry_engine.py   metric extraction, history, units
    protocol_decoder.py   the six decoders + autodetect (see protocols ref)
    alert_engine.py       rule evaluation, condition aliases, cooldowns
    session_recorder.py   JSON capture files under sessions_dir
    websocket_hub.py      subscription-aware broadcast hub
    performance_tracker.py rate/throughput snapshots
    mqtt_client.py        broker bridge (off by default)
  api/routes/             9 FastAPI routers, all under prefix "/api"
  models/__init__.py      every Pydantic schema, in one file
  config.py               pydantic-settings, UARTSCOPE_ env prefix
  database.py             SQLAlchemy async models (devices, alert rules)
```

Three rules keep this layering honest:

- **Routes are thin.** They validate against `models/__init__.py`, delegate
  to a core engine, and translate failures to HTTP codes. Business logic
  lives in `core/`, so the desktop shell and the REST layer get identical
  behaviour from the same objects.
- **Core engines are singletons.** One `device_manager`, one
  `telemetry_engine`, and so on — created at import, shared by whichever
  entry point (NiceGUI or uvicorn) imported them.
- **`models/` is the contract.** Request and response bodies on
  `/api/*` are exactly these Pydantic classes.

## Where state lives

| State | Home | Lifetime |
|---|---|---|
| Devices, alert rules | SQLite via aiosqlite (`database_url`, default `./uartscope.db`) | persistent; the file is gitignored |
| Sessions (packets, metrics, events) | JSON files in `sessions_dir` (`./sessions`), capped at `max_session_size_mb` | persistent; the directory is gitignored |
| Live telemetry history | in-memory in `telemetry_engine`, `max_history_per_metric` points per metric | process lifetime |
| Performance snapshots | in-memory ring in `performance_tracker` | process lifetime |
| WebSocket subscriptions | `websocket_hub` per-connection state | connection lifetime |

There is **no `storage/` package** — no sqlite_store.py, no postgres_store.py.
That was the old README's invention. Persistence is split deliberately: rows
that need queries (devices, rules) go to SQLite; append-mostly captures that
are exported or replayed whole go to flat JSON, which is why a session can be
shipped as a file without a database round-trip.

Both persistence roots are gitignored, so a fresh clone starts empty. At
runtime the app seeds a demo device and demo session for previews — see
[explanation-screens.md](explanation-screens.md).

## The async story

The serial read loop, telemetry batching, session writes, and the WebSocket
hub all run on one asyncio event loop. `aiosqlite` keeps database calls off
the loop's critical path, and uvicorn hosts the API on the same loop in
Docker. The UI never blocks on I/O because it subscribes to pushed
`telemetry`/`packet`/`alert` frames rather than polling — in the single
process, that push is a direct function call; in Docker, it is the same hub
over the WebSocket.

## The honest directory map

What exists at the repo root: `desktop_app.py`, `run_desktop.py`,
`launch.py`, `uartscope_follow.py`, `uartscope_theme.py`, `smoke_pages.py`,
`check_handler_order.py`, `check_dict_keys.py`, `docker-compose.yml`,
`Dockerfile.backend`, `Dockerfile.desktop`, `uartscope.spec`,
`samples/`, `scripts/simulate_device.py`, `backend/`, `docs/`.

Corrections to the architecture tree the old README printed:

- `backend/app/plugins/` contains **only** `__init__.py`. Decoders live in
  `backend/app/core/protocol_decoder.py`; there is no `uart_decoder.py`,
  `custom_protocols.py`, or `base.py`.
- `backend/app/models/` contains **only** `__init__.py` — every model in one
  file.
- `backend/app/storage/` **does not exist**.
- There is **no root-level `pyproject.toml`**; the Python project file is
  `backend/pyproject.toml`.
- `websocket_hub.py` and `performance_tracker.py` both exist under `core/`.
- `scripts/simulate_device.py` is at the repo root, not under `backend/`.

## Why the v2 pass found silent-wrong-value bugs

The same property that makes the app fast to run — every layer trusting
in-process calls with no HTTP boundary — also removes the places a contract
fails loudly. An HTTP client gets a 422 when it sends `">"` where the schema
wants `"gt"`; an in-process caller just... doesn't match. Three bug families
grew in that gap, all invisible to a UI that rendered fine:

- **Condition-name drift.** The alert-rule picker stored symbol spellings
  (`>`, `<=`) while the engine compared internal names (`gt`, `lte`). Every
  UI-created rule was a silent no-op. v2 added `_CONDITION_ALIASES` in
  `alert_engine.py` so both spellings normalize to one vocabulary — the REST
  schema still demands the canonical names and answers 422 for symbols.
- **Handler-order and dict-key drift.** With every router sharing
  `prefix="/api"`, path patterns can shadow each other (it is why a stale
  `/{id}/stop` claim looked alive: sessions' `/{session_id}/stop` resolved
  first), and a producer/consumer disagreeing on a dict key yields `None`,
  not an error. CI now gates both: `check_handler_order.py` and
  `check_dict_keys.py` run on every push, precisely because pytest passes
  while the screen silently shows nothing.
- **Protocol misrouting.** The I2C scorer claimed plain ASCII, so `READY`
  decoded as an I2C transaction — a plausible, wrong answer printed in a nice
  table. Scoring was rewritten so text wins printable input, and the case is
  a permanent fixture in `samples/payloads.json`.

The general lesson: when the UI and the engine share memory instead of a
wire, nothing catches a vocabulary or ordering mismatch at runtime — so the
repo pushes those checks into static gates and smoke tests
(`smoke_pages.py --boot --wait 60` builds every screen over HTTP on CI).

## Related documents

- [explanation-screens.md](explanation-screens.md) — how the shell presents these engines
- [reference-api.md](reference-api.md) — the Docker/external-client surface
