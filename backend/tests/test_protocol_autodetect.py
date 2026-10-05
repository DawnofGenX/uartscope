"""Protocol auto-detection must not hand text to a binary decoder.

UARTTextDecoder.can_decode() required a trailing newline:

    if any(c.isalpha() for c in text) and text.strip().endswith("\\n"):

So "hello" and "TEMP:23.4" -- the two things a serial user actually pastes into
this screen -- scored 0.0, while I2CDecoder scored 0.6 on length alone and won.
Decoding plain ASCII as an I2C transaction is nonsense: it reports an address
and a read/write direction that the bytes do not contain.

These tests assert the detection outcome, not the score, because the score is
an implementation detail and the outcome is the contract.

Run:  .venv/bin/python tests/test_protocol_autodetect.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.protocol_decoder import protocol_manager  # noqa: E402

CASES = [
    # (payload,            expected protocol,  why)
    ('hello',             'uart_text', 'plain ASCII, no newline'),
    ('TEMP:23.4',         'uart_text', 'KEY:VALUE telemetry, no newline'),
    ('OK',                'uart_text', 'two characters'),
    ('AT+CSQ',            'uart_text', 'AT command'),
    ('hello\n',           'uart_text', 'plain ASCII with newline'),
    (b'\x01\x03\x00\x00\x00\x01\x84\x0a', 'modbus_rtu',
     'valid Modbus RTU read-holding-registers with CRC'),
]


def detect(payload):
    raw = payload.encode() if isinstance(payload, str) else payload
    decoder = protocol_manager.auto_detect(raw)
    return decoder.protocol_id if decoder else None


def test_detection_outcomes() -> None:
    failures = []
    for payload, want, why in CASES:
        got = detect(payload)
        if got != want:
            failures.append(f'{payload!r} ({why}): expected {want}, got {got}')
    assert not failures, '\n'.join(failures)


def test_printable_text_is_never_binary() -> None:
    """The specific regression: ASCII must not come back as i2c/modbus.

    Binary decoders used to outscore text on length, so every plain payload
    acquired a fictitious device address and direction.
    """
    for payload in ('hello', 'TEMP:23.4', 'OK', 'READY', 'sensor ok'):
        got = detect(payload)
        assert got == 'uart_text', (
            f'{payload!r} detected as {got!r}; printable ASCII is text, and '
            f'reporting an I2C address for it is inventing data')


def test_empty_input_scores_nothing() -> None:
    """Blank input must not be confidently attributed to any protocol.

    assert_not_nothing is trivial, so this asserts the real thing: a decoder
    claiming a score for empty or whitespace-only input is wrong, because there
    is nothing there to have detected.
    """
    for payload in (b'', b'   ', b'\n'):
        raw = payload.decode('latin-1').encode('latin-1')
        for proto_id, decoder in protocol_manager._decoders.items():
            score = decoder.can_decode(raw)
            assert score == 0.0, (
                f'{proto_id} scored {score} on empty input {payload!r}')


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
