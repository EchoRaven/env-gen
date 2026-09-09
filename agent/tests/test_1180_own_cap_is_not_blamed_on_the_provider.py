"""#1180 — a run stopped by the operator's own ceiling blamed the provider.

#326 latches a TERMINAL provider error (spend/quota/hard-auth) and aborts within a tick
instead of letting lanes spin to the wall-clock cap. Its message says:

    "LLM provider budget/auth exhausted — get a budget increase or a fresh key
     (raising ENVGEN_MAX_* will NOT help)"

#1163 then reused that same latch for our OWN ceiling, ENVGEN_MAX_SPEND_USD. So a run the
operator capped reported a provider outage, and named ENVGEN_MAX_* as the thing that would
NOT help — in the same string that ends "...reached ENVGEN_MAX_SPEND_USD=$120.00".

All three netflix r17 resumes ended on that line. It is what sent me to probe whether the
API key had died; it answered 200 on the first try. Advice that names the one knob that
matters and says it will not help is worse than no advice.
"""
import inspect
import re

from env_generator.llm_generator.multi_agent import orchestrator as orch_mod

_SRC = inspect.getsource(orch_mod)


def _terminal_branch():
    """The #326 latch branch, cut at the next landmark — not a byte window (#943)."""
    i = _SRC.index("_term = _terminal_llm_error()")
    return _SRC[i:_SRC.index("if budget_exceeded:", i)]


def test_our_own_cap_is_distinguished_from_the_provider():
    branch = _terminal_branch()
    # #1202hv moved the decision into ONE shared predicate, because this site was only
    # one of three that each decided it for itself (the ledger wrote "aborted_provider"
    # for every budget stop, kickoff said "the provider is terminally unavailable").
    # The contract this test names is unchanged and now holds in three places; only the
    # spelling moved, so assert the question is ASKED rather than how it is written.
    assert "terminal_stop_is_own_budget_1202hv" in branch, (
        "the branch must ask whether OUR ceiling is the cause before blaming the provider")


def test_the_own_cap_message_points_at_the_knob_that_works():
    branch = _terminal_branch()
    own = branch[branch.index("terminal_stop_is_own_budget_1202hv("):branch.index("else:")]
    assert "provider is fine" in own
    assert "Raise ENVGEN_MAX_SPEND_USD" in own
    assert "will NOT help" not in own, (
        "the own-cap message must not carry #326's provider advice")


def test_the_provider_message_survives_for_a_real_provider_error():
    """#326's case is real (r93: ~4500 rejected attempts over ~2h) and must keep its text."""
    branch = _terminal_branch()
    other = branch[branch.index("else:"):]
    assert "LLM provider budget/auth exhausted" in other
    assert "fresh key" in other


def test_no_message_claims_both_things():
    """★ The defect itself: one string that blames the provider AND names our knob."""
    for msg in re.findall(r'"([^"]*ENVGEN_MAX[^"]*)"', _terminal_branch()):
        assert not ("provider budget/auth exhausted" in msg and "will NOT help" in msg
                    and "SPEND_USD" in msg), f"contradictory advice in one string: {msg}"
