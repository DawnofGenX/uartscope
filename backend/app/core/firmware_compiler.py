"""Compile Arduino sketches to firmware binaries via arduino-cli."""
import subprocess
from pathlib import Path

from app.core.tool_manager import ToolManager


def compile_sketch(sketch_dir: Path, fqbn: str) -> subprocess.CompletedProcess:
    """Compile an Arduino sketch directory using arduino-cli.

    Args:
        sketch_dir: Path to the directory containing the .ino sketch.
        fqbn: Fully Qualified Board Name (e.g. 'esp32:esp32:esp32').

    Returns:
        The CompletedProcess from subprocess.run.
    """
    arduino_cli = ToolManager().arduino_cli()
    return subprocess.run(
        [arduino_cli, 'compile', '--fqbn', fqbn, str(sketch_dir)],
        capture_output=True,
        text=True,
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
