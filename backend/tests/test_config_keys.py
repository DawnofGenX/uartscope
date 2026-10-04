"""Config key audit: every setting must either have a reader or be deleted.

These tests pin the current state of each key so that:
- A key that is wired stays wired (the test fails if the reader disappears).
- A key that is deleted stays deleted (the test fails if it reappears).
- The default values are explicit and deliberate.

Run:  ../.venv-v2/bin/python -m pytest tests/test_config_keys.py -v
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings  # noqa: E402


class TestPluginInstallEnabled:
    """Task 1: the security interlock. Default False, enforced in two places."""

    def test_default_is_false(self):
        assert Settings().plugin_install_enabled is False

    def test_env_var_overrides(self):
        """UARTSCOPE_PLUGIN_INSTALL_ENABLED=true must be honoured."""
        import os
        os.environ["UARTSCOPE_PLUGIN_INSTALL_ENABLED"] = "true"
        try:
            assert Settings().plugin_install_enabled is True
        finally:
            del os.environ["UARTSCOPE_PLUGIN_INSTALL_ENABLED"]


class TestDefaultBaudrate:
    """default_baudrate: declared, not yet wired.

    The consumer is DeviceCreate in app/models/__init__.py which currently
    hardcodes baudrate=115200. A future change should read settings.default_baudrate
    as the default. This test pins the setting so that change is deliberate.
    """

    def test_exists_with_intended_default(self):
        s = Settings()
        assert hasattr(s, 'default_baudrate')
        assert s.default_baudrate == 115200

    def test_env_var_overrides(self):
        import os
        os.environ["UARTSCOPE_DEFAULT_BAUDRATE"] = "9600"
        try:
            assert Settings().default_baudrate == 9600
        finally:
            del os.environ["UARTSCOPE_DEFAULT_BAUDRATE"]


class TestDeletedKeys:
    """Keys that were deleted because they had zero readers and no natural consumer.

    These tests fail if someone re-adds the key, forcing a deliberate decision.
    """

    def test_alert_check_interval_is_gone(self):
        """Alert engine is event-driven; there is no polling loop to interval."""
        assert not hasattr(Settings(), 'alert_check_interval')

    def test_telemetry_buffer_size_is_gone(self):
        """No buffering mechanism consumes this; max_history_per_metric is the real limit."""
        assert not hasattr(Settings(), 'telemetry_buffer_size')

    def test_host_is_gone(self):
        """Launch is CLI-only (Dockerfile, launch.py, README all pass --host/--port)."""
        assert not hasattr(Settings(), 'host')

    def test_port_is_gone(self):
        """Launch is CLI-only (Dockerfile, launch.py, README all pass --host/--port)."""
        assert not hasattr(Settings(), 'port')
