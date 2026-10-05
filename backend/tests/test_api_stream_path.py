"""The API stream path must record session metrics AND evaluate alerts.

Found end-to-end: a rule created through `POST /api/alerts/rules` against a
serial device never fired. The only call to `alert_engine.evaluate` in
`app/main.py` was inside the MQTT message callback, so the serial path
broadcast metrics but never checked rules. The rule looked correctly
configured and reported `trigger_count: 0` forever -- the worst failure mode
for an alerting system, because it reads as "no threshold crossings" rather
than "nothing is evaluating this".

The behavioural half drives a real pty through the real reader. The wiring
half is source-level on purpose: a test that reimplements main.py's sequence
keeps passing while main.py itself stays broken, which is exactly how this bug
survived 218 green tests.
"""
import asyncio
import os
import pty
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))

import serial                                                    # noqa: E402
from app.core.alert_engine import AlertRule, alert_engine          # noqa: E402
from app.core.device_manager import DeviceInfo                   # noqa: E402
from app.core.serial_reader import SerialReader                   # noqa: E402
from app.core.telemetry_engine import Metric, telemetry_engine     # noqa: E402
from app.models import DeviceCreate                               # noqa: E402

MAIN_PY = REPO / "backend/app/main.py"


@pytest.fixture(autouse=True)
def clean_alerts():
    saved_rules = dict(alert_engine._rules)
    saved_history = list(alert_engine._alert_history)
    alert_engine._rules.clear()
    alert_engine._alert_history.clear()
    yield
    alert_engine._rules.clear()
    alert_engine._rules.update(saved_rules)
    alert_engine._alert_history[:] = saved_history


async def _push_and_evaluate(master, port_path, payloads):
    """Exactly what app/main.py's on_data does, against a live reader."""
    got = []

    async def on_data(device_id, session_id, line):
        got.append(line)

    dev = DeviceInfo(DeviceCreate(name="d", port=port_path, baudrate=115200))
    dev.serial_conn = serial.Serial(port_path, 115200, timeout=1.0)
    dev.status = "connected"
    reader = SerialReader()
    await reader.start_device(dev, "s", on_data)
    await asyncio.sleep(0.3)

    for payload in payloads:
        os.write(master, payload)
        await asyncio.sleep(0.2)

    await asyncio.sleep(1.5)
    await reader.stop_all()
    dev.serial_conn.close()

    for line in got:
        parsed = telemetry_engine._parse(line)
        for metric in getattr(parsed, "metrics", None) or []:
            await alert_engine.evaluate(
                "dev", "sess",
                Metric(name=metric.name, value=metric.value, unit=metric.unit))
    return got


class TestAlertEngineFiresOnLiveData:
    @pytest.mark.asyncio
    async def test_a_crossed_threshold_produces_an_alert(self):
        """Baseline: the engine works when something actually evaluates it."""
        master, slave = pty.openpty()
        path = os.ttyname(slave)
        try:
            alert_engine.add_rule(AlertRule(
                id="r1", name="hot", metric_name="TEMP",
                condition="gt", threshold=20.0, cooldown=0))
            got = await _push_and_evaluate(master, path, [b"TEMP:23.4C\n"])

            assert got, "nothing arrived from the pty"
            history = alert_engine.get_alert_history()
            assert history, (
                "TEMP 23.4 against a `gt 20` rule produced no alert")
            assert history[0]["metric_name"] == "TEMP"
            assert history[0]["value"] == 23.4
            assert history[0]["severity"] == "warning"
        finally:
            os.close(master)

    @pytest.mark.asyncio
    async def test_a_rule_below_the_threshold_stays_silent(self):
        """The control: the check is not simply always-true."""
        master, slave = pty.openpty()
        path = os.ttyname(slave)
        try:
            alert_engine.add_rule(AlertRule(
                id="r2", name="hot", metric_name="TEMP",
                condition="gt", threshold=99.0, cooldown=0))
            await _push_and_evaluate(master, path, [b"TEMP:23.4C\n"])
            assert not alert_engine.get_alert_history(), (
                "a rule at 99 fired on 23.4 -- the comparison is wrong")
        finally:
            os.close(master)

    def test_unrecognised_condition_is_rejected_by_the_api_schema(self):
        """The API constrains conditions to a closed vocabulary.

        The engine also logs an unrecognised condition rather than returning
        False silently, but the schema is the first line of defence.
        """
        from app.models import AlertRuleCreate
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            AlertRuleCreate(name="x", metric_name="TEMP",
                            condition="gtt", threshold=1.0)
        ok = AlertRuleCreate(name="x", metric_name="TEMP",
                             condition="gt", threshold=1.0)
        assert ok.condition == "gt"


class TestMainPyWiring:
    """Source-level guards. main.py's own on_data is what shipped broken."""

    def test_serial_path_evaluates_alerts(self):
        src = MAIN_PY.read_text(encoding="utf-8")
        sites = src.count("await alert_engine.evaluate(")
        assert sites >= 2, (
            f"app/main.py has {sites} alert_engine.evaluate() call site(s); "
            f"one belongs to the MQTT callback and one to the serial on_data. "
            f"With only one, an alert rule can never fire for a serial device.")

    def test_serial_path_records_session_metrics(self):
        src = MAIN_PY.read_text(encoding="utf-8")
        assert "session_recorder.record_metric(" in src, (
            "app/main.py never records session metrics, so the session detail "
            "Metrics tab stays empty for API-created sessions")

    def test_evaluate_is_inside_the_serial_on_data_not_only_mqtt(self):
        """Both call sites must sit inside callbacks, not at import time."""
        src = MAIN_PY.read_text(encoding="utf-8")
        assert "async def on_data(" in src, "the serial callback is gone"
        on_data = src.split("async def on_data(", 1)[1]
        # the callback body runs to the next top-level def
        body = on_data.split("\n@app.", 1)[0]
        assert "alert_engine.evaluate(" in body, (
            "the serial on_data callback does not evaluate alerts; the only "
            "call site left is the MQTT one, which a serial device never hits")

    def test_desktop_app_still_evaluates_alerts(self):
        """The desktop path was never broken; pin that it stays correct."""
        src = (REPO / "desktop_app.py").read_text(encoding="utf-8")
        assert "alert_engine.evaluate(" in src, (
            "desktop_app.py no longer evaluates alerts on its serial path")
