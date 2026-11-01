"""A frozen build must serve, not respawn itself.

The shipped Windows .exe re-ran its own launcher: `launch.main()` did
`Popen([sys.executable, "-m", "uvicorn", ...])`, and in a PyInstaller build
`sys.executable` is the executable itself, so every child started the launcher
again. One click produced thousands of processes and no server — and no test
noticed, because the artifact was never executed.

These tests pin the bootstrap on the axis that broke:
  * when frozen, nothing may spawn a subprocess (the recursion, not a symptom);
  * the packaged path serves the API in a thread of the same process, and that
    thread really answers `/api/health`;
  * `launch.main()` under frozen delegates instead of spawning;
  * the PyInstaller recipe the release uses has the entry point that does this,
    and bundles the files the entry point reads — the CI build step names the
    spec, so a spec that drifts from the code is a shipped bug.

The Windows binary itself is exercised by the `build-windows` CI job, which now
starts it and probes :3000 and :8080. This file is what can run on Linux.

Run:  python -m pytest tests/test_packaged_entry.py -v
"""
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
import importlib.util
import re

import pytest

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(ROOT))

import run_desktop  # noqa: E402
import launch  # noqa: E402


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


@pytest.fixture
def frozen(monkeypatch):
    """Pretend this interpreter is a PyInstaller bundle rooted at the repo."""
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, '_MEIPASS', str(ROOT), raising=False)
    monkeypatch.setattr(run_desktop, 'base_path', lambda: str(ROOT))
    yield
    # main() chdirs into the bundle root; put the test's cwd back.
    monkeypatch.undo()


def test_frozen_main_spawns_no_subprocess(frozen, monkeypatch):
    """The fork bomb, stated as a rule: frozen means no Popen, ever."""
    spawned = []
    monkeypatch.setattr(subprocess, 'Popen',
                        lambda *a, **k: spawned.append(a) or pytest.fail('spawned a process'))
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: spawned.append(a))
    monkeypatch.setattr(subprocess, 'check_call', lambda *a, **k: spawned.append(a))

    started = {}
    monkeypatch.setattr(run_desktop, 'start_api_thread',
                        lambda **kw: started.setdefault('api', kw))
    shown = {}
    monkeypatch.setattr(run_desktop, 'run_desktop_ui',
                        lambda path: shown.setdefault('ui', path))

    before = Path.cwd()
    try:
        run_desktop.main()
    finally:
        import os
        os.chdir(before)

    assert spawned == [], f'frozen launcher spawned {spawned}'
    assert 'api' in started, 'the API server was not started'
    assert shown.get('ui') == str(ROOT), 'the UI entry path is wrong'


def test_launch_main_delegates_when_frozen(frozen, monkeypatch):
    """`pyinstaller launch.py` must not be a fork bomb either."""
    monkeypatch.setattr(run_desktop, 'main', lambda: setattr(run_desktop, '_delegated', True))
    monkeypatch.setattr(run_desktop, '_delegated', False, raising=False)
    monkeypatch.setattr(subprocess, 'Popen',
                        lambda *a, **k: pytest.fail('launch.main spawned a process while frozen'))

    launch.main()
    assert run_desktop._delegated is True, 'launch.main() did not hand off to the packaged entry'


def test_api_thread_really_serves_health():
    """The threaded server is not assumed to work: it answers a real request."""
    port = _free_port()
    server = run_desktop.start_api_thread(host='127.0.0.1', port=port)
    assert server is not None
    url = f'http://127.0.0.1:{port}/api/health'
    body = None
    try:
        for _ in range(100):
            try:
                with urllib.request.urlopen(url, timeout=2) as response:
                    assert response.status == 200
                    body = response.read().decode()
                    break
            except (urllib.error.URLError, ConnectionError, OSError):
                time.sleep(0.1)
        assert body is not None, f'{url} never answered'
        assert '"status":"healthy"' in body.replace(' ', '')
    finally:
        server.should_exit = True


def test_a_busy_api_port_does_not_kill_the_app(caplog):
    """8080 is llama.cpp's default too; the UI must still start.

    This is not hypothetical: on a machine running `llama-server --port 8080`,
    uvicorn raised after running the app lifespan, which shut down the shared
    singletons ("MQTT manager shut down") while the UI kept serving. The port is
    checked first now, and the fallback is logged.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as taken:
        taken.bind(('127.0.0.1', 0))
        taken.listen(1)
        busy_port = taken.getsockname()[1]
        assert run_desktop.port_is_free('127.0.0.1', busy_port) is False
        with caplog.at_level('WARNING', logger='run_desktop'):
            server = run_desktop.start_api_thread(host='127.0.0.1', port=busy_port)
    assert server is None, 'uvicorn was started on a port someone else owns'
    assert any('already in use' in record.message for record in caplog.records), \
        [r.message for r in caplog.records]


def test_api_port_env_override(monkeypatch):
    """UARTSCOPE_API_PORT moves the API off a taken port."""
    monkeypatch.setenv('UARTSCOPE_API_PORT', '18080')
    assert run_desktop.api_port() == 18080
    monkeypatch.setenv('UARTSCOPE_API_PORT', 'not-a-port')
    assert run_desktop.api_port() == run_desktop.DEFAULT_API_PORT
    monkeypatch.delenv('UARTSCOPE_API_PORT')
    assert run_desktop.api_port() == run_desktop.DEFAULT_API_PORT


def test_the_spec_ci_builds_names_the_packaged_entry_point():
    """The recipe and the CI step are checked against each other.

    CI used to run `pyinstaller launch.py`, ignoring this spec and shipping a
    bundle with no desktop_app.py. Reading both files here makes that
    divergence a test failure instead of a release note.
    """
    spec = (ROOT / 'uartscope.spec').read_text(encoding='utf-8')
    workflow = (ROOT / '.github' / 'workflows' / 'ci.yml').read_text(encoding='utf-8')

    assert "['run_desktop.py']" in spec, 'the spec no longer builds run_desktop.py'
    assert 'pyinstaller --clean uartscope.spec' in workflow, \
        'CI does not build the spec, so the spec is dead config again'
    assert 'pyinstaller --onefile' not in workflow, \
        'CI is building a .py and ignoring the spec'

    # Files the entry point reads or imports from the bundle root.
    for bundled in ('desktop_app.py', 'uartscope_theme.py', 'uartscope_follow.py',
                    'registry', 'hardware/examples'):
        assert bundled in spec, f'{bundled} is not bundled, so the packaged app cannot use it'


def test_ci_runs_the_exe_it_builds():
    """A build that is never executed is not verified."""
    workflow = (ROOT / '.github' / 'workflows' / 'ci.yml').read_text(encoding='utf-8')
    assert 'The .exe actually serves' in workflow
    assert '127.0.0.1:3000' in workflow and '127.0.0.1:8080/api/health' in workflow
    assert 'launcher forked' in workflow, 'the fork guard was removed'


def test_every_hidden_import_in_the_spec_resolves():
    """A stale name here is a Windows-only build failure.

    `nicegui.settings` was renamed in NiceGUI 3.x, and PyInstaller reports a
    hidden import it cannot find as an `ERROR:` line while still exiting 0 — so
    the only place the mistake surfaced was a full windows-latest build. Checking
    the names against the installed packages turns that into a one-second test.
    """
    spec = (ROOT / 'uartscope.spec').read_text(encoding='utf-8')
    block = spec.split('hiddenimports = collect_submodules', 1)[1].split(']', 1)[0]
    names = set(re.findall(r"'([A-Za-z0-9_.]+)'", block)) - {'app'}
    assert len(names) > 20, f'expected the spec\'s explicit hidden imports, parsed {len(names)}'
    missing = sorted(name for name in names if importlib.util.find_spec(name) is None)
    assert missing == [], f'the spec asks for modules that do not exist: {missing}'
