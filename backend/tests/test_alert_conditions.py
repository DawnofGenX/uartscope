"""Alert rule conditions.

This is not a nice-to-have. The UI's condition picker offers `>`, `<`, `>=`,
`<=` and `==`, while AlertRule.check() only ever compared against the internal
names `gt`, `lt`, `gte`, `lte`, `eq`. Every symbol fell through every branch and
returned False, so **no alert rule a user could create had ever fired** -- and
the rule looked perfectly configured while doing nothing.

These tests exist so that cannot regress. They assert the symbols the product
actually emits, not just the internal names.

Run:  ../.venv-v2/bin/python tests/test_alert_conditions.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.alert_engine import AlertRule  # noqa: E402


def rule(cond, threshold=80.0, **kw):
    return AlertRule(id='t', name='t', metric_name='TEMP',
                     condition=cond, threshold=threshold, **kw)


# The exact condition list the UI offers, with the behaviour each must have.
UI_CONDITIONS = [
    # (symbol,      threshold, value, should_trigger)
    ('>',          80.0,  95.0, True),
    ('>',          80.0,  70.0, False),
    ('<',          80.0,  70.0, True),
    ('<',          80.0,  95.0, False),
    ('>=',         80.0,  80.0, True),   # boundary is inclusive
    ('<=',         80.0,  80.0, True),   # boundary is inclusive
    ('>=',         80.0,  79.9, False),
    ('<=',         80.0,  80.1, False),
    ('==',         80.0,  80.0, True),
    ('==',         80.0,  80.5, False),
]


def test_every_ui_condition_fires() -> None:
    """The whole point: every condition the picker offers must do something."""
    for cond, thr, value, expected in UI_CONDITIONS:
        r = rule(cond, thr)
        got = r.check(value)
        assert got == expected, (
            f'condition {cond!r} with value {value} against {thr}: '
            f'expected {expected}, got {got}')


def test_internal_names_still_work() -> None:
    """Existing callers using gt/lt must not break."""
    assert rule('gt').check(95.0) is True
    assert rule('lt').check(70.0) is True
    assert rule('gte').check(80.0) is True
    assert rule('lte').check(80.0) is True


def test_unknown_condition_does_not_fire_silently() -> None:
    """A typo must not produce a rule that looks configured but never fires."""
    r = rule('approximately-greater-than')
    assert r.check(999.0) is False


def test_disabled_rule_never_fires() -> None:
    r = rule('>')
    r.enabled = False
    assert r.check(1000.0) is False


def test_cooldown_suppresses_repeat() -> None:
    r = rule('>', cooldown=60)
    assert r.check(95.0) is True
    assert r.check(95.0) is False, 'second hit inside cooldown must be suppressed'
    assert r.trigger_count == 1


def test_trigger_count_increments() -> None:
    """v1 never surfaced this, so a noisy rule looked identical to a quiet one."""
    r = rule('>', cooldown=0)
    for _ in range(3):
        r.check(95.0)
    assert r.trigger_count == 3, f'expected 3, got {r.trigger_count}'


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    failed = 0
    for t in tests:
        try:
            t()
            print(f'  PASS  {t.__name__}')
        except AssertionError as e:
            failed += 1
            print(f'  FAIL  {t.__name__}: {e}')
    print(f'\n{len(tests) - failed}/{len(tests)} passed')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
