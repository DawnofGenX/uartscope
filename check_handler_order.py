"""Static check for use-before-definition inside NiceGUI page builders.

Four separate v1 screens were broken by exactly this bug: a page wired
`on_click=some_handler` to a function defined further down the same function
body, so constructing the page raised UnboundLocalError. Terminal, Charts and
Decoder could not be opened at all, and none of it was visible without opening
the screen in a browser.

Python will not catch it at import time (it is legal, just wrong), and
pyflakes cannot either (the name is a local, so it is not "undefined"). This
walks each `def *_page()` body with the `ast` module and reports every
`on_click=` / `on_value_change=` / `on(...)` argument that names a nested
function defined later in the same body.

Run:  .venv-v2/bin/python check_handler_order.py [module.py]
"""
import ast
import sys
from pathlib import Path

# Attributes whose value is a handler that must exist before it is referenced.
HANDLER_ATTRS = {
    'on_click', 'on_value_change', 'on_change', 'on_select',
    'on_hold', 'on_release', 'on_mouse_down', 'on_mouse_up',
}


def nested_defs(fn: ast.FunctionDef) -> dict[str, int]:
    """Map nested function name -> line of its def statement."""
    out = {}
    for node in ast.walk(fn):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node is not fn:
            out.setdefault(node.name, node.lineno)
    return out


def handler_refs(fn: ast.FunctionDef) -> list[tuple[str, int, int]]:
    """Every handler-name reference inside fn, as (name, line, col)."""
    refs = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        fname = ''
        f = node.func
        if isinstance(f, ast.Attribute):
            fname = f.attr
        elif isinstance(f, ast.Name):
            fname = f.id
        # The handler may be any element constructor, e.g.
        #   ui.button('x', on_click=handler)   -> kwarg named on_click
        #   ui.switch(..., on_change=handler)  -> kwarg named on_change
        # so match on the KEYWORD name, not on the call's own name.
        for kw in node.keywords:
            if kw.arg in HANDLER_ATTRS and isinstance(kw.value, ast.Name):
                refs.append((kw.value.id, kw.value.lineno, kw.value.col_offset))
        # Positional form: element.on('event', handler)
        if fname == 'on' and len(node.args) >= 2:
            a = node.args[1]
            if isinstance(a, ast.Name):
                refs.append((a.id, a.lineno, a.col_offset))
    return refs


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else 'desktop_app.py')
    tree = ast.parse(path.read_text(), filename=str(path))

    problems = []
    pages = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        if not node.name.endswith('_page'):
            continue
        pages += 1
        defs = nested_defs(node)
        for name, line, col in handler_refs(node):
            dline = defs.get(name)
            if dline is not None and dline > line:
                problems.append(
                    (node.name, name, line, dline))

    if not problems:
        print(f'no handler-order problems in {pages} page builders')
        return 0

    print(f'{len(problems)} handler(s) referenced before definition:\n')
    for page, name, uline, dline in problems:
        print(f'  {page}()  {name}:  used at line {uline}, '
              f'defined at line {dline}  ->  UnboundLocalError on render')
    return 1


if __name__ == '__main__':
    sys.exit(main())
