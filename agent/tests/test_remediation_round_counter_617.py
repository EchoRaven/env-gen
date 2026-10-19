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
import asyncio
import inspect
import pathlib
import types

import pytest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf


@pytest.fixture(scope="module")
def src():
    """Slice to a SEMANTIC boundary, not a character count — a fixed window breaks the
    moment anything is inserted into the block (it did, when #619 landed)."""
    mod = inspect.getsource(vf)
    i = mod.index("#617 — THE TASK TITLE BORROWED THE WRONG COUNTER")
    j = mod.index("priority=\"P1\"", i)
    return mod[i:j]


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


# --- #1203pg: the counter actually ADVANCES, driven ----------------------------------------------
#
# The assertion above quotes the increment as a whole statement, which cannot see whether it
# runs. A mutation that wrapped it in `if False:` left the statement verbatim in the source and
# every assertion in this file green -- while restoring the exact state the ticket is about:
# 280 visual-gate remediation tasks across the corpus, every single one titled identically, so
# the lane could not tell it was being asked the 21st time.


def _orch_1203pg(box, created):
    _noop = lambda *a, **k: None  # noqa: E731

    class _Bus:
        async def send(self, *a, **k):
            return None

    def _create(**kw):
        created.append(kw)
        return {"id": "t%d" % len(created)}

    return types.SimpleNamespace(
        _reference_images=[{"name": "inbox", "route": "/inbox", "auth": True, "path": "x.png"}],
        _compute_app_source_signature=lambda: box["sig"],
        output_dir=str(pathlib.Path(__file__).resolve().parents[1]),
        llm=None, message_bus=_Bus(),
        _logger=types.SimpleNamespace(warning=_noop, info=_noop, error=_noop, debug=_noop),
        hubs=types.SimpleNamespace(workhub=types.SimpleNamespace(create_task=_create)),
    )


def _failing_round():
    async def _fake(*a, **k):
        return {"passed": False, "capture_transient": False, "skipped": [],
                "summary": "rendered but imperfect",
                "screens": [{"name": "inbox", "route": "/inbox", "similarity": 0.3,
                             "blank": False, "console_errors": [],
                             "deviations": ["colour"], "fixes": []}]}
    return _fake


def _rounds(monkeypatch, n):
    """Run `n` failing visual rounds and return the remediation task titles, in order."""
    created, box = [], {"sig": "sig0"}
    gate = vf.VisualFidelityGate(_orch_1203pg(box, created))
    gate.reset_for_milestone()
    monkeypatch.setattr(vf, "run_visual_fidelity", _failing_round())
    for i in range(n):
        box["sig"] = "lane-change-%d" % i      # a fresh source state each round
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(gate.maybe_run())
        finally:
            loop.close()
    return [c.get("title", "") for c in created]


def test_a_remediation_task_is_actually_filed(monkeypatch):
    """Non-vacuity: without this the uniqueness test below passes on an empty list."""
    titles = _rounds(monkeypatch, 1)
    assert titles, "no remediation task was filed at all"


def test_the_round_number_advances_between_dispatches(monkeypatch):
    titles = _rounds(monkeypatch, 3)
    assert len(titles) >= 2, titles
    assert "round 1" in titles[0], titles[0]
    assert "round 2" in titles[1], titles[1]


def test_no_two_dispatches_share_a_title(monkeypatch):
    """The ticket's own measurement, as a property: 280 tasks, every one titled the same."""
    titles = _rounds(monkeypatch, 3)
    assert len(set(titles)) == len(titles), titles


def test_the_counter_survives_a_milestone_reset(monkeypatch):
    """`_remediation_round` counts DISPATCHES, not attempts, so it is not milestone-scoped —
    pinned so a later change of scope is a decision rather than a drift."""
    titles = _rounds(monkeypatch, 2)
    assert "round 1" in titles[0] and "round 2" in titles[1]
