"""Unit inference for parsed metrics.

Charts group series onto a Y axis by unit, so a metric arriving without one is
a metric that cannot be plotted meaningfully. The KEY:VALUE parser used to
leave `unit` empty for the bare form ("TEMP:23.4") even though the JSON path
already inferred it, which is why the dashboard could not separate degrees from
decibels.

Run:  .venv/bin/python -m pytest backend/tests/test_metric_units.py -q
      (or directly: .venv/bin/python backend/tests/test_metric_units.py)
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.telemetry_engine import telemetry_engine  # noqa: E402


def _feed(device: str, *lines: str) -> None:
    async def go():
        for line in lines:
            await telemetry_engine.process_line(device, 'test-session', line)
    asyncio.run(go())


def test_bare_key_value_infers_unit() -> None:
    """'TEMP:23.4' has no trailing unit; it must still be recognised as °C."""
    telemetry_engine.clear_history('unit-test-1')
    _feed('unit-test-1', 'TEMP:23.4')
    m = telemetry_engine.get_history('unit-test-1', 'TEMP')
    assert m, 'no metric parsed from "TEMP:23.4"'
    assert m[-1].unit == '°C', f'expected °C, got {m[-1].unit!r}'


def test_inline_unit_wins_over_inference() -> None:
    """An explicit unit on the line is authoritative, not inferred."""
    telemetry_engine.clear_history('unit-test-2')
    _feed('unit-test-2', 'VOLTAGE:3.3V')
    m = telemetry_engine.get_history('unit-test-2', 'VOLTAGE')
    assert m and m[-1].unit == 'V', f'expected V, got {m[-1].unit!r}'


def test_json_path_still_works() -> None:
    """The JSON path already inferred units; that behaviour must not regress."""
    telemetry_engine.clear_history('unit-test-3')
    _feed('unit-test-3', '{"temp": 25.5, "humidity": 60}')
    h = telemetry_engine.get_all_metrics('unit-test-3')
    assert h.get('TEMP') and h['TEMP'][-1].unit == '°C'
    assert h.get('HUMIDITY') and h['HUMIDITY'][-1].unit == '%'


def test_unknown_metric_has_no_unit() -> None:
    """An unrecognised name must not be given an invented unit."""
    telemetry_engine.clear_history('unit-test-4')
    _feed('unit-test-4', 'FROBNICATOR:7')
    m = telemetry_engine.get_history('unit-test-4', 'FROBNICATOR')
    assert m and m[-1].unit is None


def test_units_distinguish_physically_incompatible_series() -> None:
    """The whole point: a °C series and a dBm series must not share an axis."""
    telemetry_engine.clear_history('unit-test-5')
    _feed('unit-test-5', 'TEMP:23.4', 'RSSI:-58')
    h = telemetry_engine.get_all_metrics('unit-test-5')
    assert h['TEMP'][-1].unit == '°C'
    assert h['RSSI'][-1].unit == 'dBm'
    assert h['TEMP'][-1].unit != h['RSSI'][-1].unit


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    failed = 0
    for t in tests:
        try:
            t()
            print(f'  PASS  {t.__name__}')
        except AssertionError as e:
            failed += 1
            print(f'  FAIL  {t.__name__}: {e}')
    print(f'\n{len(tests) - failed}/{len(tests)} passed')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
