"""The marketplace API must expose a real registry and real install.

The Marketplace screen shipped a hardcoded list: `install_plugin()` set a flag
and bumped a fabricated download counter, and nothing was ever registered with
`ProtocolManager`. These tests pin the API half of the fix, including the
failure modes that a mock gets wrong for free -- a registry that is unreachable
must not read as an empty marketplace, and an install must actually land in the
manager the decode path uses.

Run:  ../.venv-v2/bin/python -m pytest tests/test_marketplace_api.py -v
"""
import json
import sys
import textwrap
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.protocol_decoder import ProtocolManager  # noqa: E402
from app.core.plugin_registry import PluginRegistry  # noqa: E402

GOOD_PLUGIN = textwrap.dedent('''
    from app.core.protocol_decoder import ProtocolDecoder

    class LinDecoder(ProtocolDecoder):
        @property
        def name(self):
            return "LIN Bus"

        @property
        def protocol_id(self):
            return "lin_ldf"

        @property
        def description(self):
            return "LIN frames"

        def can_decode(self, raw_data):
            return 0.9

        def decode(self, raw_data):
            return {"type": "lin_ldf"}

        def encode(self, data):
            return b"\\x00"
''')

BROKEN_PLUGIN = "class Nope:\n    pass\n"


def build_app(tmp_path, manager, manifest_path):
    """A minimal app with only the marketplace router mounted."""
    from app.api.routes.marketplace import router
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.state.plugin_registry = PluginRegistry(
        manager=manager, install_dir=tmp_path / "plugins",
        state_file=tmp_path / "state.json")
    app.state.registry_manifest = manifest_path
    return app


@pytest.fixture(autouse=True)
def enable_plugin_installs():
    """Enable plugin installs for tests that exercise the install path.

    The default is False (safe by default). Tests that test install behaviour
    need to opt in; tests that test the gate use monkeypatch to flip it back.
    """
    from app.config import settings
    original = settings.plugin_install_enabled
    settings.plugin_install_enabled = True
    yield
    settings.plugin_install_enabled = original


@pytest.fixture
def wired(tmp_path):
    """A manifest, its plugin files, and a manager wired to both.

    The manifest lives at the tmp root and its module paths are relative to
    that root, which is the layout a real registry directory has: registry.json
    beside the .py files it lists.
    """
    (tmp_path / "lin_ldf.py").write_text(GOOD_PLUGIN, encoding='utf-8')
    (tmp_path / "broken.py").write_text(BROKEN_PLUGIN, encoding='utf-8')

    manifest = tmp_path / "registry.json"
    manifest.write_text(json.dumps({"plugins": [
        {"id": "lin_ldf", "name": "LIN Bus (LDF)", "version": "1.0.0",
         "description": "LIN bus frames", "author": "community",
         "downloads": 12, "tags": ["automotive"],
         "module": "lin_ldf.py", "class": "LinDecoder"},
        {"id": "broken", "name": "Broken", "version": "0.1.0",
         "description": "does not implement the interface",
         "author": "nobody", "downloads": 0, "tags": [],
         "module": "broken.py", "class": "Nope"},
    ]}), encoding='utf-8')

    manager = ProtocolManager()
    return build_app(tmp_path, manager, manifest), manager, tmp_path


async def _get(app, path):
    async with AsyncClient(transport=ASGITransport(app=app),
                           base_url="http://t") as c:
        return await c.get(path)


async def _post(app, path, payload=None):
    async with AsyncClient(transport=ASGITransport(app=app),
                           base_url="http://t") as c:
        return await c.post(path, json=payload or {})


class TestCatalog:
    @pytest.mark.asyncio
    async def test_lists_real_entries_with_install_state(self, wired):
        app, manager, tmp = wired
        r = await _post(app, "/api/plugins/refresh")
        assert r.status_code == 200, r.text

        r = await _get(app, "/api/plugins")
        assert r.status_code == 200
        body = r.json()
        assert len(body['plugins']) == 2
        ids = {p['id'] for p in body['plugins']}
        assert ids == {'lin_ldf', 'broken'}
        for p in body['plugins']:
            assert p['installed'] is False
            assert p['builtin'] is False

    @pytest.mark.asyncio
    async def test_unreachable_manifest_is_a_502_not_an_empty_list(self, wired):
        """The mock's core failure: silence read as 'nothing to install'.

        A 404 registry must surface as an error the user can see, never as an
        empty catalog that looks like a working marketplace with no plugins.
        """
        app, manager, tmp = wired
        app.state.registry_manifest = tmp / "gone.json"
        r = await _post(app, "/api/plugins/refresh")
        assert r.status_code == 502, r.text
        assert "not found" in r.json()['detail'].lower()

        r = await _get(app, "/api/plugins")
        assert r.status_code == 200
        assert r.json()['plugins'] == []
        # and the client is told the catalog is stale, so it cannot be mistaken
        # for a genuinely empty marketplace
        assert r.json()['error'] is not None

    @pytest.mark.asyncio
    async def test_catalog_reports_when_it_was_last_refreshed(self, wired):
        app, manager, tmp = wired
        await _post(app, "/api/plugins/refresh")
        r = await _get(app, "/api/plugins")
        assert r.json()['fetched_at'] is not None


class TestInstallEndpoint:
    @pytest.mark.asyncio
    async def test_install_registers_the_decoder(self, wired):
        """The whole point: the decode path can use it afterwards."""
        app, manager, tmp = wired
        await _post(app, "/api/plugins/refresh")

        r = await _post(app, "/api/plugins/lin_ldf/install")
        assert r.status_code == 200, r.text
        assert r.json()['installed'] is True

        assert manager.get_decoder('lin_ldf') is not None
        assert manager.get_decoder('lin_ldf').protocol_id == 'lin_ldf'

        # now visible as installed
        r = await _get(app, "/api/plugins")
        entry = next(p for p in r.json()['plugins'] if p['id'] == 'lin_ldf')
        assert entry['installed'] is True

    @pytest.mark.asyncio
    async def test_installed_plugin_decodes_over_the_api(self, wired):
        """Registered is not enough; it has to work end to end."""
        app, manager, tmp = wired
        await _post(app, "/api/plugins/refresh")
        await _post(app, "/api/plugins/lin_ldf/install")

        async with AsyncClient(transport=ASGITransport(app=app),
                               base_url="http://t") as c:
            r = await c.post("/api/plugins/lin_ldf/decode",
                             json={"data": "abcd"})
        assert r.status_code == 200, r.text
        assert r.json()['decoded']['type'] == 'lin_ldf'

    @pytest.mark.asyncio
    async def test_installing_an_invalid_plugin_fails_with_why(self, wired):
        """A bad plugin must be refused out loud, not marked installed."""
        app, manager, tmp = wired
        await _post(app, "/api/plugins/refresh")

        r = await _post(app, "/api/plugins/broken/install")
        assert r.status_code == 400, r.text
        assert 'decoder' in r.json()['detail'].lower()
        assert manager.get_decoder('broken') is None

        r = await _get(app, "/api/plugins")
        entry = next(p for p in r.json()['plugins'] if p['id'] == 'broken')
        assert entry['installed'] is False

    @pytest.mark.asyncio
    async def test_installing_an_unknown_id_is_404(self, wired):
        app, manager, tmp = wired
        await _post(app, "/api/plugins/refresh")
        r = await _post(app, "/api/plugins/nope/install")
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_uninstall_removes_the_decoder(self, wired):
        app, manager, tmp = wired
        await _post(app, "/api/plugins/refresh")
        await _post(app, "/api/plugins/lin_ldf/install")
        assert manager.get_decoder('lin_ldf') is not None

        r = await _post(app, "/api/plugins/lin_ldf/uninstall")
        assert r.status_code == 200
        assert manager.get_decoder('lin_ldf') is None

    @pytest.mark.asyncio
    async def test_install_before_refresh_is_a_useful_error(self, wired):
        """No catalog, no install -- but say why rather than 500."""
        app, manager, tmp = wired
        r = await _post(app, "/api/plugins/lin_ldf/install")
        assert r.status_code == 409, r.text
        assert 'refresh' in r.json()['detail'].lower()


class TestInstallGate:
    """The plugin-install interlock: off by default, enforced, honest error."""

    def test_default_is_false(self):
        """Pin the default. Without this, someone flips it back and no test notices."""
        from app.config import Settings
        assert Settings().plugin_install_enabled is False

    @pytest.mark.asyncio
    async def test_install_refused_when_disabled(self, wired, monkeypatch):
        """With plugin_install_enabled=False (the default), install is 403."""
        from app.config import settings
        monkeypatch.setattr(settings, "plugin_install_enabled", False)
        app, manager, tmp = wired
        await _post(app, "/api/plugins/refresh")

        r = await _post(app, "/api/plugins/lin_ldf/install")
        assert r.status_code == 403, r.text
        assert "UARTSCOPE_PLUGIN_INSTALL_ENABLED" in r.json()['detail']

        # The decoder must NOT be registered
        assert manager.get_decoder('lin_ldf') is None

    @pytest.mark.asyncio
    async def test_install_succeeds_when_enabled(self, wired, monkeypatch):
        """With plugin_install_enabled=True, install works exactly as before."""
        from app.config import settings
        monkeypatch.setattr(settings, "plugin_install_enabled", True)
        app, manager, tmp = wired
        await _post(app, "/api/plugins/refresh")

        r = await _post(app, "/api/plugins/lin_ldf/install")
        assert r.status_code == 200, r.text
        assert r.json()['installed'] is True
        assert manager.get_decoder('lin_ldf') is not None

    @pytest.mark.asyncio
    async def test_catalog_works_when_installs_disabled(self, wired, monkeypatch):
        """GET /api/plugins must work regardless of the install gate."""
        from app.config import settings
        monkeypatch.setattr(settings, "plugin_install_enabled", False)
        app, manager, tmp = wired
        await _post(app, "/api/plugins/refresh")

        r = await _get(app, "/api/plugins")
        assert r.status_code == 200
        assert len(r.json()['plugins']) == 2

    @pytest.mark.asyncio
    async def test_install_gate_error_names_the_setting(self, wired, monkeypatch):
        """The 403 message must tell the operator what to change."""
        from app.config import settings
        monkeypatch.setattr(settings, "plugin_install_enabled", False)
        app, manager, tmp = wired
        await _post(app, "/api/plugins/refresh")

        r = await _post(app, "/api/plugins/lin_ldf/install")
        assert r.status_code == 403
        detail = r.json()['detail']
        assert "UARTSCOPE_PLUGIN_INSTALL_ENABLED" in detail
        assert "disabled" in detail.lower()


class TestInstalledSurvivesRestart:
    @pytest.mark.asyncio
    async def test_state_is_restored_for_a_new_app_instance(self, wired):
        app, manager, tmp = wired
        await _post(app, "/api/plugins/refresh")
        await _post(app, "/api/plugins/lin_ldf/install")

        # A new manager and app over the same install dir, as after a restart.
        from app.core.plugin_registry import PluginRegistry as PR
        manager2 = ProtocolManager()
        reg2 = PR(manager=manager2, install_dir=tmp / "plugins",
                  state_file=tmp / "state.json")
        import asyncio
        await reg2.restore_installed()

        assert manager2.get_decoder('lin_ldf') is not None

    @pytest.mark.asyncio
    async def test_a_deleted_plugin_does_not_block_startup(self, wired):
        """Third-party files can vanish. Decoding must not depend on one."""
        app, manager, tmp = wired
        await _post(app, "/api/plugins/refresh")
        await _post(app, "/api/plugins/lin_ldf/install")

        (tmp / "plugins" / "lin_ldf.py").unlink()

        from app.core.plugin_registry import PluginRegistry as PR
        manager2 = ProtocolManager()
        reg2 = PR(manager=manager2, install_dir=tmp / "plugins",
                  state_file=tmp / "state.json")
        import asyncio
        restored = await reg2.restore_installed()

        assert restored == []
        assert manager2.get_decoder('lin_ldf') is None
        # built-ins still work
        assert manager2.get_decoder('uart_text') is not None
