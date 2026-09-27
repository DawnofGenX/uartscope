"""Catch reads of dict keys that no producer in the codebase ever writes.

This is not lint. It is a targeted hunt for one specific failure mode that has
already bitten this project three times, in three different screens, and each
time the symptom was a silently wrong value rather than an error:

  * session.get('session_id')   -- every session dict has 'id'; nothing writes
                                   'session_id', so every export downloaded as
                                   session_unknown.json
  * session.get('metrics_latest') -- no code path writes this key, so the
                                   "golden" baseline was always empty and the
                                   diff always passed
  * metric.unit                 -- existed but was never populated on the
                                   KEY:VALUE path, so unit-aware UI had nothing
                                   to be aware of

A missing key never raises. `.get(k, default)` returns the default, so the bug is
invisible until someone notices the output is wrong. The only defence is to
compare what the UI reads against what the producers actually write.

Usage:
    .venv-v2/bin/python check_dict_keys.py
Exit code 1 if any read key is unwritten.
"""
import ast
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TARGETS = [
    ROOT / 'desktop_app.py',
    ROOT / 'backend' / 'app' / 'core' / 'session_recorder.py',
    ROOT / 'backend' / 'app' / 'core' / 'telemetry_engine.py',
    ROOT / 'backend' / 'app' / 'core' / 'alert_engine.py',
    ROOT / 'backend' / 'app' / 'core' / 'device_manager.py',
]

# Keys the UI reads off session dicts. This is the list that matters: it is the
# contract between session_recorder's producers and the Sessions screens.
# 'metrics_latest' and 'session_name' were here while the bug was live, and are
# kept as a tripwire: neither is ever written, so any future code that reads one
# is reintroducing the same class of bug.
SESSION_KEYS_READ = {
    'id', 'name', 'device_id', 'started_at', 'ended_at', 'status',
    'packet_count', 'metric_count', 'event_count',
    'metrics_latest', 'session_id', 'session_name',
}

# The keys the Sessions screens must not read, once fixed. Kept separate so the
# checker can report "regression" rather than a permanently red build.
RETIRED_KEYS = {'metrics_latest', 'session_id', 'session_name'}


def string_keys_written(path: Path) -> set[str]:
    """Keys this file writes into a dict literal, e.g. {"name": ...}."""
    try:
        tree = ast.parse(path.read_text(encoding='utf-8', errors='ignore'))
    except SyntaxError as e:
        print(f'  (skip {path.name}: {e})')
        return set()
    keys = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for k in node.keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    keys.add(k.value)
    return keys


def main() -> int:
    producers = {}
    for t in TARGETS:
        if t.exists():
            producers[t.name] = string_keys_written(t)

    # Pooling keys across every producer is too coarse: alert_engine legitimately
    # writes "session_id" on an ALERT dict, which has nothing to do with the
    # session dicts the Sessions screens read. Keys are therefore attributed to
    # their file, and a session key must be present in session_recorder itself.
    written_all = set()
    for keys in producers.values():
        written_all |= keys
    session_written = producers.get('session_recorder.py', set())
    written = written_all

    print('keys written by session_recorder (the producer the Sessions '
          'screens read):')
    print('  ' + ' '.join(sorted(session_written)))
    print()

    # A retired key is only a failure if the UI actually reads it again. Reading
    # it from a comment or a test fixture is harmless, so check the source.
    ui_src = (ROOT / 'desktop_app.py').read_text(encoding='utf-8')
    code_only = '\n'.join(
        l for l in ui_src.splitlines() if not l.strip().startswith('#'))

    regressions = [
        k for k in sorted(RETIRED_KEYS)
        if k in session_written
        or f"'{k}'" in code_only or f'"{k}"' in code_only]

    # A live session key must be written by session_recorder specifically.
    live_unwritten = sorted(
        (SESSION_KEYS_READ - RETIRED_KEYS) - session_written)

    ok = True
    if regressions:
        ok = False
        print('REGRESSION: the UI reads a key no producer ever writes:')
        for k in regressions:
            print(f'  {k}')
        print()

    if live_unwritten:
        ok = False
        print('READ BUT NEVER WRITTEN:')
        for k in live_unwritten:
            print(f'  {k}')
        print()

    if not ok:
        print('A .get() on any of these returns its default forever, silently.')
        return 1

    print('OK: every session key the UI reads is written by a producer.')
    print(f'  retired tripwires clean: {sorted(RETIRED_KEYS)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
