"""Tests for byte-preserving serial reader.

The reader must not destroy binary protocol frames (Modbus/CAN/I2C/SPI)
by UTF-8 decoding them before downstream consumers see them.

Run:  .venv/bin/python -m pytest tests/test_byte_preservation.py -v
"""
import asyncio
import os
import pty
import sys
from pathlib import Path

import pytest
import serial

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.serial_reader import SerialReader  # noqa: E402
from app.core.protocol_decoder import ProtocolManager  # noqa: E402
from app.models import DeviceCreate  # noqa: E402
from app.core.device_manager import DeviceInfo  # noqa: E402


@pytest.fixture
def pty_pair():
    """Yield (master_fd, slave_fd, slave_name). Real character device."""
    master, slave = pty.openpty()
    slave_name = os.ttyname(slave)
    try:
        yield master, slave, slave_name
    finally:
        for fd in (master, slave):
            try:
                os.close(fd)
            except OSError:
                pass


def _make_device(port_name):
    """Build a DeviceInfo wired to a real pty slave."""
    create = DeviceCreate(name="pty-test", port=port_name)
    device = DeviceInfo(create)
    device.id = "pty-test-id"
    device.serial_conn = serial.Serial(port_name, baudrate=115200, timeout=1)
    return device


def _read_one_line(reader, device, master, data):
    """Write data to pty master, read one line through SerialReader."""
    received = []

    async def on_data(dev_id, sess_id, line):
        received.append(line)

    async def scenario():
        await reader.start_device(device, "sess-1", on_data)
        await asyncio.sleep(0.1)
        os.write(master, data)
        for _ in range(50):
            if received:
                break
            await asyncio.sleep(0.05)
        await reader.stop_device(device.id)

    asyncio.run(scenario())
    device.serial_conn.close()
    return received


class TestBytePreservation:
    """Binary protocol frames must survive the reader intact."""

    def test_modbus_frame_arrives_byte_exact(self, pty_pair):
        """A Modbus RTU frame with high bytes must arrive byte-exact.

        Before the fix: the reader UTF-8-decodes with errors="replace",
        destroying 0xFF 0x9C. The raw bytes are lost forever.
        After the fix: the reader delivers SerialData with .raw_bytes
        containing the exact original bytes.
        """
        master, slave, slave_name = pty_pair
        device = _make_device(slave_name)
        reader = SerialReader()
        received = _read_one_line(
            reader, device, master, b"\x01\x03\x02\xff\x9c\x00\x35\n"
        )

        assert len(received) >= 1
        line = received[0]
        assert hasattr(line, "raw_bytes"), (
            "reader must deliver raw bytes alongside text"
        )
        assert line.raw_bytes == b"\x01\x03\x02\xff\x9c\x00\x35\n"

    def test_modbus_frame_decodes_correctly(self, pty_pair):
        """The raw bytes must decode to the correct signed value.

        01 03 02 FF 9C 00 35 is a Modbus RTU read-holding-registers
        response encoding -100 degrees C. The data field is 0xFF9C
        which is -100 as a signed 16-bit integer.
        """
        master, slave, slave_name = pty_pair
        device = _make_device(slave_name)
        reader = SerialReader()
        received = _read_one_line(
            reader, device, master, b"\x01\x03\x02\xff\x9c\x00\x35\n"
        )

        assert len(received) >= 1
        line = received[0]
        raw = line.raw_bytes.rstrip(b"\n")
        result = ProtocolManager().decode("modbus_rtu", raw)
        assert result["data"] == "02ff9c"
        # The signed value of 0xFF9C is -100
        signed = int.from_bytes(
            bytes.fromhex("ff9c"), byteorder="big", signed=True
        )
        assert signed == -100

    def test_text_device_metrics_unchanged(self, pty_pair):
        """A text device must still produce the same metrics.

        A board printing TEMP:23.4C must still produce the same metric,
        the same session recording, the same websocket broadcast.
        """
        master, slave, slave_name = pty_pair
        device = _make_device(slave_name)
        reader = SerialReader()
        received = _read_one_line(
            reader, device, master, b"TEMP:23.4\n"
        )

        assert len(received) >= 1
        line = received[0]
        assert str(line) == "TEMP:23.4"
        assert line.raw_bytes == b"TEMP:23.4\n"

    def test_reader_never_hands_decoder_reencoded_string(self, pty_pair):
        """The reader must never hand a decoder a re-encoded string.

        If the reader delivers a mangled string (with U+FFFD replacement
        characters), re-encoding it gives different bytes than the original.
        This test proves the raw bytes are always available and are the
        exact original bytes.
        """
        master, slave, slave_name = pty_pair
        device = _make_device(slave_name)
        reader = SerialReader()
        received = _read_one_line(
            reader, device, master, b"\x01\x03\x02\xff\x9c\x00\x35\n"
        )

        assert len(received) >= 1
        line = received[0]
        # The raw bytes must be the exact original bytes
        assert line.raw_bytes == b"\x01\x03\x02\xff\x9c\x00\x35\n"
        # Re-encoding the text must NOT give the same bytes
        assert line.encode("utf-8") != line.raw_bytes

    def test_binary_frame_has_decode_error_flag(self, pty_pair):
        """A binary frame that can't be decoded as UTF-8 must be flagged.

        The honest outcome is the bytes plus a decode error, not a
        mangled string that silently verifies.
        """
        master, slave, slave_name = pty_pair
        device = _make_device(slave_name)
        reader = SerialReader()
        received = _read_one_line(
            reader, device, master, b"\x01\x03\x02\xff\x9c\x00\x35\n"
        )

        assert len(received) >= 1
        line = received[0]
        assert line.decode_error is True

    def test_text_frame_has_no_decode_error(self, pty_pair):
        """A text frame must not have a decode error."""
        master, slave, slave_name = pty_pair
        device = _make_device(slave_name)
        reader = SerialReader()
        received = _read_one_line(
            reader, device, master, b"TEMP:23.4\n"
        )

        assert len(received) >= 1
        line = received[0]
        assert line.decode_error is False
