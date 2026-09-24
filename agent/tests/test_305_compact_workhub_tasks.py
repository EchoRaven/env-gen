"""#305 — workhub_list_tasks returns COMPACT rows (id/title/status/assignee/
priority/deps), NOT each task's full description/evidence/metadata/result. Detail
via the existing workhub_get_task(id). Same 'compact list + get-by-id' pattern.
"""
import asyncio
import shutil
import sys
import tempfile
from pathlib import Path

THIS = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS.parent / "env_generator" / "llm_generator"))
from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from tools.hub_tools import WorkHubListTasksTool, WorkHubGetTaskTool  # noqa: E402


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _reg():
    tmp = Path(tempfile.mkdtemp(prefix="wh305_"))
    reg = HubRegistry(tmp)
    reg.workhub.create_task(
        title="Implement POST /api/videos",
        description="D" * 6000, assignee="backend", agent="orchestrator",
        priority="P0")
    return reg, tmp


def test_list_tasks_is_compact():
    reg, tmp = _reg()
    try:
        out = _run(WorkHubListTasksTool(agent_id="orchestrator", hub_workspace=reg)._run())
        tasks = out.data["tasks"]
        assert tasks, "should list the task"
        row = tasks[0]
        assert row.get("title") == "Implement POST /api/videos"
        assert row.get("status")
        assert "description" not in row          # heavy field dropped from LIST
        assert "evidence" not in row
        assert "metadata" not in row
        assert "get_task" in str(out.data).lower()   # recovery pointer
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_get_task_still_has_full_description():
    reg, tmp = _reg()
    try:
        tid = reg.workhub.list_tasks()[0]["id"]
        out = _run(WorkHubGetTaskTool(agent_id="orchestrator", hub_workspace=reg)._run(task_id=tid))
        assert len(str(out.data.get("description", ""))) == 6000   # full detail recoverable
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
