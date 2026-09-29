"""Plugin marketplace API.

Exposes a registry of installable protocol decoders. The screen this backs used
to render a hardcoded list and a fake install, so the routes here are written to
make the difference observable from outside:

  * an unreachable registry is a 502 with a reason, never an empty list, because
    an empty list is indistinguishable from a working marketplace with no
    plugins in it;
  * an install that fails validation returns 400 with the reason and leaves the
    plugin uninstalled, rather than reporting success;
  * the catalog reports when it was last fetched, so a client can tell stale
    data from a genuine empty registry.

The manifest is a JSON document at a configurable path. `UARTSCOPE_PLUGIN_REGISTRY`
may point at a URL; otherwise the bundled `registry/registry.json` is used, which
the app serves over HTTP so the same code path serves a local registry and a
hosted one.
"""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, HTTPException, Request

from app.core.plugin_registry import PluginRegistry, PluginValidationError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/plugins", tags=["plugins"])

# Populated by main.py at startup; tests override it on app.state.
_registry: Optional[PluginRegistry] = None
_manifest_url: Optional[str] = None
_fetched_at: Optional[str] = None
_last_error: Optional[str] = None


def configure(registry: PluginRegistry, manifest_url: Optional[str] = None) -> None:
    global _registry, _manifest_url
    _registry = registry
    _manifest_url = manifest_url


def _resolve(request: Request) -> PluginRegistry:
    """Prefer app.state so a test can inject its own wiring."""
    return getattr(request.app.state, 'plugin_registry', None) or _registry


def _manifest_for(request: Request) -> Optional[str]:
    return getattr(request.app.state, 'registry_manifest', None) or _manifest_url


async def _load(registry: PluginRegistry, url: Optional[str]) -> None:
    """Fetch a manifest from a URL or a local path, into the registry.

    Raises on any failure. Callers turn that into a status code; nothing here
    degrades to an empty catalog.
    """
    global _fetched_at, _last_error

    if not url:
        raise HTTPException(status_code=502,
                            detail="No plugin registry is configured. Set "
                                   "UARTSCOPE_PLUGIN_REGISTRY to a URL or file path.")

    # A local registry may be configured as a Path; the branches below are
    # written against a string.
    url = str(url)

    if url.startswith(('http://', 'https://')):
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(url)
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502,
                                detail=f"Plugin registry unreachable: {exc}") from exc
        if response.status_code != 200:
            raise HTTPException(
                status_code=502,
                detail=f"Plugin registry returned HTTP {response.status_code}")
        try:
            payload = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Plugin registry is not valid JSON: {exc}") from exc
        plugins = _validate_payload(payload)
        registry._catalog = plugins                 # already validated
    else:
        path = Path(url)
        if not path.exists():
            raise HTTPException(
                status_code=502,
                detail=f"Plugin registry not found: {path}")
        try:
            plugins = registry.fetch_manifest(path)
        except ValueError as exc:
            raise HTTPException(status_code=502,
                                detail=f"Plugin registry is malformed: {exc}") from exc

    _fetched_at = datetime.now(timezone.utc).isoformat()
    _last_error = None


def _validate_payload(payload: Any) -> list:
    """Reject a malformed network manifest the same way a local one is."""
    if isinstance(payload, dict):
        plugins = payload.get('plugins')
    else:
        plugins = payload
    if not isinstance(plugins, list):
        raise HTTPException(status_code=502,
                            detail="Plugin registry has no 'plugins' list")
    seen = set()
    for entry in plugins:
        if not isinstance(entry, dict):
            raise HTTPException(status_code=502,
                                detail=f"Plugin registry entry is not an object: {entry!r}")
        pid = entry.get('id')
        if not pid or not isinstance(pid, str):
            raise HTTPException(
                status_code=502,
                detail=f"Plugin registry entry has no usable id: {entry!r}")
        if pid in seen:
            raise HTTPException(status_code=502,
                                detail=f"Plugin registry lists {pid!r} twice")
        seen.add(pid)
        module = entry.get('module', '')
        if module and (Path(module).is_absolute() or '..' in Path(module).parts):
            raise HTTPException(
                status_code=502,
                detail=f"Plugin registry entry {pid!r} has an unsafe module path")
    return plugins


@router.get("")
async def list_plugins(request: Request):
    """The catalog: available plugins with their install and built-in state."""
    global _last_error
    registry = _resolve(request)
    if registry is None:
        raise HTTPException(status_code=503, detail="Plugin registry is not configured")

    url = _manifest_for(request)
    if not registry._catalog and url:
        # First read: try to populate so a client that only GETs still works.
        try:
            await _load(registry, url)
        except HTTPException as exc:
            _last_error = str(exc.detail)
    elif not registry._catalog:
        _last_error = "No plugin registry is configured."

    return {
        'plugins': registry.list_available(),
        'fetched_at': _fetched_at,
        'error': _last_error,
        'installed': [p.to_dict() for p in registry.list_installed()],
    }


@router.post("/refresh")
async def refresh(request: Request):
    """Re-read the manifest from its source."""
    global _last_error
    registry = _resolve(request)
    if registry is None:
        raise HTTPException(status_code=503, detail="Plugin registry is not configured")
    try:
        await _load(registry, _manifest_for(request))
    except HTTPException as exc:
        _last_error = str(exc.detail)
        raise
    return {'plugins': len(registry.list_available()),
            'fetched_at': _fetched_at}


@router.get("/installed")
async def installed(request: Request):
    registry = _resolve(request)
    if registry is None:
        raise HTTPException(status_code=503, detail="Plugin registry is not configured")
    return {'installed': [p.to_dict() for p in registry.list_installed()]}


@router.post("/{plugin_id}/install")
async def install(plugin_id: str, request: Request):
    """Install a plugin and register its decoder.

    Installing runs third-party Python inside the decode path. The module is
    validated first, a plugin may not claim a built-in protocol id, and nothing
    is written or registered unless both pass.
    """
    registry = _resolve(request)
    if registry is None:
        raise HTTPException(status_code=503, detail="Plugin registry is not configured")
    if not registry._catalog:
        raise HTTPException(
            status_code=409,
            detail="No plugin catalog loaded. POST /api/plugins/refresh first.")

    try:
        entry = registry.get_entry(plugin_id)
    except KeyError:
        raise HTTPException(status_code=404,
                            detail=f"Plugin {plugin_id!r} is not in the registry")

    try:
        record = await registry.install(plugin_id, source_root=_source_root(request))
    except PluginValidationError as exc:
        raise HTTPException(status_code=400,
                            detail=f"Plugin rejected: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (OSError, FileNotFoundError) as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Plugin file could not be fetched: {exc}") from exc

    logger.info("plugin %s installed by API user", plugin_id)
    return {'installed': True, 'plugin': record.to_dict()}


@router.post("/{plugin_id}/uninstall")
async def uninstall(plugin_id: str, request: Request):
    registry = _resolve(request)
    if registry is None:
        raise HTTPException(status_code=503, detail="Plugin registry is not configured")
    try:
        await registry.uninstall(plugin_id)
    except KeyError:
        raise HTTPException(status_code=404,
                            detail=f"Plugin {plugin_id!r} is not installed")
    return {'installed': False, 'plugin_id': plugin_id}


@router.post("/{plugin_id}/decode")
async def decode_with_plugin(plugin_id: str, body: Dict[str, Any], request: Request):
    """Decode a frame with one specific decoder.

    Exists so a plugin can be checked before trusting it on the live stream.
    """
    registry = _resolve(request)
    if registry is None:
        raise HTTPException(status_code=503, detail="Plugin registry is not configured")
    decoder = registry._manager.get_decoder(plugin_id)
    if decoder is None:
        raise HTTPException(status_code=404,
                            detail=f"No decoder registered as {plugin_id!r}")
    raw = body.get('data', '')
    try:
        frame = bytes.fromhex(raw) if isinstance(raw, str) else bytes(raw)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400,
                            detail=f"'data' must be hex: {exc}") from exc
    try:
        decoded = decoder.decode(frame)
    except Exception as exc:                       # noqa: BLE001 - plugin code
        logger.exception("plugin %s raised while decoding", plugin_id)
        raise HTTPException(
            status_code=500,
            detail=f"Plugin {plugin_id!r} raised while decoding: {exc}") from exc
    return {'protocol_id': plugin_id, 'decoded': decoded}


def _source_root(request: Request) -> Optional[Path]:
    """Where a manifest's relative module paths resolve.

    A local manifest ships its plugin files beside it; a remote registry
    resolves against the install directory, where a download step would have
    placed them.
    """
    url = _manifest_for(request)
    if url and not str(url).startswith(('http://', 'https://')):
        return Path(url).parent
    return None
