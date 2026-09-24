"""frontend_navigable feedback loop — a blank-shell frontend must route back to
the frontend lane.

The framework deliberately authors no UI (the lane owns it, 2026-06-11) and the
``frontend_navigable`` gate enforces >=1 page + >=1 route. But when the frontend
lane finished with page components and ZERO wired routes (observed live on the
Gemini run: 2 components, 0 routes, App.jsx imports one page but has no
BrowserRouter/Routes → "blank shell"), the failure routed NOWHERE — the lane had
already finish()ed, so it never re-engaged and validation pinned red until the
budget died. ``_dispatch_frontend_navigable`` closes the loop the same way the
GATE-C1 / visual-fidelity dispatches do: one P0 task + urgent wake to the
frontend lane per milestone. The framework still authors no UI — it only routes
the failure back to the owner.
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


class _FakeRegistry:
    def __init__(self, pages):
        self._pages = pages

    def list_ui_pages(self):
        return self._pages


_DEFAULT_PAGES = {
    "Dashboard": {"route": "/dashboard", "component": "DashboardPage", "apis_used": ["/api/metrics"]},
    "Orders": {"route": "/orders", "component": "OrdersPage", "apis_used": ["/api/orders"]},
}


def _stub(milestone="1.0.0", pages=None):
    return types.SimpleNamespace(
        hubs=types.SimpleNamespace(
            workhub=_FakeWorkHub(),
            registryhub=_FakeRegistry(_DEFAULT_PAGES if pages is None else pages)),
        message_bus=_FakeBus(),
        _logger=logging.getLogger("test_frontend_navigable_dispatch"),
        _current_milestone_version=milestone,
    )


_SOCIAL_VOCAB = ("feed", "reels", "explore", "profile", "home feed")


def test_navigable_task_lists_contract_routes_not_social_vocab():
    stub = _stub("1.0.0")
    _run(_dispatch()(stub, _fail_data()))
    desc = stub.hubs.workhub.tasks[0]["description"]
    # the lane is told to wire the DECLARED pages, derived from the contract
    assert "/dashboard" in desc and "DashboardPage" in desc
    assert "/orders" in desc and "OrdersPage" in desc
    # and NOT the hardcoded instagram screen vocabulary
    low = desc.lower()
    for w in _SOCIAL_VOCAB:
        assert w not in low, f"social vocab leaked into navigable task: {w!r}"


def test_navigable_task_empty_registry_uses_domain_neutral_fallback():
    stub = _stub("1.0.0", pages={})
    _run(_dispatch()(stub, _fail_data()))
    assert len(stub.hubs.workhub.tasks) == 1  # still dispatches
    low = stub.hubs.workhub.tasks[0]["description"].lower()
    assert "reference_spec" in low  # neutral fallback, derived from the references
    for w in _SOCIAL_VOCAB:
        assert w not in low, f"social vocab in empty-registry fallback: {w!r}"


def _dispatch():
    return Orchestrator._dispatch_frontend_navigable


def _fail_data():
    return {"checks": [{"name": "frontend_navigable", "status": "fail",
                        "detail": "2 page component(s), 0 route(s) — the frontend is a blank shell"}]}


def test_dispatches_frontend_p0_once_per_milestone():
    stub = _stub("1.0.0")
    _run(_dispatch()(stub, _fail_data()))
    assert len(stub.hubs.workhub.tasks) == 1
    task = stub.hubs.workhub.tasks[0]
    assert task["assignee"] == "frontend"
    assert task["priority"] == "P0"
    # actionable: tells the lane to wire react-router routes
    desc = task["description"].lower()
    assert "react-router" in desc or "route" in desc
    assert "app.jsx" in desc
    assert len(stub.message_bus.sent) >= 1  # urgent wake, not just a queued task

    # same milestone, validation retries every tick → no duplicate spam
    _run(_dispatch()(stub, _fail_data()))
    assert len(stub.hubs.workhub.tasks) == 1

    # next milestone → a fresh dispatch is allowed
    stub._current_milestone_version = "2.0.0"
    _run(_dispatch()(stub, _fail_data()))
    assert len(stub.hubs.workhub.tasks) == 2


def test_no_dispatch_when_navigable_passes_or_absent():
    stub = _stub()
    _run(_dispatch()(stub, {"checks": [
        {"name": "frontend_navigable", "status": "pass", "detail": "4 page(s), 4 route(s)"}]}))
    _run(_dispatch()(stub, {"checks": [
        {"name": "business_chain", "status": "fail", "detail": "..."}]}))  # different check
    _run(_dispatch()(stub, {"checks": []}))
    _run(_dispatch()(stub, None))
    assert stub.hubs.workhub.tasks == []
    assert stub.message_bus.sent == []
