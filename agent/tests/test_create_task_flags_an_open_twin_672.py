r"""#672: 55% of all cancelled tasks were duplicates, and create_task had no duplicate check.

`workhub_tasks` — 12,836 records over 144 runs — was one of the two largest unopened stores.
By terminal status: 9936 completed, 1304 still in_progress, **838 cancelled**, 706 pending,
52 failed.

Every one of the 838 carries a `cancel_reason` (the service refuses a reasonless cancel), and
grouping them:

    462 (55.1%)  duplicate of another task     — across 79 of 144 runs
     73 ( 8.7%)  projection/merge race
     18 ( 2.1%)  env not runnable / wind-down
     14 ( 1.7%)  false positive / wrong probe
    258 (30.8%)  other

The duplicate reasons are explicit: "Duplicate of task_...", "Subsumed into page-level commits",
"Deduped — blocked on frontend bug task_...", "Rolled into consolidated batch task_...".

`create_task` has no duplicate check of any kind — it validates priority and writes the record.
So every caller must roll its own, and step_runner's merge-conflict path is the only one that
does (#667's `_dup`). Each duplicate cost a create, a dispatch, a lane reading it, and a cancel
round-trip.

This does NOT block: two tasks may legitimately share a title across milestones or remediation
rounds, and refusing creation could lose real work. The new task is still created; it just
carries `duplicate_of` naming the open twin, so the caller sees the collision when it happens
instead of someone cancelling it later.

(First reading of this store reported all 838 reasons EMPTY — I looked for `metadata.cancel_reason`
while the service writes `cancel_reason` at the task's top level. Retracted; the mechanism is
sound and even refuses a cancel with no reason.)
"""
import pytest


class _Store:
    def __init__(self):
        self.data = {}

    def value(self):
        return self.data

    def get(self, k):
        return self.data.get(k)

    def update(self, fn, change_info=None):
        class _M:
            def __init__(s, d):
                s.d = d

            def set(s, k, v, agent=None):
                s.d[k] = v
                return s
        fn(_M(self.data))


class _Stores:
    def __init__(self):
        self.tasks = _Store()


def _svc():
    from env_generator.llm_generator.multi_agent.runtime.hubs.workhub.service import WorkHub
    s = WorkHub.__new__(WorkHub)
    s.stores = _Stores()
    s._emit = lambda *a, **k: None
    return s


def _mk(svc, title, assignee="frontend", **kw):
    return svc.create_task(title=title, assignee=assignee, agent="orchestrator", **kw)


# --- the collision is reported ------------------------------------------------------------------

def test_a_second_open_task_with_the_same_title_is_flagged():
    s = _svc()
    first = _mk(s, "Fix the login form")
    second = _mk(s, "Fix the login form")
    assert second.get("duplicate_of", {}).get("id") == first["id"]


def test_the_flag_names_the_twins_state():
    s = _svc()
    _mk(s, "Fix it")
    d = _mk(s, "Fix it")["duplicate_of"]
    assert d["status"] == "pending"
    assert "claimed_by" in d


def test_the_note_says_it_was_still_created():
    s = _svc()
    _mk(s, "Fix it")
    note = _mk(s, "Fix it")["duplicate_of"]["note"]
    assert "this one was still created" in note
    assert "cancel whichever is redundant" in note


def test_the_match_ignores_case_and_surrounding_space():
    s = _svc()
    first = _mk(s, "Fix The Login Form")
    assert _mk(s, "  fix the login form ")["duplicate_of"]["id"] == first["id"]


def test_an_in_progress_twin_counts():
    s = _svc()
    first = _mk(s, "Fix it")
    s.stores.tasks.data[first["id"]]["status"] = "in_progress"
    assert _mk(s, "Fix it").get("duplicate_of")


# --- it must not cry wolf ---------------------------------------------------------------------

def test_a_different_title_is_not_flagged():
    s = _svc()
    _mk(s, "Fix the login form")
    assert "duplicate_of" not in _mk(s, "Fix the signup form")


def test_a_different_assignee_is_not_flagged():
    """Two lanes doing the same-named work on their own surfaces is normal."""
    s = _svc()
    _mk(s, "Wire the API", assignee="frontend")
    assert "duplicate_of" not in _mk(s, "Wire the API", assignee="backend")


@pytest.mark.parametrize("state", ["completed", "cancelled", "failed"])
def test_a_terminal_twin_is_not_flagged(state):
    """Re-doing finished work is a new task, not a duplicate."""
    s = _svc()
    first = _mk(s, "Fix it")
    s.stores.tasks.data[first["id"]]["status"] = state
    assert "duplicate_of" not in _mk(s, "Fix it")


def test_the_first_task_is_never_flagged():
    assert "duplicate_of" not in _mk(_svc(), "Fix it")


def test_an_empty_title_never_matches():
    s = _svc()
    _mk(s, "")
    assert "duplicate_of" not in _mk(s, "")


# --- it must never cost a creation --------------------------------------------------------------

def test_the_task_is_created_either_way():
    s = _svc()
    _mk(s, "Fix it")
    second = _mk(s, "Fix it")
    assert second["id"] in s.stores.tasks.data
    assert second["status"] == "pending"


def test_it_does_not_block_or_error():
    s = _svc()
    _mk(s, "Fix it")
    assert "error" not in _mk(s, "Fix it")


def test_a_broken_store_still_creates_the_task():
    """Best-effort: a lookup fault must leave the result exactly as it was."""
    s = _svc()

    class _Boom(_Store):
        def value(self):
            raise RuntimeError("gone")

    boom = _Boom()
    s.stores.tasks = boom
    out = _mk(s, "Fix it")
    assert out["id"] in boom.data
    assert "duplicate_of" not in out


def test_priority_validation_still_runs_first():
    s = _svc()
    assert "error" in s.create_task(title="x", agent="a", priority="P9")


# --- provenance -------------------------------------------------------------------------------

def test_the_measurement_is_recorded():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime.hubs.workhub import service as sv
    flat = " ".join(inspect.getsource(sv.WorkHub.create_task).replace("#", " ").split())
    assert "462 of those" in flat and "79 of 144 runs" in flat


def test_the_decision_not_to_block_is_recorded():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime.hubs.workhub import service as sv
    flat = " ".join(inspect.getsource(sv.WorkHub.create_task).split())
    assert "This does NOT block" in flat
    assert "could lose real work" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
