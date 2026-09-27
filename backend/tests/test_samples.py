"""Every sample in samples/payloads.json must actually decode as claimed.

A sample file that documents behaviour the code does not have is worse than no
sample file: it is a test case written by hand, which is precisely the thing
these samples exist to replace. So it is checked like one.

Each `expects` block is asserted against the real decoder and the real
telemetry parser. A sample whose hex does not match its line, or whose expected
protocol is not what auto-detect returns, fails here.

Run:  ../.venv-v2/bin/python tests/test_samples.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))

from app.core.protocol_decoder import protocol_manager  # noqa: E402
from app.core.telemetry_engine import telemetry_engine  # noqa: E402

SAMPLES = json.loads((ROOT / 'samples' / 'payloads.json').read_text())


def test_sample_hex_matches_line() -> None:
    """If a sample has both `line` and `hex`, the hex must BE the line."""
    problems = []
    for s in SAMPLES['samples']:
        if 'line' not in s or 'hex' not in s:
            continue
        expected = s['line'].encode('utf-8').hex().upper()
        if s['hex'].upper() != expected:
            problems.append(
                f"{s['name']}: hex {s['hex']} does not encode "
                f"line {s['line']!r} (expected {expected})")
    assert not problems, '\n'.join(problems)


def test_sample_detects_as_claimed() -> None:
    """Auto-detect must return the protocol the sample claims."""
    problems = []
    for s in SAMPLES['samples']:
        if 'expects' not in s or 'protocol' not in s['expects']:
            continue
        raw = bytes.fromhex(s['hex'])
        decoder = protocol_manager.auto_detect(raw)
        got = decoder.protocol_id if decoder else None
        if got != s['expects']['protocol']:
            problems.append(
                f"{s['name']}: claimed {s['expects']['protocol']}, got {got}")
    assert not problems, '\n'.join(problems)


def test_sample_decoded_fields_match() -> None:
    """Decoded fields the sample claims must be present with those values."""
    problems = []
    for s in SAMPLES['samples']:
        wants = s.get('expects', {})
        if not wants or 'protocol' not in wants:
            continue
        raw = bytes.fromhex(s['hex'])
        decoded = protocol_manager.decode(wants['protocol'], raw)
        for key, want in wants.items():
            # 'metrics' is asserted by test_sample_metrics_parse_with_units
            # against the telemetry parser, not here: the protocol decoder has
            # no notion of a metric. '_'-prefixed keys are commentary.
            if key.startswith('_') or key in ('protocol', 'metrics'):
                continue
            if key == 'values' and isinstance(want, dict):
                got = decoded.get('values', {})
                for k, v in want.items():
                    if got.get(k) != v:
                        problems.append(
                            f"{s['name']}: values[{k}] == {got.get(k)!r}, "
                            f"claimed {v!r}")
            elif key in decoded:
                # Compare case-insensitively for hex-valued fields: the
                # decoder lowercases CRC and raw hex, and '840a' vs '840A' is
                # not a behavioural difference.
                got, expect = str(decoded[key]), str(want)
                if key.endswith(('crc', 'hex')) or key in ('crc', 'raw_hex'):
                    if got.lower() != expect.lower():
                        problems.append(
                            f"{s['name']}: {key} == {got!r}, claimed {expect!r}")
                elif got != expect:
                    problems.append(
                        f"{s['name']}: {key} == {got!r}, claimed {expect!r}")
            else:
                problems.append(f"{s['name']}: {key} missing from decoded output")
    assert not problems, '\n'.join(problems)


def test_sample_metrics_parse_with_units() -> None:
    """Metric samples must parse, with the units the file claims."""
    import asyncio

    async def run():
        problems = []
        for s in SAMPLES['samples']:
            if 'line' not in s:
                continue
            want_metrics = s.get('expects', {}).get('metrics')
            if not want_metrics:
                continue
            parsed = await telemetry_engine.process_line(
                'sample-device', 'sample-session', s['line'])
            got = {m.name: m for m in (parsed.metrics if parsed else [])}
            for name, want in want_metrics.items():
                if name not in got:
                    problems.append(
                        f"{s['name']}: metric {name} not parsed from "
                        f"{s['line']!r}")
                    continue
                if abs(float(got[name].value) - float(want['value'])) > 1e-6:
                    problems.append(
                        f"{s['name']}: {name} == {got[name].value}, "
                        f"claimed {want['value']}")
                if got[name].unit != want['unit']:
                    problems.append(
                        f"{s['name']}: {name} unit == {got[name].unit!r}, "
                        f"claimed {want['unit']!r}")
        return problems

    problems = asyncio.run(run())
    assert not problems, '\n'.join(problems)


def test_alert_rule_samples_are_valid() -> None:
    """Alert rule examples must name a condition the engine understands.

    Every symbol here was a no-op before 2.0.0. If a future change breaks that
    mapping again, these fail.
    """
    from app.core.alert_engine import AlertRule

    problems = []
    for r in SAMPLES.get('alert_rule_examples', []):
        rule = r.get('rule')
        if not rule:
            continue
        built = AlertRule(id='s', name='s', **rule)
        # A condition the engine cannot evaluate is detected by feeding it a
        # value that must trip the rule.
        threshold = float(rule['threshold'])
        trip = {
            '>': threshold + 1, '<': threshold - 1, '>=': threshold,
            '<=': threshold, '==': threshold,
        }.get(rule['condition'])
        if trip is None:
            problems.append(
                f"alert example uses condition {rule['condition']!r}, which "
                f"the samples do not exercise")
            continue
        if not built.check(trip):
            problems.append(
                f"alert example {rule['metric_name']} {rule['condition']} "
                f"{threshold} did not fire on {trip}")
    assert not problems, '\n'.join(problems)


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
