"""Compile Arduino sketches to firmware binaries via arduino-cli."""
import subprocess
from pathlib import Path

from app.core.tool_manager import ToolManager

# A first compile also installs the ESP32 core, which takes minutes — so this default is
# generous on purpose. The point is not the number: it is that a hung arduino-cli must raise
# instead of holding the HTTP request open forever (the flash path had exactly that bug).
DEFAULT_COMPILE_TIMEOUT = 600.0


def compile_sketch(
    sketch_dir: Path, fqbn: str, timeout: float | None = None
) -> subprocess.CompletedProcess:
    """Compile an Arduino sketch directory using arduino-cli.

    Args:
        sketch_dir: Path to the directory containing the .ino sketch.
        fqbn: Fully Qualified Board Name (e.g. 'esp32:esp32:esp32').
        timeout: Seconds to wait for arduino-cli. Defaults to
            ``DEFAULT_COMPILE_TIMEOUT``. A first compile also installs the ESP32
            core, which is why the default is minutes rather than seconds.

    Returns:
        The CompletedProcess from subprocess.run.

    Raises:
        subprocess.TimeoutExpired: if arduino-cli does not finish in time. The
            API layer turns this into a 500 instead of leaving the request
            hanging — the same class of defect the flash path had.
    """
    arduino_cli = ToolManager().arduino_cli()
    if timeout is None:
        timeout = DEFAULT_COMPILE_TIMEOUT
    return subprocess.run(
        [arduino_cli, 'compile', '--fqbn', fqbn, str(sketch_dir)],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def find_compiled_bin(sketch_dir: Path) -> Path | None:
    """Find the most recently compiled .bin file in the sketch directory.

    Args:
        sketch_dir: Path to the sketch directory.

    Returns:
        Path to the most recently modified .bin file, or None if no .bin exists.
    """
    bins = list(Path(sketch_dir).glob('*.bin'))
    if not bins:
        return None
    return max(bins, key=lambda p: p.stat().st_mtime)
