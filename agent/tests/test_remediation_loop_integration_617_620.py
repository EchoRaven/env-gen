r"""#617–#620 together: one realistic round, end to end.

Four commits touch the same path — the round counter (#617), the live-vs-record divergence
(#618), the round-delta feedback (#619) and the collateral-damage naming (#620). Each has its own
unit tests; this pins that they still compose, because the failure mode of a four-part change is
that each part passes alone and the whole says something incoherent.

The scenario is the one the arc actually produces: a screen that had cleared the bar is broken by
a later round, another screen has never passed, and one is advisory.

    shows              0.72 previously, 0.03 now, LATCHED   -> collateral damage
    login              0.50, never latched                   -> ordinary fix-list entry
    card_hover_preview 0.20, advisory                        -> out of both averages

Expected: the record keeps the best (0.61), the live number reports this capture (0.265), the
divergence is flagged (+0.345), and the task body leads with what broke, then the direction, then
the list.
"""
import json
import os

import pytest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf

_RESULTS = [
    {"name": "shows", "route": "/shows", "similarity": 0.03, "dimensions": {}},
    {"name": "login", "route": "/login", "similarity": 0.50, "dimensions": {}},
    {"name": "card_hover_preview", "route": "/x", "similarity": 0.20, "advisory": True},
]


@pytest.fixture()
def verdict(tmp_path):
    vdir = tmp_path / "design" / "visual_gate"
    vdir.mkdir(parents=True)
    # a prior, better capture — forces #500's best-of merge to matter
    (vdir / "verdict.json").write_text(json.dumps({"screens": [
        {"name": "shows", "route": "/shows", "similarity": 0.72},
        {"name": "login", "route": "/login", "similarity": 0.50}]}), encoding="utf-8")
    vf._persist_verdict(str(tmp_path), passed=False, min_similarity=0.65,
                        summary="s", coverage={}, results=_RESULTS)
    return json.loads((vdir / "verdict.json").read_text(encoding="utf-8"))


# --- the record ------------------------------------------------------------------------------

def test_the_record_keeps_the_best_capture(verdict):
    """#500 is untouched: `shows` stays at its 0.72, so the headline metric is unchanged."""
    assert verdict["blocking_average"] == pytest.approx(0.61, abs=0.005)


def test_the_live_number_reports_THIS_capture(verdict):
    assert verdict["blocking_average_live"] == pytest.approx(0.265, abs=0.005)


def test_the_advisory_screen_is_in_neither_average(verdict):
    """0.20 would drag both numbers; #542a keeps advisory out of Part-A."""
    assert verdict["blocking_average"] > 0.3 and verdict["blocking_average_live"] > 0.2


def test_the_divergence_is_flagged_with_its_size(verdict):
    assert verdict["record_exceeds_live_by"] == pytest.approx(0.345, abs=0.005)
    assert "worse than the recorded number" in verdict["record_exceeds_live_note"]


# --- the task the lane receives ------------------------------------------------------------------

@pytest.fixture()
def body():
    return vf.remediation_text(
        {"min_similarity": 0.65, "summary": "s", "screens": _RESULTS},
        None, {"shows"}, prev_live=0.61, this_live=0.27, round_no=9)


def test_it_leads_with_what_broke_then_the_direction_then_the_list(body):
    assert body.index("COLLATERAL DAMAGE") < body.index("Round 9.") < body.index("## login")


def test_the_broken_latched_screen_is_named_but_not_re_listed(body):
    assert "shows (0.03)" in body
    assert "## shows" not in body          # FIX #129's exclusion still holds


def test_the_regression_direction_is_stated_with_both_numbers(body):
    assert "0.61" in body and "0.27" in body and "-0.34" in body
    assert "reverting" in body


def test_the_round_number_is_the_dispatch_count_not_the_judge_budget(body):
    """#617: `self.attempts` resets on every source change; the round must not."""
    assert body.startswith("⚠ COLLATERAL DAMAGE") and "Round 9." in body


def test_the_never_latched_failing_screen_is_still_worked(body):
    assert "## login" in body


def test_a_clean_first_round_produces_none_of_this(body):
    """No previous round, nothing latched → byte-identical to the pre-#617 body."""
    plain = vf.remediation_text(
        {"min_similarity": 0.65, "summary": "s", "screens": _RESULTS}, None, set())
    assert plain.startswith("Visual fidelity below threshold")
    assert "COLLATERAL DAMAGE" not in plain and "Round" not in plain.split("\n")[0]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
