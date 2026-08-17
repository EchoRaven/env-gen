r"""#892: bound the visual round — but spend the budget as verdicts, not as skips.

#872 bounded ONE judge call at 300s and left the round at ~12 × that = 60 minutes, with the gate's
escapes (`escape_s`, attempt cap, plateau) evaluated only **between** rounds. 70 of the 94
non-completed corpus runs die at this gate.

★ **#872 recorded a per-round cap as "actively harmful", and that was right about the version I
had in mind.** A budget that stops *starting* screens leaves them out of `results`, and an absent
screen is `unjudged` — *"an owned screen that was never judged is a FAILURE, not a skip"* — which
converts a slow run into a permanently failing one.

**The harm was in the skip, not in the bound.** `judged = {r["name"] for r in results}` counts a
screen that appears **at all**, so recording the remaining screens as `judge_error` verdicts
(0.0, `judge_error: True`) keeps them judged: the state #142 refuses to cache and re-judges next
round, and the state a #872 timeout already produces. Bounded *and* recoverable.

That distinction is the whole ticket, and it is why the earlier refusal was correct to make and
correct to revisit — the objection was to a mechanism, not to the goal.
"""
import inspect
import re

import pytest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf


def _span():
    src = inspect.getsource(vf)
    start = src.index("#892: a per-ROUND budget")
    end = src.index("shot = shots.get", start)
    return src[start:end]


def test_the_budget_exists():
    span = _span()
    assert "_round_budget_892" in span
    assert "monotonic()" in span


def test_it_records_a_verdict_instead_of_skipping():
    """★ The safety property, and the entire difference from the version #872 refused.

    ★ REWRITTEN as behaviour. Every assertion in this file used to read source TEXT, and the round
    budget is `max(_judge_timeout_s_872(), env)` — the env var can only RAISE it — so nothing in a
    test or in the field could ever reach this path. The mechanism had never been executed. The
    verdict is now built by `_spent_verdict_892`, so it can be."""
    v = vf._spent_verdict_892({"name": "player", "route": "/watch/:id"})
    assert v["judge_error"] is True
    assert v["similarity"] == 0.0
    assert v["dimensions"] == {}


def test_the_recorded_screen_counts_as_JUDGED():
    """★ The property the whole ticket exists for, asserted against the consumer's own expression.
    `judged = {r["name"] for r in results}` counts a screen that appears AT ALL — so a record
    without `name` is a skip wearing a verdict's clothes, and an unjudged owned screen fails the
    verdict outright."""
    v = vf._spent_verdict_892({"name": "player", "route": "/watch/:id"})
    judged = {r["name"] for r in [v]}
    assert "player" in judged
    assert v["route"] == "/watch/:id"


def test_advisory_status_is_preserved():
    """An advisory screen recorded as blocking would change the verdict's arithmetic."""
    assert vf._spent_verdict_892({"name": "s", "route": "/s", "advisory": True})["advisory"] is True
    assert vf._spent_verdict_892({"name": "s", "route": "/s"})["advisory"] is False
    assert vf._spent_verdict_892({"name": "s", "route": "/s", "advisory": 0})["advisory"] is False


def test_the_deviation_says_why_and_names_the_ticket():
    """It reaches the judge-missing-list analysis and the remediation prompt; "" would read as a
    screen that was judged and found perfect."""
    v = vf._spent_verdict_892({"name": "s", "route": "/s"})
    assert v["deviations"] and "budget" in v["deviations"][0]
    assert "892" in v["deviations"][0]
    assert v["summary"]


def test_the_loop_uses_the_helper():
    """Non-vacuity for the tests above: they are only meaningful if the round loop calls this."""
    assert "results.append(_spent_verdict_892(screen))" in _span()


def test_the_budget_is_at_least_one_full_judge_call():
    """★ Below `_judge_timeout_s_872` the budget could expire during the first honest slow screen
    and no round would ever complete — the relationship, not the number, is the claim."""
    src = inspect.getsource(vf)
    # #898: the per-call ceiling became an accessor, so the round budget calls it.
    assert re.search(r"_round_budget_892 = max\(\s*\n?\s*_judge_timeout_s_872\(\),", src), src[
        src.index("_round_budget_892 = max"):src.index("_round_budget_892 = max") + 160]
    assert vf._judge_timeout_s_872() > 588.9, "one honest slow call must fit inside the budget"
    assert "ENVGEN_JUDGE_ROUND_BUDGET_S" in src


def test_spending_the_budget_is_audible():
    span = _span()
    assert "_LOG.error" in span
    assert "ROUND BUDGET SPENT" in span
    assert "NOT skipped" in span


def test_the_unjudged_failure_it_avoids_is_still_real():
    """Non-vacuity for the premise: if `visual_gate_verdict` stops failing on unjudged screens,
    the skip-versus-verdict distinction stops mattering and this note should be re-read."""
    src = inspect.getsource(vf)
    assert "never judged is a FAILURE, not a skip" in src
    assert 'judged = {str(r.get("name") or "") for r in rs}' in src


def test_a_transient_zero_is_still_not_cached():
    """#142 is what makes the spent-budget verdict recoverable rather than a pin at 0.0."""
    src = inspect.getsource(vf)
    assert "must never cache it" in src


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
