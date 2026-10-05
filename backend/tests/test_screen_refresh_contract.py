"""Every polling screen must clear its container before rebuilding.

performance_page and mqtt_page rebuilt their whole UI every 3 seconds
without clearing first, so the page grew without bound for as long as it was
open -- an unbounded element leak. Every v2 screen calls container.clear()
first. This is a structural assertion, because the leak is a property of the
page builder rather than of a function with a return value.

Run:  .venv/bin/python -m pytest tests/test_screen_refresh_contract.py -v
"""
import ast
from pathlib import Path

import pytest

DESKTOP = Path(__file__).resolve().parents[2] / "desktop_app.py"


@pytest.fixture(scope="module")
def tree():
    return ast.parse(DESKTOP.read_text(encoding="utf-8"))


def _functions_named(tree, names):
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in names:
            out[node.name] = node
    return out


def _called_names(node):
    called = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            func = sub.func
            if isinstance(func, ast.Attribute):
                called.add(func.attr)
    return called


class TestPollingScreensClearBeforeRebuilding:
    @pytest.mark.parametrize("name", ["refresh_performance", "refresh_mqtt"])
    def test_refresh_clears_its_container(self, tree, name):
        fns = _functions_named(tree, {name})
        assert name in fns, f"{name} not found in desktop_app.py"
        assert "clear" in _called_names(fns[name]), (
            f"{name} builds UI without calling .clear(); the page grows "
            f"without bound on every refresh tick")

    @pytest.mark.parametrize("name", ["refresh_performance", "refresh_mqtt"])
    def test_refresh_reenters_the_container(self, tree, name):
        """clear() leaves the ambient context on a deleted slot.

        charts_page:1275 documents this: rebuilding without an explicit
        `with container:` raises at runtime. Both screens must do the same.
        """
        fns = _functions_named(tree, {name})
        fn = fns[name]
        withs = [n for n in ast.walk(fn)
                 if isinstance(n, (ast.With, ast.AsyncWith))]
        assert withs, (
            f"{name} clears its container but never re-enters it with "
            f"`with container:`, which raises at runtime")


class TestNoScreenIsMarkedPreV2:
    def test_v2_pending_is_empty(self):
        """The 'Not yet v2' pill is driven by this literal.

        Once both screens are v2 it must be an empty set, otherwise the header
        keeps labelling finished screens as unfinished.
        """
        src = DESKTOP.read_text(encoding="utf-8")
        assert "V2_PENDING = set()" in src, (
            "V2_PENDING must become an empty set once every screen is v2")
