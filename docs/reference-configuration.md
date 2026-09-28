# UARTScope Configuration Reference

Every setting is a field of `Settings` in `backend/app/config.py`
(pydantic-settings). Override any of them with an environment variable formed
as `UARTSCOPE_` + the upper-cased field name — `database_url` becomes
`UARTSCOPE_DATABASE_URL`.

## Environment settings

| Setting | Env var | Default | What it changes |
|---|---|---|---|
| `app_name` | `UARTSCOPE_APP_NAME` | `UARTScope Pro` | App name string |
| `app_version` | `UARTSCOPE_APP_VERSION` | `2.0.1` | Version reported by `GET /api/health` |
| `debug` | `UARTSCOPE_DEBUG` | `false` | Debug mode |
| `host` | `UARTSCOPE_HOST` | `0.0.0.0` | Bind address of the uvicorn backend |
| `port` | `UARTSCOPE_PORT` | `8080` | Listen port of the uvicorn backend |
| `database_url` | `UARTSCOPE_DATABASE_URL` | `sqlite+aiosqlite:///./uartscope.db` | SQLAlchemy async URL for device and alert-rule storage. PostgreSQL example: `postgresql+asyncpg://user:pass@localhost/uartscope` |
| `default_baudrate` | `UARTSCOPE_DEFAULT_BAUDRATE` | `115200` | Baudrate pre-filled for new devices |
| `serial_timeout` | `UARTSCOPE_SERIAL_TIMEOUT` | `1.0` | Read timeout (seconds) on the serial port |
| `max_history_per_metric` | `UARTSCOPE_MAX_HISTORY_PER_METRIC` | `10000` | Points retained per metric in the telemetry history |
| `telemetry_buffer_size` | `UARTSCOPE_TELEMETRY_BUFFER_SIZE` | `500` | Size of the in-memory telemetry batching buffer |
| `sessions_dir` | `UARTSCOPE_SESSIONS_DIR` | `./sessions` | Directory where session JSON files are written |
| `max_session_size_mb` | `UARTSCOPE_MAX_SESSION_SIZE_MB` | `500` | Cap on a single session file |
| `mqtt_enabled` | `UARTSCOPE_MQTT_ENABLED` | `false` | Turns the MQTT bridge on |
| `mqtt_broker` | `UARTSCOPE_MQTT_BROKER` | `localhost` | Default broker host |
| `mqtt_port` | `UARTSCOPE_MQTT_PORT` | `1883` | Default broker port |
| `mqtt_topic_prefix` | `UARTSCOPE_MQTT_TOPIC_PREFIX` | `uartscope` | Prefix for published topics |
| `alert_check_interval` | `UARTSCOPE_ALERT_CHECK_INTERVAL` | `2.0` | How often (seconds) the alert engine evaluates rules |

`./uartscope.db` and `./sessions/` are resolved relative to the process's
working directory, and both are gitignored — a fresh clone has neither.

## Docker

`docker-compose.yml` defines two services and one named volume:

| Service | Built from | Port | Notes |
|---|---|---|---|
| `backend` | `Dockerfile.backend` | `8080:8080` | Sets `UARTSCOPE_DATABASE_URL=sqlite+aiosqlite:///./data/uartscope.db`, `UARTSCOPE_MQTT_ENABLED=false`, `UARTSCOPE_DEBUG=false`; mounts the `uartscope-data` volume at `/app/data`; `restart: unless-stopped` |
| `desktop` | `Dockerfile.desktop` | `3000:3000` | Gets `API_URL=http://backend:8080` and `depends_on: backend`; the browser talks to this service |

In Docker, the desktop container is the only place `API_URL` matters: the UI
reaches the FastAPI service over HTTP there. Run `docker compose up` and open
port 3000.

## Device simulator

`scripts/simulate_device.py` (repo root, not under `backend/`) sends fake
telemetry over a serial port:

```
python scripts/simulate_device.py [port] [baudrate] [--virtual]
```

Defaults: `/dev/ttyUSB0` at `115200`. With `--virtual` it opens a
pseudo-terminal pair and prints the slave path to point UARTScope at, so no
hardware is needed.

The flags are positional-optional: `--virtual` must come **after** `port` and
`baudrate` or argparse will treat it as the port name (`--help` opens a
serial port literally named `--help` and crashes). Safe forms:

```
python scripts/simulate_device.py /dev/ttyUSB0 115200
python scripts/simulate_device.py /dev/ttyUSB0 115200 --virtual
```

## Desktop binary

`uartscope.spec` (repo root) is the PyInstaller spec. It builds
`run_desktop.py` into a single executable named `uartscope`, bundling the
`backend/` tree as data under `app`, plus `desktop_app.py` and `launch.py`.
Hidden imports cover uvicorn, nicegui, starlette, fastapi, pydantic,
sqlalchemy/aiosqlite, and pyserial. The Windows `.exe` is built by the CI
release job and uploaded as the `uartscope-windows-x64` artifact.

## Continuous integration

`.github/workflows/ci.yml` runs, in order:

1. **Lint** — `cd backend && ruff check app/ --line-length=120 --select E9,F63,F7,F82`
2. **Tests** — `cd backend && pytest tests/ -v --tb=short` with
   `UARTSCOPE_DATABASE_URL=sqlite+aiosqlite:///./test.db` (75 tests pass on
   the current main)
3. **Static gates** — three repo-root scripts that catch bugs pytest cannot
   see because they only appear when a screen renders:
   - `python check_handler_order.py`
   - `python check_dict_keys.py`
   - `python -m uartscope_theme --audit` (WCAG contrast audit; exits 1 when a
     recorded ratio drifts from the computed one)
4. **Screen smoke test** — `python smoke_pages.py --boot --wait 60` boots the
   app and builds every screen over HTTP
5. **Docker builds** — both `Dockerfile.backend` and `Dockerfile.desktop`

A separate release job (Python 3.11) builds and uploads the Windows
executable.

## Related documents

- [reference-api.md](reference-api.md) — HTTP surface and its defaults
- [explanation-architecture.md](explanation-architecture.md) — what each
  setting actually sits on top of
