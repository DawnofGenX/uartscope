# How to connect a board

**Problem:** your board is plugged in, but UARTScope isn't showing it, or
connecting fails. Work down this page from the top; the port-in-use trap and the
permissions fix cover most real-world cases.

## 1. Scan first

On the **Devices** screen, click **Scan for devices**. The app lists every serial
port the OS exposes. A port appearing here means UARTScope *can* open it —
clicking **Add** registers the device (name = port path, baudrate 115200), and
**Start** on the device row opens the serial link (it calls the backend's
`connect` endpoint) and starts reading.

The empty state after a scan has three outcomes, and each means something:

| What you see | What it means |
|---|---|
| Ports listed | Scan worked. Add the right port. |
| `No serial ports found` | The OS doesn't see the port at all — bad cable (charge-only USB cables exist), board unpowered, or missing driver (step 4). |
| A scan error in red | The scan itself failed — usually a permissions problem (step 3). |

## 2. The #1 trap: another program is holding the port

Serial ports are exclusive: if another process has the port open, UARTScope
registers the device fine and then fails to connect. This is the most common
real-world failure, and the app's own empty state calls it out: *"If another
program has the port open, close it and scan again."*

Close everything that grabs serial ports, then scan and connect again:

- Arduino IDE's Serial Monitor, and its built-in uploader
- PuTTY, minicom, screen,tio, CoolTerm, RealTerm
- Other UARTScope instances (the desktop app, or a script that opened the port
  with pyserial)

Linux makes the offender easy to find:

```bash
sudo fuser /dev/ttyUSB0        # prints the PID holding the port
sudo lsof /dev/ttyUSB0
```

On Windows, Device Manager won't tell you the holder; close candidate apps one
at a time.

## 3. Permissions and port names

### Linux

Your user must be in the `dialout` group to open `/dev/ttyUSB*` / `/dev/ttyACM*`
without root:

```bash
groups | grep dialout || sudo usermod -aG dialout $USER
```

`usermod` takes effect at your **next login** — log out and back in (or reboot),
then confirm with `groups`. Ports:

- `/dev/ttyUSB0`, `ttyUSB1`, … — FTDI/CH34x/CP210x USB-serial chips
- `/dev/ttyACM0`, … — boards enumerating as USB CDC devices (many Arduino, Pico,
  ESP32-S2/S3 boards)

If the device shows up in `dmesg | tail` when you plug it in but not under
`/dev/`, you need the chip's kernel module or udev rule.

### macOS

Ports appear as `/dev/cu.usbserial-*` or `/dev/cu.usbmodem*` and are readable by
your user — no group changes needed. Use the `cu.*` name, not `tty.*`. Modern
macOS needs drivers only for older FTDI/CP210x chips; CH34x clones ship with
them on older macOS and via vendor kexts on newer ones.

### Windows

Ports are `COM1`, `COM3`, …. No permission model to configure, but:

- If the port doesn't appear in the scan, check Device Manager → Ports
  (COM & LPT) for a yellow-bang device and install the bridge-chip driver
  (FTDI, WCH CH34x, Silicon Labs CP210x, Raspberry Pi Pico's "Windows Driver
  Installation Files" installer).
- COM numbers above 9 are legal (`COM10`) but a few older tools can't type
  them; UARTScope handles any number.

## 4. Baudrate: you set it — there is no auto-detection

UARTScope does **not** guess baudrates. The device's baudrate field is used as
configured (default 115200). If the wrong baudrate is set, the connection still
succeeds but the Terminal shows garbage — mojibake like `ï¿½ï¿½°~` — because
UARTScope is sampling the wire at the wrong rate.

How to find the right value:

1. Check the firmware: the argument to `Serial.begin(...)` in Arduino code,
   or the UART init in your SDK. 115200 is the most common default.
2. If the firmware prints a banner on boot, try the usual suspects:
   9600, 57600, 115200 — a readable banner at a given rate is the right one.

## 5. Register via the API (headless / CI)

The same registration the UI does, over HTTP against the backend:

```bash
curl -X POST http://127.0.0.1:8080/api/devices/ \
  -H 'content-type: application/json' \
  -d '{"port": "/dev/ttyUSB8", "name": "esp32-testbench", "baudrate": 115200}'
```

```json
{"id":"f105bde5-7229-4e81-b9b5-72f1247d9206","name":"esp32-testbench","port":"/dev/ttyUSB8","protocol":"serial","baudrate":115200,"status":"detected","board_type":null,"metadata_json":{},"created_at":"2026-09-28T20:20:18.296773","last_seen":null}
```

(The `id` is assigned per instance; don't hard-code it — read it from this
response.) `DeviceCreate` fields: `port` (required), `name`, `protocol`
(default `"serial"`), `baudrate` (default 115200), `board_type`, `metadata`.
Registering a port that's already registered returns **409** with detail
`Device on /dev/ttyUSB0 already registered`. Then start the link and check data:

```bash
curl -X POST http://127.0.0.1:8080/api/devices/<id>/connect
curl http://127.0.0.1:8080/api/telemetry/latest/<id>
```

The real verbs are `connect` and `disconnect` — `start`/`stop` do not exist on
devices. See the [API reference](reference-api.md).

## Troubleshooting table

| Symptom | Cause | Fix |
|---|---|---|
| Port missing from scan, `dmesg` shows nothing on plug-in | Charge-only cable, dead board, no driver | Try a data cable; check board power; install bridge-chip driver |
| `Permission denied` opening the port | Not in `dialout` (Linux) | Step 3; remember to re-login |
| Registers but connect fails immediately | Port held by another program | Step 2 — `fuser`/`lsof` finds the PID |
| Connects, Terminal shows garbage | Wrong baudrate | Step 4 |
| Connects, terminal shows clean lines, no charts | Device prints free-form text, not `KEY:VALUE`/JSON | UARTScope only charts parsed metrics; see [decode protocols](how-to-decode-protocols.md) for raw analysis |
| 409 `already registered` | Device entry from a previous run | Remove it (`DELETE /api/devices/<id>` or the UI) or reuse the existing entry |
| Works in the app, fails in Docker | The container can't see the host's serial device | Docker Compose needs the device passed through (`devices:`); the compose file in this repo is API-oriented — run the desktop app on the host for serial work |

Related: [tutorial](tutorial-first-capture.md) (first capture end to end) ·
[configuration reference](reference-configuration.md) (`UARTSCOPE_DEFAULT_BAUDRATE`,
`UARTSCOPE_SERIAL_TIMEOUT`).
