"""Manage arduino-cli and esptool installation."""
import os
import platform
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

TOOL_DIR = Path.home() / ".uartscope" / "tools"
ARDUINO_CLI_VERSION = "1.1.1"
ESPTOOL_VERSION = "4.7.0"


class ToolManager:
    """Locate or auto-install arduino-cli and esptool."""

    def __init__(self):
        self.tool_dir = TOOL_DIR
        self.tool_dir.mkdir(parents=True, exist_ok=True)

    def arduino_cli(self) -> str:
        """Return path to arduino-cli binary, installing if needed."""
        # Check if already on PATH
        on_path = shutil.which("arduino-cli")
        if on_path:
            return on_path

        # Check our cached install
        cached = self.tool_dir / "arduino-cli"
        if cached.exists():
            return str(cached)

        # Auto-install
        return self._install_arduino_cli()

    def esptool(self) -> str:
        """Return path to esptool module (pip-installed)."""
        try:
            import esptool  # noqa: F401
            return "esptool"
        except ImportError:
            subprocess.check_call([
                sys.executable, "-m", "pip", "install", f"esptool=={ESPTOOL_VERSION}"
            ])
            return "esptool"

    def _install_arduino_cli(self) -> str:
        """Download and install arduino-cli binary."""
        system = platform.system().lower()

        if system == "windows":
            url = f"https://downloads.arduino.cc/arduino-cli/arduino-cli_{ARDUINO_CLI_VERSION}_Windows_64bit.zip"
            binary_name = "arduino-cli.exe"
        elif system == "darwin":
            url = f"https://downloads.arduino.cc/arduino-cli/arduino-cli_{ARDUINO_CLI_VERSION}_macOS_64bit.zip"
            binary_name = "arduino-cli"
        else:  # linux
            url = f"https://downloads.arduino.cc/arduino-cli/arduino-cli_{ARDUINO_CLI_VERSION}_Linux_64bit.zip"
            binary_name = "arduino-cli"

        zip_path = self.tool_dir / "arduino-cli.zip"
        extract_dir = self.tool_dir / "arduino-cli"

        # Download
        urllib.request.urlretrieve(url, zip_path)

        # Extract
        extract_dir.mkdir(exist_ok=True)
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(extract_dir)

        # Find binary and move to tool_dir
        binary = extract_dir / binary_name
        if not binary.exists():
            # Search recursively
            for f in extract_dir.rglob(binary_name):
                binary = f
                break

        dest = self.tool_dir / binary_name
        shutil.copy2(binary, dest)
        dest.chmod(0o755)

        # Cleanup
        zip_path.unlink()
        shutil.rmtree(extract_dir)

        return str(dest)

    def install_esp32_core(self) -> None:
        """Install the ESP32 board core via arduino-cli."""
        arduino = self.arduino_cli()
        subprocess.check_call([
            arduino, "core", "install", "esp32:esp32"
        ])


def ensure_tools() -> ToolManager:
    """Ensure all tools are installed and return the manager."""
    tm = ToolManager()
    tm.arduino_cli()
    tm.esptool()
    return tm
