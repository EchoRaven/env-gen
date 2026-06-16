import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from tools.hub_tools import create_hub_tools  # noqa: E402


REQUIRED_NEW_WORKHUB_TOOLS = {
    "workhub_invite_attendee",
    "workhub_remove_attendee",
    "workhub_comment",
    "workhub_reply",
    "workhub_share_implementation",
}


def _run(coro):
    return asyncio.run(coro)


class WorkHubCollabToolsTests(unittest.TestCase):
    def _hubs_and_tools(self, td):
        hubs = HubRegistry(Path(td))
        tools = create_hub_tools(agent_id="orchestrator", hub_workspace=hubs)
        return hubs, {t.NAME: t for t in tools}

    def test_all_new_workhub_tools_exported(self):
        with tempfile.TemporaryDirectory() as td:
            _, tool_by_name = self._hubs_and_tools(td)
            missing = REQUIRED_NEW_WORKHUB_TOOLS - set(tool_by_name.keys())
            self.assertEqual(missing, set(), f"missing: {missing}")

    def test_workhub_invite_attendee_adds_record(self):
        with tempfile.TemporaryDirectory() as td:
            hubs, tool_by_name = self._hubs_and_tools(td)
            page = hubs.workhub.create_page("Plan A", agent="orchestrator")
            tool = tool_by_name["workhub_invite_attendee"]
            result = _run(tool._run(resource_id=page["id"], agent_id="backend", role="reviewer"))
            data = result.data if hasattr(result, "data") else result
            self.assertEqual(data["agent_id"], "backend")
            self.assertEqual(data["role"], "reviewer")

    def test_workhub_remove_attendee_marks_removed(self):
        with tempfile.TemporaryDirectory() as td:
            hubs, tool_by_name = self._hubs_and_tools(td)
            page = hubs.workhub.create_page("Plan A", agent="orchestrator")
            hubs.workhub.invite_attendee(page["id"], "backend", role="reviewer", invited_by="orchestrator")
            tool = tool_by_name["workhub_remove_attendee"]
            result = _run(tool._run(resource_type="page", resource_id=page["id"], agent_id="backend"))
            data = result.data if hasattr(result, "data") else result
            # remove_attendee returns a dict marking the soft delete
            self.assertTrue(data.get("removed") or data.get("_removed"))

    def test_workhub_comment_persists_with_mentions(self):
        with tempfile.TemporaryDirectory() as td:
            hubs, tool_by_name = self._hubs_and_tools(td)
            page = hubs.workhub.create_page("Plan A", agent="orchestrator")
            tool = tool_by_name["workhub_comment"]
            result = _run(tool._run(resource_id=page["id"], body="Need help on auth",
                                     mentions=["backend"]))
            data = result.data if hasattr(result, "data") else result
            self.assertEqual(data["body"], "Need help on auth")
            self.assertIn("backend", data.get("mentions", []))

    def test_workhub_reply_links_to_parent_comment(self):
        with tempfile.TemporaryDirectory() as td:
            hubs, tool_by_name = self._hubs_and_tools(td)
            page = hubs.workhub.create_page("Plan A", agent="orchestrator")
            parent = hubs.workhub.comment(resource_id=page["id"], body="Question",
                                            agent="orchestrator")
            tool = tool_by_name["workhub_reply"]
            result = _run(tool._run(comment_id=parent["id"], body="Answer here"))
            data = result.data if hasattr(result, "data") else result
            self.assertEqual(data["body"], "Answer here")
            self.assertEqual(data.get("parent_id") or data.get("comment_id"), parent["id"])

    def test_workhub_share_implementation_creates_knowledge_block(self):
        with tempfile.TemporaryDirectory() as td:
            hubs, tool_by_name = self._hubs_and_tools(td)
            tool = tool_by_name["workhub_share_implementation"]
            result = _run(tool._run(title="JWT auth pattern", content="use bcrypt + jwt..."))
            data = result.data if hasattr(result, "data") else result
            # Could be a block or a record; verify it's stored
            blocks = hubs.workhub.get_shared_implementations()
            self.assertGreaterEqual(len(blocks), 1)


if __name__ == "__main__":
    unittest.main()
