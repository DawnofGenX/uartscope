import os
import sys
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.core.firmware_compiler import compile_sketch, find_compiled_bin


class TestCompileSketch:
    def test_compile_sketch_calls_subprocess_with_correct_args(self):
        """compile_sketch invokes arduino-cli compile with --fqbn and sketch dir."""
        mock_completed = MagicMock()
        mock_completed.returncode = 0

        with patch('app.core.firmware_compiler.ToolManager') as MockTM, \
             patch('app.core.firmware_compiler.subprocess.run', return_value=mock_completed) as mock_run:
            MockTM.return_value.arduino_cli.return_value = '/fake/arduino-cli'

            sketch_dir = Path('/fake/sketch')
            fqbn = 'esp32:esp32:esp32'

            result = compile_sketch(sketch_dir, fqbn)

            mock_run.assert_called_once_with(
                ['/fake/arduino-cli', 'compile', '--fqbn', fqbn, str(sketch_dir)],
                capture_output=True,
                text=True,
            )
            assert result is mock_completed

    def test_compile_sketch_uses_tool_manager_for_cli_path(self):
        """compile_sketch obtains the arduino-cli path via ToolManager."""
        with patch('app.core.firmware_compiler.ToolManager') as MockTM, \
             patch('app.core.firmware_compiler.subprocess.run') as mock_run:
            MockTM.return_value.arduino_cli.return_value = '/cached/arduino-cli'
            mock_run.return_value = MagicMock(returncode=0)

            compile_sketch(Path('/sketch'), 'fqbn:string')

            MockTM.return_value.arduino_cli.assert_called_once()


class TestFindCompiledBin:
    def test_find_compiled_bin_returns_most_recent(self, tmp_path):
        """find_compiled_bin returns the most recently modified .bin file."""
        older = tmp_path / 'older.bin'
        newer = tmp_path / 'newer.bin'
        older.write_bytes(b'old')
        newer.write_bytes(b'new')

        # Ensure newer has a later mtime
        import time
        time.sleep(0.01)
        newer.write_bytes(b'new')

        result = find_compiled_bin(tmp_path)
        assert result == newer

    def test_find_compiled_bin_returns_none_when_no_bin(self, tmp_path):
        """find_compiled_bin returns None when no .bin files exist."""
        (tmp_path / 'sketch.ino').write_text('void setup(){}')
        result = find_compiled_bin(tmp_path)
        assert result is None

    def test_find_compiled_bin_ignores_non_bin_files(self, tmp_path):
        """find_compiled_bin only considers .bin files."""
        (tmp_path / 'firmware.hex').write_bytes(b'hex')
        (tmp_path / 'sketch.ino').write_text('void setup(){}')
        result = find_compiled_bin(tmp_path)
        assert result is None
