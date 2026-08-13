r"""#642: "stale claimed task" aged the AGENT, not the task.

Auditing `integrity_check` — 1961 events across 42 runs, never looked at before — the loose ends
it reports are dominated by one flag:

    stale_claimed_tasks          65% of all checks, 41 runs, up to 70 in a single run
    dirty_worktree               58%, 42 runs
    unhandled_breaking_changes   32%, 15 runs

65% is the tell. The condition never looked at the task:

    if step_num >= stale_threshold:        # the AGENT's step number
        details["stale_claimed_tasks"].append(...)

From an agent's 5th step onward, EVERY in-progress task it held was reported stale — including
one claimed a second earlier. The old comment justified it as an approximation "since we don't
have step_num at claim time", but `claimed_at` is recorded and is read two lines below into the
payload. The real signal was in hand the whole time.

A flag that is almost always true carries no information, and it teaches the agent to ignore a
category that also contains the genuine cases — the same failure as #623's mislabel and #634's
Python-shaped error.

The replacement threshold comes from the data, not from feel. Over 3992 completed tasks the
claim→finish time is p50 2.7 min, p90 17.5, p95 29.1, max 81.9. Thirty minutes flags **4.4%** of
tasks that did complete, against 100% before.
"""
import time

import pytest

from env_generator.llm_generator.multi_agent.agents.runtime.commit_gate import (
    DEFAULT_THRESHOLDS,
    collect_loose_ends_details,
)


class _WorkHub:
    def __init__(self, tasks):
        self._tasks = tasks

    def list_tasks(self, assignee=None, status=None):
        return [t for t in self._tasks if t.get("status") == status]


class _Hubs:
    def __init__(self, tasks):
        self.workhub = _WorkHub(tasks)


def _task(age_min=None, tid="t1"):
    t = {"id": tid, "title": "x", "status": "in_progress"}
    if age_min is not None:
        t["claimed_at"] = time.time() - age_min * 60
    return t


def _stale(tasks, step_num=50, thresholds=None):
    d = collect_loose_ends_details(_Hubs(tasks), "frontend", step_num,
                                   thresholds or DEFAULT_THRESHOLDS)
    return [s["id"] for s in d["stale_claimed_tasks"]]


# --- the defect ---------------------------------------------------------------------------------

def test_a_task_claimed_seconds_ago_is_not_stale():
    """The whole bug: at step 50, a one-second-old claim was reported stale."""
    assert _stale([_task(age_min=0.01)]) == []


def test_a_task_held_past_the_threshold_is_stale():
    assert _stale([_task(age_min=45)]) == ["t1"]


def test_the_agents_step_number_no_longer_decides():
    """Same task, same age, wildly different step numbers — the verdict must not move."""
    young = _task(age_min=1)
    assert _stale([young], step_num=5) == _stale([young], step_num=500) == []


def test_a_typical_task_is_never_flagged():
    """p50 of completed tasks is 2.7 min and p90 is 17.5."""
    assert _stale([_task(age_min=2.7)]) == []
    assert _stale([_task(age_min=17.5)]) == []


def test_the_p95_boundary_is_where_it_starts():
    assert _stale([_task(age_min=29)]) == []
    assert _stale([_task(age_min=31)]) == ["t1"]


def test_only_the_old_ones_are_reported():
    out = _stale([_task(1, "fresh"), _task(60, "old"), _task(3, "mid")])
    assert out == ["old"]


# --- the fallback and the guards --------------------------------------------------------------

def test_a_task_with_no_claim_time_keeps_the_old_heuristic():
    """Behaviour must not change where the timestamp is genuinely absent."""
    assert _stale([_task(age_min=None)], step_num=50) == ["t1"]
    assert _stale([_task(age_min=None)], step_num=1) == []


def test_a_bogus_claim_time_falls_back_too():
    t = _task(age_min=None)
    t["claimed_at"] = "yesterday"
    assert _stale([t], step_num=50) == ["t1"]
    t["claimed_at"] = 0
    assert _stale([t], step_num=1) == []


def test_the_threshold_is_configurable():
    assert _stale([_task(age_min=10)], thresholds={**DEFAULT_THRESHOLDS,
                                                   "stale_task_seconds": 300}) == ["t1"]


def test_a_pending_task_is_not_a_claimed_one():
    assert _stale([{"id": "p", "status": "pending", "title": "x"}]) == []


def test_the_default_is_thirty_minutes():
    assert DEFAULT_THRESHOLDS["stale_task_seconds"] == 1800


def test_a_missing_workhub_does_not_raise():
    class _Empty:
        workhub = None
    d = collect_loose_ends_details(_Empty(), "frontend", 9, DEFAULT_THRESHOLDS)
    assert d["stale_claimed_tasks"] == []


# --- why -------------------------------------------------------------------------------------

def test_the_measurement_is_recorded():
    import inspect
    from env_generator.llm_generator.multi_agent.agents.runtime import commit_gate
    flat = " ".join(inspect.getsource(commit_gate.collect_loose_ends_details)
                    .replace("#", " ").split())
    assert "65% of the 1961 integrity checks across 41 runs" in flat
    assert "p95 29.1" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
