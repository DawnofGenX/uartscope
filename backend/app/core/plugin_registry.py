"""Plugin marketplace: a registry of installable protocol decoders.

A plugin is third-party Python that will be called on live traffic. Nothing here
can make that safe -- the moment a decoder is registered, `auto_detect` runs its
`can_decode` against every frame that arrives. What this module can do is make
the risk explicit and keep it contained:

  * A manifest is parsed and validated before anything is fetched. An entry
    without an id, or naming a file that is not a plain filename, is rejected
    rather than skipped, so a broken registry fails loudly.
  * A downloaded module is imported, and exactly one class is required to be a
    real `ProtocolDecoder` instance. A module that raises on import, or that
    exposes no conforming class, is refused before it can reach the manager.
  * A plugin may not claim the id of a built-in. `uart_text` is the id every
    text frame is matched against; a plugin squatting on it would silently take
    over decoding for all text devices.
  * Installs are recorded in a state file and re-applied on startup, so
    "installed" means installed rather than being a flag on a list item.

The trust model is deliberately not hidden: installing a plugin is an explicit
user action on a file whose origin the UI shows. See `install_plugin` in
`desktop_app.py` for the confirmation copy.
"""
import importlib.util
import json
import logging
import shutil
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config import settings
from app.core.protocol_decoder import ProtocolDecoder

logger = logging.getLogger(__name__)

# Ids the built-ins own. A plugin may not take one of these.
BUILTIN_IDS = frozenset({
    'uart_text', 'modbus_rtu', 'i2c', 'spi', 'can', 'can_dbc',
})


class PluginInstallDisabled(Exception):
    """Raised when an install is attempted while installs are turned off.

    A dedicated type so the API route can map it to 403 and the desktop UI can
    tell the operator which setting to change, instead of every caller
    re-deriving that check from the config.
    """


def default_registry_path() -> Optional[Path]:
    """The bundled `registry/registry.json`, if this install has one.

    The registry lives at the repo root, one level above `backend/`, and is
    also bundled next to the packaged app. Returns None when neither is present
    so the caller can report "no registry configured" instead of a bare 500.
    """
    here = Path(__file__).resolve()
    # backend/app/core/plugin_registry.py -> repo root
    for base in here.parents:
        candidate = base / "registry" / "registry.json"
        if candidate.is_file():
            return candidate
    return None


class PluginValidationError(Exception):
    """A candidate plugin is not safe to register.

    Raised before the decoder reaches the manager, so a bad plugin cannot break
    decoding for the built-ins.
    """


@dataclass
class InstalledPlugin:
    plugin_id: str
    name: str
    version: str
    author: str = ''
    description: str = ''
    module: str = ''
    cls: str = ''
    tags: List[str] = field(default_factory=list)
    source: str = ''

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class PluginRegistry:
    """Fetches a manifest, installs plugins, and remembers what is installed.

    `source_root` is the directory a manifest's relative module paths resolve
    against -- a local registry directory when serving our own manifest, or a
    cache directory when the manifest came off the network.
    """

    def __init__(self, manager=None, install_dir: Optional[Path] = None,
                 state_file: Optional[Path] = None,
                 builtin_ids=frozenset(BUILTIN_IDS)):
        # Imported here rather than at module scope: protocol_decoder owns the
        # ProtocolDecoder base, and a module-level import of the singleton would
        # make the test's fresh manager impossible to wire in.
        if manager is None:
            from app.core.protocol_decoder import protocol_manager
            manager = protocol_manager
        self._manager = manager
        self._install_dir = Path(install_dir) if install_dir else Path('plugins')
        self._state_file = Path(state_file) if state_file else Path('plugins/installed.json')
        self._builtin_ids = frozenset(builtin_ids)
        self._catalog: List[Dict[str, Any]] = []
        self._installed: Dict[str, InstalledPlugin] = {}
        # Read the recorded installs up front. Without this a new registry
        # reports nothing installed even though the state file says otherwise --
        # "installed" would only mean installed for the lifetime of one process,
        # and the Marketplace screen would show an empty Installed list after a
        # restart until something else happened to call restore_installed().
        # Decoders are NOT registered here: registering needs the file to be
        # present and valid, which is restore_installed()'s job at startup.
        for record in self._load_state():
            self._installed[record.plugin_id] = record

    # ── Manifest ──────────────────────────────────────────────────────────
    def fetch_manifest(self, manifest_path: Path) -> List[Dict[str, Any]]:
        """Read and validate a registry manifest.

        Raises on anything malformed. A registry that silently yields an empty
        list is indistinguishable from a marketplace with nothing in it, which
        is how the mock stayed invisible.
        """
        path = Path(manifest_path)
        if not path.exists():
            raise FileNotFoundError(f"registry manifest not found: {path}")
        try:
            raw = json.loads(path.read_text(encoding='utf-8'))
        except json.JSONDecodeError as exc:
            raise ValueError(f"registry manifest is not valid JSON: {exc}") from exc

        plugins = raw.get('plugins') if isinstance(raw, dict) else raw
        if not isinstance(plugins, list):
            raise ValueError("registry manifest has no 'plugins' list")

        seen = set()
        for entry in plugins:
            if not isinstance(entry, dict):
                raise ValueError(f"registry entry is not an object: {entry!r}")
            pid = entry.get('id')
            if not pid or not isinstance(pid, str):
                raise ValueError(f"registry entry has no usable id: {entry!r}")
            if pid in seen:
                raise ValueError(f"registry lists {pid!r} twice")
            seen.add(pid)
            # A module path must be a bare filename. Anything else is a
            # traversal attempt and is refused outright.
            module = entry.get('module', '')
            if module and (Path(module).is_absolute() or '..' in Path(module).parts):
                raise ValueError(f"registry entry {pid!r} has an unsafe module path")
        self._catalog = plugins
        return plugins

    def list_available(self) -> List[Dict[str, Any]]:
        """Catalog entries annotated with what is installed and what is built in."""
        out = []
        for entry in self._catalog:
            pid = entry.get('id', '')
            out.append({
                **entry,
                'installed': pid in self._installed,
                'builtin': pid in self._builtin_ids,
            })
        return out

    def get_entry(self, plugin_id: str) -> Dict[str, Any]:
        for entry in self._catalog:
            if entry.get('id') == plugin_id:
                return entry
        raise KeyError(plugin_id)

    # ── Validation ─────────────────────────────────────────────────────────
    @staticmethod
    def validate_source(source: str, origin: str = '<string>') -> ProtocolDecoder:
        """Compile `source`, import it, and require one conforming decoder.

        The module is executed in its own namespace, which is inherent to what
        a plugin is. Everything that can be checked without trusting it is
        checked here, and the caller is expected to have confirmed the source
        with the user first.
        """
        namespace: Dict[str, Any] = {'__name__': 'uartscope_plugin', '__file__': origin}
        try:
            code = compile(source, origin, 'exec')
            exec(code, namespace)                     # noqa: S102 - inherent to plugins
        except Exception as exc:
            raise PluginValidationError(
                f"plugin raised while loading ({type(exc).__name__}: {exc})") from exc

        candidates = [
            obj for obj in namespace.values()
            if isinstance(obj, type) and issubclass(obj, ProtocolDecoder)
            and obj is not ProtocolDecoder
            and not getattr(obj, '__abstractmethods__', None)
        ]
        if not candidates:
            raise PluginValidationError(
                'plugin exposes no concrete ProtocolDecoder subclass')
        if len(candidates) > 1:
            names = sorted(c.__name__ for c in candidates)
            raise PluginValidationError(
                f'plugin exposes several decoders ({", ".join(names)}); expected one')
        try:
            return candidates[0]()
        except Exception as exc:
            raise PluginValidationError(
                f'decoder failed to construct ({type(exc).__name__}: {exc})') from exc

    @staticmethod
    def validate_file(path: Path) -> ProtocolDecoder:
        path = Path(path)
        if not path.exists():
            raise PluginValidationError(f"plugin file not found: {path}")
        try:
            source = path.read_text(encoding='utf-8')
        except OSError as exc:
            raise PluginValidationError(f"plugin file unreadable: {exc}") from exc
        return PluginRegistry.validate_source(source, origin=str(path))

    def _check_id(self, plugin_id: str, decoder: ProtocolDecoder) -> None:
        """Refuse an id that would collide with a built-in or another plugin."""
        if plugin_id in self._builtin_ids:
            raise ValueError(
                f"{plugin_id!r} is a built-in protocol id and cannot be replaced")
        actual = decoder.protocol_id
        if actual != plugin_id:
            raise PluginValidationError(
                f"plugin declares protocol_id {actual!r} but the registry "
                f"lists it as {plugin_id!r}")

    # ── Install / uninstall ────────────────────────────────────────────────
    async def install(self, plugin_id: str, source_root: Optional[Path] = None,
                      author: str = '', source: str = '') -> InstalledPlugin:
        """Install a plugin and register its decoder.

        `source_root` is where a manifest's relative module paths resolve. When
        it is omitted the file is expected to already be in `install_dir`, which
        is the shape a network install ends in once the download has been
        written there. Pointing `source_root` at a staging directory copies the
        file into `install_dir` first.

        Order matters: validate first, refuse a colliding id second, write to
        disk third, register last. A failure at any step leaves the manager in
        the state it was in before.

        The `plugin_install_enabled` gate lives HERE, not only in the API
        route, because this method is the choke point every caller goes
        through -- and the desktop app calls it directly (desktop_app.py's
        Marketplace screen) without ever touching HTTP. A gate on the route
        alone protected the API while leaving the primary shipped product,
        the PyInstaller Windows executable, able to exec third-party Python
        with the setting off. Raising a dedicated exception type lets the
        route map it to 403 and lets the UI say something useful, instead of
        both surfaces having to re-check the flag and one of them eventually
        forgetting.
        """
        if not settings.plugin_install_enabled:
            raise PluginInstallDisabled(
                "Plugin installation is disabled. Set "
                "UARTSCOPE_PLUGIN_INSTALL_ENABLED=true to enable it."
            )

        entry = self.get_entry(plugin_id)
        module_name = entry.get('module') or f"{plugin_id}.py"
        origin_dir = Path(source_root) if source_root else self._install_dir
        candidate = origin_dir / module_name
        decoder = self.validate_file(candidate)
        self._check_id(plugin_id, decoder)

        self._install_dir.mkdir(parents=True, exist_ok=True)
        target = self._install_dir / module_name
        if target.resolve() != candidate.resolve():
            shutil.copyfile(candidate, target)

        record = InstalledPlugin(
            plugin_id=plugin_id,
            name=entry.get('name', plugin_id),
            version=entry.get('version', '0.0.0'),
            author=author or entry.get('author', ''),
            description=entry.get('description', ''),
            module=module_name,
            cls=type(decoder).__name__,
            tags=list(entry.get('tags') or []),
            source=source or str(candidate),
        )
        self._installed[plugin_id] = record
        self._manager.register(decoder)
        self._save_state()
        logger.info("installed plugin %s (%s) from %s",
                    plugin_id, record.version, candidate)
        return record

    async def uninstall(self, plugin_id: str) -> None:
        record = self._installed.get(plugin_id)
        if record is None:
            raise KeyError(plugin_id)
        self._manager.unregister(plugin_id)
        self._installed.pop(plugin_id, None)
        target = self._install_dir / record.module
        try:
            target.unlink()
        except OSError:
            # The file may already be gone; the registry state is what matters.
            logger.debug("could not remove %s", target)
        self._save_state()
        logger.info("uninstalled plugin %s", plugin_id)

    def list_installed(self) -> List[InstalledPlugin]:
        return [self._installed[k] for k in sorted(self._installed)]

    # ── Persistence ────────────────────────────────────────────────────────
    def _save_state(self) -> None:
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        payload = {'plugins': [p.to_dict() for p in self.list_installed()]}
        self._state_file.write_text(json.dumps(payload, indent=2), encoding='utf-8')

    def _load_state(self) -> List[InstalledPlugin]:
        if not self._state_file.exists():
            return []
        try:
            raw = json.loads(self._state_file.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("plugin state unreadable (%s); starting clean", exc)
            return []
        records = []
        for entry in raw.get('plugins', []):
            try:
                records.append(InstalledPlugin(**entry))
            except TypeError as exc:
                logger.warning("ignoring malformed plugin state entry: %s", exc)
        return records

    async def restore_installed(self) -> List[InstalledPlugin]:
        """Re-register everything recorded as installed.

        A plugin that has been deleted from disk, or has stopped being valid,
        is dropped from the state rather than blocking startup. The decode path
        must not depend on a third-party file remaining present.
        """
        restored: List[InstalledPlugin] = []
        for record in self._load_state():
            path = self._install_dir / record.module
            if not path.exists():
                logger.warning("installed plugin %s is missing from %s; dropping",
                               record.plugin_id, path)
                continue
            try:
                decoder = self.validate_file(path)
                self._check_id(record.plugin_id, decoder)
            except (PluginValidationError, ValueError) as exc:
                logger.warning("installed plugin %s no longer valid (%s); dropping",
                               record.plugin_id, exc)
                continue
            self._installed[record.plugin_id] = record
            self._manager.register(decoder)
            restored.append(record)
        if restored:
            self._save_state()
        return restored
