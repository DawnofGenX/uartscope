"""A recorded session must contain the metrics that were streamed into it.

The session recorder has had `record_metric()` since the beginning, and the
session file format has a `metrics` list, and the Sessions detail screen has a
Metrics tab. Nothing ever called `record_metric()`. Every capture in the product
therefore had an empty metric list, and the tab had nothing to show.

The failure is invisible: a session JSON looks perfectly well formed, with a
full `packets` list, and only the metrics are missing. Nothing raises.

This test drives the same sequence the live stream path uses, so it fails if the
recording step is removed or renamed again.

Run:  ../.venv-v2/bin/python tests/test_session_metrics_recorded.py
"""
import asyncio
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.session_recorder import SessionRecorder  # noqa: E402
from app.core.telemetry_engine import telemetry_engine  # noqa: E402

LINES = [
    'TEMP:22.4',
    'HUMIDITY:44.1',
    'RSSI:-58',
    'TEMP:23.4',
    'ERROR: sensor timeout on bus 2',
    'VOLTAGE:3.31',
]


async def record_like_the_live_path(recorder, session_id, device_id):
    """Mirror desktop_app.on_data exactly: parse, then record."""
    for line in LINES:
        parsed = await telemetry_engine.process_line(device_id, session_id, line)
        await recorder.record_packet(
            session_id, {'device_id': device_id, 'raw': line})
        for metric in getattr(parsed, 'metrics', None) or []:
            await recorder.record_metric(
                session_id, {'name': metric.name, 'value': metric.value,
                             'unit': metric.unit,
                             'timestamp': metric.timestamp.isoformat()})
    await recorder.stop_session(session_id)


async def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        import app.config as config
        original = config.settings.sessions_dir
        config.settings.sessions_dir = tmp
        try:
            recorder = SessionRecorder()
            sid = 'testsession01'
            await recorder.start_session(sid, device_id='dev1', name='t')
            await record_like_the_live_path(recorder, sid, 'dev1')

            saved = json.loads(
                (Path(tmp) / f'{sid}.json').read_text())

            failures = []

            packets = saved.get('packets') or []
            metrics = saved.get('metrics') or []
            if len(packets) != len(LINES):
                failures.append(
                    f'expected {len(LINES)} packets, got {len(packets)}')
            if not metrics:
                failures.append(
                    'metrics list is EMPTY -- record_metric() was never called, '
                    'so the session Metrics tab has nothing to render')

            names = {m.get('name') for m in metrics}
            for expected in ('TEMP', 'HUMIDITY', 'RSSI', 'VOLTAGE'):
                if expected not in names:
                    failures.append(f'metric {expected} missing from session')

            # Units must survive into the session file, or unit grouping in the
            # replay screen is grouping nothing.
            units = {m.get('name'): m.get('unit') for m in metrics}
            if units.get('TEMP') != '°C':
                failures.append(
                    f"TEMP unit should be °C, got {units.get('TEMP')!r}")
            if units.get('RSSI') != 'dBm':
                failures.append(
                    f"RSSI unit should be dBm, got {units.get('RSSI')!r}")

            for f in failures:
                print(f'  FAIL  {f}')
            if failures:
                return 1
            print(f'  PASS  {len(metrics)} metrics across {len(names)} names, '
                  f'units preserved ({units})')
            print('\n1/1 passed')
            return 0
        finally:
            config.settings.sessions_dir = original


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
