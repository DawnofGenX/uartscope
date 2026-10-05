"""The plugin-install gate must hold on EVERY path, not just the HTTP route.

Found by the orchestrator after the route-level gate shipped: `desktop_app.py`
calls `PluginRegistry.install()` directly, never touching HTTP. With the gate
living only in the API route, the primary shipped product -- the PyInstaller
Windows executable -- could still exec third-party Python with
`plugin_install_enabled=False`.

These tests pin the registry-level gate, which is the one every caller shares.
"""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))

from app.config import settings                                # noqa: E402
from app.core.plugin_registry import (PluginInstallDisabled,  # noqa: E402
                                      PluginRegistry)
from app.core.protocol_decoder import ProtocolManager          # noqa: E402

REGISTRY_DIR = REPO / "registry"
MANIFEST = REGISTRY_DIR / "registry.json"


@pytest.fixture
def registry(tmp_path):
    manager = ProtocolManager()
    reg = PluginRegistry(manager=manager, install_dir=tmp_path / "plugins",
                         state_file=tmp_path / "state.json")
    reg.fetch_manifest(MANIFEST)
    return reg


class TestGateHoldsOnTheDirectPath:
    """The desktop app's exact call shape, with installs disabled."""

    @pytest.mark.asyncio
    async def test_install_refused_when_disabled(self, registry, monkeypatch):
        """registry.install() raises rather than executing the plugin.

        This is the call desktop_app.py's Marketplace screen makes. Before the
        registry-level gate it SUCCEEDED and wrote the module to disk.
        """
        monkeypatch.setattr(settings, "plugin_install_enabled", False)
        with pytest.raises(PluginInstallDisabled) as exc:
            await registry.install("lin_ldf", source_root=REGISTRY_DIR)
        assert "UARTSCOPE_PLUGIN_INSTALL_ENABLED" in str(exc.value), (
            "the refusal must name the setting, so an operator can act on it "
            "without reading the source")

    @pytest.mark.asyncio
    async def test_nothing_written_to_disk_when_refused(self, registry, monkeypatch):
        """A refused install must leave no artefact behind.

        The install copies the module into install_dir and records it in the
        state file; either would survive a restart and make a refused install
        look like it happened.
        """
        monkeypatch.setattr(settings, "plugin_install_enabled", False)
        with pytest.raises(PluginInstallDisabled):
            await registry.install("lin_ldf", source_root=REGISTRY_DIR)
        assert not (registry._install_dir / "lin_ldf.py").exists(), \
            "the module was written despite the refusal"
        assert registry.list_installed() == [], \
            "the install was recorded despite the refusal"

    @pytest.mark.asyncio
    async def test_install_succeeds_when_enabled(self, registry, monkeypatch):
        """The gate must not break the feature when the operator opts in."""
        monkeypatch.setattr(settings, "plugin_install_enabled", True)
        record = await registry.install("lin_ldf", source_root=REGISTRY_DIR)
        assert record.plugin_id == "lin_ldf"
        assert (registry._install_dir / "lin_ldf.py").exists()

    def test_default_is_false(self):
        """Pin the safe default. Without this, flipping it back is silent."""
        from app.config import Settings
        assert Settings().plugin_install_enabled is False

    def test_desktop_app_calls_install_directly(self):
        """Pin WHY the registry gate exists.

        If someone ever routes the desktop screen through HTTP instead, this
        assertion fails and the reason for the registry-level gate can be
        re-examined rather than silently inherited.
        """
        desktop = (REPO / "desktop_app.py").read_text(encoding="utf-8")
        assert "registry.install(" in desktop, (
            "desktop_app.py no longer calls registry.install() directly -- if the "
            "Marketplace screen now goes through the API, the registry-level gate "
            "may be redundant and should be re-evaluated deliberately")
        assert "PluginInstallDisabled" in desktop, (
            "the Marketplace screen must handle the refusal, or the operator sees "
            "an unhandled exception instead of which setting to change")


class TestRouteMapsRefusalTo403:
    """The API must still answer 403, now derived from the registry.

    Wiring mirrors tests/test_marketplace_api.py, which is the proven shape for
    mounting only the marketplace router.
    """

    @pytest.mark.asyncio
    async def test_api_returns_403(self, tmp_path, monkeypatch):
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient

        from app.api.routes.marketplace import router

        monkeypatch.setattr(settings, "plugin_install_enabled", False)

        manager = ProtocolManager()
        app = FastAPI()
        app.include_router(router, prefix="/api")
        app.state.plugin_registry = PluginRegistry(
            manager=manager,
            install_dir=tmp_path / "plugins",
            state_file=tmp_path / "state.json",
        )
        app.state.plugin_registry.fetch_manifest(MANIFEST)

        async with AsyncClient(transport=ASGITransport(app=app),
                               base_url="http://t") as client:
            r = await client.post("/api/plugins/lin_ldf/install")

        assert r.status_code == 403, f"got {r.status_code}: {r.text[:300]}"
        assert "UARTSCOPE_PLUGIN_INSTALL_ENABLED" in r.text

    @pytest.mark.asyncio
    async def test_listing_still_works_when_installs_disabled(self, tmp_path,
                                                              monkeypatch):
        """Browsing the catalogue is not the threat; only installing is."""
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient

        from app.api.routes.marketplace import router

        monkeypatch.setattr(settings, "plugin_install_enabled", False)
        # POST /refresh reads settings.plugin_registry, not the manifest already
        # loaded on the registry. Without this the test depends on another test
        # having set it -- it passed in a full-suite run and failed alone, which
        # is order-dependence, not a real pass.
        manager = ProtocolManager()
        app = FastAPI()
        app.include_router(router, prefix="/api")
        reg = PluginRegistry(manager=manager, install_dir=tmp_path / "plugins",
                             state_file=tmp_path / "state.json")
        reg.fetch_manifest(MANIFEST)
        app.state.plugin_registry = reg
        # POST /refresh resolves its manifest through _manifest_for(), which
        # reads app.state.registry_manifest and falls back to the module-level
        # `_manifest_url` -- NOT settings.plugin_registry, which is only read at
        # configure() time. Setting the wrong one made this test pass in a
        # full-suite run and fail alone: order-dependence, not a real pass.
        app.state.registry_manifest = str(MANIFEST)

        async with AsyncClient(transport=ASGITransport(app=app),
                               base_url="http://t") as client:
            r = await client.post("/api/plugins/refresh")
            assert r.status_code == 200, f"refresh: {r.status_code} {r.text[:200]}"
            r = await client.get("/api/plugins")

        assert r.status_code == 200, f"got {r.status_code}: {r.text[:300]}"
        payload = r.json()
        ids = {p["id"] for p in payload["plugins"]}
        assert "lin_ldf" in ids, "the catalogue must still be browsable"
