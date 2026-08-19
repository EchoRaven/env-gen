"""#998: one open task per endpoint, not seventeen.

r162 accumulated **17 tasks for a single defect** — all authored by the orchestrator through
`workhub_task action=create`, all naming `POST /api/continue-watching` and a 405, with titles
varied just enough to look distinct:

    Fix POST /api/continue-watching 405 contract failure
    Restore missing table contract and fix POST /api/continue-watching 405
    Fix POST /api/continue-watching returning 405
    Fix POST /api/continue-watching 405 and align contract
    P0 fix POST /api/continue-watching returning 405
    …

Nine were still open when the run ended, and `incomplete_required_tasks` — the gate that
killed r162 — counts open tasks. **One unfixable defect became nine blockers.**

#794 stopped the GATE-CHECK dispatcher from cloning. This is the other creation path: the
model's own tool call, which had no dedupe at all.

Keyed on METHOD + PATH rather than title similarity: a structured signal the model itself
wrote, which cannot drift with phrasing. A title naming no endpoint is never blocked, because
most tasks are not about one endpoint.
"""

import pytest

from env_generator.llm_generator.tools.hub_tools import _open_task_for_same_endpoint_998


class _Hub:
    def __init__(self, tasks):
        self._t = tasks

    def list_tasks(self):
        return self._t


R162 = [{"id": "t1", "title": "Fix POST /api/continue-watching returning 405",
         "assignee": "backend", "status": "in_progress"}]


def test_a_second_task_for_the_same_endpoint_is_refused():
    dup = _open_task_for_same_endpoint_998(
        _Hub(R162), "Fix POST /api/continue-watching 405 and align contract", "backend")
    assert dup and dup["id"] == "t1"


@pytest.mark.parametrize("title", [
    "Fix POST /api/continue-watching 405 contract failure",
    "Restore missing table contract and fix POST /api/continue-watching 405",
    "P0 fix POST /api/continue-watching returning 405",
    "Fix POST /api/continue-watching runtime 405",
])
def test_every_r162_variant_collapses(title):
    """The real titles from r162. Phrasing varies; the endpoint does not."""
    assert _open_task_for_same_endpoint_998(_Hub(R162), title, "backend")


def test_a_different_endpoint_is_allowed():
    assert _open_task_for_same_endpoint_998(
        _Hub(R162), "Fix POST /api/my-list returning 405", "backend") is None


def test_a_different_method_on_the_same_path_is_allowed():
    """GET and POST on one path are genuinely different work."""
    assert _open_task_for_same_endpoint_998(
        _Hub(R162), "Fix GET /api/continue-watching returning 500", "backend") is None


def test_a_closed_task_does_not_block():
    closed = [{"id": "t9", "title": "Fix POST /api/continue-watching 405",
               "assignee": "backend", "status": "completed"}]
    assert _open_task_for_same_endpoint_998(
        _Hub(closed), "Fix POST /api/continue-watching 405", "backend") is None


def test_another_lane_may_hold_its_own_task():
    assert _open_task_for_same_endpoint_998(
        _Hub(R162), "Fix POST /api/continue-watching 405", "frontend") is None


def test_a_title_without_an_endpoint_is_never_blocked():
    """Most tasks are not about one endpoint and must stay unaffected."""
    assert _open_task_for_same_endpoint_998(
        _Hub(R162), "Record ui_flow evidence for nine critical pages", "backend") is None


def test_a_broken_hub_does_not_block_creation():
    class _Boom:
        def list_tasks(self):
            raise RuntimeError("hub down")

    assert _open_task_for_same_endpoint_998(
        _Boom(), "Fix POST /api/continue-watching 405", "backend") is None


def test_the_control_lets_all_seventeen_through():
    """Planted control: the PRE-FIX path called create_task directly with no lookup, which is
    how one defect became nine open blockers."""
    def _pre_fix(_title, _assignee):
        return None

    assert _pre_fix("Fix POST /api/continue-watching 405", "backend") is None, (
        "the control was supposed to permit the duplicate; if it does not, this fix is "
        "unmotivated")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
