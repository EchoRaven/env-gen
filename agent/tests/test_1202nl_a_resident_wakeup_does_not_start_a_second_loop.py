"""#1202nl: a resident wakeup waits for the lane's running loop instead of starting a second one.

The urgent task_ready path refuses to start a loop while one runs (V30, depth != 0) or while a
kickoff section is being authored (#1202ms). Resident wakeups arrive through the main loop's task
queue and asked neither: in the tiktok-r12x logs 608 of 1108 worker-lane resident wakeups (55%)
entered `run_agentic_loop` at depth >= 2, beside another loop in the same lane.

tiktok-r125 M3 kickoff, frontend: section loop at 09:03:02; resident wakeup starts P0 remediation
at 09:03:43; `process_task` re-pins `_active_phase`; the remediation loops' `finish()` calls are
rejected as kickoff finishes at 09:09:12 and 09:15:53, using both corrective turns; the section is
written as an auto-backup stub at 09:19 after the meeting waited 7 minutes on the frontend.
"""
from __future__ import annotations

import ast
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.agents.base import EnvGenAgent  # noqa: E402

BASE = LLM / "multi_agent" / "agents" / "base.py"


class _Log:
    def __init__(self):
        self.lines = []

    def info(self, m, *a):
        self.lines.append(m)

    warning = info


def _lane(depth=0, authoring=None):
    return SimpleNamespace(agent_id="frontend", _agentic_loop_depth=depth,
                           _kickoff_authoring_1202ms=authoring, _logger=_Log())


def _wait(lane, release_after=None, **env):
    async def _go():
        if release_after is not None:
            async def _release():
                await asyncio.sleep(release_after)
                lane._agentic_loop_depth = 0
                lane._kickoff_authoring_1202ms = None
            asyncio.ensure_future(_release())
        return await EnvGenAgent._await_no_running_loop_1202nl(lane, "resident_message_wakeup")
    return asyncio.run(_go())


def test_an_idle_lane_starts_at_once():
    lane = _lane()
    assert _wait(lane) is True
    assert lane._logger.lines == []


def test_r125_the_wakeup_waits_while_the_kickoff_loop_runs(monkeypatch):
    monkeypatch.setenv("ENVGEN_RESIDENT_WAIT_SEC", "30")
    lane = _lane(depth=1, authoring="doc_27858e9ee4")
    assert _wait(lane, release_after=1.2) is True
    assert lane._agentic_loop_depth == 0
    assert any("#1202nl" in ln for ln in lane._logger.lines)


def test_a_wedged_loop_does_not_starve_the_queue(monkeypatch):
    monkeypatch.setenv("ENVGEN_RESIDENT_WAIT_SEC", "1")
    lane = _lane(depth=1)
    assert _wait(lane) is False
    assert any("proceeding" in ln for ln in lane._logger.lines)


def test_process_task_waits_before_it_pins_the_phase():
    """The wait must come before `_active_phase` is re-pinned, or the kickoff loop's phase is
    overwritten while it is still running."""
    tree = ast.parse(BASE.read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "process_task")
    src = ast.get_source_segment(BASE.read_text(encoding="utf-8"), fn)
    wait = src.index("_await_no_running_loop_1202nl(")
    pin = src.index("self._active_phase = ")
    assert wait < pin
    assert 'startswith("resident_")' in src[:wait]
