"""Register the renamed handler impls with their page's _late_bindings registry.

Runs after _rewire_late.py. Idempotent.
"""
import re
import sys
from pathlib import Path

P = Path('/home/hermes/gh-polish/uartscope/desktop_app.py')

# (page, handler) -> where to insert the registration (after the impl body ends)
PAIRS = [
    ('alerts_page', 'show_add_rule_dialog'),
    ('alerts_page', 'ack_all'),
    ('session_detail_page', 'go_back'),
    ('session_detail_page', 'start_replay'),
    ('mqtt_page', 'show_add_broker_dialog'),
]


def main() -> int:
    src = P.read_text()
    added = []

    for page, h in PAIRS:
        reg_line = f"    _bind_{page}('{h}', _{h}_impl)\n"
        if reg_line in src:
            continue
        # find the def of the impl
        m = re.search(rf'\n    (?:async )?def _{re.escape(h)}_impl\(', src)
        if not m:
            print(f'  !! _{h}_impl not found')
            continue
        # find the end of that def: next line at indent <= 4 starting a def
        rest = src[m.end():]
        nxt = re.search(r'\n    (?:async )?def ', rest)
        if nxt:
            end = m.end() + nxt.start() + 1
        else:
            end = len(src)
        src = src[:end] + reg_line + '\n' + src[end:]
        added.append(f'{page}.{h}')

    P.write_text(src)
    print('registered:', ', '.join(added) or 'nothing')
    return 0


if __name__ == '__main__':
    sys.exit(main())
