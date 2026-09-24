"""PROPOSAL #21 — deterministic remediation dispatch for the UNCOVERED validation
failing-checks (close the coverage gap).

The validate→remediate loop previously re-dispatched only `business_endpoints_implemented`
(→backend) and `frontend_navigable` (→frontend). Every OTHER lane-actionable failing
check routed NOWHERE, so when its owning lane had finished and gone idle, the orchestrator
LLM just "waited" and the gate pinned red forever (youtube run #4: frontend idle 30min on
`frontend_dead_controls`; backend stalled on `business_endpoints_reachable` — both with no
deterministic re-dispatch → no unanimous-green api_smoke → no RunHub gate run → no delivery).

`dispatch_failing_checks` (a check→owner table) re-wakes the owning lane with a P0 task +
urgent task_ready for each uncovered failing check, carrying the check's detail (dead_controls
names the offending .jsx files). Same family as #20 (deterministically re-wake an idle lane).
Guarded per-milestone (dict), re-armed by rearm_owner_dispatch.

C6 (owner-routing, filename specificity, guard/re-arm, no-op safety). LOCAL-ONLY (gitignored).
"""

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

from multi_agent.orchestrator import Orchestrator  # noqa: E402
from multi_agent.runtime.framework_validation import FrameworkValidation  # noqa: E402


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
        _logger=logging.getLogger("test_failing_checks_dispatch"),
        _current_milestone_version=milestone,
    )


def _dispatch():
    return Orchestrator._dispatch_failing_checks


_DEAD = {"name": "frontend_dead_controls", "status": "fail",
         "detail": "interactive markup with NO bound handler/API call — a user "
                   "clicking these gets nothing: SignupPage.jsx, CommentBox.jsx"}
_REACH = {"name": "business_endpoints_reachable", "status": "fail",
          "detail": "GET /api/videos/search → 404"}


def test_dead_controls_routes_to_frontend_with_filenames():
    stub = _stub()
    _run(_dispatch()(stub, {"checks": [_DEAD]}))
    assert len(stub.hubs.workhub.tasks) == 1
    task = stub.hubs.workhub.tasks[0]
    assert task["assignee"] == "frontend"
    assert task["priority"] == "P0"
    # SPECIFICITY: the offending files are named in the task body
    assert "SignupPage.jsx" in task["description"]
    assert "CommentBox.jsx" in task["description"]
    # urgent wake (not just a queued task), targeted at the frontend
    assert len(stub.message_bus.sent) == 1
    msg = stub.message_bus.sent[0]
    assert getattr(msg.header, "target_agent_id", None) == "frontend" or \
        getattr(msg, "target_agent_id", None) == "frontend"


def test_endpoints_reachable_routes_to_backend():
    # OWNER-ROUTING: a backend-owned check must wake the BACKEND, not the frontend.
    stub = _stub()
    _run(_dispatch()(stub, {"checks": [_REACH]}))
    assert len(stub.hubs.workhub.tasks) == 1
    assert stub.hubs.workhub.tasks[0]["assignee"] == "backend"


def test_two_lanes_dispatched_when_both_fail():
    # run #4's exact tail: frontend dead_controls + backend reachable simultaneously.
    stub = _stub()
    _run(_dispatch()(stub, {"checks": [_DEAD, _REACH]}))
    owners = sorted(t["assignee"] for t in stub.hubs.workhub.tasks)
    assert owners == ["backend", "frontend"]


def test_guard_one_per_milestone_then_rearm_refires():
    stub = _stub("1.0.0")
    _run(_dispatch()(stub, {"checks": [_DEAD]}))
    assert len(stub.hubs.workhub.tasks) == 1
    # validation retries every tick → no duplicate within the milestone
    _run(_dispatch()(stub, {"checks": [_DEAD]}))
    assert len(stub.hubs.workhub.tasks) == 1
    # rearm_owner_dispatch (changed/stuck failure set) clears the dict guard → re-fires
    FrameworkValidation(stub).rearm_owner_dispatch()
    _run(_dispatch()(stub, {"checks": [_DEAD]}))
    assert len(stub.hubs.workhub.tasks) == 2


def test_rearm_resets_the_dict_guard():
    # C4 explicitly: the per-check dict guard MUST be reset by rearm_owner_dispatch.
    stub = _stub()
    stub._check_owner_dispatched = {"frontend_dead_controls": "1.0.0"}
    FrameworkValidation(stub).rearm_owner_dispatch()
    assert stub._check_owner_dispatched == {}


def test_unlisted_or_passing_or_covered_checks_are_noops():
    stub = _stub()
    # already-covered (has its own helper) → NOT re-dispatched here
    _run(_dispatch()(stub, {"checks": [{"name": "frontend_navigable", "status": "fail", "detail": "x"}]}))
    _run(_dispatch()(stub, {"checks": [{"name": "business_endpoints_implemented", "status": "fail", "detail": "x"}]}))
    # passing check, unknown check, empty, None
    _run(_dispatch()(stub, {"checks": [{"name": "frontend_dead_controls", "status": "pass", "detail": "ok"}]}))
    _run(_dispatch()(stub, {"checks": [{"name": "totally_unknown_check", "status": "fail", "detail": "x"}]}))
    _run(_dispatch()(stub, {"checks": []}))
    _run(_dispatch()(stub, None))
    assert stub.hubs.workhub.tasks == []
    assert stub.message_bus.sent == []


def test_all_uncovered_backend_checks_route_to_backend():
    for name in ("business_endpoints_correct_shape", "auth_enforced_401",
                 "business_writes_persist"):
        stub = _stub()
        _run(_dispatch()(stub, {"checks": [{"name": name, "status": "fail", "detail": "d"}]}))
        assert len(stub.hubs.workhub.tasks) == 1, name
        assert stub.hubs.workhub.tasks[0]["assignee"] == "backend", name


def test_frontend_reachable_routes_to_frontend():
    stub = _stub()
    _run(_dispatch()(stub, {"checks": [{"name": "frontend_reachable", "status": "fail", "detail": "container not serving"}]}))
    assert stub.hubs.workhub.tasks[0]["assignee"] == "frontend"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
