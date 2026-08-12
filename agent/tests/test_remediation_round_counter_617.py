r"""#617: every remediation round told the lane it was the first.

Chasing "is agent self-healing the bottleneck?", the loop turns out to be alive and the amnesia
is the defect.

    capture rounds per run   median 7   (max 26)   — the gate DOES re-measure
    visual-gate tasks/run    median 6   (max 21)   — it DOES re-dispatch
    of 280 such tasks in 40 runs, ALL 280 are titled "attempt 1"

`self.attempts` is the JUDGING budget for the CURRENT frontend source — reset to 0 whenever the
source changes, capped at 3. A remediation always changes the source, so by the time the next
verdict lands it is 1 again. The title borrowed a variable that means something else.

The cost is not cosmetic: the lane cannot tell it is being asked the twenty-first time about the
same screens, and any escalation or give-up logic keyed on the round can never fire. The two
counters are now distinct and both are shown — the round, and the judge's per-source budget.
"""
import inspect

import pytest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf


@pytest.fixture(scope="module")
def src():
    mod = inspect.getsource(vf)
    i = mod.index("#617")
    return mod[i:i + 2200]


def test_the_title_reports_a_ROUND(src):
    assert 'f"round {self._remediation_round}' in src


def test_the_title_still_shows_the_judging_budget_separately(src):
    assert "judge attempt " in src and "{self.attempts}/3 on this source" in src


def test_the_round_increments_per_dispatch(src):
    assert 'self._remediation_round = getattr(self, "_remediation_round", 0) + 1' in src


def test_it_increments_BEFORE_the_task_is_created(src):
    assert src.index("_remediation_round") < src.index("create_task(")


def test_the_judging_budget_is_left_alone(src):
    """`self.attempts` still means what the judge needs it to mean — the per-source cap."""
    assert "self.attempts = " not in src


def test_the_per_source_reset_that_caused_this_is_still_intact():
    mod = inspect.getsource(vf)
    assert "fresh per-source judging budget" in mod
    assert "if self.attempts >= 3:" in mod


def test_the_counter_survives_an_instance_without_the_attribute(src):
    """`getattr(..., 0)` so an object constructed before this change cannot raise."""
    assert 'getattr(self, "_remediation_round", 0)' in src


def test_the_measurement_that_justifies_it_is_recorded(src):
    flat = " ".join(src.replace("#", " ").split())
    assert "280 visual-gate remediation tasks" in flat
    assert "every single one titled" in flat


def test_the_loop_being_HEALTHY_is_recorded_too(src):
    """The finding is amnesia, not a dead loop — the next reader must not 'fix' the wrong thing."""
    flat = " ".join(src.replace("#", " ").split())
    assert "7 capture rounds per run" in flat and "182" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
