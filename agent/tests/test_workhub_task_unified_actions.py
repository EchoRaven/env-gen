"""workhub_task unified actions (Instagram run #4 fix).

Real LLM backend lanes call the single ``workhub_task`` tool with
``action="fail"``/``"cancel"`` plus a ``reason`` kwarg (conflating it with the
sibling ``workhub_fail_task`` / ``workhub_cancel_task`` tools). Before the fix
that crashed ``WorkHubTaskTool._run()`` with "unexpected keyword argument
'reason'" — 22 hard failures in one episode on Instagram run #4, wasting backend
turns. These pin: fail/cancel route correctly with the reason, a stray ``reason``
on any action no longer crashes, extra unknown kwargs are tolerated, and a truly
unknown action returns an error result (not an exception).
"""

import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from tools.hub_tools import WorkHubTaskTool  # noqa: E402


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _tool():
    wh = MagicMock(name="workhub")
    wh.fail_task.return_value = {"id": "t1", "status": "failed"}
    wh.cancel_task.return_value = {"id": "t1", "status": "cancelled"}
    wh.complete_task.return_value = {"id": "t1", "status": "done"}
    t = WorkHubTaskTool()
    t._hubs = SimpleNamespace(workhub=wh)
    t._agent_id = "backend"
    return t, wh


class WorkHubTaskUnifiedActions(unittest.TestCase):
    def test_action_fail_routes_with_reason(self):
        t, wh = _tool()
        res = _run(t._run(action="fail", task_id="t1", reason="cannot impl"))
        wh.fail_task.assert_called_once_with("t1", "backend", reason="cannot impl")
        self.assertEqual(res.data["status"], "failed")

    def test_action_cancel_routes_with_reason(self):
        t, wh = _tool()
        res = _run(t._run(action="cancel", task_id="t1", reason="abort"))
        wh.cancel_task.assert_called_once_with("t1", "backend", reason="abort")
        self.assertEqual(res.data["status"], "cancelled")

    def test_reason_kwarg_does_not_crash_complete(self):
        # The exact run #4 crash: a ``reason`` passed to a non-fail action.
        t, wh = _tool()
        res = _run(t._run(action="complete", task_id="t1", reason="x"))
        self.assertEqual(res.data["status"], "done")

    def test_tolerates_stray_kwarg(self):
        t, wh = _tool()
        res = _run(t._run(action="fail", task_id="t1", reason="r", bogus="zzz"))
        self.assertEqual(res.data["status"], "failed")

    def test_unknown_action_returns_error_not_exception(self):
        t, _wh = _tool()
        res = _run(t._run(action="frobnicate", task_id="t1"))
        self.assertFalse(res.success)
        self.assertIn("Unknown workhub_task action", res.error_message or "")


if __name__ == "__main__":
    unittest.main()
