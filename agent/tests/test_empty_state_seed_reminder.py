"""FIX #133 — the visual judge reports empty_state per screen, and the gate reminds the
BACKEND lane (once per milestone) to seed the missing rows.

Root cause (run-47/50, user question 1 + user direction "提醒 backend agent 添加数据"):
reels rendered "No reels available" because its table had no seed rows — the reference's
design skeleton (video chrome, action rail) only renders WITH data, so the judge could
never fairly score the screen and remediation kept telling the FRONTEND to fix a data
problem. Now the judge flags empty_state, and the framework files a backend seed task.

ENV-AGNOSTIC + LOCAL-ONLY (agent/tests/ gitignored).
"""

import asyncio
import sys
import types
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import multi_agent.runtime.visual_fidelity as vf  # noqa: E402
from multi_agent.runtime.visual_fidelity import (  # noqa: E402
    VisualFidelityGate, _parse_verdict, _JUDGE_INSTRUCTIONS)


# ── judge prompt + verdict parsing ──────────────────────────────────────────

def test_judge_instructions_request_empty_state():
    assert '"empty_state"' in _JUDGE_INSTRUCTIONS


def test_parse_verdict_reads_empty_state():
    v = _parse_verdict('{"similarity": 0.2, "empty_state": true, "deviations": []}')
    assert v["empty_state"] is True
    v = _parse_verdict('{"similarity": 0.7, "deviations": []}')
    assert v["empty_state"] is False           # absent -> False, key always present


# ── gate: one backend seed reminder per milestone ───────────────────────────

class _WorkHub:
    def __init__(self):
        self.tasks = []
    def create_task(self, **kw):
        self.tasks.append(kw)
        return {"id": f"task_{len(self.tasks)}"}


class _Bus:
    def __init__(self):
        self.sent = []
    async def send(self, msg):
        self.sent.append(msg)


def _mk_orch(tmp_path):
    orch = types.SimpleNamespace()
    orch.output_dir = tmp_path
    orch._reference_images = [str(tmp_path / "reels.png")]
    (tmp_path / "reels.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    orch._compute_app_source_signature = lambda: "sig1"
    orch.llm = None
    orch.hubs = types.SimpleNamespace(workhub=_WorkHub())
    orch.message_bus = _Bus()
    import logging
    orch._logger = logging.getLogger("test.vfgate")
    return orch


def _result(empty_names, passed_names=()):
    screens = []
    for n in empty_names:
        screens.append({"name": n, "route": "/" + n, "similarity": 0.2, "passed": False,
                        "advisory": False, "empty_state": True, "dimensions": {},
                        "deviations": [], "fixes": []})
    for n in passed_names:
        screens.append({"name": n, "route": "/" + n, "similarity": 0.8, "passed": True,
                        "advisory": False, "empty_state": False, "dimensions": {},
                        "deviations": [], "fixes": []})
    return {"passed": False, "summary": "below 0.65", "screens": screens, "skipped": []}


def _run_gate_once(orch, result, gate=None, sig="sig1"):
    g = gate or VisualFidelityGate(orch)
    orch._compute_app_source_signature = lambda: sig
    async def _fake_rvf(*a, **k):
        return result
    with mock.patch.object(vf, "run_visual_fidelity", _fake_rvf):
        asyncio.run(g.maybe_run())
    return g


def test_empty_state_screen_files_backend_seed_task(tmp_path):
    orch = _mk_orch(tmp_path)
    _run_gate_once(orch, _result(["reels"]))
    backend = [t for t in orch.hubs.workhub.tasks if t.get("assignee") == "backend"]
    assert len(backend) == 1, orch.hubs.workhub.tasks
    assert "reels" in backend[0]["description"]
    assert "seed" in backend[0]["description"].lower()
    # the wake message went to the backend lane too (BaseMessage.header.target_agent_id)
    def _target(m):
        h = getattr(m, "header", None)
        return getattr(h, "target_agent_id", None) if h is not None else (
            m.get("target_agent_id") if isinstance(m, dict) else None)
    assert any(_target(m) == "backend" for m in orch.message_bus.sent), \
        [_target(m) for m in orch.message_bus.sent]


def test_seed_reminder_fires_once_per_milestone(tmp_path):
    orch = _mk_orch(tmp_path)
    g = _run_gate_once(orch, _result(["reels"]), sig="sig1")
    _run_gate_once(orch, _result(["reels"]), gate=g, sig="sig2")  # new source, judged again
    backend = [t for t in orch.hubs.workhub.tasks if t.get("assignee") == "backend"]
    assert len(backend) == 1, "guard must prevent a task per re-judge round"
    g.reset_for_milestone()
    _run_gate_once(orch, _result(["reels"]), gate=g, sig="sig3")
    backend = [t for t in orch.hubs.workhub.tasks if t.get("assignee") == "backend"]
    assert len(backend) == 2, "new milestone re-arms the reminder"


def test_no_empty_state_no_backend_task(tmp_path):
    orch = _mk_orch(tmp_path)
    # failing screens but none empty-state -> frontend remediation only
    res = _result([], passed_names=[])
    res["screens"] = [{"name": "login", "route": "/login", "similarity": 0.3,
                       "passed": False, "advisory": False, "empty_state": False,
                       "dimensions": {}, "deviations": [], "fixes": []}]
    _run_gate_once(orch, res)
    assert not [t for t in orch.hubs.workhub.tasks if t.get("assignee") == "backend"]
    assert [t for t in orch.hubs.workhub.tasks if t.get("assignee") == "frontend"]


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
