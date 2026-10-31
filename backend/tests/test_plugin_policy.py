"""The plugin capability policy must refuse what it claims to refuse.

The marketplace runs third-party Python inside the decode path. Until now the
only defence was "read the source first" -- honest, and useless as a gate. This
pins the policy that replaced it:

  * a plugin that imports `os`, `socket`, `subprocess`, `pickle` or reaches for
    `__class__` is refused, with the line number;
  * it is refused **before** it is compiled, so a refused plugin's import-time
    side effects never happen (that ordering is what the file-marker test
    proves -- an AST check bolted on after `exec` would still pass "the
    violation is reported" while leaking the write);
  * a manifest may pin a SHA-256, and bytes that do not match the pin are never
    imported;
  * the digest is recorded on install and re-checked at startup, so a plugin
    swapped on disk after install is dropped instead of loaded.

The policy is a seatbelt, not a sandbox: `while True: pass` defeats it, and no
test here pretends otherwise. See backend/app/core/plugin_policy.py.

Run:  python -m pytest tests/test_plugin_policy.py -v
"""
import asyncio
import json
import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import plugin_policy  # noqa: E402
from app.core.plugin_registry import (  # noqa: E402
    PluginRegistry,
    PluginValidationError,
)
from app.core.protocol_decoder import ProtocolManager  # noqa: E402

REGISTRY_DIR = Path(__file__).resolve().parents[2] / 'registry'

GOOD_PLUGIN = textwrap.dedent('''
    import struct
    from typing import Dict

    from app.core.protocol_decoder import ProtocolDecoder

    class LdfDecoder(ProtocolDecoder):
        """LIN bus decoder."""

        @property
        def name(self):
            return "LIN Bus (LDF)"

        @property
        def protocol_id(self):
            return "lin_ldf"

        def can_decode(self, raw_data):
            return 0.9 if raw_data[:1] == b"\\x55" else 0.0

        def decode(self, raw_data):
            return {"type": "lin_ldf", "id": struct.unpack("<B", raw_data[:1])[0]}

        def encode(self, data):
            return bytes([data.get("id", 0)])
''')


@pytest.fixture(autouse=True)
def enable_plugin_installs():
    from app.config import settings
    original = settings.plugin_install_enabled
    settings.plugin_install_enabled = True
    yield
    settings.plugin_install_enabled = original


# ── the bundled registry has to keep working ──────────────────────────────
def test_bundled_plugins_pass_the_policy():
    """The policy must not refuse the decoders the product itself ships."""
    manifest = json.loads((REGISTRY_DIR / 'registry.json').read_text(encoding='utf-8'))
    assert manifest['plugins'], 'bundled registry is empty'
    for entry in manifest['plugins']:
        path = REGISTRY_DIR / entry['module']
        assert plugin_policy.check_source(path.read_text(encoding='utf-8'),
                                          origin=str(path)) == [], \
            f"the policy now refuses UARTScope's own {entry['id']} plugin"
        decoder = PluginRegistry.validate_file(path)
        assert decoder.protocol_id == entry['id']


def test_bundled_manifest_digests_match_the_files_on_disk():
    """A pin nobody checks is decoration; this is the check."""
    manifest = json.loads((REGISTRY_DIR / 'registry.json').read_text(encoding='utf-8'))
    for entry in manifest['plugins']:
        path = REGISTRY_DIR / entry['module']
        assert entry.get('sha256'), f"{entry['id']} ships without a pinned digest"
        assert plugin_policy.file_sha256(path) == entry['sha256'].lower(), (
            f"{entry['id']}: registry.json pins a digest that does not match "
            f"registry/{entry['module']} -- update the pin with the file")


# ── hostile plugins are refused, by line ─────────────────────────────────
HOSTILE_CASES = [
    ('import os\n', 'os'),
    ('import subprocess\n', 'subprocess'),
    ('import socket\n', 'socket'),
    ('import pickle\n', 'pickle'),
    ('import importlib\n', 'importlib'),
    ('from pathlib import Path\n', 'pathlib'),
    ('from app.core.tool_manager import ToolManager\n', 'app.core.tool_manager'),
    ('from . import sibling\n', 'relative'),
    ('open("/etc/passwd")\n', 'open'),
    ('eval("1+1")\n', 'eval'),
    ('exec("x = 1")\n', 'exec'),
    ('__import__("os")\n', '__import__'),
    ('globals()["x"] = 1\n', 'globals'),
    ('getattr(object, "__class__")\n', 'getattr'),
    ('x = ().__class__.__bases__\n', '__class__'),
    ('x = "{}__subclasses__".format(1)\n', '__subclasses__'),
]


@pytest.mark.parametrize('source,token', HOSTILE_CASES)
def test_hostile_snippet_is_refused_by_the_policy(source, token):
    violations = plugin_policy.check_source(source, origin='<hostile>')
    assert violations, f'policy accepted: {source!r}'
    joined = ' '.join(violations)
    assert token in joined, f'violation does not name {token!r}: {violations}'
    assert 'line ' in joined, 'a refusal has to say which line'


@pytest.mark.parametrize('source,token', HOSTILE_CASES)
def test_hostile_snippet_cannot_be_installed(source, token):
    """The policy is wired into the installer, not just importable."""
    with pytest.raises(PluginValidationError) as excinfo:
        PluginRegistry.validate_source(source, origin='<hostile>')
    message = str(excinfo.value)
    assert 'capability policy' in message
    assert token in message


def test_refusal_happens_before_anything_runs(tmp_path):
    """Ordering proof: the module-level write must never happen.

    A policy applied after `exec` would still report the violation, and the
    marker file would exist. This is the only test here that can tell those two
    implementations apart.
    """
    marker = tmp_path / 'executed.txt'
    source = textwrap.dedent(f'''
        import pathlib
        pathlib.Path({str(marker)!r}).write_text("the plugin ran")
    ''')
    with pytest.raises(PluginValidationError):
        PluginRegistry.validate_source(source, origin='<side-effect>')
    assert not marker.exists(), 'a refused plugin executed its import-time code'


def test_a_plugin_that_needs_nothing_fancy_is_accepted():
    """False-positive guard: the allowlist has to cover real decoders."""
    assert plugin_policy.check_source(GOOD_PLUGIN) == []


# ── manifest digests ─────────────────────────────────────────────────────
def _write_plugin(directory: Path, name: str, source: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(source, encoding='utf-8')
    return path


def _registry(manager, tmp_path, entry):
    plugins = tmp_path / 'plugins'
    _write_plugin(plugins, 'lin_ldf.py', GOOD_PLUGIN)
    manifest = tmp_path / 'registry.json'
    manifest.write_text(json.dumps({'plugins': [entry]}), encoding='utf-8')
    reg = PluginRegistry(manager=manager, install_dir=plugins,
                         state_file=tmp_path / 'state.json')
    reg.fetch_manifest(manifest)
    return reg


def _entry(**overrides):
    entry = {'id': 'lin_ldf', 'name': 'LIN Bus', 'version': '1.0.0',
             'module': 'lin_ldf.py', 'class': 'LdfDecoder'}
    entry.update(overrides)
    return entry


def test_install_refuses_bytes_that_do_not_match_the_pin(tmp_path):
    manager = ProtocolManager()
    reg = _registry(manager, tmp_path, _entry(sha256='0' * 64))
    with pytest.raises(PluginValidationError) as excinfo:
        asyncio.run(reg.install('lin_ldf'))
    message = str(excinfo.value)
    assert 'digest mismatch' in message
    # Both digests are named, so an operator can tell a stale pin from an attack.
    assert '0' * 64 in message
    assert plugin_policy.file_sha256(tmp_path / 'plugins' / 'lin_ldf.py') in message
    assert manager.get_decoder('lin_ldf') is None, 'a refused plugin was registered'


def test_install_with_a_correct_pin_records_the_digest(tmp_path):
    manager = ProtocolManager()
    reg = _registry(manager, tmp_path, _entry())
    expected = plugin_policy.file_sha256(tmp_path / 'plugins' / 'lin_ldf.py')
    reg = _registry(manager, tmp_path, _entry(sha256=expected))
    record = asyncio.run(reg.install('lin_ldf'))
    assert record.sha256 == expected
    assert manager.get_decoder('lin_ldf') is not None


def test_install_without_a_pin_still_records_a_digest(tmp_path):
    """Unpinned manifests are allowed, but they do not skip tamper detection."""
    manager = ProtocolManager()
    reg = _registry(manager, tmp_path, _entry())
    actual = plugin_policy.file_sha256(tmp_path / 'plugins' / 'lin_ldf.py')
    record = asyncio.run(reg.install('lin_ldf'))
    assert record.sha256 == actual


def test_restore_drops_a_plugin_whose_bytes_changed_after_install(tmp_path):
    manager = ProtocolManager()
    reg = _registry(manager, tmp_path, _entry())
    asyncio.run(reg.install('lin_ldf'))
    assert (tmp_path / 'plugins' / 'lin_ldf.py').exists()

    # Same policy-clean source, different bytes: exactly what a swap looks like.
    installed = tmp_path / 'plugins' / 'lin_ldf.py'
    installed.write_text(GOOD_PLUGIN + '\n# injected\n', encoding='utf-8')

    fresh_manager = ProtocolManager()
    restarted = PluginRegistry(manager=fresh_manager, install_dir=tmp_path / 'plugins',
                               state_file=tmp_path / 'state.json')
    restored = asyncio.run(restarted.restore_installed())
    assert restored == [], 'a tampered plugin was restored'
    assert fresh_manager.get_decoder('lin_ldf') is None


def test_every_violation_is_reported_not_just_the_first():
    """An operator fixing a plugin should see the whole list in one pass."""
    violations = plugin_policy.check_source(
        'import os\nimport socket\nx = eval("1")\n')
    assert len(violations) == 3, violations
    assert [v.split(':')[0] for v in violations] == ['line 1', 'line 2', 'line 3']
