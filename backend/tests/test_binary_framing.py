"""Binary framing: a frame is delimited by silence, not by a newline.

`readline()` terminates on 0x0A / 0x0D. A Modbus RTU payload can legally
contain either -- a register value of 10 is 0x000A, and status bytes are
arbitrary. Measured before this test existed:

    wrote 010302000aaa550d0a  ->  ['010302000a', 'aa550d0a']

Two chunks, so the decoder received a truncated frame plus trailing CRC
garbage. Byte preservation (SerialData) could not help: the bytes were
correct, they were cut in the wrong place. No test wrote a 0x0A payload byte,
which is why 201 passing tests missed it.

A real RS-485 master frames a response by a 3.5-character silent inter-frame
gap and sends NO terminator at all, so a correct reader accumulates bytes and
emits a frame when the line goes quiet.

Run:  .venv/bin/python -m pytest tests/test_binary_framing.py -v
"""
import asyncio
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))

import serial                                                    # noqa: E402
from app.config import settings                                  # noqa: E402
from app.core.device_manager import DeviceInfo                   # noqa: E402
from app.core.protocol_decoder import ProtocolManager            # noqa: E402
from app.core.serial_reader import SerialReader                   # noqa: E402
from app.models import DeviceCreate                               # noqa: E402


async def _read_chunks(tmp_path, payload, baud=9600, gap=0.0, settle=1.2,
                       protocol='modbus_rtu'):
    """Write `payload` into a real pty and collect what the reader delivers.

    Defaults to `modbus_rtu` so binary framing is exercised; the text tests
    pass protocol='serial', which is line-framed.
    """
    import os
    import pty

    master, slave = pty.openpty()
    path = os.ttyname(slave)

    got = []

    async def on_data(device_id, session_id, line):
        got.append(line)

    dev = DeviceInfo(DeviceCreate(name="m", port=path, baudrate=baud,
                                  protocol=protocol))
    dev.serial_conn = serial.Serial(path, baud, timeout=settings.serial_timeout)
    dev.status = "connected"

    reader = SerialReader()
    await reader.start_device(dev, "s", on_data)
    await asyncio.sleep(0.25)          # let the reader park on the fd
    os.write(master, payload)
    if gap:
        await asyncio.sleep(gap)
    await asyncio.sleep(settle)
    await reader.stop_all()
    os.close(master)
    return got


class TestBinaryFraming:
    @pytest.mark.asyncio
    async def test_frame_containing_0x0a_is_not_split(self, tmp_path):
        """A 0x0A payload byte must not end the frame.

        This is the regression that 201 green tests missed.
        """
        # slave 1, fn 3, 2 data bytes, register value 0x000A, CRC, CRLF
        frame = bytes([0x01, 0x03, 0x02, 0x00, 0x0A, 0xAA, 0x55])
        got = await _read_chunks(tmp_path, frame + b"\r\n")

        assert len(got) == 1, (
            f"the frame was split into {len(got)} chunks: "
            f"{[g.raw_bytes.hex() for g in got]}. A decoder given the first "
            f"fragment sees a truncated frame."
        )
        assert got[0].raw_bytes.rstrip(b"\r\n") == frame

    @pytest.mark.asyncio
    async def test_gap_delimited_frame_with_no_terminator(self, tmp_path):
        """A real Modbus master sends no newline at all -- just silence."""
        frame = bytes([0x01, 0x03, 0x02, 0x00, 0x2A, 0x11, 0x61])
        got = await _read_chunks(tmp_path, frame, gap=0.4)

        assert len(got) == 1, (
            f"expected one frame from a gap-delimited write, got {len(got)}: "
            f"{[g.raw_bytes.hex() for g in got]}"
        )
        assert got[0].raw_bytes.rstrip(b"\r\n") == frame

    @pytest.mark.asyncio
    async def test_decoder_reads_the_right_value(self, tmp_path):
        """End to end: preserved + correctly framed bytes decode correctly."""
        frame = bytes([0x01, 0x03, 0x02, 0x00, 0x0A, 0xAA, 0x55])
        got = await _read_chunks(tmp_path, frame + b"\r\n")

        res = ProtocolManager().decode("modbus_rtu", got[0].raw_bytes.rstrip(b"\r\n"))
        # data is the byte-count field followed by the register bytes
        assert res.get("data", "").lower() == "02000a", (
            f"decode -> {res}. Expected data='02000a' (byte count 2, value 0x000A)."
        )

    @pytest.mark.asyncio
    async def test_two_frames_in_one_burst_are_separate(self, tmp_path):
        """Back-to-back frames with a gap must arrive as two frames."""
        # Distinct payloads, so a merged buffer is detectable rather than
        # looking like two identical frames.
        f1 = bytes([0x01, 0x03, 0x02, 0x00, 0x2A, 0x11, 0x61])
        f2 = bytes([0x02, 0x03, 0x02, 0x00, 0x63, 0xC4, 0x8B])

        import os
        import pty
        master, slave = pty.openpty()
        path = os.ttyname(slave)
        got = []

        async def on_data(device_id, session_id, line):
            got.append(line)

        dev = DeviceInfo(DeviceCreate(name="m", port=path, baudrate=9600,
                                      protocol="modbus_rtu"))
        dev.serial_conn = serial.Serial(path, 9600, timeout=settings.serial_timeout)
        dev.status = "connected"
        reader = SerialReader()
        await reader.start_device(dev, "s", on_data)
        await asyncio.sleep(0.25)
        os.write(master, f1)
        await asyncio.sleep(0.05)          # inter-frame gap, far > T3.5
        os.write(master, f2)
        await asyncio.sleep(1.5)
        await reader.stop_all()
        os.close(master)

        frames = [g.raw_bytes.rstrip(b"\r\n") for g in got]
        assert frames == [f1, f2], f"expected two distinct frames, got {frames}"


class TestTextPathIsNotRegressed:
    """The framing change must not alter how text devices behave."""

    @pytest.mark.asyncio
    async def test_text_line_arrives_whole(self, tmp_path):
        got = await _read_chunks(tmp_path, b"TEMP:23.4C HUM:45%\n", protocol='serial')
        assert len(got) == 1, f"expected one line, got {[g.raw_bytes for g in got]}"
        assert got[0] == "TEMP:23.4C HUM:45%"
        assert got[0].decode_error is False
        assert got[0].raw_bytes == b"TEMP:23.4C HUM:45%\n"

    @pytest.mark.asyncio
    async def test_text_metrics_still_parse(self, tmp_path):
        """The metric extraction the whole app depends on still works.

        Units come from the trailing-unit capture in METRIC_PATTERN, so both
        keys carry the unit as written on the line. `_infer_unit` is only the
        fallback for bare values like "HUM:45" with no unit character, and it
        does not know the abbreviation "HUM" -- a separate, pre-existing gap
        that this test deliberately does not assert either way.
        """
        from app.core.telemetry_engine import telemetry_engine
        got = await _read_chunks(tmp_path, b"TEMP:23.4C HUM:45%\n", protocol='serial')
        parsed = telemetry_engine._parse(got[0])
        names = {m.name: (m.value, m.unit) for m in parsed.metrics}
        assert names.get("TEMP") == (23.4, "C"), f"got {names}"
        assert names.get("HUM") == (45.0, "%"), f"got {names}"

    @pytest.mark.asyncio
    async def test_two_text_lines_in_a_burst(self, tmp_path):
        got = await _read_chunks(tmp_path, b"TEMP:1\nHUM:2\nTEMP:3\n", protocol='serial')
        assert [str(g) for g in got] == ["TEMP:1", "HUM:2", "TEMP:3"], \
            f"got {[str(g) for g in got]}"

    @pytest.mark.asyncio
    async def test_mixed_text_and_binary_stream(self, tmp_path):
        """Both frame kinds in one stream, each delivered correctly."""
        import os
        import pty
        master, slave = pty.openpty()
        path = os.ttyname(slave)
        got = []

        async def on_data(device_id, session_id, line):
            got.append(line)

        dev = DeviceInfo(DeviceCreate(name="m", port=path, baudrate=9600,
                                      protocol="modbus_rtu"))
        dev.serial_conn = serial.Serial(path, 9600, timeout=settings.serial_timeout)
        dev.status = "connected"
        reader = SerialReader()
        await reader.start_device(dev, "s", on_data)
        await asyncio.sleep(0.25)

        frame = bytes([0x01, 0x03, 0x02, 0x00, 0x0A, 0xAA, 0x55])
        os.write(master, b"TEMP:19.5\n")
        await asyncio.sleep(0.2)
        os.write(master, frame)          # no terminator
        await asyncio.sleep(0.35)        # gap closes the binary frame
        os.write(master, b"HUM:60\n")
        await asyncio.sleep(1.2)
        await reader.stop_all()
        os.close(master)

        # Under gap framing a text line and the binary frame are one buffer if
        # they arrive inside the same gap window -- that is correct behaviour
        # for a binary device, and the reason framing is chosen per protocol
        # rather than globally. What must hold: no payload byte was destroyed,
        # and the frame is still recoverable from the delivered bytes.
        assert got, "nothing delivered at all"
        everything = b"".join(g.raw_bytes for g in got)
        assert frame in everything, (
            f"binary frame lost or mangled. delivered={everything.hex()}")
        text_seen = "".join(str(g) for g in got)
        assert "TEMP:19.5" in text_seen and "HUM:60" in text_seen, (
            f"text payload missing from delivery: {text_seen!r}")


class TestNoSilentRevert:
    def test_framing_mode_is_chosen_per_protocol(self):
        """Binary protocols must get gap framing; text keeps line framing.

        A behavioural test cannot see someone collapsing this to a single mode
        behind a still-passing text path, so pin the mechanism directly.
        """
        from app.core.serial_reader import BINARY_PROTOCOLS, _is_binary_protocol

        for pid in ("modbus_rtu", "can", "can_dbc", "i2c", "spi"):
            assert _is_binary_protocol(pid), f"{pid} must be gap-framed"
        # The default protocol id is text and MUST stay line-framed: gap framing
        # merges a burst of text lines into one delivery.
        assert not _is_binary_protocol("serial")
        assert not _is_binary_protocol(None)

    def test_gap_framing_mechanism_is_present(self):
        """The reader must actually use an inter-character gap for binary."""
        import inspect
        from app.core.serial_reader import SerialReader
        src = inspect.getsource(SerialReader)
        assert "_read_gap_framed" in src and "select.select" in src, (
            "gap framing has been removed from the reader, so binary frames "
            "containing 0x0A will be split again")
