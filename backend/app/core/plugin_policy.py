"""Static capability policy for marketplace plugins, plus artifact digests.

What this is: a seatbelt. What it is not: a sandbox. The distinction is the
whole reason this module exists, so it is written down here rather than implied.

A real sandbox is an OS boundary -- a separate process with a restricted
syscall surface, a container, seccomp. None of those are available in this
product's shape:

  * `can_decode` is called on **every frame that arrives**, for every installed
    decoder, inside the serial read loop. Putting an IPC hop in that path would
    put a setTimeout-sized cost per frame on a tool whose selling point is
    live traffic at 921600 baud.
  * Shipping a container runtime with a Windows .exe is not a thing.

So the achievable guarantee is: a plugin that tries to open a socket, run a
process, read a file or reach into interpreter internals is **refused at
install time, with the line number**, instead of being discovered later. A
determined attacker defeats it -- `while True: pass` is not something an AST
walk can see, and Python's object graph is reachable from any live object if
you insist. That is why the default is still "installs are off", the UI still
says "read the source first", and the trust boundary in the README says
trusted publishers only.

The policy is an allowlist, not a denylist: an import nobody has thought about
is refused, not permitted. Adding a module to `ALLOWED_IMPORTS` is a deliberate
act with a review behind it.
"""
import ast
import hashlib
from pathlib import Path
from typing import List, Optional

# Modules a decoder legitimately needs to parse bytes into structured output.
# Deliberately pure computation: no filesystem, no network, no process, no
# dynamic import, no pickling (which is code execution by another name).
ALLOWED_IMPORTS = frozenset({
    'abc',
    'array',
    'base64',
    'binascii',
    'bisect',
    'cmath',
    'codecs',
    'collections',
    'copy',
    'csv',
    'dataclasses',
    'datetime',
    'decimal',
    'enum',
    'fractions',
    'functools',
    'hashlib',
    'heapq',
    'hmac',
    'io',
    'itertools',
    'json',
    'math',
    'numbers',
    'operator',
    're',
    'statistics',
    'string',
    'struct',
    'textwrap',
    'time',
    'typing',
    'unicodedata',
    'zlib',
    # The decoder base class. Nothing else under `app.` is reachable: naming the
    # full module rather than the `app` root is what keeps a plugin out of
    # app.core.tool_manager, which shells out.
    'app.core.protocol_decoder',
})

# Builtins that are either code execution or the standard doorway to it.
BANNED_NAMES = frozenset({
    'eval', 'exec', 'compile', '__import__', 'open', 'breakpoint',
    'globals', 'locals', 'vars', 'getattr', 'setattr', 'delattr',
    'input', 'exit', 'quit', 'help',
})

# Substrings that mean "trying to walk the interpreter's own object graph".
BANNED_SUBSTRINGS = (
    '__class__', '__globals__', '__builtins__', '__subclasses__', '__mro__',
    '__bases__', '__import__', '__loader__', '__code__', '__dict__',
    '__getattribute__', '__reduce__', '__setstate__',
)

# Dunders a decoder may legitimately define or call. Anything else shaped like
# `__x__` is refused, because that is the shape of every escape.
SAFE_DUNDERS = frozenset({
    '__init__', '__len__', '__eq__', '__ne__', '__hash__', '__repr__',
    '__str__', '__iter__', '__next__', '__call__', '__enter__', '__exit__',
    '__contains__', '__getitem__', '__setitem__', '__bool__', '__format__',
    '__doc__', '__name__',
})


def _sort_key(message: str) -> int:
    digits = ''
    for ch in message.split(':', 1)[0].split()[-1]:
        if ch.isdigit():
            digits += ch
    return int(digits or 0)


def _is_safe_dunder(name: str) -> bool:
    if not (name.startswith('__') and name.endswith('__')):
        return True
    return name in SAFE_DUNDERS


def _import_targets(node: ast.AST):
    """Yield (candidate_module_names, lineno) for an import statement.

    A `from X import Y` statement can mean either "attribute Y of module X"
    (`from typing import Dict`) or "submodule Y of package X" (`from app.core
    import protocol_decoder`). Both readings are emitted so the allowlist can
    accept the first and refuse the second.
    """
    if isinstance(node, ast.Import):
        for alias in node.names:
            yield (alias.name,), node.lineno
    elif isinstance(node, ast.ImportFrom):
        if node.level:
            # Relative imports have no meaning for a standalone plugin file and
            # would resolve somewhere the policy never inspected.
            yield (f"{'.' * node.level}{node.module or ''}",), node.lineno
            return
        module = node.module or ''
        for alias in node.names:
            if alias.name == '*':
                yield (module,), node.lineno
                continue
            candidates = [module] if module else []
            if module:
                candidates.append(f"{module}.{alias.name}")
            else:
                candidates.append(alias.name)
            yield tuple(candidates), node.lineno


def check_source(source: str, origin: str = '<plugin>') -> List[str]:
    """Return every policy violation in `source`, as human-readable strings.

    Empty list means the source passed. Raising is the caller's decision, so
    the API route and the desktop app can both report the full list rather than
    only the first thing that was wrong.
    """
    try:
        tree = ast.parse(source, filename=origin)
    except SyntaxError as exc:
        return [f"line {exc.lineno or '?'}: plugin is not valid Python: {exc.msg}"]

    violations: List[str] = []

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for candidates, lineno in _import_targets(node):
                if any(c in ALLOWED_IMPORTS for c in candidates):
                    continue
                module = candidates[0]
                if module.startswith('.'):
                    reason = 'a relative import, which a standalone plugin cannot use'
                else:
                    reason = 'not on the plugin allowlist'
                violations.append(
                    f"line {lineno}: import of {module!r} is {reason}. "
                    f"Plugins are limited to pure computation "
                    f"(struct, re, json, math, typing, ...); a decoder has "
                    f"no filesystem, network or process access."
                )

        elif isinstance(node, ast.Attribute):
            if not _is_safe_dunder(node.attr):
                violations.append(
                    f"line {node.lineno}: access to {node.attr!r} reaches into "
                    f"interpreter internals and is refused."
                )

        elif isinstance(node, ast.Name):
            if isinstance(node.ctx, ast.Load) and node.id in BANNED_NAMES:
                violations.append(
                    f"line {node.lineno}: {node.id!r} is not available to "
                    f"plugins ({'code execution' if node.id in {'eval', 'exec', 'compile', '__import__'} else 'process or interpreter access'})."
                )
            elif node.id.startswith('__') and node.id.endswith('__') \
                    and node.id not in SAFE_DUNDERS:
                violations.append(
                    f"line {node.lineno}: reference to {node.id!r} reaches into "
                    f"interpreter internals and is refused."
                )

        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            # A string is how the object graph gets walked after `getattr` and
            # friends were banned: getattr(x, '__class__'). Catching the literal
            # closes the spelling without pretending to close the idea.
            for banned in BANNED_SUBSTRINGS:
                if banned in node.value:
                    violations.append(
                        f"line {node.lineno}: string literal contains {banned!r}, "
                        f"which is the shape of an interpreter escape."
                    )
                    break

    # Deduplicate while keeping the first line-order occurrence: one bad import
    # inside a loop body should not produce nine identical complaints.
    seen = set()
    unique: List[str] = []
    for message in sorted(violations, key=_sort_key):
        if message not in seen:
            seen.add(message)
            unique.append(message)
    return unique


def file_sha256(path: Path) -> str:
    """Hex SHA-256 of a plugin artifact, streamed so a large file is fine."""
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b''):
            digest.update(chunk)
    return digest.hexdigest()


def check_digest(path: Path, expected: Optional[str]) -> str:
    """Compare `path` against a manifest digest.

    Returns the actual digest. Raises ValueError on a mismatch -- a registry
    that pins a hash and serves different bytes is the one failure mode a
    signature-less marketplace can actually detect, so it should be loud.
    """
    actual = file_sha256(path)
    if expected:
        expected_norm = expected.strip().lower()
        if expected_norm != actual:
            raise ValueError(
                f"digest mismatch for {Path(path).name}: manifest pins "
                f"{expected_norm}, file is {actual}. The file is not the one "
                f"the registry published."
            )
    return actual
