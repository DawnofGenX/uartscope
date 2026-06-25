"""Serial Reader — async data acquisition from serial ports."""
import asyncio
import logging
from typing import Optional, Callable
from datetime import datetime

import serial

from app.config import settings
from app.core.device_manager import DeviceInfo

logger = logging.getLogger(__name__)


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
            logger.warning(f"Reader already running for {device.id}")
            return

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
                    decoded = line.decode("utf-8", errors="replace").strip()
                    if decoded:
                        device.last_seen = datetime.utcnow()
                        device.bytes_received += len(line)
                        device.packet_count += 1
                        # Call the data callback
                        if asyncio.iscoroutinefunction(on_data):
                            await on_data(device.id, session_id, decoded)
                        else:
                            on_data(device.id, session_id, decoded)
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
