"""Regression tests for the Terminal-screen serial callback contract.

Two bugs are pinned here:

1. ARITY — SerialReader._read_loop calls the data callback with THREE
   positional args (device_id, session_id, line). The Terminal screen's
   ``stream_loop`` in desktop_app.py defined ``on_data(line="")`` — ONE arg.
   On the first real line the reader raised ``TypeError`` which was swallowed
   by the broad ``except Exception`` in the read loop, so the Terminal received
   ZERO bytes from real hardware. This survived a green 161-test suite and
   green CI because CI has no serial hardware.

2. DEAD READER — SerialReader._read_tasks is keyed device_id -> Task and is
   only ever popped inside stop_device. If the reader task dies (unplug,
   exception, cancellation) the stale entry stays, and every later
   start_device for that device is a silent no-op that only logs a warning.
   The device is permanently bricked.

Run:  .venv/bin/python -m pytest tests/test_terminal_callback_contract.py -v
"""
import ast
import asyncio
import inspect
import os
import pty
import sys
from pathlib import Path

import pytest
import serial

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.serial_reader import SerialReader  # noqa: E402
from app.models import DeviceCreate  # noqa: E402
from app.core.device_manager import DeviceInfo  # noqa: E402


DESKTOP_APP = Path(__file__).resolve().parents[2] / "desktop_app.py"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_terminal_callback(extra_ns=None):
    """Pull the real ``on_data`` callback out of desktop_app.py's stream_loop.

    This is the production callback — not a copy. If the fix in desktop_app.py
    is reverted, this returns the broken 1-arg version and the behavioural
    test fails.

    ``extra_ns`` is merged into the exec namespace so the callback's closure
    variables (like ``queue``) can be provided by the caller.
    """
    source = DESKTOP_APP.read_text()
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "stream_loop":
            for child in ast.walk(node):
                if isinstance(child, ast.AsyncFunctionDef) and child.name == "on_data":
                    module = ast.Module(body=[child], type_ignores=[])
                    ns = dict(extra_ns or {})
                    exec(compile(module, str(DESKTOP_APP), "exec"), ns)
                    return ns["on_data"]
    raise AssertionError("Could not find on_data inside stream_loop in desktop_app.py")


def _make_device(port_name):
    """Build a DeviceInfo wired to a real pty slave."""
    create = DeviceCreate(name="pty-test", port=port_name)
    device = DeviceInfo(create)
    device.id = "pty-test-id"
    device.serial_conn = serial.Serial(port_name, baudrate=115200, timeout=1)
    return device


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


# ---------------------------------------------------------------------------
# Task 1 — callback arity contract
# ---------------------------------------------------------------------------

class TestCallbackArityContract:
    """The Terminal callback must accept the reader's 3-arg contract."""

    def test_desktop_app_on_data_takes_three_positional_params(self):
        """Source-level guard: no on_data in desktop_app.py may take < 3 args.

        This is the cheap, fast check that catches a future revert of the
        one-line fix. It parses the AST — no import of the NiceGUI app needed.
        """
        source = DESKTOP_APP.read_text()
        tree = ast.parse(source)

        on_data_defs = [
            node for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "on_data"
        ]
        assert on_data_defs, "desktop_app.py must define an on_data callback"

        for func_def in on_data_defs:
            # Count positional params (excluding *args, **kwargs, keyword-only)
            n_positional = len(func_def.args.posonlyargs) + len(func_def.args.args)
            assert n_positional >= 3, (
                f"desktop_app.py on_data at line {func_def.lineno} takes "
                f"{n_positional} positional params; the reader calls with 3 "
                f"(device_id, session_id, line)"
            )

    def test_terminal_callback_delivers_lines_over_pty(self, pty_pair):
        """Behavioural: the REAL Terminal callback must receive lines.

        Uses the actual on_data extracted from desktop_app.py. Before the fix
        this callback takes 1 arg; the reader calls it with 3; TypeError is
        swallowed; zero lines arrive. After the fix it takes 3 args and lines
        flow.
        """
        master, slave, slave_name = pty_pair
        device = _make_device(slave_name)
        reader = SerialReader()
        received = []
        queue = asyncio.Queue()
        on_data = _extract_terminal_callback(extra_ns={"queue": queue})

        async def scenario():
            await reader.start_device(device, "sess-1", on_data)
            # Give the reader a moment to start its loop
            await asyncio.sleep(0.1)
            # Write a real line to the pty master — the kernel delivers it
            # to the slave exactly as a USB adapter would.
            os.write(master, b"TEMP:23.4\n")
            # Wait for the line to be read, decoded, and delivered
            for _ in range(50):
                if not queue.empty():
                    break
                await asyncio.sleep(0.05)
            # Drain whatever the callback put into the queue
            while not queue.empty():
                received.append(await queue.get())
            await reader.stop_device(device.id)

        asyncio.run(scenario())
        device.serial_conn.close()

        assert len(received) >= 1, (
            f"Terminal callback received {len(received)} lines from real "
            f"hardware — the arity bug is present"
        )
        assert received[0] == "TEMP:23.4", (
            f"unexpected line content: {received[0]!r}"
        )

    def test_three_arg_callback_receives_device_and_session(self, pty_pair):
        """A correct 3-arg callback gets device_id and session_id delivered."""
        master, slave, slave_name = pty_pair
        device = _make_device(slave_name)
        reader = SerialReader()

        captured = {}

        async def on_data_3arg(dev_id, sess_id, line):
            captured["dev_id"] = dev_id
            captured["sess_id"] = sess_id
            captured["line"] = line

        async def scenario():
            await reader.start_device(device, "sess-42", on_data_3arg)
            await asyncio.sleep(0.1)
            os.write(master, b"HUM:55\n")
            for _ in range(50):
                if "line" in captured:
                    break
                await asyncio.sleep(0.05)
            await reader.stop_device(device.id)

        asyncio.run(scenario())
        device.serial_conn.close()

        assert captured.get("dev_id") == "pty-test-id", (
            f"device_id not delivered: {captured.get('dev_id')!r}"
        )
        assert captured.get("sess_id") == "sess-42", (
            f"session_id not delivered: {captured.get('sess_id')!r}"
        )
        assert captured.get("line") == "HUM:55", (
            f"line not delivered: {captured.get('line')!r}"
        )


# ---------------------------------------------------------------------------
# Task 2 — dead reader lockout
# ---------------------------------------------------------------------------

class TestDeadReaderTakeover:
    """A crashed reader must not permanently brick the device."""

    async def test_dead_task_is_replaced_on_restart(self, pty_pair):
        """A completed/cancelled task in _read_tasks must be discarded and
        a fresh reader started. Before the fix, start_device returns early
        and the stale entry stays forever.
        """
        master, slave, slave_name = pty_pair
        device = _make_device(slave_name)
        reader = SerialReader()

        # Simulate a dead reader: a task that already finished
        async def _dead():
            return

        dead_task = asyncio.create_task(_dead())
        await asyncio.sleep(0)  # let it complete
        assert dead_task.done()
        reader._read_tasks[device.id] = dead_task

        await reader.start_device(device, "sess-1", lambda *a: None)
        new_task = reader._read_tasks.get(device.id)
        assert new_task is not dead_task, (
            "start_device did not replace the dead reader task — "
            "the device is permanently bricked"
        )
        assert not new_task.done(), "new task should be running"
        await reader.stop_device(device.id)
        device.serial_conn.close()

    def test_live_task_is_not_duplicated(self, pty_pair):
        """A genuinely running reader must still be protected from double-start.
        The existing guard's purpose is preserved.
        """
        master, slave, slave_name = pty_pair
        device = _make_device(slave_name)
        reader = SerialReader()

        async def scenario():
            await reader.start_device(device, "sess-1", lambda *a: None)
            first_task = reader._read_tasks.get(device.id)
            assert first_task is not None
            assert not first_task.done()

            # Second start_device must be a no-op
            await reader.start_device(device, "sess-2", lambda *a: None)
            second_task = reader._read_tasks.get(device.id)
            assert second_task is first_task, (
                "start_device duplicated a live reader task"
            )
            await reader.stop_device(device.id)

        asyncio.run(scenario())
        device.serial_conn.close()

    def test_crashed_reader_task_is_recovered(self, pty_pair):
        """Cover the crash path: a task that raised an exception is detected
        and replaced on the next start_device.
        """
        master, slave, slave_name = pty_pair
        device = _make_device(slave_name)
        reader = SerialReader()

        async def _crash():
            raise RuntimeError("simulated reader crash")

        async def scenario():
            # Plant a crashed task
            crashed = asyncio.create_task(_crash())
            await asyncio.sleep(0)  # let it raise
            assert crashed.done()
            assert crashed.exception() is not None
            reader._read_tasks[device.id] = crashed

            # start_device must take over
            await reader.start_device(device, "sess-1", lambda *a: None)
            new_task = reader._read_tasks.get(device.id)
            assert new_task is not crashed, (
                "start_device did not replace the crashed reader task"
            )
            assert not new_task.done()
            await reader.stop_device(device.id)

        asyncio.run(scenario())
        device.serial_conn.close()

    async def test_dead_task_logs_error_with_device_name(self, pty_pair, caplog):
        """Replacing a dead reader must log at ERROR with device name and port,
        so a user attaching a board sees why their reader was replaced.
        """
        import logging

        master, slave, slave_name = pty_pair
        device = _make_device(slave_name)
        reader = SerialReader()

        async def _dead():
            return

        dead_task = asyncio.create_task(_dead())
        await asyncio.sleep(0)
        reader._read_tasks[device.id] = dead_task

        with caplog.at_level(logging.ERROR, logger="app.core.serial_reader"):
            await reader.start_device(device, "sess-1", lambda *a: None)
            await reader.stop_device(device.id)

        device.serial_conn.close()

        error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert error_records, (
            "replacing a dead reader must log at ERROR level"
        )
        combined = " ".join(r.getMessage() for r in error_records)
        assert device.name in combined or device.port in combined, (
            f"ERROR log must mention device name or port; got: {combined!r}"
        )
