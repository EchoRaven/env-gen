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
    """★ The safety property, and the entire difference from the version #872 refused."""
    span = _span()
    i = span.index("if _spent_892:")
    block = span[i:]
    assert "results.append" in block
    assert '"judge_error": True' in block
    assert '"similarity": 0.0' in block
    assert block.rstrip().endswith("continue")


def test_the_recorded_screen_keeps_its_identity():
    """It must carry `name` — that is the only field `judged` looks at, so a verdict without it
    is a skip wearing a verdict's clothes."""
    span = _span()
    assert '"name": screen["name"]' in span
    assert '"route": screen["route"]' in span


def test_advisory_status_is_preserved():
    """An advisory screen recorded as blocking would change the verdict's arithmetic."""
    assert '"advisory": bool(screen.get("advisory"))' in _span()


def test_the_budget_is_at_least_one_full_judge_call():
    """★ Below `_JUDGE_TIMEOUT_S_872` the budget could expire during the first honest slow screen
    and no round would ever complete — the relationship, not the number, is the claim."""
    assert vf._JUDGE_TIMEOUT_S_872 == 300.0
    src = inspect.getsource(vf)
    assert re.search(r"_round_budget_892 = max\(\s*\n?\s*_JUDGE_TIMEOUT_S_872,", src)
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
