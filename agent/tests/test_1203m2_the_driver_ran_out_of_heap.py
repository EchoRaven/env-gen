r"""#1203m2: the Playwright driver filled node's default heap and took the browser with it.

The driver is a bundled node process -- the protocol bridge, not Chromium -- so node's
default old-space ceiling applies. Measured on the binary this repo resolves: 4288 MB, and
the corpus OOM reports die at 4099 MB used.

30 OOM events across 19 of the 39 modern root logs, every one with `playwright/driver/node`
in its native stack, at driver uptimes of min 11.5 / median 59 / max 200 minutes -- i.e. a
long-lived driver, and the only one that lives that long is this package's shared one.
`Connection closed while reading from the driver` appears 9 times modern and **9 of 9** are
preceded by one of those OOMs within 1-4s (one at 89s): the error #1199 had to carve out of
the product verdict and #1198 rebuilds around, 44 rebuilds across 21 runs.

Nothing in the tree set NODE_OPTIONS. 8192 MB was verified to take effect on that binary
(-> 8384 MB) and to be inherited by the driver playwright actually spawns, read back from
its /proc/<pid>/environ.
"""
from __future__ import annotations

import ast
import inspect
import os
import textwrap

import pytest

from env_generator.llm_generator.tools.browser import _bootstrap
from env_generator.llm_generator.tools.browser._bootstrap import driver_heap_1203m2


@pytest.fixture(autouse=True)
def _clean_env():
    """NODE_OPTIONS/ENVGEN_DRIVER_HEAP_MB are process-wide; never leak them out of a test."""
    keep = {k: os.environ.get(k) for k in ("NODE_OPTIONS", "ENVGEN_DRIVER_HEAP_MB")}
    for k in keep:
        os.environ.pop(k, None)
    try:
        yield
    finally:
        for k, v in keep.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_the_ceiling_is_raised_inside_and_gone_after():
    with driver_heap_1203m2():
        assert os.environ["NODE_OPTIONS"] == "--max-old-space-size=8192"
    assert "NODE_OPTIONS" not in os.environ, "the variable outlived the spawn it was for"


def test_an_existing_node_options_is_kept():
    os.environ["NODE_OPTIONS"] = "--enable-source-maps"
    with driver_heap_1203m2():
        got = os.environ["NODE_OPTIONS"]
        assert "--enable-source-maps" in got and "--max-old-space-size=8192" in got
    assert os.environ["NODE_OPTIONS"] == "--enable-source-maps"


def test_an_operator_who_already_chose_a_ceiling_keeps_it():
    os.environ["NODE_OPTIONS"] = "--max-old-space-size=2048"
    with driver_heap_1203m2():
        assert os.environ["NODE_OPTIONS"] == "--max-old-space-size=2048"


@pytest.mark.parametrize("raw,expect_set", [("16384", True), ("0", False), ("-1", False)])
def test_the_override_is_honoured_including_opting_out(raw, expect_set):
    os.environ["ENVGEN_DRIVER_HEAP_MB"] = raw
    with driver_heap_1203m2():
        if expect_set:
            assert os.environ["NODE_OPTIONS"] == "--max-old-space-size=16384"
        else:
            assert "NODE_OPTIONS" not in os.environ


def test_a_junk_override_falls_back_rather_than_raising():
    os.environ["ENVGEN_DRIVER_HEAP_MB"] = "lots"
    with driver_heap_1203m2():
        assert os.environ["NODE_OPTIONS"] == "--max-old-space-size=%d" % (
            _bootstrap._DRIVER_HEAP_MB_1203M2,)


def test_the_block_restores_even_when_the_body_raises():
    os.environ["NODE_OPTIONS"] = "--enable-source-maps"
    with pytest.raises(RuntimeError):
        with driver_heap_1203m2():
            raise RuntimeError("the spawn failed")
    assert os.environ["NODE_OPTIONS"] == "--enable-source-maps"


def test_the_spawn_itself_is_inside_the_block():
    """The helper is worthless unless the `start()` it is for happens under it.

    Asserted on the real method's AST -- `ensure_browser` is async and reaching the spawn
    needs a live driver, so a unit test cannot execute this call site (#1203ji's fifth
    MISSED shape). The property is structural: the `await async_playwright().start()` node
    must be a descendant of a `with driver_heap_1203m2()` body.
    """
    from env_generator.llm_generator.tools.browser._manager import BrowserManager

    tree = ast.parse(textwrap.dedent(inspect.getsource(BrowserManager.ensure_browser)))

    def _is_pw_start(node):
        return (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute) and node.func.attr == "start"
                and isinstance(node.func.value, ast.Call)
                and getattr(node.func.value.func, "id", "") == "async_playwright")

    starts = [n for n in ast.walk(tree) if _is_pw_start(n)]
    assert len(starts) == 1, "the driver spawn moved or was duplicated"

    guarded = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.With, ast.AsyncWith)):
            continue
        if not any(isinstance(it.context_expr, ast.Call)
                   and getattr(it.context_expr.func, "id", "") == "driver_heap_1203m2"
                   for it in node.items):
            continue
        guarded += [n for s in node.body for n in ast.walk(s) if _is_pw_start(n)]
    assert guarded, "the driver is still spawned with node's default heap"
