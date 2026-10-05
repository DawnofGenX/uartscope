"""Serial Reader — async data acquisition from serial ports."""
import asyncio
import logging
import select
from typing import Optional, Callable
from datetime import datetime

import serial

from app.config import settings
from app.core.device_manager import DeviceInfo

logger = logging.getLogger(__name__)


# Protocols whose frames are delimited by silence, not by a newline. Modbus
# RTU is the canonical case: a master pauses 3.5 character times between
# frames and sends no terminator, and a payload byte may be 0x0A or 0x0D.
# `serial` is the default protocol id and is text -- it must stay line-framed,
# because gap framing merges a burst of text lines into one delivery.
BINARY_PROTOCOLS = frozenset({'modbus_rtu', 'can', 'can_dbc', 'i2c', 'spi'})


def _is_binary_protocol(protocol: Optional[str]) -> bool:
    """Whether this device's protocol needs gap framing instead of line framing."""
    return (protocol or '').strip().lower() in BINARY_PROTOCOLS


def _read_available(conn) -> bytes:
    """Read whatever is already buffered, without ever blocking.

    `Serial.read(n)` waits for up to `n` bytes or for `timeout` to expire,
    whichever comes first. That is wrong immediately after select() reports the
    fd readable: at 9600 a 256-byte request blocks the full 1 s
    `serial_timeout` waiting for bytes that will never arrive, and any frame
    that lands inside that window is appended to the same buffer. Measured:
    two frames written 50 ms apart merged into one 14-byte "frame".

    `in_waiting` reports what the driver already holds, so asking for exactly
    that many bytes returns immediately. The read is still bounded by the
    port's own timeout, so a device that stops mid-frame cannot hang here --
    it returns short, the gap expires, and the partial frame is delivered
    rather than silently discarded.
    """
    waiting = getattr(conn, 'in_waiting', 0) or 0
    return conn.read(waiting) if waiting else b''


def inter_byte_timeout_for(baudrate: int, bytesize: int = 8, parity: str = 'N',
                           stopbits: float = 1.0) -> float:
    """Seconds of silence that ends a binary frame, from Modbus RTU's 3.5 chars.

    A Modbus master frames a response by pausing for 3.5 character times, then
    sends the next frame. Anything less than that is indistinguishable from the
    gap between two characters of one frame, so a reader has to know the real
    number or it will cut frames in half.

    T3.5 is specified from the character time, which includes start bit, data
    bits, parity (if any) and stop bits -- hence the full expression rather than
    a plain 11/baud. At 9600 8N1 that is about 4.0 ms; the floor keeps a
    pathological baudrate from collapsing the window to a busy-spin.
    """
    bits_per_char = 1 + bytesize + (1 if parity not in ('N', 'n', None) else 0) + stopbits
    char_time = bits_per_char / float(baudrate or 9600)
    return max(3.5 * char_time, 0.002)


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

    raw_bytes: bytes
    decode_error: bool

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
        """Main read loop for a serial device.

        Framing is per-device, because no single rule fits both kinds of
        traffic:

        * Line framing (`readline()`) for text protocols. This is what the app
          has always done and what every existing consumer expects -- one line
          in, one callback out. Measured while building the binary path: three
          lines written in one burst arrived as a SINGLE merged frame under gap
          framing, which would have broken every text device on earth.
        * Gap framing for binary protocols. `readline()` terminates on
          0x0A/0x0D and a Modbus payload may legally contain either -- a
          register value of 10 is 0x000A. Measured before this change, such a
          frame arrived as two chunks, so the decoder got a truncated frame
          plus trailing CRC. A real RS-485 master also sends no terminator at
          all, only a 3.5-character pause, so newline framing cannot deliver a
          Modbus response correctly even when the payload happens to contain no
          newline byte.

        The gap is derived from the device's own line settings, so a 9600 8E1
        sensor is framed at the correct width rather than at a hardcoded 1 s.
        """
        conn = None
        original_timeout = settings.serial_timeout

        while True:
            try:
                conn = device.serial_conn
                if not conn or not conn.is_open:
                    logger.warning(f"Serial port not open for {device.name}, waiting...")
                    await asyncio.sleep(2)
                    continue

                if _is_binary_protocol(device.protocol):
                    await self._read_gap_framed(device, session_id, on_data, conn)
                else:
                    await self._read_line_framed(device, session_id, on_data, conn)

            except asyncio.CancelledError:
                break
            except serial.SerialException as e:
                logger.error(f"Serial read error on {device.name}: {e}")
                device.status = "error"
                await asyncio.sleep(2)
            except Exception as e:
                logger.error(f"Unexpected error in read loop for {device.name}: {e}")
                await asyncio.sleep(1)
            finally:
                # Never leave a shrunken inter_byte_timeout on a port another
                # reader may pick up.
                if conn is not None:
                    try:
                        conn.inter_byte_timeout = original_timeout
                    except Exception:
                        pass

    async def _emit(self, device, session_id, on_data, frame: bytes):
        """Turn one framed chunk of bytes into a delivery to the callback."""
        try:
            decoded = frame.decode("utf-8").strip()
            serial_data = SerialData(decoded, frame, decode_error=False)
        except UnicodeDecodeError:
            # Binary data: keep the bytes, text is a lossy repr
            decoded = frame.decode("utf-8", errors="replace").strip()
            serial_data = SerialData(decoded, frame, decode_error=True)

        if not serial_data:
            return
        device.last_seen = datetime.utcnow()
        device.bytes_received += len(frame)
        device.packet_count += 1
        if asyncio.iscoroutinefunction(on_data):
            await on_data(device.id, session_id, serial_data)
        else:
            on_data(device.id, session_id, serial_data)

    async def _read_line_framed(self, device, session_id, on_data, conn):
        """One newline-delimited line per delivery. Unchanged legacy behaviour."""
        loop = asyncio.get_event_loop()
        line = await loop.run_in_executor(None, conn.readline)
        if line:
            await self._emit(device, session_id, on_data, line)
        else:
            # No data, brief sleep to avoid busy-waiting
            await asyncio.sleep(0.001)

    async def _read_gap_framed(self, device, session_id, on_data, conn):
        """One frame per silent inter-character gap, newline-agnostic."""
        gap = inter_byte_timeout_for(
            device.baudrate,
            getattr(conn, 'bytesize', 8) or 8,
            getattr(conn, 'parity', 'N') or 'N',
            getattr(conn, 'stopbits', 1) or 1,
        )
        loop = asyncio.get_event_loop()
        buffer = bytearray()

        while True:
            # Poll with select() rather than a blocking read. pyserial's
            # inter_byte_timeout does NOT shorten a read once bytes are
            # buffered -- measured: with inter_byte_timeout=4ms a read() still
            # blocked the full serial_timeout of 1.0s -- so the gap has to be
            # enforced here, against a clock. It also stops a silent device
            # from pinning an executor thread forever.
            ready, _, _ = await loop.run_in_executor(
                None, select.select, [conn], [], [], gap
            )
            if not ready:
                if not buffer:
                    continue
                frame = bytes(buffer)
                buffer.clear()
                await self._emit(device, session_id, on_data, frame)
                continue

            chunk = _read_available(conn)
            if chunk:
                buffer.extend(chunk)


# Singleton
serial_reader = SerialReader()
