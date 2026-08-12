r"""#619: tell the lane whether its last round helped.

#617 found every remediation round labelled "attempt 1" (280 of 280). #618 found the persisted
score keeps the best-of-captures merge, so a regression never reaches the record (the record
beats the live code in 24 of 39 runs, by up to +0.44). Between them the lane had no way to learn
from its own previous round — and the outcome shows it: across the 29 runs with two or more
scored rounds, **19 improved but 10 ended WORSE** than they started (r103 −0.40 over 12 rounds),
at a mean of **+0.003 per round**.

The gate already holds both numbers when it writes the task. Leading with the delta costs nothing
and is the one piece of feedback a blind retry loop lacks:

    worse       -> name the regression and suggest reverting that round FIRST
    better      -> say so, keep going
    unchanged   -> say the last kind of change did nothing; try another dimension

With no previous round to compare (the first dispatch, or a caller that passes nothing) the body
is byte-identical to before.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime.visual_fidelity import remediation_text as rt

_RESULT = {"screens": [{"name": "login", "route": "/login", "similarity": 0.5,
                        "dimensions": {}}], "summary": "x"}


def _head(**kw):
    return rt(_RESULT, None, set(), **kw).split("\n")[0]


# --- the three branches -----------------------------------------------------------------

def test_a_regression_is_named_and_reverting_is_suggested_first():
    h = _head(prev_live=0.62, this_live=0.48, round_no=7)
    assert "MADE THIS WORSE" in h and "0.62" in h and "0.48" in h and "-0.14" in h
    assert "reverting" in h


def test_an_improvement_says_keep_going():
    h = _head(prev_live=0.48, this_live=0.61, round_no=8)
    assert "helped" in h and "+0.13" in h and "same direction" in h


def test_noise_is_called_noise_and_redirects_the_effort():
    h = _head(prev_live=0.50, this_live=0.505, round_no=9)
    assert "effectively nothing" in h and "different dimension" in h


def test_the_round_number_is_shown():
    assert _head(prev_live=0.5, this_live=0.4, round_no=12).startswith("Round 12.")


# --- what must not change -----------------------------------------------------------------

def test_no_previous_round_leaves_the_body_untouched():
    assert rt(_RESULT, None, set()).startswith("Visual fidelity below threshold")


def test_a_missing_or_non_numeric_delta_is_inert():
    for kw in ({"prev_live": None, "this_live": 0.5},
               {"prev_live": 0.5, "this_live": None},
               {"prev_live": "x", "this_live": 0.5}):
        assert rt(_RESULT, None, set(), **kw).startswith("Visual fidelity below threshold")


def test_the_screen_list_still_follows_the_header():
    body = rt(_RESULT, None, set(), prev_live=0.62, this_live=0.48, round_no=3)
    assert "## login" in body and body.index("MADE THIS WORSE") < body.index("## login")


def test_the_latched_exclusion_still_applies():
    """FIX #129: a screen that already cleared the bar must stay out of the fix list."""
    body = rt(_RESULT, None, {"login"}, prev_live=0.62, this_live=0.48, round_no=3)
    assert "## login" not in body


# --- wiring ------------------------------------------------------------------------------------

def test_the_dispatch_passes_both_numbers_and_the_round():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf
    src = inspect.getsource(vf)
    i = src.index("prev_live=_prev_live")
    window = src[i:i + 200]
    assert "this_live=_this_live" in window and "round_no=self._remediation_round" in window


def test_the_previous_value_is_stored_for_the_next_round():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf
    src = inspect.getsource(vf)
    i = src.index("_prev_live = getattr(self,")
    assert "self._prev_live_average = _this_live" in src[i:i + 200]


def test_the_live_average_uses_the_same_exclusions_as_part_A():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf
    src = inspect.getsource(vf)
    i = src.index("#619: what THIS capture scored")
    window = src[i:i + 600]
    assert 'not x.get("advisory")' in window and 'x.get("blank") is not True' in window


def test_the_measurement_that_justifies_it_is_recorded():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf
    flat = " ".join(inspect.getsource(vf.remediation_text).replace("#", " ").split())
    assert "10 ended WORSE" in flat and "+0.003 per round" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
