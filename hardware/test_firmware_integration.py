# hardware/test_firmware_integration.py
"""Integration test for firmware flashing pipeline."""
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.core.board_detector import detect_board
from app.core.tool_manager import ToolManager
from app.core.firmware_compiler import compile_sketch, find_compiled_bin
from app.core.firmware_flasher import flash_firmware


def test_full_pipeline():
    """Test compile + flash pipeline with a real sketch."""
    boards = detect_board()
    if not boards:
        print("SKIP: No ESP32 board detected")
        return

    board = boards[0]
    port = board["port"]
    fqbn = board["fqbn"]

    sketch_dir = Path(__file__).parent / "esp32_acceptance"

    tm = ToolManager()
    tm.install_esp32_core()
    result = compile_sketch(sketch_dir, fqbn)
    assert result.returncode == 0, f"Compile failed: {result.stderr}"

    bin_file = find_compiled_bin(sketch_dir)
    assert bin_file is not None, "No .bin produced"

    flash_result = flash_firmware(bin_file, port)
    assert flash_result.returncode == 0, f"Flash failed: {flash_result.stderr}"

    print(f"OK: Flashed {bin_file.name} to {port}")


if __name__ == "__main__":
    test_full_pipeline()
