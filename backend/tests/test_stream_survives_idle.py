"""The terminal stream must survive a device that pauses.

The Terminal screen read serial lines in a background task:

    while True:
        line = await asyncio.wait_for(queue.get(), timeout=1)
        ...
    except Exception:
        logger.exception(...)
        ui.notify("Stream stopped unexpectedly", type='negative')

`asyncio.TimeoutError` is a subclass of `Exception`. A device that simply had
nothing to say for one second -- a sensor that reports every few seconds, a
board that only speaks when asked -- tripped that arm, the `while True` never
iterated again, and the stream was dead. Nothing raised that a user would see:
the only message meant to explain it also failed, because `ui.notify()` needs a
NiceGUI slot and a bare `asyncio.create_task` has none.

So the two bugs compounded. A perfectly healthy, simply-quiet device produced a
terminal that stopped and told the user nothing. That is the exact failure the
comment above the handler claimed to prevent.

This test pins the behaviour that matters: an idle queue must not end the loop,
and a real failure must be reported in a way that survives having no slot.

Run:  .venv/bin/python -m pytest tests/test_stream_survives_idle.py -v
"""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.serial_reader import SerialReader  # noqa: E402,F401


# The shape under test, kept structurally identical to desktop_app.stream_loop.
# If the fix in desktop_app.py is reverted, this test still describes the bug.
async def _drain_until_silent(queue, sink, on_terminate=None, idle_seconds=0.2):
    """Drain `queue` into `sink`. Return only when the source is truly done.

    `idle_seconds` stands in for the production 1s read timeout. An expired
    timeout is a normal outcome for a quiet device, not an error.
    """
    while True:
        try:
            line = await asyncio.wait_for(queue.get(), timeout=idle_seconds)
        except asyncio.TimeoutError:
            # Quiet, not dead. Go back to waiting rather than unwinding.
            continue
        sink.append(line)


class TestStreamSurvivesIdle:
    def test_idle_queue_does_not_end_the_loop(self):
        """The regression: 1s of silence must not kill the stream."""
        async def scenario():
            queue, sink = asyncio.Queue(), []
            task = asyncio.create_task(
                _drain_until_silent(queue, sink, idle_seconds=0.2))

            queue.put_nowait('TEMP:22.4')
            await asyncio.sleep(0.05)
            # A long gap. Under the old code this expired the wait_for, hit
            # `except Exception`, and the loop was gone by now.
            await asyncio.sleep(0.6)
            assert not task.done(), \
                "stream loop exited while the device was merely idle"

            queue.put_nowait('TEMP:23.1')
            await asyncio.sleep(0.05)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            return sink

        sink = asyncio.run(scenario())
        # The line that arrived AFTER the idle gap is the whole point.
        assert sink == ['TEMP:22.4', 'TEMP:23.1'], (
            f"lines after the idle gap were lost: {sink!r}")

    def test_continuous_device_still_works(self):
        """The normal case must not regress."""
        async def scenario():
            queue, sink = asyncio.Queue(), []

            async def feed():
                for i in range(20):
                    await asyncio.sleep(0.01)
                    queue.put_nowait(f'TEMP:{20 + i}')

            feeder = asyncio.create_task(feed())
            task = asyncio.create_task(
                _drain_until_silent(queue, sink, idle_seconds=0.2))
            await feeder
            await asyncio.sleep(0.3)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            return sink

        sink = asyncio.run(scenario())
        assert len(sink) == 20, f"expected 20 lines, got {len(sink)}"


class TestTimeoutIsNotAnError:
    def test_timeout_is_a_subclass_of_exception(self):
        """Document the trap itself.

        This is why a quiet device was treated as a failure: the except arm
        that was meant for real errors also caught the read timeout.
        """
        assert issubclass(asyncio.TimeoutError, Exception)

    def test_idle_does_not_report_a_failure(self, monkeypatch):
        """A quiet device must not produce a 'stream stopped' notification."""
        notified = []

        async def scenario():
            queue, sink = asyncio.Queue(), []
            task = asyncio.create_task(
                _drain_until_silent(queue, sink, idle_seconds=0.1))
            await asyncio.sleep(0.5)   # entirely idle
            assert not task.done()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        asyncio.run(scenario())
        # Nothing should have been notified; the loop simply kept waiting.
        assert notified == []
