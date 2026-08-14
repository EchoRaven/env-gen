r"""#744: 62% of the "open P0 bugs" the delivery path counts are already fixed.

`list_open_bugs` filtered on `metadata.bug_state` alone. That field is written at creation and
moved only by `update_bug_state`/`close_bug`, which almost nobody calls — across the 1477 bug
tasks in the 148-run corpus it reads:

    open 1201   assigned 224   escalated 41   closed 6   fix_proposed 3   triaged 1
    fix_verified 1

**Six.** Completing the TASK does not touch it, so 616 tasks sit at `status=completed` with
`bug_state=open`, and `OPEN_STATES` counts both `open` and `assigned`. Two fields encode one
lifecycle, and only one of them is maintained.

Measured on the population the delivery path actually reads:

    open P0s by bug_state alone           821  across 120 runs
    ... also excluding a terminal status  310  across  90 runs
    already fixed but counted as open     511  (62%)

This is not cosmetic. `collect_open_p0_by_source` (#630) is built on this list, its result
becomes `bugs["p0"]`, and that value's only use is
``verdict = "PASS" if bugs["p0"] == 0 else "DEFECTS"`` — a verdict the delivery gate reads. So a
run that FIXED every P0 still scored DEFECTS and deferred. #630 widened that gate deliberately
and correctly (the verifier files 207 of 314 P0s and was invisible to it); the stale field then
turned the widened gate hardest against the runs that had done the work.

`failed` is deliberately not terminal: an attempted fix that did not work leaves the bug
outstanding — the same reading #743 takes of that status.
"""
import inspect

import pytest

from env_generator.llm_generator.multi_agent.runtime import bug_schema
from env_generator.llm_generator.multi_agent.runtime.hubs.workhub import service as svc


class _Store:
    def __init__(self, tasks):
        self._t = tasks

    def value(self):
        return self._t


class _Stores:
    def __init__(self, tasks):
        self.tasks = _Store(tasks)


def _svc(tasks):
    s = object.__new__(svc.WorkHub)
    s.stores = _Stores(tasks)
    return s


def _bug(tid, status, bug_state="open", severity="P0", created=0.0):
    return {"id": tid, "status": status, "created_at": created,
            "metadata": {"kind": bug_schema.KIND, "bug_state": bug_state,
                         "severity": severity}}


# --- the defect -------------------------------------------------------------------------------

def test_a_completed_bug_is_not_open():
    s = _svc({"a": _bug("a", "completed")})
    assert s.list_open_bugs() == []


def test_a_cancelled_bug_is_not_open():
    s = _svc({"a": _bug("a", "cancelled")})
    assert s.list_open_bugs() == []


def test_the_616_shape_is_covered():
    """status=completed while bug_state stayed `open` — the exact corpus shape, 616 of them."""
    s = _svc({"a": _bug("a", "completed", "open"),
              "b": _bug("b", "completed", "assigned"),
              "c": _bug("c", "pending", "open")})
    assert [b["id"] for b in s.list_open_bugs()] == ["c"]


# --- what must STILL be open ----------------------------------------------------------------------

def test_a_failed_bug_is_still_open():
    """An attempted fix that did not work leaves the bug outstanding (#743's reading)."""
    s = _svc({"a": _bug("a", "failed")})
    assert [b["id"] for b in s.list_open_bugs()] == ["a"]


@pytest.mark.parametrize("status", ["pending", "in_progress", "failed", "", None])
def test_every_non_terminal_status_stays_open(status):
    s = _svc({"a": _bug("a", status)})
    assert len(s.list_open_bugs()) == 1


def test_a_closed_bug_state_is_still_excluded():
    """#744 ADDS a condition; it must not weaken the original one."""
    s = _svc({"a": _bug("a", "pending", "closed"), "b": _bug("b", "pending", "escalated")})
    assert s.list_open_bugs() == []


def test_the_original_open_states_are_untouched():
    assert bug_schema.OPEN_STATES == frozenset(
        {"open", "triaged", "assigned", "in_progress", "fix_proposed"})


def test_a_non_bug_task_is_never_listed():
    s = _svc({"a": {"id": "a", "status": "pending", "metadata": {"kind": "impl"}}})
    assert s.list_open_bugs() == []


# --- the ordering contract survives -----------------------------------------------------------------

def test_p0_still_sorts_before_p1_then_oldest_first():
    s = _svc({
        "late_p0": _bug("late_p0", "pending", severity="P0", created=200.0),
        "early_p0": _bug("early_p0", "pending", severity="P0", created=100.0),
        "p1": _bug("p1", "pending", severity="P1", created=1.0),
    })
    assert [b["id"] for b in s.list_open_bugs()] == ["early_p0", "late_p0", "p1"]


def test_assigned_to_inherits_the_fix():
    """`list_bugs_assigned_to` filters `list_open_bugs`, so it must not resurrect a fixed bug."""
    done = _bug("a", "completed"); done["assignee"] = "frontend"
    live = _bug("b", "pending"); live["assignee"] = "frontend"
    s = _svc({"a": done, "b": live})
    assert [b["id"] for b in s.list_bugs_assigned_to("frontend")] == ["b"]


# --- non-vacuity: the old behaviour is reproducible here --------------------------------------------

def test_the_old_filter_would_have_returned_the_fixed_bug():
    """Guards against passing because the harness never reaches the filter."""
    t = _bug("a", "completed", "open")
    assert (t["metadata"]["bug_state"] in bug_schema.OPEN_STATES), (
        "the bug_state condition alone still admits it — only the status check excludes it")
    assert _svc({"a": t}).list_open_bugs() == []


# --- provenance ---------------------------------------------------------------------------------------

def test_the_measurement_is_recorded():
    d = " ".join((svc.WorkHub.list_open_bugs.__doc__ or "").split())
    assert "821 open P0s across 120 runs" in d
    assert "62% of them were already completed or cancelled" in d


def test_the_consequence_is_recorded_not_just_the_count():
    d = " ".join((svc.WorkHub.list_open_bugs.__doc__ or "").split())
    assert 'verdict = "PASS" if bugs["p0"] == 0 else "DEFECTS"' in d
    assert "a run that FIXED every P0 still scored DEFECTS and deferred" in d


def test_630_is_credited_not_blamed():
    """#630's widening was right; the stale field is what turned it against good runs."""
    d = " ".join((svc.WorkHub.list_open_bugs.__doc__ or "").split())
    assert "widened this gate deliberately and correctly" in d


def test_the_failed_carve_out_is_justified_in_place():
    d = " ".join((svc.WorkHub.list_open_bugs.__doc__ or "").split())
    assert "`failed` is deliberately NOT terminal" in d


def test_the_two_fields_diagnosis_is_recorded():
    src = inspect.getsource(svc.WorkHub)
    i = src.index("#744:")
    assert "Two fields encode one lifecycle and they drift by construction." in src[i:]
    assert "**closed 6**" in src[i:]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
