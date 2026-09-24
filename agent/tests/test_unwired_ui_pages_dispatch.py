"""ui_page-wiring feedback loop — declared-but-unwired pages must route back to
the frontend lane.

The ``deliverability_ui_page_unwired`` gate HARD-blocks delivery when a declared
ui_page's route isn't wired in App.jsx (or its component file is missing) — even
on a functionally-validated app (api_smoke probes only the backend). Observed
live on the Gemini instagram run (2026-06-13): App.jsx wired ONLY ``/login``
while 12 declared pages (home/explore/reels/messages/profile/…) sat unwired →
delivery blocked for hours. The blocker routed NOWHERE: ``frontend_navigable``
passes on >=1 route (login alone), so ITS dispatch went quiet, while delivery
needs EVERY declared page wired. ``_dispatch_unwired_ui_pages`` closes the loop
the same way the GATE-C1 / navigable / visual dispatches do — ONE P0 task + urgent
wake to the frontend lane per milestone, listing the specific unwired pages. The
framework authors no UI; it only routes the gap (with registry truth) back to the
owner.
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


class _FakeRegistryHub:
    """A2: the unwired-pages dispatch now reads ui_pages from RegistryHub
    (``list_ui_pages()``), not WorkHub. RegistryHub owns create_task? No —
    tasks still land on WorkHub. This fake only supplies the page registry."""

    def __init__(self, pages):
        self._pages = pages

    def list_ui_pages(self):
        return self._pages


class _FakeBus:
    def __init__(self):
        self.sent = []

    async def send(self, msg):
        self.sent.append(msg)


def _stub(pages, milestone="1.0.0"):
    return types.SimpleNamespace(
        hubs=types.SimpleNamespace(
            workhub=_FakeWorkHub(),
            registryhub=_FakeRegistryHub(pages),
        ),
        message_bus=_FakeBus(),
        _logger=logging.getLogger("test_unwired_ui_pages_dispatch"),
        _current_milestone_version=milestone,
        _unwired_ui_pages_dispatched=None,
    )


def _dispatch():
    return Orchestrator._dispatch_unwired_ui_pages


# blocker strings exactly as frontend_audit.ui_page_delivery_blockers emits them
def _blockers():
    return [
        "ui_page `home` declared but unusable: route `/` not wired in App.jsx",
        "ui_page `explore` declared but unusable: component `ExplorePage` not "
        "found — expected at src/pages/ExplorePage.jsx; route `/explore` not "
        "wired in App.jsx",
    ]


def _pages():
    return {
        "login": {"route": "/login", "component": "LoginPage"},   # wired — NOT in blockers
        "home": {"route": "/", "component": "HomePage"},
        "explore": {"route": "/explore", "component": "ExplorePage"},
    }


def test_dispatches_p0_to_frontend_listing_unwired_pages():
    stub = _stub(_pages(), "1.0.0")
    _run(_dispatch()(stub, _blockers()))

    assert len(stub.hubs.workhub.tasks) == 1
    task = stub.hubs.workhub.tasks[0]
    assert task["assignee"] == "frontend"
    assert task["priority"] == "P0"
    desc = task["description"]
    low = desc.lower()
    assert "app.jsx" in low and "route" in low
    # the SPECIFIC unwired pages (from the blockers) are listed with route→component
    # PROPOSAL #51 (b): per-page STUB/UNWIRED directive (component + route), not "route → <Comp/>"
    assert "HomePage (route /)" in desc
    assert "ExplorePage (route /explore)" in desc
    # the WIRED login page (not named in a blocker) is NOT in the work list
    assert "LoginPage" not in desc
    # an urgent wake, not just a queued task
    assert len(stub.message_bus.sent) >= 1


def test_idempotent_per_milestone_but_refreshes_next_milestone():
    stub = _stub(_pages(), "1.0.0")
    _run(_dispatch()(stub, _blockers()))
    # same milestone, gate recomputes every tick → no duplicate spam
    _run(_dispatch()(stub, _blockers()))
    assert len(stub.hubs.workhub.tasks) == 1

    # next milestone → a fresh dispatch is allowed
    stub._current_milestone_version = "2.0.0"
    _run(_dispatch()(stub, _blockers()))
    assert len(stub.hubs.workhub.tasks) == 2


def test_no_dispatch_when_nothing_unwired():
    stub = _stub(_pages(), "1.0.0")
    _run(_dispatch()(stub, []))        # all pages wired → no blockers
    _run(_dispatch()(stub, None))      # defensive: None
    assert stub.hubs.workhub.tasks == []
    assert stub.message_bus.sent == []


def test_falls_back_to_blocker_text_when_pages_registry_empty():
    # if the ui_pages registry is unavailable, still dispatch with the raw
    # blocker prose so the lane isn't left with an empty work list.
    stub = _stub({}, "1.0.0")
    _run(_dispatch()(stub, _blockers()))
    assert len(stub.hubs.workhub.tasks) == 1
    desc = stub.hubs.workhub.tasks[0]["description"]
    assert "home" in desc and "explore" in desc  # the blocker prose survived


# FIX #171: a #166 MAP blocker uses the same "declared but unusable" prefix but the map page
# IS wired — the generic stub/unwired message ("add a Route") is misleading and drops the
# actionable "build the real Leaflet map" instruction. The dispatch must recognize a map
# blocker and pass its actionable text through.
def test_map_blocker_gets_map_specific_message_not_add_route():
    stub = _stub({"home_map": {"route": "/", "component": "HomeMap"}}, "1.0.0")
    _run(_dispatch()(stub, [
        "ui_page `home_map` declared but unusable: it is a MAP surface but the frontend "
        "uses NO map library (a fake <div> background, not a map) — build the REAL Leaflet "
        "map (react-leaflet MapContainer + OSM TileLayer with an explicit height, markers "
        "from the places data, per the map_surface_template). A CSS box pretending to be a "
        "map is rejected."]))
    assert len(stub.hubs.workhub.tasks) == 1
    desc = stub.hubs.workhub.tasks[0]["description"].lower()
    assert "leaflet" in desc or "map library" in desc or "real" in desc and "map" in desc
    # must NOT tell the lane to add a route it already has
    assert "unwired — add" not in desc
