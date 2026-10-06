import os
import sys
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.core.tool_manager import ToolManager


class TestToolManager:
    def setup_method(self):
        self.tm = ToolManager()

    def test_tool_manager_finds_or_installs(self):
        """ToolManager finds arduino-cli on PATH."""
        with patch('shutil.which', return_value='/usr/bin/arduino-cli'):
            result = self.tm.arduino_cli()
            assert result == '/usr/bin/arduino-cli'

    def test_tool_manager_uses_cached_binary(self):
        """ToolManager uses cached binary when not on PATH."""
        with patch('shutil.which', return_value=None):
            cached = self.tm.tool_dir / 'arduino-cli'
            cached.touch()
            try:
                result = self.tm.arduino_cli()
                assert result == str(cached)
            finally:
                cached.unlink()

    def test_tool_manager_installs_when_missing(self):
        """ToolManager installs arduino-cli when not found."""
        with patch('shutil.which', return_value=None):
            with patch.object(self.tm, '_install_arduino_cli', return_value='/fake/arduino-cli') as mock_install:
                cached = self.tm.tool_dir / 'arduino-cli'
                if cached.exists():
                    cached.unlink()
                result = self.tm.arduino_cli()
                assert result == '/fake/arduino-cli'
                mock_install.assert_called_once()

    def test_esptool_is_pip_installed(self):
        """esptool is importable."""
        result = self.tm.esptool()
        assert result == 'esptool'

    def test_esptool_installs_when_missing(self):
        """esptool gets pip-installed when not importable."""
        import builtins
        real_import = builtins.__import__
        def mock_import(name, *args, **kwargs):
            if name == 'esptool':
                raise ImportError("No module named 'esptool'")
            return real_import(name, *args, **kwargs)

        with patch('builtins.__import__', side_effect=mock_import):
            with patch('subprocess.check_call') as mock_call:
                result = self.tm.esptool()
                assert result == 'esptool'
                mock_call.assert_called_once()
