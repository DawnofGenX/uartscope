"""Serial Reader — async data acquisition from serial ports."""
import asyncio
import logging
from typing import Optional, Callable
from datetime import datetime

import serial

from app.config import settings
from app.core.device_manager import DeviceInfo

logger = logging.getLogger(__name__)


class SerialData(str):
    """A serial line that carries both text and raw bytes.

    Subclasses ``str`` so every existing ``on_data`` callback that expects
    a text line continues to work unchanged — ``strip()``, ``startswith()``,
    ``split()``, ``encode()``, ``len()`` all behave exactly as before.

    Binary protocol frames (Modbus/CAN/I2C/SPI) are not valid UTF-8.  The
    reader used to decode with ``errors="replace"`` and hand the mangled
    string to decoders, which then produced plausible-looking but wrong
    data (and even passed CRC checks).  ``SerialData`` fixes this by
    preserving the exact original bytes in ``raw_bytes`` and flagging
    whether the text is trustworthy via ``decode_error``.
    """

    def __new__(cls, text: str, raw_bytes: bytes, decode_error: bool = False):
        instance = super().__new__(cls, text)
        instance.raw_bytes = raw_bytes
        instance.decode_error = decode_error
        return instance


class SerialReader:
    """Reads data from a serial port asynchronously and feeds the telemetry engine."""

    def __init__(self):
        self._read_tasks: dict = {}  # device_id -> asyncio.Task
        self._running = False

    async def start_device(
        self,
        device: DeviceInfo,
        session_id: str,
        on_data: Callable[[str, str, str], None],  # device_id, session_id, line
    ):
        """Start reading from a device's serial port."""
        if device.id in self._read_tasks:
            existing = self._read_tasks[device.id]
            if not existing.done():
                logger.warning(f"Reader already running for {device.id}")
                return
            # A dead or cancelled reader leaves a stale entry that would brick
            # the device forever: every later start_device is a silent no-op.
            # Take over by starting fresh.
            logger.error(
                f"Replacing dead reader for {device.name} ({device.port})"
            )

        task = asyncio.create_task(self._read_loop(device, session_id, on_data))
        self._read_tasks[device.id] = task
        logger.info(f"Serial reader started for {device.name} ({device.port})")

    async def stop_device(self, device_id: str):
        """Stop reading from a device."""
        task = self._read_tasks.pop(device_id, None)
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            logger.info(f"Serial reader stopped for {device_id}")

    async def stop_all(self):
        """Stop all serial readers."""
        for device_id in list(self._read_tasks.keys()):
            await self.stop_device(device_id)

    async def _read_loop(
        self,
        device: DeviceInfo,
        session_id: str,
        on_data: Callable,
    ):
        """Main read loop for a serial device."""
        while True:
            try:
                if not device.serial_conn or not device.serial_conn.is_open:
                    logger.warning(f"Serial port not open for {device.name}, waiting...")
                    await asyncio.sleep(2)
                    continue

                # Read line with timeout
                try:
                    line = await asyncio.get_event_loop().run_in_executor(
                        None,
                        device.serial_conn.readline
                    )
                except serial.SerialException as e:
                    logger.error(f"Serial read error on {device.name}: {e}")
                    device.status = "error"
                    await asyncio.sleep(2)
                    continue

                if line:
                    # Try strict UTF-8 first. If the bytes are valid text,
                    # text and raw_bytes are the same. If they are binary
                    # protocol data (Modbus/CAN/I2C/SPI), we preserve the
                    # exact bytes in raw_bytes and flag decode_error so
                    # downstream consumers know the text is untrustworthy.
                    try:
                        decoded = line.decode("utf-8").strip()
                        serial_data = SerialData(decoded, line, decode_error=False)
                    except UnicodeDecodeError:
                        # Binary data: keep the bytes, text is a lossy repr
                        decoded = line.decode("utf-8", errors="replace").strip()
                        serial_data = SerialData(decoded, line, decode_error=True)

                    if serial_data:
                        device.last_seen = datetime.utcnow()
                        device.bytes_received += len(line)
                        device.packet_count += 1
                        # Call the data callback
                        if asyncio.iscoroutinefunction(on_data):
                            await on_data(device.id, session_id, serial_data)
                        else:
                            on_data(device.id, session_id, serial_data)
                else:
                    # No data, brief sleep to avoid busy-waiting
                    await asyncio.sleep(0.001)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Unexpected error in read loop for {device.name}: {e}")
                await asyncio.sleep(1)


# Singleton
serial_reader = SerialReader()
