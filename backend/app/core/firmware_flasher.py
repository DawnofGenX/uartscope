"""Flash binary firmware to ESP32 via esptool."""
import subprocess
from pathlib import Path


def flash_firmware(bin_file: Path, port: str, baud: int = 921600) -> subprocess.CompletedProcess:
    """Flash a .bin file to an ESP32 on the given serial port.

    Uses esptool's write_flash command with the standard ESP32 app offset (0x1000).
    """
    return subprocess.run(
        [
            "-m", "esptool",
            "--port", port,
            "--baud", str(baud),
            "write_flash",
            "0x1000",  # Standard ESP32 app offset
            str(bin_file),
        ],
        capture_output=True,
        text=True,
    )
