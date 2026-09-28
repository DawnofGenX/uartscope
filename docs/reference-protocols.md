# Protocol Decoder Reference

The decoder engine is `backend/app/core/protocol_decoder.py`: a
`ProtocolManager` holding six built-in decoder plugins, exposed over HTTP as
`/api/protocols/*` (see [reference-api.md](reference-api.md)) and used
in-process by the desktop Decoder screen. There is no separate `plugins/`
package — `backend/app/plugins/` holds only an empty `__init__.py`.

## The six decoders

| `protocol_id` | Name | What it parses | Notes |
|---|---|---|---|
| `uart_text` | UART Text | AT commands (`AT+...`), NMEA sentences (`$G...`), debug print, CSV and key-value telemetry (`TEMP:23.4`) | Also extracts numeric metrics with units and feeds the Charts screen |
| `modbus_rtu` | Modbus RTU | Address, function code, data, CRC — function codes 1–6, 15, 16 | Address must be 1–247 |
| `i2c` | I2C | 7/10-bit addressing, read/write bit, ACK/NACK | Scores only against a known-address table |
| `spi` | SPI | MOSI/MISO byte pairs, CS polarity, clock modes | Heuristic only — no framing to trust |
| `can` | CAN Bus | CAN 2.0A/B: 11/29-bit ID, DLC, data bytes, CRC | |
| `can_dbc` | CAN DBC | CAN frames decoded through signal definitions from a `.dbc` file | Decode-only; needs a loaded DBC |

All six define `encode`; the API's encode endpoint works for every one of
them. **`can_dbc` is decode-only for signal semantics** — it maps raw CAN
bytes to named signals via the database; it does not assemble signal values
back into frames. `.ldf` (LIN) files are accepted by the load endpoint but
return `"LDF format not yet implemented"`.

## Autodetect scoring

`POST /api/protocols/decode` with `"protocol_id": "auto"` (the default) calls
`can_decode()` on every plugin and keeps the highest score. A decoder wins
only above a **0.3 floor**; below it the endpoint reports
`"No protocol detected with sufficient confidence"`. Scores per decoder, from
`can_decode()` in the source:

| Decoder | Condition | Score |
|---|---|---|
| UART Text | starts `AT`/`AT+` | 0.9 |
| UART Text | starts `$G` (NMEA) | 0.95 |
| UART Text | entirely printable ASCII | 0.7 |
| Modbus RTU | address 1–247, function code in table | 0.75 |
| I2C | first byte's 7-bit address in the known-address table | 0.6 |
| SPI | length ≥ 4 and even | 0.4 |
| CAN | byte 3 ≤ 8 and length ≥ 3 + DLC + 1 | 0.65 |
| anything else | — | 0.0 |

This ordering is a v2 fix. Before it, plain ASCII text like `READY` scored
under I2C's old heuristic and was misrouted; the I2C decoder now returns 0.0
for all-printable input, and `samples/payloads.json` carries `READY` as a
regression fixture. When two decoders both score, the higher wins — text
beats Modbus and CAN on printable payloads.

## Frame shapes and worked examples

All examples below were sent to a live `/api/protocols/decode` as
`{"protocol_id": "...", "raw_hex": "..."}`.

### UART Text

UTF-8 text lines. Subtypes: AT command, NMEA sentence, key-value
(`KEY:value`, comma-separated pairs), plain debug print.

```json
// 41542B49443F0D0A  ->  "AT+ID?"
{"success": true, "protocol_id": "uart_text",
 "decoded": {"type": "text", "content": "AT+ID?",
             "subtype": "at_command", "command": "AT+ID?"}}

// auto on "2447504747412C3132..."  ->  "$GPGGA,123519,4807.080,N,..."
{"decoded": {"type": "text", "content": "$GPGGA,...",
             "subtype": "nmea", "sentence_type": "$GPGGA"}}
```

Key-value lines additionally yield `metrics` entries with parsed values and
inferred units (`TEMP:23.4` → 23.4 °C, `RSSI:-67` → −67 dBm).

### Modbus RTU

`[addr][func][data...][crc-lo][crc-hi]`.

```json
// 010300000001840A
{"decoded": {"type": "modbus_rtu", "device_addr": 1, "function_code": 3,
             "function_name": "Read Holding Registers",
             "data": "00000001", "crc": "840a", "length": 8}}
```

Encoding accepts `{"slave_address":1,"function_code":3,"register_address":0,"quantity":1}`
and returns `{"raw_hex": "01030000", "length": 4}` — note the encoder emits
the request frame without computing the CRC.

### I2C

First byte packs a 7-bit address and R/W bit; extended 10-bit addressing and
ACK/NACK bits are parsed. Detection consults a `KNOWN_ADDRESSES` table, so
only traffic aimed at recognized chips is claimed.

### SPI

Even-length payloads are read as MOSI/MISO pairs, with chip-select polarity
and clock mode reported. With no framing, treat its output as suggestive,
not authoritative.

### CAN

`[id-hi][id-lo][dlc][data...][crc?]`, 11-bit (standard) or 29-bit
(extended) IDs:

```json
// 18DAF110023F0000000000
{"decoded": {"type": "can", "can_id": "0x18DA", "can_id_decimal": 6362,
             "dlc": 241, "data": "10023f0000000000",
             "data_bytes": [16, 2, 63, 0, 0, 0, 0, 0],
             "crc": "", "raw_hex": "18daf110023f0000000000", "extended": true}}
```

The example is a naive split, which shows the decoder's limits: without a DBC
database, a raw byte stream is interpreted positionally and fields like `dlc`
can come out wrong. Use `can_dbc` for real CAN networks.

### CAN DBC

Load a database first, then frames decode into named signals:

```bash
curl -X POST http://localhost:8080/api/protocols/dbc/load \
  -H 'Content-Type: application/json' \
  -d '{"filename":"vehicle.dbc","content":"<dbc file text>"}'
```

```json
{"success": true, "filename": "vehicle.dbc",
 "result": {"messages": [...], "signals": [...]}}
```

The file arrives as text in the request body; on the desktop Decoder screen
you pick a `.dbc` file from disk instead. Check state with
`GET /api/protocols/dbc/loaded` (`{"loaded": true, "messages": N,
"total_signals": N, "message_ids": ["0x1A0", ...], "message_names": {...}}`).
The parse path is `DBCDecoder.load_dbc_file()`; the API's text variant is
`load_dbc_text()`, which spills the content to a temporary `.dbc` file.
`.ldf` files are recognised by extension and refused as
"LDF format not yet implemented".

## Adding your own sample payloads

`samples/payloads.json` is the fixture set behind the Decoder screen's
example picker and the decoder regression checks. Format:

```json
{
  "samples": [
    {
      "name": "Temperature and humidity telemetry",
      "line": "TEMP:23.4",
      "hex": "54454D503A32332E34",
      "expects": {
        "protocol": "uart_text",
        "subtype": "key_value",
        "metrics": {"TEMP": {"value": 23.4, "unit": "°C"}}
      }
    }
  ],
  "alert_rule_examples": [
    {"rule": {"metric_name": "TEMP", "condition": ">", "threshold": 30.0,
              "severity": "critical"},
     "fires_when": "TEMP exceeds 30 °C"}
  ]
}
```

Per sample: `name` (display label), `line` (ASCII a serial device would
send; optional for binary protocols), `hex` (the byte form pasted into the
Decoder's Hex field), and `expects` — the decode result to assert
(`protocol`, plus type-specific keys like `subtype`, `metrics`,
`device_addr`, `function_code`, `crc`). The `alert_rule_examples` block holds
rule shapes in the UI's symbol spelling (`>`, `<`, `>=`) for alert testing.
To add a payload: compute the hex of your line
(`echo -n 'TEMP:23.4' | xxd -p`), pick the `protocol` id above, and describe
what the decoder should return in `expects`.

## Related documents

- [reference-api.md](reference-api.md) — the `/api/protocols/*` endpoints
- [how-to-decode-protocols.md](how-to-decode-protocols.md) — the Decoder screen walkthrough
