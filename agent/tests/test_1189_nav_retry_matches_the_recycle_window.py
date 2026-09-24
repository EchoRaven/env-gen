"""#1189 — the navigation retry gave up an order of magnitude before the event it waits for.

#996 retries a refused navigation because "a validation cycle recycles the compose project
(`down -v` -> build -> up), and anything touching the live stack in that window gets
nothing". It allowed three attempts with 3s + 6s of sleep — NINE seconds. Measured over
netflix-r22's resume, pairing each `docker down` with the `docker up` that completed after it:

    51 windows   median 20s   P75 28s   P90 111s   max 250s
    longer than 9s: 50 of 51  (98%)

So it abandoned the navigation while the stack was still coming up in 98% of recycles. That
resume ended holding three failing ui_flow records — title-detail-open, login_auth_flow,
profile_creation — every one an ERR_CONNECTION_REFUSED, one of them refused by the FRONTEND's
own origin, on an app that answers register/login/titles correctly when probed by hand. 72
ERR_CONNECTION_REFUSED events across 102 down/up cycles. #1154 discounts such records after
the fact; this stops minting them.
"""
import asyncio
import os

import pytest

from env_generator.llm_generator.tools.browser import core as C


@pytest.fixture(autouse=True)
def clean_env():
    os.environ.pop("ENVGEN_NAV_WAIT_SEC", None)
    yield
    os.environ.pop("ENVGEN_NAV_WAIT_SEC", None)


def test_the_budget_covers_the_measured_window():
    """120s clears the P90 (111s); 9s cleared almost nothing."""
    assert C._nav_wait_budget_1189() == 120.0
    assert C._nav_wait_budget_1189() > 111, "must cover the P90 recycle window"


def test_the_budget_is_bounded_and_overridable():
    for raw, want in (("0", 0.0), ("9999", 600.0), ("abc", 120.0), ("", 120.0), ("-5", 0.0)):
        os.environ["ENVGEN_NAV_WAIT_SEC"] = raw
        assert C._nav_wait_budget_1189() == want, raw


def test_zero_restores_the_old_give_up_immediately():
    os.environ["ENVGEN_NAV_WAIT_SEC"] = "0"
    assert C._nav_wait_budget_1189() == 0.0


def test_the_wait_is_deadline_based_not_attempt_counted():
    """★ The defect was the SHAPE: three attempts cannot cover a variable window.

    `range(3)` bounds the wait by a count, so a longer recycle is never survived no matter
    how brief each sleep is. A deadline adapts to the actual outage.
    """
    import inspect
    src = inspect.getsource(C.BrowserNavigateTool.execute)
    assert "_deadline" in src and "monotonic" in src
    assert "for _attempt in range(3)" not in src, "the attempt-counted loop is the defect"


def test_a_non_connection_error_is_not_retried():
    """A real page error must surface at once — the wait is only for a down origin."""
    import inspect
    src = inspect.getsource(C.BrowserNavigateTool.execute)
    # Anchor on the GUARD, not on the first mention of the marker — the first occurrence is
    # in the comment above the loop, and slicing around it tested prose.
    i = src.index("if not any(k in _txt for k in (")
    # Landmark, not a byte count: #943's ratchet exists because a window sized in bytes
    # breaks when a comment grows, and I wrote one here on the ninth sighting of that class.
    tail = src[i:src.index("_last_exc = _e", i)]
    assert "raise" in tail, "anything not connection-class must re-raise immediately"


def test_a_dead_origin_still_fails_with_its_own_error():
    import inspect
    src = inspect.getsource(C.BrowserNavigateTool.execute)
    assert "raise _last_exc" in src, "after the deadline the original error must surface"


def test_the_wait_is_logged_through_a_real_logger():
    """The log line sits in a try/except; without a module logger the NameError would be
    swallowed and the wait would be invisible."""
    assert hasattr(C, "_LOG1189")
    import inspect
    assert "_LOG1189.info" in inspect.getsource(C.BrowserNavigateTool.execute)
