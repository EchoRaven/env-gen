"""#1203gu: the escape window ran while the gate it guards was unreachable.

`squad_release_decision`'s 900s wall-clock is anchored to the squad's LAUNCH, but the gate
sits below `_maybe_framework_deliver`'s early return on a non-empty failed-check set -- so the
window can expire during a stretch in which this gate could not have been the blocker, and the
first tick that reaches it releases without the `'defect'` branch ever reading the verdict.

r171 measured it on two milestones: M3 shipped v1.2.0 with 4 open P0 after 26 consecutive
`gate_failed_checks` ticks, and M4's first reachable tick came SEVEN SECONDS after the window
closed while a 2-open-P0 verdict had been in hand since 661s. Corpus: 16 escapes report
`0 attempts` WITH a verdict in hand, across 10 of the 12 most recent runs, shipping 103 P0.

The fix spends ONE deferral on a verdict nobody has acted on. Its cost ceiling is structural:
the window has already expired, so the granted deferral makes `attempts` 1 and the next call
releases. These tests pin that ceiling, not just the happy path.
"""
import ast
import inspect
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime.test_user_squad import (
    squad_release_decision as _decide,
)

ORCH = (Path(__file__).resolve().parents[1]
        / "env_generator/llm_generator/multi_agent/orchestrator.py")


def test_an_unacted_verdict_past_the_window_defers():
    assert _decide(0.0, 0, 5000.0, verdict_unacted=True) == "defer"


def test_the_granted_deferral_releases_on_the_very_next_call():
    """The cost ceiling: one deferral, then the expired window releases."""
    assert _decide(0.0, 0, 5000.0, verdict_unacted=True) == "defer"
    assert _decide(0.0, 1, 5001.0, verdict_unacted=True) == "release"


def test_a_verdict_already_acted_on_does_not_buy_a_second_deferral():
    assert _decide(0.0, 1, 5000.0, verdict_unacted=True) == "release"


def test_no_verdict_past_the_window_still_releases():
    """The 132 corpus escapes that report `possibly-open` must behave exactly as before."""
    assert _decide(0.0, 0, 5000.0, verdict_unacted=False) == "release"
    assert _decide(0.0, 0, 5000.0) == "release"


def test_the_attempt_cap_still_wins_over_an_unacted_verdict():
    assert _decide(0.0, 3, 5000.0, verdict_unacted=True) == "release"
    assert _decide(0.0, 9, 5000.0, verdict_unacted=True) == "release"


def test_the_cap_releases_even_inside_the_window():
    """The real test of the cap: inside the window only `max_attempts` can release.

    The assertion above uses an EXPIRED window, so disabling the cap check entirely leaves it
    green -- a mutation caught that while this file was being written.
    """
    assert _decide(0.0, 3, 100.0, verdict_unacted=True) == "release"
    assert _decide(0.0, 3, 100.0, verdict_unacted=False) == "release"
    assert _decide(0.0, 2, 100.0, verdict_unacted=False) == "defer"


def test_inside_the_window_the_flag_changes_nothing():
    assert _decide(0.0, 0, 100.0, verdict_unacted=True) == "defer"
    assert _decide(0.0, 0, 100.0, verdict_unacted=False) == "defer"


def test_a_missing_clock_never_releases_on_wallclock():
    assert _decide(None, 0, 10 ** 9, verdict_unacted=True) == "defer"
    assert _decide(None, 0, 10 ** 9, verdict_unacted=False) == "defer"


def test_no_deadlock_is_reachable_from_any_state():
    """Exhaustive: past the window, EVERY start burns at most one attempt then releases."""
    for unacted in (True, False):
        attempts, released = 0, 0
        for tick in range(10):
            if _decide(0.0, attempts, 5000.0 + tick, verdict_unacted=unacted) == "release":
                released += 1
                break
            attempts += 1
        assert released == 1, unacted
        assert attempts <= 1, "a verdict may buy ONE deferral, never more"


def test_the_default_keeps_the_pre_gu_behaviour():
    """Callers that do not pass the flag must see exactly the old decision."""
    params = inspect.signature(_decide).parameters
    assert params["verdict_unacted"].default is False


def _gu_lines():
    return ORCH.read_text(encoding="utf-8").split("\n")


def test_the_caller_passes_the_flag_it_computes():
    """AST: the call site carries `verdict_unacted=` and its value comes from fj's reader."""
    tree = ast.parse(ORCH.read_text(encoding="utf-8"))
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name)
             and n.func.id == "squad_release_decision"]
    assert calls, "no call to squad_release_decision found"
    kw = {k.arg for c in calls for k in c.keywords}
    assert "verdict_unacted" in kw, "the caller never tells the decision a verdict is in hand"
    # the value must be derived from fj's reader, not hardcoded
    srcs = [ast.unparse(k.value) for c in calls for k in c.keywords if k.arg == "verdict_unacted"]
    names = [n for n in srcs]
    body = ORCH.read_text(encoding="utf-8")
    for n in names:
        assert "_inhand1203gu" in body, "the flag must be computed from squad_verdict_in_hand_1203fj"
        assert n.strip() not in ("True", "False"), "the flag must be computed, not hardcoded"


def test_the_read_sits_above_the_decision():
    """The positional property #1203fj lacked: reading a verdict after the decision is useless."""
    lines = _gu_lines()
    read = next(i for i, l in enumerate(lines) if "_inhand1203gu(getattr" in l)
    decide = next(i for i, l in enumerate(lines)
                  if "squad_release_decision(" in l and "import" not in l)
    assert read < decide, "fj's reader must run BEFORE the release decision"


def test_the_early_return_really_sits_above_the_clock_stamp():
    """The structural premise of this ticket: a red failed-check set returns above the gate."""
    lines = _gu_lines()
    early = next(i for i, l in enumerate(lines) if "return  # not deliverable yet" in l)
    stamp = next(i for i, l in enumerate(lines) if "_tu_squad_deferred_since = _now" in l)
    assert early < stamp, (
        "if the failed-check return no longer precedes the clock stamp, this ticket's "
        "diagnosis has changed and the comment above must be re-measured")
