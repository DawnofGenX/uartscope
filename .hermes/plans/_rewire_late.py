"""One-shot refactor: route use-before-def handlers through _late_bindings().

Rewrites the remaining v1 offenders (alerts_page, session_detail_page,
mqtt_page) to bind at click time instead of raising UnboundLocalError on
render. Idempotent: running it twice is a no-op.
"""
import re
import sys
from pathlib import Path

# (page, handler) pairs still referencing a handler defined later.
TARGETS = {
    'alerts_page': ['show_add_rule_dialog', 'ack_all'],
    'session_detail_page': ['go_back', 'start_replay'],
    'mqtt_page': ['show_add_broker_dialog'],
}

P = Path('/home/hermes/gh-polish/uartscope/desktop_app.py')


def main() -> int:
    src = P.read_text()
    changed = []

    for page, handlers in TARGETS.items():
        # 1) give the page a registry, right after its def line
        m = re.search(rf'\ndef {page}\(\):\n', src)
        if not m:
            print(f'  !! {page} not found')
            continue
        if f'_bind_{page}' not in src:
            reg = (f'\n    _bind_{page}, _late_{page} = _late_bindings()\n')
            src = src[:m.end()] + reg + src[m.end():]

        for h in handlers:
            # 2) rewrite every reference in a handler position
            src = re.sub(
                rf'(\bon_click=){re.escape(h)}\b',
                rf"\1_late_{page}('{h}')",
                src)
            src = re.sub(
                rf"(\.on\('[a-z]+',\s*){re.escape(h)}\b",
                rf"\1_late_{page}('{h}')",
                src)
            # 3) rename the definition and register it
            src = re.sub(
                rf'\n(    (?:async )?def ){re.escape(h)}\(',
                rf'\n\1_{h}_impl(',
                src, count=1)
            changed.append(f'{page}.{h}')

    P.write_text(src)
    print('rewired:', ', '.join(changed) or 'nothing')
    return 0


if __name__ == '__main__':
    sys.exit(main())
