"""The plugin marketplace must install something real.

The Marketplace screen was a UI mock. `install_plugin()` set
`plugin['installed'] = True` and incremented a download counter that was itself
fabricated, so the screen showed a working marketplace that had never installed
anything. `ProtocolManager.register()` has existed the whole time and was never
called from it.

This pins the behaviour that matters: installing a plugin from a registry must
put a working decoder into the registry that the decode path actually uses, and
uninstalling must remove it. A mock cannot pass this.

The plugin is loaded from a file on disk and validated against the
`ProtocolDecoder` interface before it is registered, because a plugin is
third-party code that will run inside the decode path.

Run:  .venv/bin/python -m pytest tests/test_plugin_marketplace.py -v
"""
import asyncio
import json
import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.protocol_decoder import ProtocolManager, ProtocolDecoder  # noqa: E402
from app.core.plugin_registry import (  # noqa: E402
    PluginRegistry,
    PluginValidationError,
    InstalledPlugin,
)

# A decoder that satisfies the interface, standing in for a downloaded plugin.
GOOD_PLUGIN = textwrap.dedent('''
    from app.core.protocol_decoder import ProtocolDecoder

    class LdfDecoder(ProtocolDecoder):
        """LIN bus decoder."""

        @property
        def name(self):
            return "LIN Bus (LDF)"

        @property
        def protocol_id(self):
            return "lin_ldf"

        @property
        def description(self):
            return "LIN bus frames"

        def can_decode(self, raw_data):
            return 0.9

        def decode(self, raw_data):
            return {"type": "lin_ldf", "raw": raw_data.hex()}

        def encode(self, data):
            return b"\\x00"
''')


@pytest.fixture(autouse=True)
def enable_plugin_installs():
    """Enable plugin installs for tests that exercise the install path.

    The default is False (safe by default). Tests that test install behaviour
    need to opt in.
    """
    from app.config import settings
    original = settings.plugin_install_enabled
    settings.plugin_install_enabled = True
    yield
    settings.plugin_install_enabled = original


@pytest.fixture(autouse=True)
def isolate_protocol_manager():
    """Keep plugin registrations out of the shared decoder manager.

    `PluginRegistry` defaults to the `protocol_manager` singleton, so a test
    that installs a plugin registers its decoder for the rest of the session.
    Auto-detect then prefers the leftover plugin and unrelated tests fail with
    confusing messages ("expected uart_text, got lin_ldf").

    Snapshot the registered ids before each test and remove anything added
    afterwards, so this module cannot affect anything else.
    """
    from app.core.protocol_decoder import protocol_manager

    before = {d["id"] for d in protocol_manager.list_decoders()}
    yield
    after = {d["id"] for d in protocol_manager.list_decoders()}
    for extra in after - before:
        protocol_manager.unregister(extra)


def _write_plugin(directory: Path, name: str, source: str = GOOD_PLUGIN) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(source, encoding='utf-8')
    return path


def _registry_file(directory: Path, plugins) -> Path:
    """A registry manifest in the shape a hosted registry would serve."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "registry.json"
    path.write_text(json.dumps({"plugins": plugins}), encoding='utf-8')
    return path


def _lin_manifest(directory: Path) -> Path:
    return _registry_file(directory, [
        {"id": "lin_ldf", "name": "LIN Bus (LDF)", "version": "1.0.0",
         "description": "LIN frames", "author": "someone",
         "downloads": 10, "tags": ["automotive"],
         "module": "lin_ldf.py", "class": "LdfDecoder"},
    ])


def _registry(manager, tmp_path, manifest=None) -> PluginRegistry:
    """A registry that has actually read its manifest.

    Install only accepts a plugin the catalog offers, so every install test has
    to load the manifest first -- an unfetched registry has nothing to install,
    which is the point of get_entry raising KeyError.
    """
    plugins = tmp_path / "plugins"
    plugins.mkdir(parents=True, exist_ok=True)
    _write_plugin(plugins, "lin_ldf.py")
    reg = PluginRegistry(manager=manager, install_dir=plugins,
                         state_file=tmp_path / "state.json")
    reg.fetch_manifest(manifest or _lin_manifest(tmp_path))
    return reg


class TestRegistryFetch:
    def test_reads_plugins_from_a_manifest(self, tmp_path):
        reg = _registry_file(tmp_path, [
            {"id": "lin_ldf", "name": "LIN Bus (LDF)", "version": "1.0.0",
             "description": "LIN frames", "author": "someone",
             "downloads": 10, "tags": ["automotive"],
             "module": "lin_ldf.py",
             "class": "LdfDecoder"},
        ])
        found = PluginRegistry().fetch_manifest(reg)
        assert len(found) == 1
        assert found[0]['id'] == 'lin_ldf'
        assert found[0]['name'] == 'LIN Bus (LDF)'

    def test_missing_manifest_is_an_explicit_error(self, tmp_path):
        """A 404 must not read as an empty marketplace.

        That is how a mock hides itself: silence looks identical to "nothing to
        install".
        """
        with pytest.raises(FileNotFoundError):
            PluginRegistry().fetch_manifest(tmp_path / "nope.json")

    def test_malformed_manifest_is_rejected(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("{not json", encoding='utf-8')
        with pytest.raises(ValueError):
            PluginRegistry().fetch_manifest(bad)

    def test_entry_without_an_id_is_rejected(self, tmp_path):
        """An entry that cannot be addressed cannot be installed."""
        reg = _registry_file(tmp_path, [{"name": "nameless", "version": "1.0.0"}])
        with pytest.raises(ValueError):
            PluginRegistry().fetch_manifest(reg)


class TestPluginValidation:
    def test_a_valid_decoder_passes(self, tmp_path):
        path = _write_plugin(tmp_path / "plugins", "lin_ldf.py")
        decoder = PluginRegistry.validate_file(path)
        assert isinstance(decoder, ProtocolDecoder)
        assert decoder.protocol_id == 'lin_ldf'
        assert decoder.can_decode(b'\x01') == 0.9

    def test_a_class_missing_the_interface_is_rejected(self, tmp_path):
        """The whole point of validating: a plugin that does not implement the
        contract must not reach the registry, where auto_detect would call it
        on live traffic and raise."""
        bad = textwrap.dedent('''
            class NotADecoder:
                name = "nope"

                def can_decode(self, raw):
                    return 0.5
        ''')
        path = _write_plugin(tmp_path / "plugins", "bad.py", bad)
        with pytest.raises(PluginValidationError):
            PluginRegistry.validate_file(path)

    def test_a_plugin_that_raises_on_construction_is_rejected(self, tmp_path):
        exploding = textwrap.dedent('''
            raise RuntimeError("boom at import time")

            class Whatever:
                pass
        ''')
        path = _write_plugin(tmp_path / "plugins", "boom.py", exploding)
        with pytest.raises(PluginValidationError):
            PluginRegistry.validate_file(path)

    def test_a_plugin_with_no_decoder_class_is_rejected(self, tmp_path):
        path = _write_plugin(tmp_path / "plugins", "empty.py", "x = 1\n")
        with pytest.raises(PluginValidationError):
            PluginRegistry.validate_file(path)


class TestInstallAndUninstall:
    def test_install_registers_a_working_decoder(self, tmp_path):
        """The end-to-end claim: install, then the decode path can use it."""
        manager = ProtocolManager()
        registry = _registry(manager, tmp_path)

        installed = asyncio.run(registry.install("lin_ldf"))

        assert installed.plugin_id == 'lin_ldf'
        # It is live in the manager the API decodes through.
        assert manager.get_decoder('lin_ldf') is not None
        assert manager.get_decoder('lin_ldf').protocol_id == 'lin_ldf'
        # And it is listed alongside the built-ins.
        ids = [d['id'] for d in manager.list_decoders()]
        assert 'lin_ldf' in ids
        assert 'uart_text' in ids, "built-ins must survive an install"

    def test_installed_plugin_actually_decodes(self, tmp_path):
        """Not just registered: the decode path must return its result."""
        manager = ProtocolManager()
        registry = _registry(manager, tmp_path)
        asyncio.run(registry.install("lin_ldf"))

        result = manager.decode('lin_ldf', b'\xAB\xCD')
        assert result['type'] == 'lin_ldf'

    def test_uninstall_removes_it_from_the_manager(self, tmp_path):
        manager = ProtocolManager()
        registry = _registry(manager, tmp_path)
        asyncio.run(registry.install("lin_ldf"))
        assert manager.get_decoder('lin_ldf') is not None

        asyncio.run(registry.uninstall('lin_ldf'))
        assert manager.get_decoder('lin_ldf') is None
        assert registry.list_installed() == []

    def test_install_persists_across_a_new_registry(self, tmp_path):
        """State must survive a restart, or 'installed' is a lie again."""
        manager = ProtocolManager()
        registry = _registry(manager, tmp_path)
        state = tmp_path / "state.json"

        asyncio.run(registry.install("lin_ldf"))
        assert state.exists(), "install must be recorded on disk"

        # A fresh manager and registry, as if the app had been restarted.
        manager2 = ProtocolManager()
        second = PluginRegistry(manager=manager2, install_dir=tmp_path / "plugins",
                                state_file=state)
        asyncio.run(second.restore_installed())

        assert manager2.get_decoder('lin_ldf') is not None
        assert [p.plugin_id for p in second.list_installed()] == ['lin_ldf']

    def test_installing_an_unknown_id_fails_loudly(self, tmp_path):
        """No silent no-op: a bad id must raise, not pretend to install."""
        manager = ProtocolManager()
        registry = _registry(manager, tmp_path)
        with pytest.raises(KeyError):
            asyncio.run(registry.install("does-not-exist"))

    def test_cannot_overwrite_a_builtin_id(self, tmp_path):
        """A plugin squatting on `uart_text` would hijack every text frame.

        This is the reason install validates instead of just registering.
        """
        plugins = tmp_path / "plugins"
        plugins.mkdir(parents=True, exist_ok=True)
        _write_plugin(plugins, "squat.py",
                      GOOD_PLUGIN.replace("lin_ldf", "uart_text"))
        manager = ProtocolManager()
        registry = PluginRegistry(manager=manager, install_dir=plugins,
                                  state_file=tmp_path / "state.json")
        registry.fetch_manifest(_registry_file(tmp_path, [
            {"id": "uart_text", "name": "Squatter", "version": "1.0.0",
             "module": "squat.py", "class": "LdfDecoder"},
        ]))

        with pytest.raises(ValueError):
            asyncio.run(registry.install("uart_text"))
        # The real decoder must still be the built-in.
        assert type(manager.get_decoder('uart_text')).__name__ == 'UARTTextDecoder'

    def test_declared_id_must_match_the_code(self, tmp_path):
        """A manifest that misnames its plugin is a broken registry entry.

        Without this check the file is registered under the code's id while the
        catalog claims another, and uninstall can then never remove it.
        """
        plugins = tmp_path / "plugins"
        plugins.mkdir(parents=True, exist_ok=True)
        _write_plugin(plugins, "lin_ldf.py")
        manager = ProtocolManager()
        registry = PluginRegistry(manager=manager, install_dir=plugins,
                                  state_file=tmp_path / "state.json")
        registry.fetch_manifest(_registry_file(tmp_path, [
            {"id": "something_else", "name": "Mislabelled", "version": "1.0.0",
             "module": "lin_ldf.py", "class": "LdfDecoder"},
        ]))
        with pytest.raises(PluginValidationError):
            asyncio.run(registry.install("something_else"))
        assert manager.get_decoder('lin_ldf') is None


class TestUntrustedPluginCannotHijackAutodetect:
    def test_autodetect_survives_a_raising_plugin(self, tmp_path):
        """`auto_detect` calls every decoder on live traffic.

        A plugin that raises inside `can_decode` must not take the detector down
        with it, or one bad download breaks decoding for everything.
        """
        manager = ProtocolManager()

        class Raiser(ProtocolDecoder):
            @property
            def name(self):
                return "raiser"

            @property
            def protocol_id(self):
                return "raiser"

            def can_decode(self, raw_data):
                raise ValueError("malformed plugin")

            def decode(self, raw_data):
                return {}

            def encode(self, data):
                return b""

        manager.register(Raiser())
        # Must not raise, and must still find a real decoder.
        found = manager.auto_detect(b'TEMP:22.4')
        assert found is not None
        assert found.protocol_id == 'uart_text'


class TestStateSurvivesANewRegistry:
    """A recorded install must be visible to a registry that did not make it.

    Regression: `PluginRegistry.__init__` did not read the state file, so
    `list_installed()` was empty in any new instance. "Installed" then only
    meant installed for the lifetime of one process, and the Marketplace screen
    showed an empty Installed list after a restart.
    """

    def test_a_new_registry_sees_a_previously_installed_plugin(self, tmp_path):
        install_dir = tmp_path / "plugins"
        state = tmp_path / "state.json"
        manifest = _lin_manifest(tmp_path)
        _write_plugin(install_dir, "lin_ldf.py")

        first = PluginRegistry(install_dir=install_dir, state_file=state)
        first.fetch_manifest(manifest)
        asyncio.run(first.install("lin_ldf", source_root=install_dir))
        assert [p.plugin_id for p in first.list_installed()] == ["lin_ldf"]

        second = PluginRegistry(install_dir=install_dir, state_file=state)
        assert [p.plugin_id for p in second.list_installed()] == ["lin_ldf"], (
            "a fresh registry must report the recorded install")

    def test_a_new_registry_marks_it_installed_in_the_catalog(self, tmp_path):
        install_dir = tmp_path / "plugins"
        state = tmp_path / "state.json"
        manifest = _lin_manifest(tmp_path)
        _write_plugin(install_dir, "lin_ldf.py")

        first = PluginRegistry(install_dir=install_dir, state_file=state)
        first.fetch_manifest(manifest)
        asyncio.run(first.install("lin_ldf", source_root=install_dir))

        second = PluginRegistry(install_dir=install_dir, state_file=state)
        second.fetch_manifest(manifest)
        entry = second.list_available()[0]
        assert entry["installed"] is True

    def test_constructing_a_registry_does_not_register_the_decoder(self, tmp_path):
        """Reading the state must not import the module.

        `__init__` records what is installed; only restore_installed() actually
        imports and registers. Importing during construction would run
        third-party code outside a deliberate action.
        """
        from app.core.protocol_decoder import ProtocolManager

        install_dir = tmp_path / "plugins"
        state = tmp_path / "state.json"
        manifest = _lin_manifest(tmp_path)
        _write_plugin(install_dir, "lin_ldf.py")

        first = PluginRegistry(install_dir=install_dir, state_file=state)
        first.fetch_manifest(manifest)
        asyncio.run(first.install("lin_ldf", source_root=install_dir))

        manager = ProtocolManager()
        second = PluginRegistry(manager=manager, install_dir=install_dir,
                                state_file=state)
        registered = {d["id"] for d in manager.list_decoders()}
        assert "lin_ldf" not in registered, (
            "constructing a registry must not import or register a plugin; "
            "that belongs to restore_installed()")
