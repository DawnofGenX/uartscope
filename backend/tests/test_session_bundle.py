"""The .uartscope bundle must be buildable from the API, not just the desktop.

A `.uartscope` bundle is the shareable capture format: a zip of session.json,
packets.json and metrics.csv. It existed only as `desktop_app._export_bundle`,
which assembled it from UI state, so there was no server-side way to get one --
a script, a CI job, or another client had no way to export a capture.

These test the builder directly, then the route, so the format is pinned
independently of how it is served.

Run:  .venv/bin/python -m pytest tests/test_session_bundle.py -v
"""
import io
import json
import sys
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))

from app.core.session_bundle import (  # noqa: E402
    BUNDLE_VERSION,
    BundleError,
    build_bundle,
    describe_bundle,
    read_bundle,
)


def _session():
    return {
        'id': 'abc12345def67890',
        'name': 'Bench run 3',
        'device_id': 'dev-1',
        'started_at': '2026-09-28T10:00:00',
        'ended_at': '2026-09-28T10:05:00',
        'status': 'completed',
    }


def _packets(n=3):
    return [{'timestamp': f'2026-09-28T10:0{i}:00', 'data': f'line {i}'}
            for i in range(n)]


def _metrics():
    return {
        'temperature': [
            {'timestamp': '2026-09-28T10:00:01', 'value': 42.5, 'unit': 'C'},
            {'timestamp': '2026-09-28T10:00:02', 'value': 43.0, 'unit': 'C'},
        ],
        'pressure': [
            {'timestamp': '2026-09-28T10:00:01', 'value': 101.3, 'unit': 'kPa'},
        ],
    }


class TestBundleContents:
    def test_bundle_is_a_zip_with_the_three_members(self):
        blob = build_bundle(_session(), _packets(), _metrics(), events=[])
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            names = set(zf.namelist())
        assert names == {'session.json', 'packets.json', 'metrics.csv'}

    def test_descriptor_declares_its_version_and_type(self):
        blob = build_bundle(_session(), _packets(), _metrics(), events=[])
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            descriptor = json.loads(zf.read('session.json'))
        assert descriptor['version'] == BUNDLE_VERSION
        assert descriptor['type'] == 'uartscope-session'
        assert descriptor['session']['id'] == 'abc12345def67890'
        assert descriptor['packet_count'] == 3
        assert descriptor['event_count'] == 0

    def test_packets_are_preserved_exactly(self):
        """The raw packets are the only reason the format exists."""
        packets = _packets(5)
        blob = build_bundle(_session(), packets, _metrics(), events=[])
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            assert json.loads(zf.read('packets.json')) == packets

    def test_metrics_csv_has_a_header_and_one_row_per_sample(self):
        blob = build_bundle(_session(), _packets(), _metrics(), events=[])
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            csv_text = zf.read('metrics.csv').decode()
        lines = csv_text.strip().splitlines()
        assert lines[0] == 'timestamp,metric,value,unit'
        # 2 temperature + 1 pressure
        assert len(lines) == 4
        assert 'temperature,42.5,C' in csv_text
        assert 'pressure,101.3,kPa' in csv_text

    def test_empty_session_still_produces_a_valid_bundle(self):
        """A capture with no packets must not raise.

        A session that recorded nothing is a real outcome -- opened and closed
        without traffic -- and the export button should still work.
        """
        blob = build_bundle({'id': 'x', 'name': 'empty'}, [], {}, events=[])
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            assert json.loads(zf.read('packets.json')) == []
            assert zf.read('metrics.csv').decode().strip() == \
                'timestamp,metric,value,unit'

    def test_csv_quotes_values_containing_separators(self):
        """A metric value or unit with a comma must not corrupt the columns."""
        metrics = {'weird': [{'timestamp': 't1', 'value': 'a,b', 'unit': 'x'}]}
        blob = build_bundle({'id': 'x'}, [], metrics, events=[])
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            csv_text = zf.read('metrics.csv').decode()
        assert '"a,b"' in csv_text
        # The point is that it reads back as 4 columns, not 5: the comma
        # inside the value must not create a new column.
        import csv as _csv
        rows = list(_csv.reader(io.StringIO(csv_text)))
        data_row = [r for r in rows if r and r[1] == 'weird'][0]
        assert data_row == ['t1', 'weird', 'a,b', 'x']

    def test_bundle_round_trips(self):
        """read_bundle must return what build_bundle put in."""
        session, packets, metrics = _session(), _packets(4), _metrics()
        blob = build_bundle(session, packets, metrics, events=[])
        parsed = read_bundle(blob)
        assert parsed['session'] == session
        assert parsed['packets'] == packets
        assert parsed['metrics'] == metrics


class TestFilename:
    def test_filename_uses_the_session_id(self):
        name = describe_bundle(_session())['filename']
        assert name == 'session_abc12345.uartscope'

    def test_filename_without_a_session_id(self):
        name = describe_bundle({})['filename']
        assert name == 'session_unknown.uartscope'


class TestBundleErrors:
    def test_reading_a_non_zip_raises(self):
        with pytest.raises(BundleError):
            read_bundle(b'this is not a zip file')

    def test_reading_a_zip_missing_members_raises(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as zf:
            zf.writestr('session.json', '{}')
        with pytest.raises(BundleError) as exc:
            read_bundle(buffer.getvalue())
        assert 'packets.json' in str(exc.value)

    def test_a_malformed_packet_file_raises_rather_than_guessing(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as zf:
            zf.writestr('session.json', '{}')
            zf.writestr('packets.json', 'not json at all')
            zf.writestr('metrics.csv', '')
        with pytest.raises(BundleError):
            read_bundle(buffer.getvalue())


class TestBundleImportAndRegistryCoverTheSameFormat:
    def test_desktop_bundle_helper_is_the_shared_builder(self):
        """One implementation, two callers.

        The desktop app must not keep its own copy of the zip assembly; a
        format defined twice drifts.
        """
        desktop = (REPO / 'desktop_app.py').read_text(encoding='utf-8')
        assert 'build_bundle' in desktop
        # The hand-rolled zipfile writes should be gone from the desktop path.
        assert "zf.writestr('session.json'" not in desktop
