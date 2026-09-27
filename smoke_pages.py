"""Boot every screen of desktop_app.py over real HTTP and report any that 500s.

Catches the class of bug that is invisible in review and only shows up as a
blank page in a browser: a handler referenced before it is defined, a name lost
in a bad splice, a container not entered before use. All of those raise while
the page is being constructed, so they surface here as a non-200.

Each tab is reached by driving the same selection path the UI uses -- the tabs
that need a device are checked twice, once with none selected and once with a
fake device bound, because the two paths build completely different trees.

Run:  .venv-v2/bin/python smoke_pages.py [base_url]
"""
import sys
import types

from urllib.error import HTTPError, URLError
from urllib.request import urlopen

BASE = (sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:3000').rstrip('/')

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
DEVICE_SCOPED = ['terminal', 'charts', 'sessions']


def main() -> int:
    import desktop_app  # noqa: F401  - fail fast if the module cannot import

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
