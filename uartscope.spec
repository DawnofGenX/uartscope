# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller recipe for the Windows build — the one the release workflow uses.

This file used to be dead config: CI ran
`pyinstaller --onefile --name uartscope --clean launch.py`, which ignores a spec
entirely. The result was a bundle containing launch.py and nothing else — no
desktop_app.py, no backend, no registry — and launch.py re-ran the launcher from
inside itself, so the released .exe spawned thousands of copies of itself and
never served a page.

Two things keep that from recurring:
  * `backend` is on `pathex`, so the real `app` package is *analyzed and frozen
    as code* rather than copied as data, and `collect_submodules` picks up every
    route module (a data copy breaks the moment one module imports a sibling);
  * the entry point is `run_desktop.py`, which serves the API and the UI in one
    process. CI also runs the built .exe and probes both ports, so a binary that
    does not start cannot be attached to a release.
"""
import os
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# Make `app` importable at build time so collect_submodules can walk it: the
# package lives in backend/, not at the repo root.
sys.path.insert(0, os.path.join(SPECPATH, 'backend'))

datas = [
    # Executed (not imported) by run_desktop.py with __name__ == '__main__', so
    # PyInstaller's import analysis never sees it: it has to ship as data.
    ('desktop_app.py', '.'),
    ('launch.py', '.'),
    ('run_desktop.py', '.'),
    # Imported by desktop_app.py from the bundle root.
    ('uartscope_theme.py', '.'),
    ('uartscope_follow.py', '.'),
    # Read from disk at runtime: the marketplace manifest, and the firmware
    # examples the Firmware screen lists.
    ('registry', 'registry'),
    ('hardware/examples', 'hardware/examples'),
]

# NiceGUI ships its own JS/CSS assets; without them the UI answers 200 and then
# fails to render.
datas += collect_data_files('nicegui')

hiddenimports = collect_submodules('app') + [
    'uvicorn', 'uvicorn.logging', 'uvicorn.loops', 'uvicorn.loops.auto',
    'uvicorn.protocols', 'uvicorn.protocols.http', 'uvicorn.protocols.http.auto',
    'uvicorn.protocols.websockets', 'uvicorn.protocols.websockets.auto',
    'uvicorn.lifespan', 'uvicorn.lifespan.on',
    'nicegui', 'nicegui.ui', 'nicegui.page', 'nicegui.context', 'nicegui.events',
    'nicegui.defaults',
    'starlette', 'starlette.applications', 'starlette.middleware',
    'starlette.requests', 'starlette.responses', 'starlette.routing',
    'starlette.staticfiles', 'starlette.websockets',
    'fastapi', 'fastapi.middleware', 'fastapi.staticfiles',
    'pydantic', 'pydantic.fields', 'pydantic.main',
    'sqlalchemy', 'sqlalchemy.ext.asyncio', 'sqlalchemy.pool', 'aiosqlite',
    'serial', 'serial.tools', 'serial.tools.list_ports', 'aiofiles',
]

a = Analysis(
    ['run_desktop.py'],
    pathex=[os.path.join(SPECPATH, 'backend')],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='uartscope',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
