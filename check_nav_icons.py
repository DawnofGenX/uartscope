"""Static check that every NAV_ITEMS entry names an icon that actually exists.

The Firmware tab shipped with `('firmware', 'memory', ...)`. `memory` was never a
key in uartscope_theme.ICONS, and `icon()` raises KeyError on an unknown name.
Because `build_sidebar()` renders every nav item on EVERY page, that one bad
string 500'd all thirteen screens -- devices, terminal, charts, the lot -- while
the app still started and answered `/` with 200. The only visible symptom was a
red screen in the browser and a wall of `http=500` in CI, with the real cause
buried 30 frames deep in a server log nobody reads.

Two things went wrong, and both are worth preventing separately:

  1. Nothing checked the string against ICONS. `check_handler_order.py` catches
     use-before-definition; this catches a name that will never resolve.
  2. `smoke_pages.py` listed the tabs by hand, so the new tab was not in TABS
     and the screen that broke the build was never the screen under test. The
     list is now derived from NAV_ITEMS, so adding a nav item cannot silently
     skip its own coverage.

Python cannot catch either on its own: the tuple is legal, and the string is
only wrong against data in another module.

Run:  python check_nav_icons.py [module.py]
Exits 1 on any unknown icon name.
"""
import ast
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_TARGET = HERE / 'desktop_app.py'


def load_icons() -> set[str]:
    """Read the icon names straight out of uartscope_theme.ICONS.

    Imported rather than parsed so the checker cannot drift from the real set.
    """
    sys.path.insert(0, str(HERE))
    from uartscope_theme import ICONS
    return set(ICONS)


def nav_items(tree: ast.Module) -> list[tuple[str, str, int]]:
    """Extract (tab_id, icon_name, lineno) for every NAV_ITEMS tuple literal."""
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if 'NAV_ITEMS' not in targets:
            continue
        if not isinstance(node.value, (ast.List, ast.Tuple)):
            continue
        for elt in node.value.elts:
            if not isinstance(elt, ast.Tuple) or len(elt.elts) < 2:
                continue
            tab = elt.elts[0]
            icon_name = elt.elts[1]
            if not (isinstance(tab, ast.Constant)
                    and isinstance(icon_name, ast.Constant)):
                continue
            out.append((tab.value, icon_name.value, elt.lineno))
    return out


def check(target: Path) -> list[str]:
    """Return a list of human-readable problems. Empty list means clean."""
    tree = ast.parse(target.read_text(encoding='utf-8'))
    items = nav_items(tree)
    if not items:
        return [f'{target.name}: no NAV_ITEMS list literal found']

    icons = load_icons()
    problems = []
    for tab_id, icon_name, lineno in items:
        if icon_name not in icons:
            problems.append(
                f'{target.name}:{lineno}  nav item {tab_id!r} names icon '
                f'{icon_name!r}, which is not in ICONS '
                f'(add it to uartscope_theme.ICONS or change the nav item). '
                f'build_sidebar() renders every item on every page, so this '
                f'breaks every screen.'
            )
    return problems


def main(argv: list[str]) -> int:
    target = Path(argv[1]) if len(argv) > 1 else DEFAULT_TARGET
    if not target.exists():
        print(f'no such file: {target}')
        return 2

    problems = check(target)
    for p in problems:
        print(p)
    if problems:
        print(f'\n{len(problems)} unknown icon name(s) in NAV_ITEMS')
        return 1
    print(f'{target.name}: every NAV_ITEMS icon name exists in ICONS')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))