# How to decode protocols

**Problem:** you have raw bytes — from a bus capture, a hex dump, or a stream
that isn't parseable telemetry — and you want to know what they mean.

UARTScope ships six protocol decoders. All six decode, and all six also encode.
A `.dbc` file is only needed to turn CAN IDs and bytes into named signals on
decode; the CAN-DBC encoder does not require one.

| ID | Name | Covers |
|---|---|---|
| `uart_text` | UART Text | AT commands, NMEA GPS sentences, debug prints, CSV / `KEY:VALUE` lines |
| `modbus_rtu` | Modbus RTU | Function codes 1–6, 15, 16; CRC check |
| `i2c` | I2C | 7/10-bit addressing, read/write, ACK/NACK |
| `spi` | SPI | MOSI/MISO, CS polarity, clock modes |
| `can` | CAN Bus | CAN 2.0A/B — 11/29-bit IDs, data bytes, CRC |
| `can_dbc` | CAN DBC | CAN signals decoded through a `.dbc` database file |

## The Decoder screen

Open **Decoder** in the rail. It has three parts:

1. **Protocol picker** — `auto` plus the six protocols. Start with `auto`.
2. **Hex field** — the bytes as hex, e.g. `010300010001840A` (the placeholder
   shows exactly that). Spaces and colons are stripped, and an odd digit count
   or non-hex character gives a pointed error, not a crash.
3. **Result panel** — the decoded fields, plus the raw hex you fed it.

If a device is selected, the screen also shows a live-stream hint: every line
from that device runs through the decoder, so you can watch a bus decode frame
by frame instead of pasting one-off payloads.

### Feeding it without hardware: `samples/payloads.json`

The repo ships fixtures at [`samples/payloads.json`](../samples/payloads.json).
Each entry carries a `hex` form — paste that into the Decoder's hex field — and
a `line` form you can send down a (virtual) serial line instead, plus an
`expects` block so you can check the decode against ground truth. Try the
Modbus fixture `010300010001840A` (a read-holding-registers request) with the
picker on `auto` — it decodes as function code 3, "Read Holding Registers",
CRC `840a` validated.

## Autodetect

`auto` scores every decoder against the bytes and picks the best, with a
confidence floor: below the floor it reports *"No protocol detected with
sufficient confidence"* rather than guessing. Text-like payloads are explicitly
scored toward `uart_text` — an earlier release misrouted them to I2C, and v2
fixed that, so pasting an AT command now decodes instead of returning nothing.

## A real decode, over the API

The Decoder screen calls the same backend route, `POST /api/protocols/decode`.
Body fields: `raw_hex` (hex string) and `protocol_id` (defaults to `auto`).
All output below is copied from live calls against a running backend on :8080.

Autodetect a telemetry line:

```bash
curl -s -X POST http://127.0.0.1:8080/api/protocols/decode \
  -H 'content-type: application/json' \
  -d '{"raw_hex": "54454D503A32332E34", "protocol_id": "auto"}'
```

```json
{"success":true,"protocol_id":"uart_text","protocol_name":"UART Text","decoded":{"type":"text","content":"TEMP:23.4","subtype":"key_value","values":{"TEMP":"23.4"}}}
```

A Modbus RTU request — `auto` recognizes it and validates the CRC:

```bash
curl -s -X POST http://127.0.0.1:8080/api/protocols/decode \
  -H 'content-type: application/json' \
  -d '{"raw_hex": "010300000002C40B", "protocol_id": "auto"}'
```

```json
{"success":true,"protocol_id":"modbus_rtu","protocol_name":"Modbus RTU","decoded":{"type":"modbus_rtu","device_addr":1,"function_code":3,"function_name":"Read Holding Registers","data":"00000002","crc":"c40b","length":8}}
```

An AT command, forced onto `uart_text`:

```bash
curl -s -X POST http://127.0.0.1:8080/api/protocols/decode \
  -H 'content-type: application/json' \
  -d '{"raw_hex": "41542B435351", "protocol_id": "uart_text"}'
```

```json
{"success":true,"protocol_id":"uart_text","protocol_name":"UART Text","decoded":{"type":"text","content":"AT+CSQ","subtype":"at_command","command":"AT+CSQ"}}
```

If the picker is unsure, the honest answer looks like this — no decode is
better than a wrong one:

```json
{"success":false,"message":"No protocol detected with sufficient confidence","raw_hex":"..."}
```

## Encoding (the other direction)

`POST /api/protocols/encode` takes `protocol_id` plus a `data` object and
returns raw hex — verified with Modbus:

```bash
curl -s -X POST http://127.0.0.1:8080/api/protocols/encode \
  -H 'content-type: application/json' \
  -d '{"protocol_id": "modbus_rtu", "data": {"device_addr": 1, "function_code": 3, "start_register": 0, "quantity": 2}}'
```

```json
{"protocol_id":"modbus_rtu","raw_hex":"01030000","length":4}
```

All six implement encode, `can_dbc` included — it returns a fixed 12-byte
CAN ID plus data frame. Unknown protocol IDs return 404, so scripts can fail
loudly.

## DBC files for CAN

Raw CAN gives you IDs and bytes; a `.dbc` file maps those to named signals with
scaling and units.

- **UI:** Decoder screen → **CAN database** panel → paste the `.dbc` file's
  contents → load. The status line flips from `No DBC loaded` to the loaded
  file, and `can_dbc` decodes appear in results.
- **API:** `POST /api/protocols/dbc/load` with body
  `{"content": "<file contents>", "filename": "vehicle.dbc"}` (`.ldf` files are
  accepted too), and `GET /api/protocols/dbc/loaded` to check what's active.

The DBC route is a plain JSON body — send file contents, not a multipart
upload.

## Gotchas

- **Hex, not text, in the Decoder field.** The fixtures' `line` values
  (`AT+CSQ`) go to a device's serial line; their `hex` values go to the Decoder.
  (Converting yourself: `echo -n 'AT+CSQ' | xxd -p` → `41542b435351`.)
- **Autodetect is deliberately conservative.** Piping the *same* bytes through
  with an explicit `protocol_id` often succeeds where `auto` abstained — check
  the expected protocol from the fixture's `expects` block before concluding
  the decode is broken.
- **Live decoding needs a connected device**; the Decoder screen's live mode
  reads from the selected device's stream.
- **DBC must be loaded before `can_dbc` decodes anything** — the picker will
  select the protocol but signal names only exist once a database is loaded.

Related: [tutorial](tutorial-first-capture.md) ·
[connect a board](how-to-connect-a-board.md) ·
[protocol reference](reference-protocols.md)
