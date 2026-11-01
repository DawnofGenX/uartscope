#!/usr/bin/env python3
"""UARTScope Pro — desktop entry point, for a packaged .exe and for dev.

A frozen build has no interpreter to spawn: `sys.executable` is this executable,
so the v1 launcher's `Popen([sys.executable, "-m", "uvicorn", ...])` re-ran the
launcher itself. Every child started the launcher again, which started two more.
Clicked once, it produced thousands of `uartscope.exe` processes and served
nothing — the released Windows binary had never worked, and nothing caught it
because no test ever executed the artifact.

Here the packaged path runs both servers **inside this process**:
  * the REST API (the real `app.main:app`) on :8080 in a daemon thread;
  * the NiceGUI desktop UI on :3000, by executing desktop_app.py with
    `__name__ == "__main__"` — the guard it already uses to decide whether to
    serve.
That is the same pair of ports the dev launcher serves, from one process.
"""
import os
import runpy
import sys
import threading


def base_path() -> str:
    """Where the bundled files live.

    PyInstaller extracts a onefile build to `sys._MEIPASS`; from source it is the
    directory this file sits in.
    """
    frozen_root = getattr(sys, '_MEIPASS', None)
    if frozen_root:
        return frozen_root
    return os.path.dirname(os.path.abspath(__file__))


def is_frozen() -> bool:
    return bool(getattr(sys, 'frozen', False))


def start_api_thread(host: str = '0.0.0.0', port: int = 8080):
    """Serve `app.main:app` on :8080 without leaving this process.

    uvicorn only installs signal handlers when it is the main thread
    (`Server.capture_signals` returns early otherwise), so running the server in
    a worker thread needs no handler juggling — it is the documented-safe case.

    Returns the `uvicorn.Server` so a caller can join or stop it (`should_exit`);
    the server runs in a daemon thread, so process exit does not wait for it.
    """
    import uvicorn
    from app.main import app as api_app

    config = uvicorn.Config(api_app, host=host, port=port, log_level='warning')
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, name='uartscope-api', daemon=True)
    thread.start()
    return server


def run_desktop_ui(path: str) -> None:
    """Execute desktop_app.py as `__main__` so its `ui.run(...)` block fires.

    Importing it would define the page and then return: the
    `if __name__ in {"__main__", "__mp_main__"}` guard at the bottom is where the
    server actually starts.
    """
    runpy.run_path(os.path.join(path, 'desktop_app.py'), run_name='__main__')


def main() -> None:
    path = base_path()

    if is_frozen():
        # The bundled package sits at the root of _MEIPASS; data files
        # (registry/, hardware/examples/) are resolved relative to cwd by some
        # screens, so the working directory moves with it.
        sys.path.insert(0, path)
        os.chdir(path)
        start_api_thread()
        run_desktop_ui(path)
        return

    # From source: keep the two-process dev launcher, which restarts the backend
    # cleanly on Ctrl+C. Imported here so this module stays importable by tests
    # without starting anything.
    from launch import main as dev_main
    dev_main()


if __name__ == '__main__':
    main()
