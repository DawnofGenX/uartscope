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

# Local helpers that take a handler as a positional argument. The handler is
# always the final positional arg, so scanning keywords alone is not enough --
# _btn('x', 'cls', handler) has no handler keyword at all.
HANDLER_HELPERS = {'_btn', '_late', '_goto', '_render'}


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
        # Helper form: _btn('Label', 'classes', handler) and friends. These take
        # the handler as the last positional argument, so the keyword scan above
        # misses them entirely -- which is how a _btn(...) call shipped with
        # UnboundLocalError while this checker reported the file clean.
        if fname in HANDLER_HELPERS and node.args:
            for a in reversed(node.args):
                if isinstance(a, ast.Name):
                    refs.append((a.id, a.lineno, a.col_offset))
                    break
    return refs


def undefined_names(fn: ast.FunctionDef, module_names: set[str]) -> list[tuple[str, str, int]]:
    """Names referenced inside fn that are neither local, module-level, nor builtin.

    This catches a different failure from the ordering check: a page that
    references a helper which does not exist at all. That happened when a
    rewrite dropped the `_late_bindings()` line a page needed -- the ordering
    check passed, every handler was correctly ordered, and the page still
    raised NameError on every render.
    """
    import builtins

    defined: set[str] = set(module_names) | set(dir(builtins))
    for node in ast.walk(fn):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defined.add(node.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            defined.add(node.id)
        elif isinstance(node, ast.arg):
            defined.add(node.arg)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                defined.add((alias.asname or alias.name).split('.')[0])
        elif isinstance(node, ast.ExceptHandler) and node.name:
            defined.add(node.name)

    missing = []
    seen = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            if node.id not in defined and (node.id, node.lineno) not in seen:
                seen.add((node.id, node.lineno))
                missing.append((fn.name, node.id, node.lineno))
    return missing


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else 'desktop_app.py')
    tree = ast.parse(path.read_text(), filename=str(path))

    module_names = {
        n.name for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    } | {
        (a.asname or a.name).split('.')[0]
        for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))
        for a in n.names
    } | {
        t.id for n in tree.body if isinstance(n, ast.Assign)
        for t in n.targets if isinstance(t, ast.Name)
    } | {
        # Annotated module constants (`_LINE_BUFFER: dict[str, list] = ...`).
        # Omitting AnnAssign made a defined name look undefined, which is a
        # false positive that trains you to ignore the check.
        n.target.id for n in tree.body
        if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)
    }

    problems = []
    missing_names = []
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
        missing_names.extend(undefined_names(node, module_names))

    if missing_names:
        print(f'{len(missing_names)} undefined name(s) in page builders:\n')
        for page, name, line in sorted(missing_names, key=lambda t: t[2]):
            print(f'  {page}()  {name}  (line {line})  ->  NameError on render')
        print()

    if not problems and not missing_names:
        print(f'no handler-order problems in {pages} page builders')
        print(f'no undefined names in {pages} page builders')
        return 0

    print(f'{len(problems)} handler(s) referenced before definition:\n')
    for page, name, uline, dline in problems:
        print(f'  {page}()  {name}:  used at line {uline}, '
              f'defined at line {dline}  ->  UnboundLocalError on render')
    return 1


if __name__ == '__main__':
    sys.exit(main())
