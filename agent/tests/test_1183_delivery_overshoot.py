"""#1183 — a ceiling that kills a run which is already finishing spends everything to save a little.

The spend cap exists to bound a WEDGE. It has repeatedly ended runs that were not wedged but
converging, and each time the money already spent was what got lost:

  r17 resume 2  stopped at $150.36 having taken the gate from 5 failed checks to 1
  r17 resume 3  stopped at $120.28 with ui_flow:signup green and one record left
  r20           reached "final deliverability is green with zero blockers" at $403 of $500

Three runs, ~$670, none delivered. Once the delivery gate PASSES there is nothing left for a
cap to protect: the remaining work is the release, it is bounded, and stopping there discards
the whole run. So the ceiling is raised by a bounded factor while the gate reports zero
blockers — and a run that wedges after passing still stops, 25% later.
"""
import os

import pytest

import utils.llm as L

PRICES = dict(ENVGEN_PRICE_IN_PER_M="5.50", ENVGEN_PRICE_CACHED_PER_M="0.55",
              ENVGEN_PRICE_OUT_PER_M="33.00")
_KEYS = tuple(PRICES) + ("ENVGEN_MAX_SPEND_USD", "ENVGEN_DELIVERY_OVERSHOOT")


@pytest.fixture(autouse=True)
def clean():
    def reset():
        for k in _KEYS:
            os.environ.pop(k, None)
        L._LLM_USAGE.update(calls=0, prompt=0, cached=0, completion=0, cache_unreported=0)
        L._TERMINAL_LLM_ERROR["reason"] = None
        L.mark_delivering_1183(False)
    reset()
    yield
    reset()


def _spend(usd):
    """Book `usd` of OUTPUT tokens at the configured rate."""
    os.environ.update(PRICES)
    L._record_usage_1163(0, 0, int(round(usd / 33.00 * 1_000_000)))


def test_under_the_cap_nothing_latches():
    os.environ["ENVGEN_MAX_SPEND_USD"] = "100"
    _spend(90)
    assert L._TERMINAL_LLM_ERROR["reason"] is None


def test_a_wedged_run_still_stops_at_the_cap():
    """The cap's actual job — unchanged when the gate has not passed."""
    os.environ["ENVGEN_MAX_SPEND_USD"] = "100"
    _spend(101)
    assert "BudgetExceeded" in (L._TERMINAL_LLM_ERROR["reason"] or "")


def test_a_delivering_run_is_not_stopped_at_the_cap():
    """★ r20's situation: gate green, $403 spent, $500 ceiling."""
    os.environ["ENVGEN_MAX_SPEND_USD"] = "100"
    L.mark_delivering_1183()
    _spend(110)
    assert L._TERMINAL_LLM_ERROR["reason"] is None, (
        "a run whose gate has passed must not be killed for the tail of the release")


def test_the_overshoot_is_bounded_and_stated():
    os.environ["ENVGEN_MAX_SPEND_USD"] = "100"
    L.mark_delivering_1183()
    _spend(126)
    reason = L._TERMINAL_LLM_ERROR["reason"] or ""
    assert "BudgetExceeded" in reason, "25% is a bound, not an exemption"
    assert "delivery overshoot" in reason and "the gate had passed" in reason


def test_an_overshoot_below_one_cannot_tighten_the_cap():
    """A misconfigured 0.5 must not turn a $500 ceiling into $250 at the worst moment."""
    os.environ["ENVGEN_DELIVERY_OVERSHOOT"] = "0.5"
    assert L._overshoot_1183() == 1.0
    for bad in ("", "abc", "-3"):
        os.environ["ENVGEN_DELIVERY_OVERSHOOT"] = bad
        assert L._overshoot_1183() >= 1.0
    os.environ["ENVGEN_DELIVERY_OVERSHOOT"] = "99"
    assert L._overshoot_1183() == 2.0, "and it must not be unbounded either"


def test_the_flag_follows_the_gate_rather_than_latching():
    """Nothing but a passing gate may raise the ceiling, and a LATER failure must lower it.

    Observed live on r21's resume: the gate passed once, the ceiling rose, and the gate then
    failed again on `deliverability_ui_page_unwired` while the run kept the raised ceiling —
    relaxed for a run that was no longer finishing. The verdict is passed through, so the
    state is the gate's current answer and not a one-way latch.
    """
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import delivery_gate as dg
    assert "mark_delivering_1183(bool(ok))" in inspect.getsource(dg)


def test_a_gate_that_fails_again_lowers_the_ceiling():
    os.environ["ENVGEN_MAX_SPEND_USD"] = "100"
    L.mark_delivering_1183(True)
    _spend(110)
    assert L._TERMINAL_LLM_ERROR["reason"] is None, "green gate -> overshoot"
    L.mark_delivering_1183(False)          # the next evaluation failed
    L._record_usage_1163(0, 0, 1)          # any further spend re-checks the ceiling
    assert "BudgetExceeded" in (L._TERMINAL_LLM_ERROR["reason"] or ""), (
        "a run that is no longer finishing must be back under the plain cap")
