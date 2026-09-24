r"""#1202dm: the compose race shares a cap built for a failure it cannot exhibit.

#1202cc detects the sharpest signal in the gate: a round where SOME screens photographed and
others refused the connection. Its own reasoning for why that is safe to exclude:

    A refusal is a TRANSPORT error, and the same round holds successful captures -- a server
    cannot be serving and refusing at once, so the stack moved underneath us.

It then bounds the refund by the shared `_TRANSIENT_REFUND_CAP`, justified like this:

    Bounded by the caller's existing _TRANSIENT_REFUND_CAP, so an app that is genuinely down
    satisfies this every round, exhausts the refunds and lands on a real verdict

That justification does not hold for THIS branch, and the branch's own precondition is why.
An app that is genuinely down photographs NOTHING — zero successes — and is handled by the
`capture unavailable — 0 of N screen(s) photographed` path instead. The mixed-evidence branch
is unreachable for it. So the cap is protecting against a case that cannot occur here, while
spending the budget of one that provably can.

The cost is live. netflix-r44, 12:50:18:

    Visual fidelity: capture raced the compose stack — 1 screen(s) photographed but 11
    refused the connection (browse_home; browse_home_rows; games (+8 more not shown)); the
    app was torn down mid-round, so this is not a judgment — attempt refunded, will retry
    next tick (unreachable 2/3).

Two of three refunds gone at ONE judgment and $171 spent. On the third, a torn-down app
becomes a real verdict: false-low scores that both poison the run's fidelity history and
dispatch lane remediation for a defect the lane did not cause.

Still bounded — a framework that raced forever must not defer forever — just bounded
separately, and by a number that reflects a transient the framework inflicts on itself.
#1202dl removes the mutation half of that race; this keeps the remaining half from
converting into false verdicts.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf


def test_the_race_result_is_marked_distinctly():
    """The caller cannot budget it separately if it cannot tell it apart."""
    assert hasattr(vf, "_COMPOSE_RACE_REFUND_CAP_1202DM")
    assert vf._COMPOSE_RACE_REFUND_CAP_1202DM > vf._TRANSIENT_REFUND_CAP, (
        "a self-inflicted transient should not share the budget of a possibly-broken app")


def test_the_gate_tracks_it_in_its_own_counter():
    """gate_state must persist it, or it resets and the bound means nothing (#664)."""
    import inspect
    src = inspect.getsource(vf)
    assert "compose_race_refunds_1202dm" in src
    # persisted alongside the other refund counters
    persist = src[src.index('"transient_refunds", "unreachable_refunds"'):]
    assert "compose_race_refunds_1202dm" in persist[:400], (
        "the new counter is not in the persisted field list")


def test_the_race_branch_sets_the_marker():
    """#1202cc's mixed-evidence return must carry the flag the caller keys on."""
    import inspect
    src = inspect.getsource(vf)
    at = src.index("capture raced the compose stack")
    # semantic boundary, not a byte count: a window sized in bytes stops covering the thing
    # it was written for the first time a comment above it grows (#943).
    window = src[at:src.index("judge = judge_fn", at)]
    assert "compose_race_1202dm" in window, (
        "the compose-race result is indistinguishable from other capture_unavailable causes")


def test_the_caller_budgets_the_race_separately():
    import inspect
    src = inspect.getsource(vf)
    at = src.index('result.get("capture_unavailable") or result.get("auth_unavailable")')
    # same boundary #655b uses for this branch
    window = src[at:src.index("FIX #75a: EVERY judged screen", at)]
    assert "compose_race_1202dm" in window, (
        "the refund branch still spends unreachable_refunds on the compose race")


def test_the_shared_cap_is_unchanged_for_everything_else():
    """#75a/#655b's bounds are not what this loosens."""
    assert vf._TRANSIENT_REFUND_CAP == 3
