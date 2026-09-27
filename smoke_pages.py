"""Boot every screen of desktop_app.py over real HTTP and report any that 500s.

Catches the class of bug that is invisible in review and only shows up as a
blank page in a browser: a handler referenced before it is defined, a name lost
in a bad splice, a container not entered before use. All of those raise while
the page is being constructed, so they surface here as a non-200.

Each tab is reached by driving the same selection path the UI uses -- the tabs
that need a device are checked twice, once with none selected and once with a
fake device bound, because the two paths build completely different trees.

Two modes:

    .venv-v2/bin/python smoke_pages.py              # probe a running app
    .venv-v2/bin/python smoke_pages.py --boot       # start the app, probe, stop

--boot is what CI uses. Without it the script only tests whatever happens to be
listening, which in CI is nothing.
"""
import argparse
import os
import subprocess
import sys
import time

from urllib.error import HTTPError, URLError
from urllib.request import urlopen

_P = argparse.ArgumentParser(add_help=True)
_P.add_argument('base_url', nargs='?', default='http://127.0.0.1:3000')
_P.add_argument('--boot', action='store_true',
                help='start desktop_app.py, wait for it, then probe it')
_P.add_argument('--wait', type=int, default=60,
                help='seconds to wait for the app to come up (default 60)')
_ARGS = _P.parse_args()

BASE = _ARGS.base_url.rstrip('/')

# Tabs reachable by query param, and the device state each needs exercised.
TABS = [
    'devices', 'terminal', 'charts', 'performance', 'mqtt',
    'alerts', 'sessions', 'decoder', 'marketplace',
]

EXPECT_MARKERS = {
    # A page that renders 200 but is actually the error page is still a failure.
    'error_markers': ['Server error', 'NameError', 'Traceback',
                      'UnboundLocalError', 'has been deleted'],
}


def probe(path: str) -> tuple[int, str]:
    """Fetch a page. Uses urllib so the smoke test needs no dependency beyond
    the stdlib -- it has to run in whatever venv the app runs in."""
    try:
        with urlopen(f'{BASE}{path}', timeout=20) as r:
            return r.status, r.read().decode('utf-8', 'replace')
    except HTTPError as e:
        return e.code, e.read().decode('utf-8', 'replace')
    except (URLError, OSError) as e:
        return 0, f'{type(e).__name__}: {e}'


# Screens that build a completely different tree once a device is bound. These
# are the ones that were broken in v1: Terminal and Decoder each raised
# UnboundLocalError during construction, and the device-free path never touched
# the code that raised.
# 'session-detail' is not a rail tab -- it is reached by choosing a session --
# so it is listed here rather than derived from the nav items. It was the screen
# with the most missing functionality, and the one hardest to reach in a test.
DEVICE_SCOPED = ['terminal', 'charts', 'sessions', 'session-detail']


def wait_for_app(timeout: int) -> bool:
    """Poll until the app answers, or give up. Returns False on timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        code, _ = probe('/')
        if code == 200:
            return True
        time.sleep(1.0)
    return False


def main() -> int:
    server = None
    if not _ARGS.boot:
        # Probing with nothing running produces 13 identical "http=0" failures
        # that read like a product bug. CI hit exactly that: the workflow called
        # this script with --wait but no --boot, so it tested an empty port.
        # Say so up front instead of reporting a wall of connection errors.
        code, body = probe('/')
        if code == 0:
            print('Nothing is listening at ' + BASE + '.')
            print('Start the app first, or pass --boot to have this script start it.')
            return 2
    if _ARGS.boot:
        server = subprocess.Popen(
            [sys.executable, 'desktop_app.py'],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        print(f'starting desktop_app.py (pid {server.pid}), '
              f'waiting up to {_ARGS.wait}s...')
        if not wait_for_app(_ARGS.wait):
            print('FAIL  the app never came up')
            if server.poll() is None:
                server.terminate()
            output = server.stdout.read().decode('utf-8', 'replace') \
                if server.stdout else ''
            print(output[-2000:])
            return 1
        print('app is up\n')

    try:
        return _probe_all()
    finally:
        if server is not None and server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=10)
            except Exception:
                server.kill()


def _probe_all() -> int:

    failures = []
    checks = [(t, False) for t in TABS] + [(t, True) for t in DEVICE_SCOPED]
    for tab, with_device in checks:
        path = f'/smoke/{tab}' + ('?with_device=true' if with_device else '')
        code, body = probe(path)
        bad = [m for m in EXPECT_MARKERS['error_markers'] if m in body]
        label = f'{tab}[dev]' if with_device else tab
        if code != 200 or bad:
            failures.append((label, code, bad))
            print(f'  FAIL  {label:14s} http={code} markers={bad}')
        else:
            print(f'  OK    {label:14s} http=200 {len(body):>7,d} bytes')

    if failures:
        print(f'\n{len(failures)} screen(s) failed')
        return 1
    print(f'\nall {len(checks)} screen builds served cleanly')
    return 0


if __name__ == '__main__':
    sys.exit(main())
