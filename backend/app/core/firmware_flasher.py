"""Flash binary firmware to ESP32 via esptool."""
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_TIMEOUT = 120.0  # seconds; a healthy flash finishes well under this


def _esptool_argv() -> list[str]:
    """Resolve how to invoke esptool.

    Prefer the ``esptool`` console script on PATH (what pip installs);
    fall back to running the esptool Python module with the current
    interpreter.
    """
    on_path = shutil.which("esptool")
    if on_path:
        return [on_path]
    return [sys.executable, "-m", "esptool"]


def flash_firmware(
    bin_file: Path,
    port: str,
    baud: int = 921600,
    timeout: float | None = None,
) -> subprocess.CompletedProcess:
    """Flash a .bin file to an ESP32 on the given serial port.

    Uses esptool's write_flash command with the standard ESP32 app offset (0x1000).

    Args:
        timeout: Seconds to wait for esptool to finish. Defaults to
            DEFAULT_TIMEOUT. Pass an explicit value to override.

    Raises:
        subprocess.TimeoutExpired: if esptool does not finish within ``timeout``
            seconds (e.g. the chip never entered download mode).
    """
    if timeout is None:
        timeout = DEFAULT_TIMEOUT
    return subprocess.run(
        [
            *_esptool_argv(),
            "--port", port,
            "--baud", str(baud),
            "write_flash",
            "0x1000",  # Standard ESP32 app offset
            str(bin_file),
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
