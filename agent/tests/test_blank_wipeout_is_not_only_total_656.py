r"""#656: a capture that blanked 9 of 13 screens was "partial", so it got no refund and no score.

Same defect shape as #655, in the blank path. `capture_transient` was

    bool(_blank_screens) and not shots

— TOTAL blankness, nothing less. One surviving shot made a near-total blackout "partial".
Measured over the run logs: 58 blank events across 20 runs, and 18 of them (31%) name 8 or more
screens. Near-total, never total.

That matters because `_blocking_average` (#542a) drops every `blank is True` screen from its
denominator as "a transient env glitch" — with no bound and no persistence check. So a
near-total blackout neither refunds the attempt nor counts; the gate is decided by whatever few
screens survived:

    r60   9 blank -> the average was taken over 4 screens
    r43   7 blank -> over 5
    r121  4 blank -> over 4, giving blocking_average 0.6125

The rule needs no tuned constant: the gate must not be decided by FEWER screens than it
refunded. Bounded by the existing `_TRANSIENT_REFUND_CAP` (3), so a genuinely blank app still
flows to a real verdict. A true minority blank is unchanged — #75a's reason for that ("a
partial-blank must not discard a fixable sibling's 0.55 and suppress its remediation") holds
precisely while the siblings are the majority.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime.visual_fidelity import (
    _blank_wipeout_656 as wipeout,
)

_SHOTS = {"some_screen": "/tmp/a.png"}


def _results(blank, scored, advisory=0):
    return ([{"name": f"b{i}", "blank": True} for i in range(blank)]
            + [{"name": f"s{i}", "blank": False} for i in range(scored)]
            + [{"name": f"a{i}", "blank": True, "advisory": True} for i in range(advisory)])


def _call(blank, scored, advisory=0, shots=_SHOTS):
    return wipeout(_results(blank, scored, advisory), ["b%d" % i for i in range(blank)], shots)


# --- the runs this was measured on ---------------------------------------------------------------

@pytest.mark.parametrize("run,blank,scored", [("r60", 9, 4), ("r43", 7, 5), ("r121", 4, 4)])
def test_a_near_total_blackout_now_refunds(run, blank, scored):
    assert _call(blank, scored) is True, run


@pytest.mark.parametrize("run,blank,scored", [("r125", 3, 8), ("r72", 2, 12), ("r86", 1, 12)])
def test_a_minority_blank_still_flows_to_a_real_verdict(run, blank, scored):
    """#75a: a fixable sibling's 0.55 and its remediation must not be discarded."""
    assert _call(blank, scored) is False, run


def test_the_boundary_is_fewer_scored_than_refunded():
    """The whole rule: the gate must not be decided by fewer screens than it refunded."""
    assert _call(5, 5) is True         # equal — not credible
    assert _call(5, 6) is False        # scored screens are the majority


# --- the original case is untouched ------------------------------------------------------------

def test_a_total_blackout_still_refunds():
    assert wipeout(_results(9, 0), ["b0"], {}) is True
    assert wipeout([], ["b0"], {}) is True, "no results at all, but blanks recorded"


def test_no_blanks_is_never_a_refund():
    assert _call(0, 12) is False
    assert wipeout(_results(0, 12), [], {}) is False, "no shots but nothing blanked either"


def test_an_empty_run_is_safe():
    assert wipeout([], [], {}) is False
    assert wipeout(None, None, None) is False


# --- advisory screens must not tip the scale -------------------------------------------------------

def test_advisory_screens_are_outside_the_decision():
    """#542a already excludes them from the gate; they must not vote on its credibility."""
    assert _call(2, 12, advisory=8) is False
    assert _call(7, 5, advisory=8) is True


def test_a_run_of_only_advisory_screens_never_refunds():
    res = [{"name": "a", "blank": True, "advisory": True}]
    assert wipeout(res, ["a"], _SHOTS) is False


# --- properties ----------------------------------------------------------------------------

def test_it_is_deterministic_and_pure():
    res, blanks = _results(7, 5), ["b0"]
    before = [dict(r) for r in res]
    assert wipeout(res, blanks, _SHOTS) == wipeout(res, blanks, _SHOTS)
    assert res == before


def test_malformed_records_do_not_crash_it():
    res = [None, "x", {"blank": True}, {"blank": False}]
    assert wipeout(res, ["b"], _SHOTS) is True


# --- wiring ---------------------------------------------------------------------------------

def test_the_returned_flag_uses_it():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf
    src = inspect.getsource(vf.run_visual_fidelity)
    assert '"capture_transient": _blank_wipeout_656(results, _blank_screens, shots)' in src
    assert "bool(_blank_screens) and not shots" not in src


def test_the_existing_cap_still_bounds_it():
    """A genuinely blank app must not defer forever — #656 adds no new escape hatch."""
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf
    src = inspect.getsource(vf)
    assert "self.transient_refunds < _TRANSIENT_REFUND_CAP" in src


def test_the_measurement_is_recorded():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf
    flat = " ".join(inspect.getsource(vf._blank_wipeout_656).replace("#", " ").split())
    assert "58 blank events across 20 runs" in flat
    assert "18 of them (31%)" in flat
    assert "r60 9 blank -> the average was taken over 4 screens" in flat


def test_why_a_minority_blank_is_left_alone_is_recorded():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf
    flat = " ".join(inspect.getsource(vf._blank_wipeout_656).split())
    assert "while the siblings are the majority" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
