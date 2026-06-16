"""Guard: tool-arg-friction fixes surfaced live in run #6.

Three tools rejected/mis-suggested what the model naturally supplied:
  - suggest_tools: `run_command` fuzzy-matched `workhub_comment`, preempting the
    curated shell intent (→ should lead with execute_bash).
  - registryhub_list_tables: rejected a `status` kwarg that list_endpoints accepts.
  - run_start: required `generated_dir` (framework context the model can't know).
"""

import sys
import asyncio
import types
import unittest
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.agents.runtime.tooling import suggest_tools  # noqa: E402


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class SuggestToolsTests(unittest.TestCase):
    AVAIL = ["execute_bash", "workhub_comment", "workhub_create_task",
             "registryhub_list_tables", "read", "write", "check_inbox", "send_message"]

    def test_run_command_leads_with_execute_bash_not_comment(self):
        hits = suggest_tools("run_command", self.AVAIL)
        self.assertTrue(hits, "expected a suggestion")
        self.assertEqual(hits[0], "execute_bash")  # shell intent leads, not workhub_comment

    def test_execute_command_maps_to_execute_bash(self):
        self.assertIn("execute_bash", suggest_tools("execute_command", self.AVAIL))

    def test_plain_typo_still_fuzzy_resolves(self):
        # no intent keyword → fuzzy still catches a near-miss tool name
        hits = suggest_tools("check_inbx", self.AVAIL)
        self.assertIn("check_inbox", hits)


class ListTablesStatusKwargTests(unittest.TestCase):
    def _tool(self):
        from tools.hub_tools import RegistryHubListTablesTool
        tables = {"users": {"status": "implemented"}, "videos": {"status": "defined"}}
        hubs = types.SimpleNamespace(
            schema_hub=types.SimpleNamespace(list_tables=lambda provider=None: tables))
        return RegistryHubListTablesTool(agent_id="verifier", hub_workspace=hubs)

    def test_status_kwarg_accepted_and_filters(self):
        res = _run(self._tool()._run(status="implemented"))
        self.assertTrue(res.success, getattr(res, "error_message", None))
        self.assertEqual(list(res.data["tables"].keys()), ["users"])

    def test_no_status_returns_all(self):
        res = _run(self._tool()._run())
        self.assertEqual(set(res.data["tables"].keys()), {"users", "videos"})


class RunStartGeneratedDirTests(unittest.TestCase):
    def test_generated_dir_auto_derived_from_base_dir(self):
        from tools.run_tools import RunStartTool
        captured = {}

        def _start_run(branch, generated_dir, base_url, agent):
            captured.update(branch=branch, generated_dir=generated_dir)
            return {"id": "run1", "status": "started"}

        hubs = types.SimpleNamespace(base_dir="/data/.../generated/youtube",
                                     runhub=types.SimpleNamespace(start_run=_start_run))
        tool = RunStartTool(agent_id="verifier", hub_workspace=hubs)
        # model omits generated_dir (the live crash) → auto-derived, no error
        res = _run(tool._run(branch="agent/orchestrator", base_url="http://localhost:8081"))
        self.assertTrue(res.success, getattr(res, "error_message", None))
        self.assertEqual(captured["generated_dir"], "/data/.../generated/youtube")


if __name__ == "__main__":
    unittest.main()
