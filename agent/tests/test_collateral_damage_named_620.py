r"""#620: name the screens the last round broke.

#129 keeps a LATCHED (already-passed) screen out of the fix list so the lane is not told to
re-work something it already got right. That cannot stop the lane from BREAKING it while fixing
another screen — they share components (a nav bar, a card).

Tracking every screen that left the below-bar list and later came back:

    113 REAL fall-backs across 12 runs   (scores like 0.03 / 0.05 / 0.42)
     32 fall-backs to 0.00               (the env-down captures #500's merge exists to absorb)

The two are separated deliberately: treating the 0.00s as regressions would repeat the mistake of
believing a signal without a control.

#619 tells the lane the average moved. It never said WHICH screen was lost — and a latched screen
is precisely the one nothing else in the task body mentions, because #129 removed it.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime.visual_fidelity import remediation_text as rt


def _result(**scores):
    return {"min_similarity": 0.65,
            "summary": "x",
            "screens": [{"name": n, "route": f"/{n}", "similarity": v, "dimensions": {}}
                        for n, v in scores.items()]}


# --- the warning ---------------------------------------------------------------------------

def test_a_latched_screen_below_the_bar_is_named_with_its_score():
    body = rt(_result(login=0.50, shows=0.03), None, {"shows"})
    assert body.startswith("⚠ COLLATERAL DAMAGE")
    assert "shows (0.03)" in body


def test_it_says_why_the_screen_is_not_in_the_fix_list():
    body = rt(_result(login=0.50, shows=0.03), None, {"shows"})
    assert "#129 keeps a passed screen out of it" in body
    assert "shared component" in body


def test_several_broken_screens_are_all_named():
    body = rt(_result(login=0.50, shows=0.03, movies=0.05), None, {"shows", "movies"})
    assert "movies (0.05)" in body and "shows (0.03)" in body


def test_the_warning_precedes_the_round_feedback_and_the_fix_list():
    body = rt(_result(login=0.50, shows=0.03), None, {"shows"},
              prev_live=0.62, this_live=0.48, round_no=7)
    assert body.index("COLLATERAL DAMAGE") < body.index("Round 7.") < body.index("## login")


# --- when it must stay silent -----------------------------------------------------------------

def test_a_latched_screen_still_ABOVE_the_bar_is_not_named():
    body = rt(_result(login=0.50, shows=0.80), None, {"shows"})
    assert "COLLATERAL DAMAGE" not in body


def test_a_failing_screen_that_never_latched_is_not_collateral_damage():
    """It is in the fix list already — that is where it belongs."""
    body = rt(_result(login=0.50, shows=0.03), None, set())
    assert "COLLATERAL DAMAGE" not in body
    assert "## shows" in body


def test_nothing_latched_means_no_header():
    assert rt(_result(login=0.50), None, set()).startswith("Visual fidelity below threshold")


def test_a_missing_or_non_numeric_score_cannot_trigger_it():
    r = _result(login=0.50)
    r["screens"].append({"name": "shows", "route": "/shows", "dimensions": {}})
    assert "COLLATERAL DAMAGE" not in rt(r, None, {"shows"})


def test_the_bar_comes_from_the_result_not_a_constant():
    """A run with a different min_similarity must be judged against its own bar."""
    r = _result(login=0.50, shows=0.70)
    r["min_similarity"] = 0.80
    assert "shows (0.70)" in rt(r, None, {"shows"})


def test_the_latched_screen_is_still_excluded_from_the_fix_list():
    """#620 names it; #129's exclusion must remain in force."""
    body = rt(_result(login=0.50, shows=0.03), None, {"shows"})
    assert "## shows" not in body


def test_the_measurement_that_justifies_it_is_recorded():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf
    flat = " ".join(inspect.getsource(vf.remediation_text).replace("#", " ").split())
    assert "113 real fall-backs across 12 runs" in flat
    assert "only 32" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
