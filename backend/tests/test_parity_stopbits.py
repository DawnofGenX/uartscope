"""Tests for configurable parity and stopbits on serial devices.

Real RS-485 sensors (Modbus RTU) commonly use 8E1 (8 data bits, even
parity, 1 stop bit). The app hardcoded 8N1, so every frame failed CRC
against a device configured for 8E1.

Run:  .venv/bin/python -m pytest tests/test_parity_stopbits.py -v
"""
import asyncio
import os
import pty
import sys
from pathlib import Path

import pytest
import serial

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models import DeviceCreate, DeviceResponse  # noqa: E402
from app.core.device_manager import DeviceManager, DeviceInfo  # noqa: E402


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


class TestDeviceCreateValidation:
    """DeviceCreate must accept and validate parity/stopbits."""

    def test_accepts_8e1_configuration(self):
        """A Modbus RTU sensor at 9600 baud, 8E1 must be expressible."""
        create = DeviceCreate(
            name="modbus-sensor",
            port="/dev/ttyUSB0",
            protocol="modbus_rtu",
            baudrate=9600,
            parity="E",
            stopbits=1,
        )
        assert create.parity == "E"
        assert create.stopbits == 1.0

    def test_rejects_invalid_parity(self):
        """An invalid parity must raise a validation error."""
        with pytest.raises(Exception):
            DeviceCreate(
                name="bad-parity",
                port="/dev/ttyUSB0",
                parity="X",
            )

    def test_rejects_invalid_stopbits(self):
        """An invalid stopbits must raise a validation error."""
        with pytest.raises(Exception):
            DeviceCreate(
                name="bad-stopbits",
                port="/dev/ttyUSB0",
                stopbits=3,
            )

    def test_defaults_to_8n1(self):
        """Omitting parity/stopbits must yield 8N1 (today's behaviour)."""
        create = DeviceCreate(name="default", port="/dev/ttyUSB0")
        assert create.parity == "N"
        assert create.stopbits == 1.0

    def test_accepts_all_valid_parity_values(self):
        """All pyserial parity values must be accepted."""
        for p in ("N", "E", "O", "M", "S"):
            create = DeviceCreate(name=f"parity-{p}", port="/dev/ttyUSB0", parity=p)
            assert create.parity == p

    def test_accepts_all_valid_stopbits_values(self):
        """All pyserial stopbits values must be accepted."""
        for sb in (1, 1.5, 2):
            create = DeviceCreate(name=f"stopbits-{sb}", port="/dev/ttyUSB0", stopbits=sb)
            assert create.stopbits == float(sb)


class TestDeviceManagerConnect:
    """device_manager.connect() must apply parity/stopbits to the port."""

    def test_connect_applies_8e1_settings(self, pty_pair):
        """connect() must open the port with even parity and 1 stop bit."""
        master, slave, slave_name = pty_pair
        manager = DeviceManager()
        create = DeviceCreate(
            name="modbus-sensor",
            port=slave_name,
            protocol="modbus_rtu",
            baudrate=9600,
            parity="E",
            stopbits=1,
        )
        device = asyncio.run(manager.add_device(create))

        try:
            result = asyncio.run(manager.connect(device.id))
            assert result is True
            assert device.serial_conn is not None
            assert device.serial_conn.is_open
            assert device.serial_conn.parity == serial.PARITY_EVEN
            assert device.serial_conn.stopbits == serial.STOPBITS_ONE
        finally:
            asyncio.run(manager.disconnect(device.id))

    def test_connect_defaults_to_8n1(self, pty_pair):
        """Omitting parity/stopbits must yield 8N1 exactly as today."""
        master, slave, slave_name = pty_pair
        manager = DeviceManager()
        create = DeviceCreate(
            name="default-device",
            port=slave_name,
            baudrate=115200,
        )
        device = asyncio.run(manager.add_device(create))

        try:
            result = asyncio.run(manager.connect(device.id))
            assert result is True
            assert device.serial_conn is not None
            assert device.serial_conn.parity == serial.PARITY_NONE
            assert device.serial_conn.stopbits == serial.STOPBITS_ONE
        finally:
            asyncio.run(manager.disconnect(device.id))

    def test_connect_applies_8o1_settings(self, pty_pair):
        """connect() must open the port with odd parity and 1 stop bit."""
        master, slave, slave_name = pty_pair
        manager = DeviceManager()
        create = DeviceCreate(
            name="odd-parity-device",
            port=slave_name,
            baudrate=9600,
            parity="O",
            stopbits=1,
        )
        device = asyncio.run(manager.add_device(create))

        try:
            result = asyncio.run(manager.connect(device.id))
            assert result is True
            assert device.serial_conn.parity == serial.PARITY_ODD
            assert device.serial_conn.stopbits == serial.STOPBITS_ONE
        finally:
            asyncio.run(manager.disconnect(device.id))

    def test_connect_applies_2_stopbits(self, pty_pair):
        """connect() must open the port with 2 stop bits."""
        master, slave, slave_name = pty_pair
        manager = DeviceManager()
        create = DeviceCreate(
            name="two-stopbits",
            port=slave_name,
            baudrate=9600,
            parity="N",
            stopbits=2,
        )
        device = asyncio.run(manager.add_device(create))

        try:
            result = asyncio.run(manager.connect(device.id))
            assert result is True
            assert device.serial_conn.stopbits == serial.STOPBITS_TWO
        finally:
            asyncio.run(manager.disconnect(device.id))


class TestDeviceResponse:
    """DeviceResponse must propagate parity/stopbits."""

    def test_response_includes_parity_and_stopbits(self):
        """DeviceResponse must carry parity and stopbits."""
        create = DeviceCreate(
            name="test",
            port="/dev/ttyUSB0",
            parity="E",
            stopbits=1,
        )
        device = DeviceInfo(create)
        device.id = "test-id"
        device.status = "connected"
        device.created_at = device.created_at
        device.last_seen = None

        resp = device.to_response()
        assert resp.parity == "E"
        assert resp.stopbits == 1.0

    def test_response_defaults_to_8n1(self):
        """DeviceResponse must default to 8N1."""
        create = DeviceCreate(name="default", port="/dev/ttyUSB0")
        device = DeviceInfo(create)
        device.id = "test-id"
        device.status = "connected"
        device.created_at = device.created_at
        device.last_seen = None

        resp = device.to_response()
        assert resp.parity == "N"
        assert resp.stopbits == 1.0


class TestMetadataRoundTrip:
    """Parity/stopbits must survive a metadata_json round-trip.

    When a device is loaded from the DB, devices.py constructs
    DeviceCreate without parity/stopbits. The values are in
    metadata_json. This test simulates that path.
    """

    def test_parity_stopbits_survive_metadata_round_trip(self):
        """A device created with 8E1 must reconnect with 8E1 after a
        metadata round-trip (simulating DB load)."""
        # Step 1: Create a device with 8E1
        create = DeviceCreate(
            name="modbus-sensor",
            port="/dev/ttyUSB0",
            protocol="modbus_rtu",
            baudrate=9600,
            parity="E",
            stopbits=1,
        )
        # The model_validator injects parity/stopbits into metadata
        assert create.metadata["parity"] == "E"
        assert create.metadata["stopbits"] == 1.0

        # Step 2: Simulate DB load — construct DeviceCreate from DB fields
        # (devices.py does NOT pass parity/stopbits explicitly)
        db_loaded = DeviceCreate(
            name="modbus-sensor",
            port="/dev/ttyUSB0",
            protocol="modbus_rtu",
            baudrate=9600,
            metadata=create.metadata,  # metadata_json from DB
        )
        # The model_validator(mode="before") must extract them from metadata
        assert db_loaded.parity == "E"
        assert db_loaded.stopbits == 1.0

    def test_explicit_parity_overrides_metadata(self):
        """If parity is explicitly provided, it must take precedence
        over metadata."""
        create = DeviceCreate(
            name="test",
            port="/dev/ttyUSB0",
            parity="O",
            metadata={"parity": "E", "stopbits": 1.0},
        )
        assert create.parity == "O"
