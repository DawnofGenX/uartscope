"""End-to-end firmware flash/compile tests against stub executables on PATH.

Unlike test_firmware_flasher.py / test_firmware_compiler.py (which patch
subprocess.run and therefore never execute the argv), these tests put real
stub ``esptool`` and ``arduino-cli`` executables — files created in a tmp bin
dir and prepended to PATH — in front of the real code. The argv the app
builds is actually exec'd, so this suite catches a wrong/fragile argv that
mocks cannot.

No hardware, no network: the stubs only log their argv to a JSONL file and
exit with a chosen status. The serial port is a fake path in tmp_path; the
flasher passes it through to esptool and never opens it, so no real /dev
node is required.

Run:  cd backend && python -m pytest tests/test_firmware_flash_e2e.py -v
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.core.firmware_flasher import flash_firmware  # noqa: E402
from app.core.firmware_compiler import compile_sketch  # noqa: E402

# Stub executable: logs its full argv (argv[0] = the path the kernel exec'd)
# to $STUB_LOG, then behaves per $STUB_MODE:
#   ok   -> exit 0 with a stdout message
#   fail -> exit 2 with a stderr message
#   hang -> sleep $STUB_HANG_SECONDS (default 60)
STUB_SOURCE = """#!/usr/bin/env python3
import json, os, sys, time

log = os.environ["STUB_LOG"]
with open(log, "a") as f:
    f.write(json.dumps({"argv": sys.argv}) + "\\n")

mode = os.environ.get("STUB_MODE", "ok")
if mode == "fail":
    sys.stderr.write("stub: simulated failure (chip not in download mode)\\n")
    sys.exit(2)
if mode == "hang":
    time.sleep(float(os.environ.get("STUB_HANG_SECONDS", "60")))
sys.stdout.write("stub: wrote 100 bytes to 0x1000\\n")
sys.exit(0)
"""


@pytest.fixture
def stub_bin(tmp_path, monkeypatch):
    """Put stub esptool + arduino-cli on PATH; return (bin_dir, log_path)."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "stub_calls.jsonl"
    for name in ("esptool", "arduino-cli"):
        stub = bin_dir / name
        stub.write_text(STUB_SOURCE)
        stub.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("STUB_LOG", str(log))
    monkeypatch.setenv("STUB_MODE", "ok")
    # Keep ToolManager from mkdir'ing into the real home dir during tests.
    import app.core.tool_manager as tool_manager
    monkeypatch.setattr(tool_manager, "TOOL_DIR", tmp_path / "tools")
    return bin_dir, log


def _calls(log_path: Path) -> list[dict]:
    if not log_path.exists():
        return []
    return [json.loads(line) for line in log_path.read_text().splitlines() if line]


def _make_bin(tmp_path: Path) -> Path:
    bin_file = tmp_path / "firmware.bin"
    bin_file.write_bytes(b"\x00" * 100)
    return bin_file


class TestFlashE2E:
    def test_flash_executes_stub_on_path_and_builds_expected_argv(self, tmp_path, stub_bin):
        """The argv actually exec'd is exactly what esptool expects, in order."""
        bin_dir, log = stub_bin
        bin_file = _make_bin(tmp_path)
        port = str(tmp_path / "ttyUSB0")  # fake port; flasher passes it through

        result = flash_firmware(bin_file, port)

        assert result.returncode == 0
        calls = _calls(log)
        assert len(calls) == 1, f"expected exactly one esptool invocation, got {calls}"
        argv = calls[0]["argv"]
        # argv[0] must be the stub on PATH — proves the real code resolved and
        # exec'd a PATH entry (not a literal '-m' or a missing binary).
        assert argv[0] == str(bin_dir / "esptool")
        assert argv[1:] == [
            "--port", port,
            "--baud", "921600",
            "write_flash",
            "0x1000",
            str(bin_file),
        ]

    def test_flash_custom_baud_in_argv(self, tmp_path, stub_bin):
        """A non-default baud rate lands in the right argv position."""
        _, log = stub_bin
        bin_file = _make_bin(tmp_path)

        result = flash_firmware(bin_file, "/dev/ttyUSB0", baud=115200)

        assert result.returncode == 0
        argv = _calls(log)[0]["argv"]
        assert argv[1:] == [
            "--port", "/dev/ttyUSB0",
            "--baud", "115200",
            "write_flash",
            "0x1000",
            str(bin_file),
        ]

    def test_flash_zero_exit_reported_as_success(self, tmp_path, stub_bin):
        """A zero exit from esptool is reported as success with its stdout."""
        _, log = stub_bin
        bin_file = _make_bin(tmp_path)

        result = flash_firmware(bin_file, "/dev/ttyUSB0")

        assert result.returncode == 0
        assert "wrote 100 bytes to 0x1000" in result.stdout
        assert result.stderr == ""

    def test_flash_nonzero_exit_surfaced_with_stderr(self, tmp_path, stub_bin, monkeypatch):
        """A non-zero exit is a failure whose message carries esptool's stderr."""
        _, log = stub_bin
        bin_file = _make_bin(tmp_path)
        monkeypatch.setenv("STUB_MODE", "fail")

        result = flash_firmware(bin_file, "/dev/ttyUSB0")

        assert result.returncode == 2
        assert "simulated failure (chip not in download mode)" in result.stderr

    def test_flash_hang_reported_as_timeout(self, tmp_path, stub_bin, monkeypatch):
        """A hung esptool is reported as a timeout, not a hung test run."""
        _, log = stub_bin
        bin_file = _make_bin(tmp_path)
        monkeypatch.setenv("STUB_MODE", "hang")
        monkeypatch.setenv("STUB_HANG_SECONDS", "60")

        with pytest.raises(subprocess.TimeoutExpired) as exc_info:
            flash_firmware(bin_file, "/dev/ttyUSB0", timeout=1)

        assert exc_info.value.timeout == 1


class TestFlashApiE2E:
    """The API layer must surface stub failures/timeouts, not swallow them."""

    @pytest.fixture
    def client(self, tmp_path, stub_bin):
        import tempfile

        db_dir = tempfile.mkdtemp(prefix="uartscope-flash-e2e-")
        os.environ["UARTSCOPE_DATABASE_URL"] = f"sqlite+aiosqlite:///{db_dir}/test.db"

        from fastapi.testclient import TestClient
        from app.main import app

        with TestClient(app) as c:
            yield c

    def test_flash_api_surfaces_failure_stderr(self, client, tmp_path, stub_bin, monkeypatch):
        """POST /api/firmware/flash returns 500 with esptool's stderr in the detail."""
        _, log = stub_bin
        bin_file = _make_bin(tmp_path)
        monkeypatch.setenv("STUB_MODE", "fail")

        resp = client.post("/api/firmware/flash", json={
            "bin_path": str(bin_file),
            "port": "/dev/ttyUSB0",
            "baud": 921600,
        })

        assert resp.status_code == 500
        assert "simulated failure (chip not in download mode)" in resp.json()["detail"]

    def test_flash_api_surfaces_timeout(self, client, tmp_path, stub_bin, monkeypatch):
        """A hung esptool yields a 500 'timed out' response, not a hung request.

        DEFAULT_TIMEOUT is shortened to 1s (the stub sleeps 60s) so the suite
        stays fast; the real route -> flasher -> subprocess path is exercised.
        """
        _, log = stub_bin
        bin_file = _make_bin(tmp_path)
        monkeypatch.setenv("STUB_MODE", "hang")
        monkeypatch.setenv("STUB_HANG_SECONDS", "60")
        import app.core.firmware_flasher as flasher
        monkeypatch.setattr(flasher, "DEFAULT_TIMEOUT", 1)

        resp = client.post("/api/firmware/flash", json={
            "bin_path": str(bin_file),
            "port": "/dev/ttyUSB0",
            "baud": 921600,
        })

        assert resp.status_code == 500
        assert "timed out" in resp.json()["detail"].lower()


class TestCompileE2E:
    def test_compile_executes_stub_on_path_and_builds_expected_argv(self, tmp_path, stub_bin):
        """The argv actually exec'd is exactly what arduino-cli expects."""
        bin_dir, log = stub_bin
        sketch_dir = tmp_path / "sketch"
        sketch_dir.mkdir()
        (sketch_dir / "sketch.ino").write_text("void setup(){}\nvoid loop(){}\n")

        result = compile_sketch(sketch_dir, "esp32:esp32:esp32")

        assert result.returncode == 0
        calls = _calls(log)
        assert len(calls) == 1, f"expected exactly one arduino-cli invocation, got {calls}"
        argv = calls[0]["argv"]
        assert argv[0] == str(bin_dir / "arduino-cli")
        assert argv[1:] == ["compile", "--fqbn", "esp32:esp32:esp32", str(sketch_dir)]

    def test_compile_nonzero_exit_surfaced_with_stderr(self, tmp_path, stub_bin, monkeypatch):
        """A non-zero arduino-cli exit is a failure carrying its stderr."""
        _, log = stub_bin
        sketch_dir = tmp_path / "sketch"
        sketch_dir.mkdir()
        (sketch_dir / "sketch.ino").write_text("void setup(){}\nvoid loop(){}\n")
        monkeypatch.setenv("STUB_MODE", "fail")

        result = compile_sketch(sketch_dir, "esp32:esp32:esp32")

        assert result.returncode == 2
        assert "simulated failure (chip not in download mode)" in result.stderr
