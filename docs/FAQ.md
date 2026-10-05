# UARTScope Pro — FAQ

Answers to the questions that actually come up, including the ones this project
has a history of getting wrong. Every command here was run as written; every
default is read from `backend/app/config.py` at the time of writing.

- [Getting started](#getting-started)
- [Hardware and serial ports](#hardware-and-serial-ports)
- [Protocols and decoding](#protocols-and-decoding)
- [The plugin marketplace](#the-plugin-marketplace)
- [Sessions and export](#sessions-and-export)
- [Configuration](#configuration)
- [Troubleshooting](#troubleshooting)
- [Development](#development)

---

## Getting started

### Do I need a physical board?

No. There are three levels, in increasing order of realism:

| Option | What it proves | Command |
|---|---|---|
| Built-in simulator | The UI and the charts work | `python scripts/simulate_device.py /dev/ttyUSB0 115200 --virtual` |
| A virtual serial port (`/dev/pts/N`) | The real reader, framing and decoders | the simulator above, then connect to the printed `/dev/pts/N` |
| A physical board | Real UART timing and real USB bridging | see [Hardware](#hardware-and-serial-ports) |

The simulator prints the port to connect to:

```text
Virtual serial port: /dev/pts/5
Connect UARTScope to: /dev/pts/5
```

### Do I need to run uvicorn separately?

Not for local use. `desktop_app.py` imports the backend modules in-process and
serves the UI itself on **http://localhost:3000**.

You only need uvicorn for the Docker path, or if you want the REST API on its
own:

```bash
cd backend && python -m uvicorn app.main:app --port 8080
curl http://127.0.0.1:8080/api/health
```

### Which Python version?

**3.11–3.13.** That is the CI matrix. The code uses `asyncio_mode = "auto"`
from pytest-asyncio, which older pytest-asyncio releases do not support.

### Which port does the desktop app use?

3000 for the UI. 8080 is the standalone backend API. They do not conflict.

---

## Hardware and serial ports

### My board doesn't show up in the port list. Why?

Detection only lists ports the OS reports. Check in order:

1. **Is the device visible to the OS at all?**
   ```bash
   python -c "import serial.tools.list_ports as lp; print([p.device for p in lp.comports()])"
   ```
   If that list is empty, the problem is the driver or the USB bridge, not
   UARTScope.
2. **What the port is called.** The name depends on the USB bridge chip, not the
   board:

   | Bridge / board | Port name |
   |---|---|
   | CH340, FTDI, CP210x, PL2303 | `/dev/ttyUSB0` (Linux) |
   | Native USB — ESP32-S3, ESP32-C3, Arduino Uno R3 | `/dev/ttyACM0` (Linux) |
   | Most USB-serial adapters | `COM3`, `COM4`, … (Windows) |

   On macOS the device appears as a `/dev/cu.*` node, and you want the **`cu`**
   form rather than `tty` — the `tty` form blocks oddly on some adapters:
   ```bash
   ls /dev/cu.*
   ```

3. **Windows.** Install the driver for your bridge chip if the board is not
   recognised; CH340 and CP210x in particular need one and Windows will not
   supply it. A native-USB board may also need **BOOT** held while plugging it
   in the first time.

4. **Linux permissions.** A port owned by group `dialout` that you are not in
   gives `PermissionError` on open:
   ```bash
   sudo usermod -aG dialout $USER     # then log out and back in
   ```
   You do not need `sudo` to run UARTScope afterwards — the port is already
   open by then.

5. **Linux, and no device node appears at all.** The driver is missing:
   ```bash
   dmesg | tail -20
   ```
   `cp210x`, `ftdi_sio` and `ch341` are normally built in already.

### It connects, then the stream stops after a second or two.

Older versions had this bug: the read loop treated the normal case of "no data
for a moment" as a fatal error and exited. That is fixed, and there is a
regression test (`test_stream_survives_idle.py`) because it shipped once.

If it still happens, the device is almost certainly not sending anything. Send
`TEMP:23.4\n` by hand and see whether it appears on the Terminal screen.

### Can I stop and restart a device without restarting the app?

Yes, and it now works after a crash. Previously a reader that died left a stale
entry that made every later start a silent no-op — the device stayed bricked
until the app was restarted. `start_device` now detects a dead task and takes
over, logging at ERROR with the device name and port.

### How do I set 8E1 for an RS-485 / Modbus sensor?

Set it per device. Parity and stopbits are part of the device, not global:

| Field | Accepted values | Default |
|---|---|---|
| `baudrate` | any standard rate | `115200` |
| `parity` | `N`, `E`, `O`, `M`, `S` | `N` |
| `stopbits` | `1`, `1.5`, `2` | `1` |

Invalid values are rejected with a validation error rather than failing later at
port-open time. Leaving them unset gives 8N1, which is what every existing
device gets.

### Where are these stored?

In the device's existing `metadata_json` column, not as new table columns. The
project calls `Base.metadata.create_all` at startup and has no migration
framework, so adding a column would break existing databases with
`no such column`. Storing them in the JSON column that already exists means no
migration and no upgrade step.

---

## Protocols and decoding

### Which protocols are built in?

UART text, Modbus RTU, I2C, SPI, CAN, and CAN DBC. LIN (LDF), J1939 and DALI
ship in the registry catalogue and install as plugins.

### Which framing does a device use? This matters.

**Set the protocol correctly, or binary frames will be split.**

| Device protocol | Framing | Use for |
|---|---|---|
| `serial` (the default) | newline-delimited | text telemetry, AT commands, anything printing lines |
| `modbus_rtu`, `can`, `can_dbc`, `i2c`, `spi` | silent inter-character gap | binary protocols |

Binary protocols are **not** newline-delimited. A Modbus RTU master frames a
response by pausing 3.5 character times and sends no terminator at all, and a
payload byte may legitimately be `0x0A` — which is also the newline character.
So a device speaking Modbus must have its protocol set to `modbus_rtu`;
configured as `serial` it will be line-framed and frames will be cut.

There is no reliable automatic detection at the framing layer, so this is your
choice to make. Auto-detection exists for *decoding*, separately, via
`/api/protocols/detect`.

### What is `SerialData`? Why is a line also an object?

Every line the reader delivers is a `str` subclass carrying two extra
attributes:

- `raw_bytes` — the exact bytes as they arrived
- `decode_error` — `True` when the bytes are not valid UTF-8

Text devices are unaffected: `strip()`, `split()`, `encode()` and `len()`
behave exactly as on a plain string. For binary protocols, decode with
`raw_bytes`, **not** with the text — the text form of a binary frame is a lossy
placeholder.

Previously bytes were decoded with `errors="replace"`, so any byte outside
UTF-8 became U+FFFD *before* a decoder saw it. A real Modbus response
containing `0xFF 0x9C` reached the decoder as two replacement characters and
produced plausible-looking but wrong data — and even passed a CRC check. That
is what `raw_bytes` and `decode_error` exist to prevent.

### How do I decode a frame I captured?

Feed the bytes, not the text:

```python
from app.core.protocol_decoder import ProtocolManager
ProtocolManager().decode("modbus_rtu", frame_bytes)
```

### The decoder reports a wrong value even though the CRC passed.

Check whether you are decoding the text form. If a frame arrived with
`decode_error=True`, its string form has been through a lossy conversion. Use
`raw_bytes`.

---

## The plugin marketplace

### Installing a plugin does nothing / gets refused.

**This is expected on a fresh install.** Plugin installation is **disabled by
default**, because installing a plugin runs third-party Python inside the
application process with no sandbox. Enable it deliberately:

```bash
UARTSCOPE_PLUGIN_INSTALL_ENABLED=true python desktop_app.py
```

A refused install tells you exactly this, and nothing is written to disk.

### Is installing a plugin safe?

No, and the app does not pretend otherwise. Installing executes the plugin's
module with `exec()` in the application process. Validation checks the plugin's
*shape* — that it exposes a real `ProtocolDecoder` subclass and does not claim
a built-in protocol id — but a valid plugin can still do whatever its code
does. The Marketplace screen states this on the page rather than burying it.

The control is `plugin_install_enabled`, enforced inside
`PluginRegistry.install()` — the single point every caller goes through,
including the desktop app. An earlier version gated only the HTTP route, which
left the shipped Windows executable able to install plugins with the setting
off; that is fixed, and `test_plugin_install_gate.py` pins it on both paths.

### Do I need to restart after installing?

No. The decoder is registered with the live decoder table as soon as the
install completes, so it is usable immediately. Installs do survive a restart.

### Can I host my own registry?

Yes — `UARTSCOPE_PLUGIN_REGISTRY` accepts a URL or a file path. With it unset,
the bundled `registry/registry.json` is used.

---

## Sessions and export

### How do I export a capture?

`GET /api/export/session/{id}/bundle` produces a `.uartscope` zip. The same
builder backs the desktop export, so both produce an identical format.

CSV values containing a comma are quoted properly, and numeric types survive
the round trip instead of flattening to strings.

---

## Configuration

All settings are environment variables prefixed `UARTSCOPE_`.

| Variable | Default | Notes |
|---|---|---|
| `UARTSCOPE_DATABASE_URL` | `sqlite+aiosqlite:///./uartscope.db` | Postgres: `postgresql+asyncpg://user:pass@host/uartscope` |
| `UARTSCOPE_SERIAL_TIMEOUT` | `1.0` | seconds |
| `UARTSCOPE_MAX_HISTORY_PER_METRIC` | `10000` | per device, per metric |
| `UARTSCOPE_SESSIONS_DIR` | `./sessions` | |
| `UARTSCOPE_MAX_SESSION_SIZE_MB` | `500` | |
| `UARTSCOPE_PLUGIN_REGISTRY` | *(bundled)* | URL or path |
| `UARTSCOPE_PLUGIN_INSTALL_DIR` | `./plugins` | |
| `UARTSCOPE_PLUGIN_INSTALL_ENABLED` | **`false`** | off by default, see above |
| `UARTSCOPE_MQTT_ENABLED` | `false` | |
| `UARTSCOPE_MQTT_BROKER` | `localhost` | |
| `UARTSCOPE_MQTT_PORT` | `1883` | |
| `UARTSCOPE_MQTT_TOPIC_PREFIX` | `uartscope` | |
| `UARTSCOPE_DEBUG` | `false` | |

`UARTSCOPE_DEFAULT_BAUDRATE` exists but is **not** wired to anything yet —
`DeviceCreate` hardcodes `115200`. Setting it changes nothing today.

### Why was `host`, `port`, `telemetry_buffer_size` and `alert_check_interval` removed?

They were declared with explanatory comments and had **zero readers anywhere in
the codebase**. A comment describing behaviour the code does not implement is a
defect, so they were deleted rather than left to look functional. If you were
setting them, they never did anything.

---

## Troubleshooting

### A metric shows no unit

`TEMP:23.4` (no unit character) falls back to name inference, which knows
`temp`, `temperature`, `humidity`, `voltage`, `rpm`, `rssi` and similar.
Abbreviations it does not know — `HUM` for instance — get no unit. Writing
`TEMP:23.4C` includes the unit explicitly and always works.

### Charts freeze a couple of seconds after opening.

This was a real bug, fixed in v2.0.x: three background loops read
`ui.context.client` *inside* the coroutine, where it does not exist, so they
died on their first tick. Charts silently froze and alerts were never
delivered. The fix captures the client in the page body.

If you see it, check you are on a current version.

### The Terminal screen shows nothing but the device is connected.

Check the device's protocol is `serial`. Under gap framing a text device's
lines are merged; under line framing a binary device's frames are split. See
[Which framing does a device use](#which-framing-does-a-device-use-this-matters).

### A screen is blank or missing.

Build every screen headless and see which one fails:

```bash
python smoke_pages.py --boot --wait 60
```

It requests all 13 screen builds over real HTTP and reports non-200s. A screen
that raises while being constructed shows up here rather than as a mystery
blank page.

### How do I check the serial path is working without a board?

The test suite does this with a **pty**, which is a real character device the
kernel drives exactly as it drives a USB adapter. No board and no root needed:

```bash
cd backend && python -m pytest tests/test_binary_framing.py \
  tests/test_byte_preservation.py \
  tests/test_parity_stopbits.py \
  tests/test_terminal_callback_contract.py -v
```

CI runs these and additionally **fails the build if they stop running** — a
skip guard added for "no serial hardware in CI" would otherwise turn the only
tests covering the reader into silent no-ops.

---

## Development

```bash
# from the repo root, with a venv active
python -m pytest backend/tests/ -q
python check_handler_order.py      # screens that raise while being built
python check_dict_keys.py          # UI reads a key no producer writes
python -m uartscope_theme --audit  # WCAG contrast, computed not eyeballed
python smoke_pages.py --boot --wait 60
```

Lint is `ruff check app/ --line-length=120 --select E9,F63,F7,F82` from
`backend/`, enforced in CI.

### Testing against a real ESP32

Sensors are not needed. `hardware/esp32_acceptance/` contains firmware that
emits the exact byte patterns this project has historically mishandled — a
frame containing `0x0A`, a gap-delimited frame with no terminator, and a frame
containing invalid UTF-8 — with CRCs computed on-device.

Flash `esp32_acceptance.ino`, then:

```bash
python hardware/esp32_acceptance/real_hw_check.py --port /dev/ttyUSB0 --protocol modbus_rtu
```

Use `--protocol modbus_rtu`: the binary frames are only delivered whole under
gap framing.

`verify_checker_discriminates.py` proves the checker can actually tell a working
reader from a broken one, by replaying the same bytes through both.

### Where did the long-form guides go?

The twelve markdown guides were removed because they were written for v2.0.1 and
verified against that release; keeping stale documentation is worse than having
none. They are recoverable from the `v2.0.1` tag:

https://github.com/DawnofGenX/uartscope/tree/v2.0.1/docs

---

## License

MIT — see [LICENSE](../LICENSE).
