"""#1202nn: an unfiltered workhub_list_tasks lists open tasks and COUNTS the closed ones.

tiktok-r125's WorkHub held 642 tasks at the end of M3: 516 completed, 122 cancelled, 4 open. Its
last resume made 238 unfiltered `workhub_list_tasks` calls (the orchestrator's delivery wakes
chiefly); each returned every row, ~150KB, nearly all of the tool's 40MB of results in that resume,
and each result stayed in the caller's prompt for the rest of its loop. That resume spent $742, of
which cached prompt tokens were ~$256 — so payload size is not free just because it is cached.

Asking for a status still lists exactly those rows.
"""
import asyncio
import shutil
import sys
import tempfile
from pathlib import Path

THIS = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS.parent / "env_generator" / "llm_generator"))
from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from tools.hub_tools import WorkHubListTasksTool  # noqa: E402


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _reg():
    tmp = Path(tempfile.mkdtemp(prefix="wh1202nn_"))
    reg = HubRegistry(tmp)
    ids = {}
    for name in ("done_a", "done_b", "dropped", "open", "broken", "claimed"):
        t = reg.workhub.create_task(title=name, description="x", assignee="backend",
                                    agent="orchestrator")
        ids[name] = t["id"] if isinstance(t, dict) else t
    wh = reg.workhub
    for name in ("done_a", "done_b", "broken", "claimed"):
        wh.claim_task(ids[name], agent="backend")
    wh.complete_task(ids["done_a"], agent="backend")
    wh.complete_task(ids["done_b"], agent="backend")
    wh.fail_task(ids["broken"], agent="backend", reason="x")
    wh.cancel_task(ids["dropped"], agent="orchestrator", reason="x")
    return reg, tmp


def _tool(reg):
    return WorkHubListTasksTool(agent_id="orchestrator", hub_workspace=reg)


def test_r125_an_unfiltered_list_names_only_open_work():
    reg, tmp = _reg()
    try:
        out = _run(_tool(reg)._run()).data
        titles = sorted(r["title"] for r in out["tasks"])
        assert titles == ["broken", "claimed", "open"], titles
        assert out["omitted_by_status"] == {"completed": 2, "cancelled": 1}
        assert 'status="completed"' in out["_detail"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_asking_for_a_status_still_lists_those_rows():
    reg, tmp = _reg()
    try:
        out = _run(_tool(reg)._run(status="completed")).data
        assert sorted(r["title"] for r in out["tasks"]) == ["done_a", "done_b"]
        assert "omitted_by_status" not in out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_nothing_closed_means_nothing_to_report():
    tmp = Path(tempfile.mkdtemp(prefix="wh1202nn_"))
    try:
        reg = HubRegistry(tmp)
        reg.workhub.create_task(title="only", description="x", assignee="backend",
                                agent="orchestrator")
        out = _run(_tool(reg)._run()).data
        assert [r["title"] for r in out["tasks"]] == ["only"]
        assert "omitted_by_status" not in out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
