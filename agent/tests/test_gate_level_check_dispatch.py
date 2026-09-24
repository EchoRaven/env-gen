"""PROPOSAL #49 (user: gate-detected problems must route back to the owning lane for
repair, not silently dead-end). RemediationDispatcher.dispatch_gate_level_checks routes
each lane-owned DELIVERY-GATE-level failed_check to its owner (P0 task + urgent wake,
guarded per-milestone) and LOGS any uncovered failing check so it never silently
dead-ends. LOCAL-ONLY (gitignored)."""
from __future__ import annotations

import asyncio
import logging
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.runtime.remediation_dispatcher import RemediationDispatcher  # noqa: E402


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        asyncio.set_event_loop(None)
        loop.close()


class _FakeWorkHub:
    def __init__(self):
        self.tasks = []

    def create_task(self, **kw):
        self.tasks.append(kw)
        return {"id": f"task_{len(self.tasks)}"}


class _FakeBus:
    def __init__(self):
        self.sent = []

    async def send(self, msg):
        self.sent.append(msg)


def _stub(milestone="1.0.0"):
    return types.SimpleNamespace(
        hubs=types.SimpleNamespace(workhub=_FakeWorkHub()),
        message_bus=_FakeBus(),
        _logger=logging.getLogger("test_gate_level_check_dispatch"),
        _current_milestone_version=milestone,
    )


def test_business_response_key_noncanonical_routes_to_backend():
    orch = _stub()
    _run(RemediationDispatcher(orch).dispatch_gate_level_checks(
        ["business_response_key_noncanonical"]))
    assert len(orch.hubs.workhub.tasks) == 1
    t = orch.hubs.workhub.tasks[0]
    assert t["assignee"] == "backend" and t["priority"] == "P0"
    assert orch.message_bus.sent, "an urgent task_ready must be sent to the owner"


def test_contract_alignment_routes_to_backend():
    orch = _stub()
    _run(RemediationDispatcher(orch).dispatch_gate_level_checks(["contract_alignment_failed"]))
    assert orch.hubs.workhub.tasks and orch.hubs.workhub.tasks[0]["assignee"] == "backend"


def test_guarded_one_dispatch_per_milestone():
    orch = _stub()
    rd = RemediationDispatcher(orch)
    _run(rd.dispatch_gate_level_checks(["business_response_key_noncanonical"]))
    _run(rd.dispatch_gate_level_checks(["business_response_key_noncanonical"]))
    assert len(orch.hubs.workhub.tasks) == 1, "must dispatch once per milestone (storm control)"


def test_bespoke_covered_checks_not_dispatched_and_not_logged_uncovered(caplog=None):
    orch = _stub()
    # ui_page_unwired / no_successful_run are covered elsewhere → no task, no uncovered-log.
    _run(RemediationDispatcher(orch).dispatch_gate_level_checks(
        ["deliverability_ui_page_unwired", "deliverability_no_successful_run",
         "incomplete_required_tasks"]))
    assert orch.hubs.workhub.tasks == []


def test_uncovered_check_logged_not_silent():
    import logging as _l
    orch = _stub()
    recs = []
    h = _l.Handler(); h.emit = lambda r: recs.append(r.getMessage())
    orch._logger.addHandler(h); orch._logger.setLevel(_l.WARNING)
    _run(RemediationDispatcher(orch).dispatch_gate_level_checks(["some_unknown_gate_check"]))
    orch._logger.removeHandler(h)
    assert orch.hubs.workhub.tasks == []  # unknown owner → not dispatched
    assert any("some_unknown_gate_check" in m and "NO remediation owner" in m for m in recs), \
        "an uncovered failing check MUST be logged, never silently dead-end"


def test_duplicate_check_names_dispatch_one_task():
    # #328 (r93 dead-nav storm): one gate decline surfaced 7 identical
    # 'deliverability_dead_nav_link' entries; the persist-counter treated the in-list
    # duplicates as separate re-declines and fired 3 duplicate P0 tasks (dup #1/#4/#7) +
    # woke the lane 10x for one trivial fix. Duplicates must collapse to ONE task.
    orch = _stub()
    _run(RemediationDispatcher(orch).dispatch_gate_level_checks(
        ["deliverability_dead_nav_link"] * 7))
    assert len(orch.hubs.workhub.tasks) == 1, \
        f"duplicate check names must dispatch ONE task, got {len(orch.hubs.workhub.tasks)}"


def test_empty_is_noop():
    orch = _stub()
    _run(RemediationDispatcher(orch).dispatch_gate_level_checks([]))
    _run(RemediationDispatcher(orch).dispatch_gate_level_checks(None))
    assert orch.hubs.workhub.tasks == []


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
