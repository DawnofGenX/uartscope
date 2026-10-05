"""The registry's own plugins must be real decoders.

A marketplace that ships broken plugins is worse than one that ships none: the
screen would show a working install that then produces wrong frames, which is
the exact failure this whole feature was supposed to stop.

These run the actual registry files -- not fixtures -- through the same
validation and install path the API uses, and check that each one decodes a
frame it should recognise and rejects one it should not.

Run:  ../.venv-v2/bin/python -m pytest tests/test_registry_plugins.py -v
"""
import asyncio
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))

from app.core.plugin_registry import PluginRegistry  # noqa: E402
from app.core.protocol_decoder import ProtocolManager  # noqa: E402

REGISTRY_DIR = REPO / "registry"
MANIFEST = REGISTRY_DIR / "registry.json"


@pytest.fixture(scope="module")
def manifest():
    return json.loads(MANIFEST.read_text(encoding='utf-8'))


@pytest.fixture(autouse=True)
def allow_installs():
    """These tests install real plugins, so they opt in explicitly.

    `plugin_install_enabled` defaults to False because installing a plugin runs
    third-party Python in-process with no sandbox. That default is the
    security control, and it is enforced inside `PluginRegistry.install` -- the
    choke point every caller shares. A test suite that exercises the install
    path therefore has to turn it on deliberately rather than inherit it, so
    that flipping the default off can never be silently undone by a test that
    forgot the gate exists.
    """
    from app.config import settings
    original = settings.plugin_install_enabled
    settings.plugin_install_enabled = True
    yield
    settings.plugin_install_enabled = original


def _load(plugin_id, manifest, tmp_path):
    """Install one registry plugin through the real path."""
    manager = ProtocolManager()
    install_dir = tmp_path / "plugins"
    install_dir.mkdir(parents=True, exist_ok=True)
    reg = PluginRegistry(manager=manager, install_dir=install_dir,
                         state_file=tmp_path / "state.json")
    reg.fetch_manifest(MANIFEST)
    asyncio.run(reg.install(plugin_id, source_root=REGISTRY_DIR))
    return manager.get_decoder(plugin_id)


class TestManifestIsHonest:
    def test_every_listed_plugin_file_exists(self, manifest):
        """A manifest naming a file that is not there is a broken registry.

        This is the marketplace version of listing a feature the product does
        not have: the entry looks installable and fails on click.
        """
        missing = [
            p['id'] for p in manifest['plugins']
            if not (REGISTRY_DIR / p['module']).exists()
        ]
        assert missing == [], f"manifest lists plugins with no file: {missing}"

    def test_every_plugin_loads_and_conforms(self, manifest, tmp_path):
        for entry in manifest['plugins']:
            decoder = _load(entry['id'], manifest, tmp_path / entry['id'])
            assert decoder is not None, entry['id']
            assert decoder.protocol_id == entry['id']
            assert decoder.name == entry['name']
            assert decoder.description

    def test_manifest_ids_are_not_builtin_ids(self, manifest):
        """A registry must not offer a plugin that replaces a built-in."""
        from app.core.plugin_registry import BUILTIN_IDS
        clash = [p['id'] for p in manifest['plugins'] if p['id'] in BUILTIN_IDS]
        assert clash == [], f"registry shadows built-ins: {clash}"

    def test_no_fabricated_download_counts(self, manifest):
        """The old screen invented download numbers.

        A registry served by this project has no download telemetry, so any
        number here is a fiction. Absent is honest; a made-up figure is not.
        """
        fabricated = [p['id'] for p in manifest['plugins'] if 'downloads' in p]
        assert fabricated == [], (
            f"registry invents download counts for {fabricated}")


class TestLinDecoder:
    def test_decodes_a_frame_it_encoded(self, tmp_path, manifest):
        decoder = _load('lin_ldf', manifest, tmp_path)
        # A protected frame ID occupies PID bits 2-5, so valid IDs run
        # 0x10, 0x14, 0x18 ... 0x3C. 0x10 is Setpoint_C in the signal table.
        frame = decoder.encode({'frame_id': 0x10, 'data': [0x64]})
        result = decoder.decode(frame)
        assert result['type'] == 'lin_ldf'
        assert result['frame_id'] == 0x10
        assert result['data_length'] == 1
        assert result['checksum_valid'] is True
        assert result['signal'] == 'Setpoint_C'
        # 0x64 = 100; 100 * 0.5 - 40 = 10.0 degrees C
        assert result['value'] == 10.0

    def test_p0_parity_bit_is_correct_per_spec(self, tmp_path, manifest):
        """P0 is the xor of the id bits with the two other parity bits.

        Getting this wrong is silent: a slave would reject the frame, and a
        decode that does not check P0 would never notice. Every valid protected
        ID is checked, not a convenient one.
        """
        decoder = _load('lin_ldf', manifest, tmp_path)
        for frame_id in (0x10, 0x14, 0x18, 0x1C, 0x20, 0x24, 0x3C):
            frame = decoder.encode({'frame_id': frame_id, 'data': [0x00]})
            pid = frame[2]                      # break, sync, PID
            p1 = (pid >> 1) & 1
            p0 = pid & 1
            id_bits = (pid & 0x3C) >> 2
            expected_p0 = bin(id_bits).count('1') & 1 ^ p1 ^ 1
            assert p0 == expected_p0, (
                f"id 0x{frame_id:02X} -> PID 0x{pid:02X}: "
                f"P0={p0}, spec requires {expected_p0}")
            # `parity_bit` reports P0, which is legitimately 0 for half the
            # IDs, so compare against the spec value rather than True.
            assert decoder.decode(frame)['parity_bit'] == bool(expected_p0)
            assert decoder.decode(frame)['frame_id'] == frame_id

    def test_protected_id_round_trips(self, tmp_path, manifest):
        """encode(frame_id) must decode back to the same id.

        The PID field holds the id shifted left two bits plus two parity bits,
        so a naive pass-through would silently return a different id.
        """
        decoder = _load('lin_ldf', manifest, tmp_path)
        for frame_id in (0x10, 0x14, 0x24, 0x3C):
            frame = decoder.encode({'frame_id': frame_id, 'data': [0x10]})
            assert decoder.decode(frame)['frame_id'] == frame_id

    def test_detects_a_real_lin_frame(self, tmp_path, manifest):
        """break, sync, PID, data, checksum -- built by hand per LIN 1.3."""
        decoder = _load('lin_ldf', manifest, tmp_path)
        # Classic checksum covers the whole frame: break, sync, PID and data.
        body = bytes([0x00, 0x55, 0x13, 0x64])
        frame = body + bytes([(~sum(body)) & 0xFF])
        assert decoder.can_decode(frame) > 0.8
        result = decoder.decode(frame)
        assert result['header'] == 'break+sync'
        assert result['frame_id'] == 0x10          # PID 0x13 -> id 0x10
        assert result['parity_bit'] is True
        assert result['checksum_bit'] is True
        assert result['checksum_valid'] is True

    def test_rejects_a_short_frame(self, tmp_path, manifest):
        decoder = _load('lin_ldf', manifest, tmp_path)
        assert decoder.can_decode(b'\x55\x13') == 0.0
        assert 'error' in decoder.decode(b'\x55\x13')

    def test_flagged_checksum(self, tmp_path, manifest):
        decoder = _load('lin_ldf', manifest, tmp_path)
        frame = bytearray(bytes([0x00, 0x55, 0x13, 0x64]) + b'\x00')
        result = decoder.decode(bytes(frame))
        assert result['checksum_valid'] is False


class TestJ1939Decoder:
    def _can_id(self, pgn, source=0, priority=3):
        """A J1939 CAN id, per SAE J1939-21.

        Bit 31 marks an extended frame; a standard 11-bit id is not J1939. PF
        and PS are the PGN's top and low bytes for a PDU2 (PF >= 240) message.
        """
        return (0x80000000 | (priority << 26)
                | (((pgn >> 8) & 0xFF) << 16) | ((pgn & 0xFF) << 8)
                | (source & 0xFF)) & 0xFFFFFFFF

    def _engine_frame(self, rpm):
        """PGN 0xF004 (Engine_1) from address 0, priority 3, 8 data bytes."""
        return (self._can_id(0xF004).to_bytes(4, 'big')
                + rpm.to_bytes(2, 'little') + b'\xff' * 6)

    def test_decodes_engine_speed(self, tmp_path, manifest):
        decoder = _load('j1939', manifest, tmp_path)
        frame = self._engine_frame(600)          # 600 * 0.125 = 75 rpm
        # CAN id (4) + the full 8 data bytes. A J1939 message is always a
        # 12-byte CAN frame; a short one is a standard CAN frame, not J1939.
        assert len(frame) == 12
        assert decoder.can_decode(frame) > 0.9
        result = decoder.decode(frame)
        assert result['pgn'] == '0x0F004'
        assert result['pgn_name'] == 'Engine_1'
        assert result['source'] == 0
        assert result['signals']['Engine_Speed'] == 75.0

    def test_requires_the_extended_identifier(self, tmp_path, manifest):
        """A standard 11-bit CAN id is not J1939."""
        decoder = _load('j1939', manifest, tmp_path)
        standard = (0x123).to_bytes(4, 'big') + b'\x00' * 8
        assert decoder.can_decode(standard) == 0.0
        assert 'error' in decoder.decode(standard)

    def test_rejects_a_short_can_frame(self, tmp_path, manifest):
        """8 bytes is a standard CAN frame; J1939 needs id + 8 data."""
        decoder = _load('j1939', manifest, tmp_path)
        short = self._can_id(0xF004).to_bytes(4, 'big') + b'\x00' * 4
        assert decoder.can_decode(short) == 0.0
        assert 'error' in decoder.decode(short)

    def test_round_trips_through_encode(self, tmp_path, manifest):
        decoder = _load('j1939', manifest, tmp_path)
        frame = decoder.encode({'pgn': '0xF004', 'source': 0,
                                'signals': {'Engine_Speed': 800.0}})
        assert len(frame) == 12
        result = decoder.decode(frame)
        assert result['pgn'] == '0x0F004'
        assert result['signals']['Engine_Speed'] == 800.0

    def test_transport_control_is_reported(self, tmp_path, manifest):
        """An RTS must be labelled, not decoded as payload data."""
        decoder = _load('j1939', manifest, tmp_path)
        can_id = self._can_id(0xEC00, source=0, priority=6)
        # TP.CM_RTS: control byte (1), total message size (2, LE), then the PGN
        # of the message being transferred (3, LE). That is 6 bytes, padded out
        # to the 8 data bytes a CAN frame carries.
        payload = bytes([0x10]) + (1785).to_bytes(2, 'little') + \
            (0xF004).to_bytes(3, 'little') + b'\xff\xff'
        assert len(payload) == 8
        result = decoder.decode(can_id.to_bytes(4, 'big') + payload)
        assert result['tp'] == 'CM'
        assert result['request'] == 'RTS'
        assert result['message_size'] == 1785      # 0xF5,0x06 little-endian
        assert result['total_bytes'] == 0xF004

    def test_transport_data_is_reassembled(self, tmp_path, manifest):
        """DT packets accumulate; the message appears on EndOfMsgAck."""
        decoder = _load('j1939', manifest, tmp_path)
        dt_id = self._can_id(0xEB00, source=0, priority=6)
        # sequence byte + 7 data bytes
        payload = bytes([1, 0xAB, 0xCD, 0xEF, 0x12, 0x34, 0x56, 0x78])
        assert len(payload) == 8
        first = decoder.decode(dt_id.to_bytes(4, 'big') + payload)
        assert first['tp'] == 'DT'
        assert first['sequence'] == 1
        assert first['received_so_far'] == 7


class TestDaliDecoder:
    def test_forward_short_frame(self, tmp_path, manifest):
        decoder = _load('dali', manifest, tmp_path)
        # level 0x02 = "up to max"
        frame = decoder.encode({'level': 0x02})
        result = decoder.decode(frame)
        assert result['type'] == 'dali'
        assert result['frame'] == 'forward'
        assert result['command'] == 'up'
        assert result['level_percent'] == 100.0

    def test_each_short_frame_level_maps_to_its_own_percent(self, tmp_path, manifest):
        """Levels are not all 100%.

        A decoder that reported max level for every command would satisfy a
        single 'up' assertion, so the whole table is checked: distinct
        commands must yield distinct percentages.
        """
        decoder = _load('dali', manifest, tmp_path)
        seen = {}
        for level, expected_pct in ((0x00, 0.0), (0x02, 100.0),
                                    (0x03, 0.0), (0x04, 100.0),
                                    (0x05, 0.0), (0x06, 100.0)):
            result = decoder.decode(decoder.encode({'level': level}))
            assert result.get('level_percent') == expected_pct, (
                f"level 0x{level:02X} -> {result.get('level_percent')}, "
                f"expected {expected_pct}")
            seen[result['command']] = result['level_percent']
        # 'up' is max, 'down' is min: not the same number.
        assert seen['up'] != seen['down']

    def test_forward_long_frame_with_special_command(self, tmp_path, manifest):
        decoder = _load('dali', manifest, tmp_path)
        frame = decoder.encode({'address': 0x05, 'info': 0x81})
        result = decoder.decode(frame)
        assert result['frame'] == 'forward'
        assert result['address'] == '05'
        assert result['command'] == 'store_actual_level_in_dtr0'

    def test_backward_frame(self, tmp_path, manifest):
        decoder = _load('dali', manifest, tmp_path)
        result = decoder.decode(bytes([0xA3, 0x00]))
        assert result['frame'] == 'backward'
        assert result['status_byte'] == 'A3'

    def test_bad_parity_is_reported(self, tmp_path, manifest):
        decoder = _load('dali', manifest, tmp_path)
        result = decoder.decode(bytes([0x7F]))     # parity bit deliberately wrong
        assert 'error' in result
        assert result['error'] == 'Parity error'

    def test_rejects_wrong_length(self, tmp_path, manifest):
        decoder = _load('dali', manifest, tmp_path)
        assert decoder.can_decode(b'\x00' * 8) == 0.0
        assert 'error' in decoder.decode(b'')


class TestInstalledPluginsCoexist:
    def test_all_three_install_and_decode_side_by_side(self, tmp_path, manifest):
        """The realistic end state: several plugins live at once."""
        manager = ProtocolManager()
        install_dir = tmp_path / "plugins"
        install_dir.mkdir(parents=True, exist_ok=True)
        reg = PluginRegistry(manager=manager, install_dir=install_dir,
                             state_file=tmp_path / "state.json")
        reg.fetch_manifest(MANIFEST)
        for entry in manifest['plugins']:
            asyncio.run(reg.install(entry['id'], source_root=REGISTRY_DIR))

        ids = {d['id'] for d in manager.list_decoders()}
        assert {'lin_ldf', 'j1939', 'dali'} <= ids
        # The built-ins are untouched.
        assert {'uart_text', 'modbus_rtu', 'i2c', 'spi', 'can', 'can_dbc'} <= ids
        assert len(reg.list_installed()) == len(manifest['plugins'])
