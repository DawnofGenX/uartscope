"""Tests for firmware flashing via esptool.

Run:  cd backend && python -m pytest tests/test_firmware_flasher.py -v
"""
import os
import sys
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.core.firmware_flasher import flash_firmware  # noqa: E402


def _make_completed_process(returncode=0, stdout="", stderr=""):
    """Create a mock CompletedProcess."""
    proc = MagicMock(spec=subprocess.CompletedProcess)
    proc.returncode = returncode
    proc.stdout = stdout
    proc.stderr = stderr
    return proc


def test_flash_firmware_calls_esptool(tmp_path):
    """flash_firmware invokes esptool with correct arguments."""
    bin_file = tmp_path / "firmware.bin"
    bin_file.write_bytes(b"\x00" * 100)

    mock_proc = _make_completed_process(returncode=0, stdout="ok", stderr="")

    with patch("subprocess.run", return_value=mock_proc) as mock_run:
        result = flash_firmware(bin_file, "/dev/ttyUSB0")

    assert result.returncode == 0
    mock_run.assert_called_once()

    cmd = mock_run.call_args[0][0]
    assert "esptool" in cmd
    assert "write_flash" in cmd
    assert "/dev/ttyUSB0" in cmd
    assert str(bin_file) in cmd


def test_flash_firmware_default_baud(tmp_path):
    """Default baud rate is 921600."""
    bin_file = tmp_path / "firmware.bin"
    bin_file.write_bytes(b"\x00" * 100)

    mock_proc = _make_completed_process(returncode=0)

    with patch("subprocess.run", return_value=mock_proc) as mock_run:
        flash_firmware(bin_file, "/dev/ttyUSB0")

    cmd = mock_run.call_args[0][0]
    assert "921600" in cmd


def test_flash_firmware_custom_baud(tmp_path):
    """Custom baud rate is passed through."""
    bin_file = tmp_path / "firmware.bin"
    bin_file.write_bytes(b"\x00" * 100)

    mock_proc = _make_completed_process(returncode=0)

    with patch("subprocess.run", return_value=mock_proc) as mock_run:
        flash_firmware(bin_file, "/dev/ttyUSB0", baud=115200)

    cmd = mock_run.call_args[0][0]
    assert "115200" in cmd


def test_flash_firmware_uses_0x1000_offset(tmp_path):
    """Flash offset is 0x1000 (standard ESP32 app offset)."""
    bin_file = tmp_path / "firmware.bin"
    bin_file.write_bytes(b"\x00" * 100)

    mock_proc = _make_completed_process(returncode=0)

    with patch("subprocess.run", return_value=mock_proc) as mock_run:
        flash_firmware(bin_file, "/dev/ttyUSB0")

    cmd = mock_run.call_args[0][0]
    assert "0x1000" in cmd


def test_flash_firmware_returns_completed_process(tmp_path):
    """flash_firmware returns the CompletedProcess from subprocess.run."""
    bin_file = tmp_path / "firmware.bin"
    bin_file.write_bytes(b"\x00" * 100)

    mock_proc = _make_completed_process(returncode=0, stdout="flashing...", stderr="")

    with patch("subprocess.run", return_value=mock_proc):
        result = flash_firmware(bin_file, "/dev/ttyUSB0")

    assert result is mock_proc
    assert result.stdout == "flashing..."
