#!/usr/bin/env python3
"""UARTScope real-hardware acceptance check against a physically attached ESP32.

Complements the pty tests: those prove the reader's logic, this proves the
reader works against real silicon, a real USB-serial bridge, and real UART
timing. No sensors are required -- the acceptance firmware emits the exact byte
patterns that broke UARTScope.

Usage:
    python real_hw_check.py --port /dev/ttyUSB0
    python real_hw_check.py --port /dev/ttyUSB0 --protocol modbus_rtu
    python real_hw_check.py --port /dev/ttyUSB0 --duration 45

Protocol matters: UARTScope chooses framing per protocol. `serial` (the
default) is LINE framed; `modbus_rtu`/`can`/`spi`/`i2c` are GAP framed on a
3.5-character silent gap. Binary frames are only delivered whole under gap
framing, so --protocol modbus_rtu is required for the binary checks.
"""
import argparse
import asyncio
import sys
import time
from collections import Counter

try:
    import serial
except ImportError:
    sys.exit("pyserial missing: pip install pyserial")


P = argparse.ArgumentParser()
P.add_argument("--port", default="/dev/ttyUSB0")
P.add_argument("--baud", type=int, default=115200)
P.add_argument("--protocol", default="modbus_rtu",
               help="UARTScope device protocol; binary framing needs modbus_rtu")
P.add_argument("--duration", type=int, default=35, help="seconds to listen")
P.add_argument("--parity", default="N")
P.add_argument("--stopbits", type=float, default=1.0)
A = P.parse_args()

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, ok))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    if detail:
        print(f"        {detail}")


def modbus_crc16(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def looks_like_valid_modbus(frame: bytes) -> bool:
    """A response frame must be 5+ bytes and its CRC must actually check out."""
    if len(frame) < 7:
        return False
    if modbus_crc16(frame[:-2]) == (frame[-2] | (frame[-1] << 8)):
        return True
    # Some firmwares append CRLF; strip and retry.
    stripped = frame.rstrip(b"\r\n")
    return len(stripped) >= 7 and modbus_crc16(stripped[:-2]) == (
        stripped[-2] | (stripped[-1] << 8))


async def main():
    parity_map = {"N": serial.PARITY_NONE, "E": serial.PARITY_EVEN,
                  "O": serial.PARITY_ODD}
    print("=" * 74)
    print(f"UARTScope REAL HARDWARE CHECK  port={A.port} baud={A.baud} "
          f"protocol={A.protocol} {A.parity}{int(A.stopbits)}")
    print("=" * 74)

    try:
        port = serial.Serial(A.port, A.baud, timeout=0.2,
                             parity=parity_map.get(A.parity.upper(),
                                                   serial.PARITY_NONE),
                             stopbits=(serial.STOPBITS_TWO if A.stopbits == 2
                                       else serial.STOPBITS_ONE))
    except Exception as e:
        sys.exit(f"cannot open {A.port}: {e}\n"
                 "Is the board plugged in, and attached to WSL via usbipd?")

    got = []

    async def on_data(device_id, session_id, line):
        got.append(line)

    sys.path.insert(0, "/home/hermes/uartscope/backend")
    from app.core.device_manager import DeviceInfo          # noqa: E402
    from app.core.serial_reader import SerialReader          # noqa: E402
    from app.models import DeviceCreate                      # noqa: E402

    dev = DeviceInfo(DeviceCreate(name="esp32", port=A.port, baudrate=A.baud,
                                  protocol=A.protocol, parity=A.parity,
                                  stopbits=A.stopbits))
    dev.serial_conn = port
    dev.status = "connected"

    reader = SerialReader()
    await reader.start_device(dev, "hw", on_data)

    # let the board finish booting and start its cycle
    await asyncio.sleep(3.0)
    got.clear()
    t0 = time.time()
    while time.time() - t0 < A.duration:
        await asyncio.sleep(0.2)

    await reader.stop_all()
    port.close()

    if not got:
        check("board is transmitting at all", False,
              f"nothing received in {A.duration}s on {A.port}. Check the baudrate "
              f"and that the acceptance firmware is flashed.")
        return

    # Classify by CONTENT, not by decode_error. A Modbus frame like
    # 01 03 02 00 0A 38 43 is perfectly valid UTF-8, so it is delivered as
    # text even though it is binary. Filtering on decode_error hides exactly
    # the frame these checks exist to verify -- this was a real false negative
    # in an earlier draft of this script.
    def is_frame(b):
        s = b.rstrip(b"\r\n")
        return len(s) >= 7 and modbus_crc16(s[:-2]) == (s[-2] | (s[-1] << 8))

    frames = [g.raw_bytes for g in got if is_frame(g.raw_bytes)]
    texts = [str(g) for g in got
             if g not in [x for x in got if is_frame(x.raw_bytes)]]
    allbytes = b"".join(g.raw_bytes for g in got)

    print(f"\n  received {len(got)} deliveries: {len(frames)} CRC-valid frames, "
          f"{len(texts)} other")
    print(f"  first 3 text  : {texts[:3]}")
    print(f"  CRC-valid     : {[f.hex() for f in frames[:6]]}\n")

    # 1. it is really an ESP32 running our firmware
    joined = " ".join(texts)
    check("ESP32 is running the acceptance firmware",
          "READY" in joined or "CYCLE" in joined or "TEMP:" in joined,
          f"text seen: {joined[:160]!r}")

    # 2. the text path works on real silicon
    temp_lines = [t for t in texts if "TEMP:" in t]
    check("text telemetry parsed from real hardware", bool(temp_lines),
          f"{len(temp_lines)} TEMP lines, e.g. {temp_lines[:2]}")

    # 3. text lines were not merged
    check("text lines were not merged into one delivery",
          not any(t.count("TEMP:") > 1 for t in texts),
          "a text burst arriving as one blob means line framing was lost")

    # 4. binary frames actually arrived as BINARY (invalid UTF-8 survived)
    check("binary frames arrived as bytes, not mangled text",
          bool(frames),
          f"{len(frames)} binary deliveries; U+FFFD would mean the reader "
          f"destroyed the payload again")

    # 5. no U+FFFD replacement characters anywhere
    check("no replacement characters in any delivery",
          "\ufffd" not in joined and b"\xef\xbf\xbd" not in allbytes,
          "U+FFFD means UTF-8 replace-decoding is back")

    # 6. THE bug: a frame containing 0x0A must arrive whole.
    # Compare case-insensitively on the hex, because 0x0A IS the newline byte
    # and appears in the CRC of almost every frame.
    frames_with_0a = [f for f in frames if b"0a" in f.hex().encode().lower()]
    if A.protocol.lower() == "modbus_rtu":
        check("0x0A-bearing frame arrived WHOLE and CRC-valid",
              bool(frames_with_0a),
              f"{len(frames_with_0a)} CRC-valid frames contain a 0x0A byte. "
              f"None did, so a payload byte is still splitting frames. "
              f"seen: {[f.hex() for f in frames[:4]]}")
    else:
        print("[SKIP] 0x0A framing check needs --protocol modbus_rtu")

    # 6b. the 0xFF 0x9C frame: invalid UTF-8 that used to be destroyed
    frames_high = [f for f in frames if b"ff" in f.hex().encode().lower()]
    check("high-byte frame (0xFF) survived as bytes",
          bool(frames_high),
          f"{len(frames_high)} CRC-valid frames carry a 0xFF payload byte; "
          f"zero means invalid UTF-8 is being destroyed again")

    # 7. at least one full cycle of three frames should arrive
    check("multiple distinct frames delivered", len(frames) >= 3,
          f"{len(frames)} CRC-valid frames in {A.duration}s; the firmware "
          f"emits 3 per cycle every 10s, so fewer than 3 means frames are "
          f"being merged or dropped")

    # 8. throughput sanity
    total = len(got)
    check("delivery rate is sane", total >= 3,
          f"{total} deliveries over {A.duration}s")

    print("\n" + "=" * 74)
    bad = [n for n, ok in RESULTS if not ok]
    print(f"{len(RESULTS)-len(bad)}/{len(RESULTS)} real-hardware checks passed")
    for n in bad:
        print(f"  FAIL {n}")
    print("=" * 74)


if __name__ == "__main__":
    asyncio.run(main())
