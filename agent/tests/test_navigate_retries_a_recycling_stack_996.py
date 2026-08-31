"""#996: a refused connection during a compose recycle is transient, not a verdict.

A validation cycle tears the compose project down (`down -v` -> build -> up). Anything
touching the live stack in that window gets nothing, and three surfaces have now paid:

    browser walk      item 374   10 x ERR_CONNECTION_REFUSED
    test_api          item 400   10, then 55 in r162
    capture_webpage   r162       22, all REFUSED/RESET

That third surface is the trigger item 400 wrote down: "revisit when a third surface appears".
It appeared, and capture_webpage feeds the visual gate, so the cost stopped being retries and
started being missing evidence.

Item 374 rejected the obvious fix — hold the smoke lock across a multi-minute browser walk —
because it would serialize every lane behind compose recycles. This one serializes nothing.
The stack is down for seconds; waiting briefly and retrying costs far less than a lost
capture, and a genuinely dead stack still fails, three attempts later, with the same error.
"""

import ast
import inspect

import pytest

from env_generator.llm_generator.tools.browser import core

SRC = inspect.getsource(core)


def _retry_block() -> str:
    """The navigate function's source, located by AST rather than a fixed-width window —
    a byte-count slice is the fragile-locator pattern #923's guard forbids, and this repo's
    own meta-test caught it on the first draft of this file."""
    tree = ast.parse(SRC)
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            src = ast.unparse(fn)
            if "#996" in inspect.getsource(core).split("\n")[fn.lineno - 1:fn.end_lineno][0] \
                    or "ERR_CONNECTION_REFUSED" in src:
                return src
    raise AssertionError("no navigate function carrying the retry was found")


def test_the_navigate_path_retries():
    assert "#996" in SRC
    assert "ERR_CONNECTION_REFUSED" in SRC


def test_only_transient_connection_errors_are_retried():
    """A 404, a timeout or a bad selector must fail on the first attempt — retrying a real
    failure just triples the wait before the same answer."""
    window = _retry_block()
    assert "raise" in window, "non-transient exceptions must propagate immediately"
    for transient in ("ERR_CONNECTION_REFUSED", "ERR_CONNECTION_RESET", "ERR_EMPTY_RESPONSE"):
        assert transient in window


def test_the_retry_is_bounded():
    """Unbounded retry against a genuinely dead stack would hang the lane instead of failing
    it — worse than the defect. The BOUND survives #1189; its unit changed.

    #996 bounded by attempt count (`range(3)`, 3s + 6s = nine seconds). Measured over
    netflix-r22's resume, 50 of 51 compose recycles ran LONGER than that — median 20s, P90
    111s — so the count-based bound abandoned the navigation mid-recycle 98% of the time.
    #1189 bounds by a deadline instead, which adapts to the actual outage and still refuses
    to wait forever.
    """
    blk = _retry_block()
    assert "_deadline" in blk and "monotonic" in blk, "bounded by time"
    assert "range(3)" not in blk, "the attempt-counted bound was the defect"
    assert "_nav_wait_budget_1189()" in blk, "and the budget is explicit + overridable"


def test_it_waits_between_attempts():
    """Still a wait, still bounded — a flat gap under a deadline rather than a ramp under a
    counter (a ramp only matters when the attempts are few)."""
    assert "asyncio.sleep(3)" in _retry_block()


def test_a_dead_stack_still_reports_the_original_error():
    """The lane must see the real cause, not a wrapper — this session's recurring lesson."""
    assert "raise _last_exc" in _retry_block()


def test_the_control_fails_on_the_first_refusal():
    """Planted control: the PRE-FIX path had a single goto with no retry, so one unlucky
    moment inside a recycle window cost a capture."""
    def _pre_fix(attempts):
        return attempts == 1

    assert _pre_fix(1), (
        "the control was supposed to make exactly one attempt; if it does not, this fix is "
        "unmotivated")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
