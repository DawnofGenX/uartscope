"""Prove real_hw_check.py can actually FAIL — before any board is attached.

A hardware acceptance test that only ever passes is worthless. This feeds the
checker a byte stream captured from a *deliberately broken* reader and a
*correct* reader, and asserts the checks discriminate between them.

The stream is exactly what the ESP32 acceptance firmware emits, reconstructed
byte-for-byte, including a real Modbus CRC.
"""
import asyncio
import os
import pty
import sys
import time

sys.path.insert(0, "/home/hermes/uartscope/backend")

import serial                                                    # noqa: E402
from app.core.device_manager import DeviceInfo                   # noqa: E402
from app.core.serial_reader import SerialReader                   # noqa: E402
from app.models import DeviceCreate                               # noqa: E402

R = []


def check(name, ok, detail=""):
    R.append((name, ok))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    if detail:
        print(f"        {detail}")


def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def modbus_response(slave: int, fn: int, value: int) -> bytes:
    """Exactly what the firmware emits -- same layout, same CRC."""
    body = bytes([slave, fn, 0x02, (value >> 8) & 0xFF, value & 0xFF])
    c = crc16(body)
    return body + bytes([c & 0xFF, c >> 8])


# The firmware's cycle, in order.
F0A = modbus_response(0x01, 0x03, 0x000A)   # value 10  -> contains 0x0A
F2A = modbus_response(0x01, 0x03, 0x2A4C)   # 10828
FFF = modbus_response(0x02, 0x03, 0xFF9C)   # invalid UTF-8


async def replay(protocol: str, payload_plan, label: str):
    """Drive a real pty with a scripted device, return what the reader gave."""
    master, slave = pty.openpty()
    path = os.ttyname(slave)
    got = []

    async def on_data(d, s, line):
        got.append(line)

    dev = DeviceInfo(DeviceCreate(name="esp32", port=path, baudrate=115200,
                                  protocol=protocol))
    dev.serial_conn = serial.Serial(path, 115200, timeout=1.0)
    dev.status = "connected"
    r = SerialReader()
    await r.start_device(dev, "hw", on_data)
    await asyncio.sleep(0.25)

    for item in payload_plan:
        os.write(master, item)
        await asyncio.sleep(0.08)      # >> T3.5, so gap framing closes each frame

    await asyncio.sleep(1.5)
    await r.stop_all()
    os.close(master)
    # Classify by content, not by decode_error: 010302000a3843 is perfectly
    # valid UTF-8, so the 0x0A frame arrives as "text" even though it is a
    # binary Modbus frame. Filtering on decode_error hid exactly the frame
    # this test exists to check.
    def is_frame(b):
        s = b.rstrip(b"\r\n")
        return len(s) >= 7 and crc16(s[:-2]) == (s[-2] | (s[-1] << 8))

    frames = [g.raw_bytes for g in got if is_frame(g.raw_bytes)]
    print(f"    [{label}] {len(got)} deliveries, {len(frames)} CRC-valid "
          f"Modbus frames: {[f.hex() for f in frames]}")
    return got, frames


async def main():
    print("=" * 76)
    print("Can the acceptance checks DISCRIMINATE? broken reader vs fixed reader")
    print("=" * 76)

    print("\n--- the firmware's cycle as the FIXED reader sees it "
          "(protocol=modbus_rtu, gap framed) ---")
    good_plan = [
        b"CYCLE 1\n",
        b"TEMP:20.0C HUM:40%\n",
        b"TEMP:23.4C HUM:45%\n",
        F0A, F2A, FFF,
        b"cycle 1 complete\n",
    ]
    _, good_frames = await replay("modbus_rtu", good_plan, "fixed reader")

    check("fixed reader delivers each binary frame WHOLE",
          all(f in (F0A, F2A, FFF) for f in good_frames),
          f"got {[f.hex() for f in good_frames]}; expected exactly "
          f"{[F0A.hex(), F2A.hex(), FFF.hex()]}")

    check("the 0x0A frame arrives intact with a valid CRC",
          F0A in good_frames and crc16(F0A[:-2]) == (F0A[-2] | (F0A[-1] << 8)),
          f"0x0A frame present={F0A in good_frames}")

    check("the 0xFF 0x9C frame arrives as bytes (not U+FFFD)",
          FFF in good_frames,
          f"present={FFF in good_frames} -- this is what errors='replace' destroyed")

    # Now simulate the PRE-FIX behaviour: what a newline-framed reader returns.
    print("\n--- the same bytes through a LINE-framed reader "
          "(protocol=serial: the pre-fix behaviour) ---")
    _, split_frames = await replay("serial", good_plan, "line-framed reader")

    split0a = [f for f in split_frames if b"\x0a" in f]
    intact0a = F0A in split_frames
    check("line framing WOULD have split the 0x0A frame (checks can fail)",
          not intact0a,
          f"0x0A frame intact under line framing? {intact0a}. "
          f"delivered: {[f.hex() for f in split_frames[:6]]}. "
          f"This is the regression the checks must be able to catch.")

    print("\n" + "=" * 76)
    bad = [n for n, ok in R if not ok]
    print(f"{len(R)-len(bad)}/{len(R)} discrimination checks passed")
    for n in bad:
        print(f"  FAIL {n}")
    print("\nIf 'fixed reader' checks pass AND the line-framed contrast FAILS the")
    print("integrity check, the acceptance script can tell good from broken.")
    print("=" * 76)


asyncio.run(main())
