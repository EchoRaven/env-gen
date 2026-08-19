"""#1003: station three, found on the twelfth search and fixed.

r162's terminal blocker was `POST /api/continue-watching → 405`. It produced 17 tasks and was
never fixed, and the backend lane's task said "reproduce POST … returning 405" because that is
all the detail contained:

    failed=['business_endpoints_reachable:GET /api/search → 500; GET /api/my-list → 500; …']

The evidence path has three stations. #1000 fixed capture and #1001 fixed classification — but
both live in runhub's probe path, and **`business_endpoints_reachable` is fed by a different
HTTP helper entirely**: `validation_runner._http`, which returned `{status, body_text, error}`
and no headers.

So the sibling path was repaired while the one that actually built r162's detail kept dropping
the header. A 405 is required by HTTP to carry `Allow:` naming the methods the server does
accept — the fact that turns "reproduce this" into "compare this list against the route
declaration".

Appended only for 405 and capped at 48 characters, because `compose_unreachable_detail`
budgets the first 300 chars for a backend traceback and its docstring records a lane acting on
exactly that prefix.
"""

import inspect

import pytest

from env_generator.llm_generator.multi_agent.runtime import validation_runner as vr

SRC = inspect.getsource(vr)


def _http_source() -> str:
    """`_http`'s exact source, located by AST. A slice between `def` markers guesses at the
    layout and was wrong on the first draft — this repo's own guards forbid fixed-width
    source windows for the same reason."""
    import ast
    for node in ast.walk(ast.parse(SRC)):
        if isinstance(node, ast.FunctionDef) and node.name == "_http":
            return ast.get_source_segment(SRC, node) or ""
    raise AssertionError("_http not found")


def test_the_http_helper_returns_headers():
    """Every return path — success, HTTPError (where a 405 lands), and transport failure.

    Asserted on the RETURN NODES, not by counting the string: `_http` also takes a `headers`
    parameter and handles request headers, so a substring count says 5 and means nothing.
    """
    import ast
    fn = next(n for n in ast.walk(ast.parse(SRC))
              if isinstance(n, ast.FunctionDef) and n.name == "_http")
    returns = [n for n in ast.walk(fn) if isinstance(n, ast.Return)
               and isinstance(n.value, ast.Dict)]
    assert len(returns) == 3, f"expected three exits, found {len(returns)}"
    for r in returns:
        keys = {k.value for k in r.value.keys
                if isinstance(k, ast.Constant) and isinstance(k.value, str)}
        assert "headers" in keys, f"an exit without headers: {sorted(keys)}"


def test_the_error_branch_reads_them_from_the_exception():
    """A 405 raises HTTPError; `e.headers` is where Allow lives."""
    assert 'getattr(e, "headers", {})' in SRC


def test_the_detail_appends_allow_for_a_405():
    assert "app accepts:" in SRC
    i = SRC.index("app accepts:")
    window = SRC[SRC.index("_extra1003 = \"\""):i]
    assert 'res["status"] == 405' in window, "only a 405 should gain the suffix"


def test_the_suffix_is_capped():
    """compose_unreachable_detail budgets 300 chars for a traceback; an unbounded header list
    would push the root cause out of the prefix the lane reads."""
    assert "[:48]" in SRC


def test_non_405_failures_are_unchanged():
    """A 500 has no Allow to report and must keep its existing one-line shape."""
    i = SRC.index("_extra1003")
    assert 'unreachable.append(' in SRC[i:], "the append must still happen for every failure"


def test_the_control_emits_the_number_alone():
    """Planted control: the PRE-FIX line, which is what r162's lane received."""
    method, path, status = "POST", "/api/continue-watching", 405
    pre_fix = f"{method} {path} \u2192 {status}"
    assert pre_fix == "POST /api/continue-watching \u2192 405"
    assert "accepts" not in pre_fix, (
        "the control was supposed to carry no method list; if it does, this fix is "
        "unmotivated")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
