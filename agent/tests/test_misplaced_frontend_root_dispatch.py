"""wrong-root frontend feedback loop — a full app built at the repo root must
route back to the frontend lane to be relocated under app/frontend/.

Observed live (gemini instagram 2026-06-13): the frontend lane authored a
COMPLETE Vite app at the REPO ROOT (./src/App.jsx with 10 routes, ./src/pages/
with 8 pages, its own ./package.json) — but docker builds `../app/frontend` and
the delivery gate audits `app/frontend/src`, which held only the blank baseline
shell. So delivery saw `ui_page_unwired` ×12 forever even though a real app
existed. `_detect_misplaced_frontend_root` spots the richer-at-root tree and
`_dispatch_misplaced_frontend_root` routes a RELOCATE task back to the lane (the
framework never moves the lane's UI files itself).
"""

from __future__ import annotations

import asyncio
import logging
import sys
import tempfile
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


def _mk_frontend(base: Path, n_pages: int, n_routes: int):
    """Create a frontend tree at `base` with n_pages page files + n_routes routes."""
    pages = base / "pages"
    pages.mkdir(parents=True, exist_ok=True)
    for i in range(n_pages):
        (pages / f"Page{i}.jsx").write_text("export default function P(){return null}")
    routes = "".join(f'<Route path="/{i}" element={{<P{i}/>}} />' for i in range(n_routes))
    (base / "App.jsx").write_text(f"function App(){{return <Routes>{routes}</Routes>}}")


def _detect(output_dir):
    stub = types.SimpleNamespace(output_dir=Path(output_dir),
                                 _logger=logging.getLogger("t"))
    return Orchestrator._detect_misplaced_frontend_root(stub)


def test_detects_misplaced_root_app_over_blank_canonical():
    with tempfile.TemporaryDirectory() as td:
        out = Path(td)
        _mk_frontend(out / "src", n_pages=8, n_routes=10)                     # real app at repo root
        _mk_frontend(out / "app" / "frontend" / "src", n_pages=1, n_routes=1)  # blank baseline
        info = _detect(out)
        assert info is not None
        assert info["root_pages"] == 8 and info["canonical_pages"] == 1
        assert info["root_routes"] == 10 and info["canonical_routes"] == 1


def test_no_false_positive_when_canonical_is_the_real_app():
    # the CORRECT layout: app/frontend/src has the app, repo root has no src/ →
    # must NOT flag (else we'd dispatch a spurious relocate on every healthy run).
    with tempfile.TemporaryDirectory() as td:
        out = Path(td)
        _mk_frontend(out / "app" / "frontend" / "src", n_pages=8, n_routes=10)
        assert _detect(out) is None


def test_no_false_positive_when_root_src_is_sparse():
    # a stray root src/ with <2 pages and <2 routes is not "a real app" → no flag.
    with tempfile.TemporaryDirectory() as td:
        out = Path(td)
        _mk_frontend(out / "src", n_pages=1, n_routes=1)
        _mk_frontend(out / "app" / "frontend" / "src", n_pages=8, n_routes=10)
        assert _detect(out) is None


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


def _dispatch_stub(milestone="1.0.0"):
    return types.SimpleNamespace(
        hubs=types.SimpleNamespace(workhub=_FakeWorkHub()),
        message_bus=_FakeBus(),
        _logger=logging.getLogger("t"),
        _current_milestone_version=milestone,
        _misplaced_frontend_dispatched=None,
    )


def _info():
    return {"root_pages": 8, "canonical_pages": 1, "root_routes": 10, "canonical_routes": 2}


def test_dispatches_p0_relocate_task_to_frontend():
    stub = _dispatch_stub()
    _run(Orchestrator._dispatch_misplaced_frontend_root(stub, _info()))
    assert len(stub.hubs.workhub.tasks) == 1
    task = stub.hubs.workhub.tasks[0]
    assert task["assignee"] == "frontend"
    assert task["priority"] == "P0"
    low = task["description"].lower()
    assert "app/frontend/" in low and "repo root" in low
    assert "move" in low  # the instruction is RELOCATE, not 'wire each route'
    assert len(stub.message_bus.sent) >= 1


def test_idempotent_per_milestone_and_none_guard():
    stub = _dispatch_stub()
    _run(Orchestrator._dispatch_misplaced_frontend_root(stub, _info()))
    _run(Orchestrator._dispatch_misplaced_frontend_root(stub, _info()))  # same milestone
    assert len(stub.hubs.workhub.tasks) == 1
    stub._misplaced_frontend_dispatched = None
    _run(Orchestrator._dispatch_misplaced_frontend_root(stub, None))     # nothing to do
    assert len(stub.hubs.workhub.tasks) == 1
