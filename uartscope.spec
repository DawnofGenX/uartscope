# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['run_desktop.py'],
    pathex=[],
    binaries=[],
    datas=[('backend', 'app'), ('desktop_app.py', '.'), ('launch.py', '.')],
    hiddenimports=['uvicorn', 'uvicorn.logging', 'uvicorn.loops', 'uvicorn.loops.auto', 'uvicorn.protocols', 'uvicorn.protocols.http', 'uvicorn.protocols.http.auto', 'uvicorn.protocols.websockets', 'uvicorn.protocols.websockets.auto', 'uvicorn.lifespan', 'uvicorn.lifespan.on', 'nicegui', 'nicegui.ui', 'nicegui.page', 'nicegui.context', 'nicegui.events', 'nicegui.settings', 'starlette', 'starlette.applications', 'starlette.middleware', 'starlette.requests', 'starlette.responses', 'starlette.routing', 'starlette.staticfiles', 'starlette.websockets', 'fastapi', 'fastapi.middleware', 'fastapi.staticfiles', 'pydantic', 'pydantic.fields', 'pydantic.main', 'sqlalchemy', 'sqlalchemy.ext.asyncio', 'sqlalchemy.pool', 'aiosqlite', 'serial', 'serial.tools', 'serial.tools.list_ports', 'aiofiles'],
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
