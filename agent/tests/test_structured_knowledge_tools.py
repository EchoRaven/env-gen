"""Tests for structured knowledge LLM tools (Cutover 15)."""

import asyncio
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _fresh_store(tmp):
    """Build an isolated KnowledgeStore over a temp sqlite file."""
    from multi_agent.knowledge.store import KnowledgeStore
    db_path = Path(tmp) / "k.db"
    return KnowledgeStore(db_url=f"sqlite:///{db_path}")


class StructuredKnowledgeToolsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="struct_k_"))
        self.store = _fresh_store(self.tmp)
        # Reset the module-level singleton to use our isolated store
        from tools import knowledge_tools as _kt
        _kt._knowledge_store = self.store

    def tearDown(self) -> None:
        from tools import knowledge_tools as _kt
        _kt._knowledge_store = None
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ---- submit_adr ----

    def test_submit_adr_with_all_required_fields_succeeds(self) -> None:
        from tools.structured_knowledge_tools import SubmitADRTool
        result = _run_async(SubmitADRTool().execute(
            title="ADR-001: use postgres",
            decision="use postgres",
            context="need ACID for financial data",
            alternatives=["mysql", "sqlite"],
            consequences="ops overhead is acceptable",
            status="accepted"))
        self.assertTrue(result.success, f"failed: {result.error_message}")
        self.assertIn("id", result.data)

    def test_submit_adr_rejects_missing_alternatives(self) -> None:
        from tools.structured_knowledge_tools import SubmitADRTool
        result = _run_async(SubmitADRTool().execute(
            title="x", decision="d", context="c",
            alternatives=[], consequences="x", status="accepted"))
        self.assertFalse(result.success)

    def test_submit_adr_rejects_invalid_status(self) -> None:
        from tools.structured_knowledge_tools import SubmitADRTool
        result = _run_async(SubmitADRTool().execute(
            title="x", decision="d", context="c",
            alternatives=["a"], consequences="x", status="bogus"))
        self.assertFalse(result.success)

    # ---- submit_runbook ----

    def test_submit_runbook_with_all_required_succeeds(self) -> None:
        from tools.structured_knowledge_tools import SubmitRunbookTool
        result = _run_async(SubmitRunbookTool().execute(
            title="deploy frontend",
            trigger="ready to ship feature/x",
            steps=["pull main", "yarn build", "yarn deploy"],
            verification="curl /health returns 200",
            rollback="yarn deploy --rollback"))
        self.assertTrue(result.success, f"failed: {result.error_message}")

    def test_submit_runbook_rejects_fewer_than_3_steps(self) -> None:
        from tools.structured_knowledge_tools import SubmitRunbookTool
        result = _run_async(SubmitRunbookTool().execute(
            title="x", trigger="t",
            steps=["one", "two"],
            verification="v", rollback="r"))
        self.assertFalse(result.success)

    # ---- submit_postmortem ----

    def test_submit_postmortem_with_all_required_succeeds(self) -> None:
        from tools.structured_knowledge_tools import SubmitPostmortemTool
        result = _run_async(SubmitPostmortemTool().execute(
            title="P-001: feed 500s",
            incident_date="2026-05-23",
            impact="p99 +400ms for 30min",
            timeline=["12:00 alert fired", "12:05 oncall paged",
                       "12:30 rolled back"],
            root_cause="cache miss storm after deploy",
            action_items=["add cache warming step to runbook"]))
        self.assertTrue(result.success, f"failed: {result.error_message}")

    def test_submit_postmortem_rejects_empty_action_items(self) -> None:
        from tools.structured_knowledge_tools import SubmitPostmortemTool
        result = _run_async(SubmitPostmortemTool().execute(
            title="x", incident_date="2026-05-23", impact="i",
            timeline=["a", "b", "c"], root_cause="r", action_items=[]))
        self.assertFalse(result.success)

    def test_submit_postmortem_rejects_fewer_than_3_timeline_entries(self) -> None:
        from tools.structured_knowledge_tools import SubmitPostmortemTool
        result = _run_async(SubmitPostmortemTool().execute(
            title="x", incident_date="2026-05-23", impact="i",
            timeline=["a", "b"], root_cause="r", action_items=["x"]))
        self.assertFalse(result.success)

    # ---- list tools ----

    def test_list_adrs_returns_submitted_adrs(self) -> None:
        from tools.structured_knowledge_tools import (
            SubmitADRTool, ListADRsTool,
        )
        _run_async(SubmitADRTool().execute(
            title="ADR-001", decision="d", context="c",
            alternatives=["a"], consequences="x", status="accepted"))
        _run_async(SubmitADRTool().execute(
            title="ADR-002", decision="d2", context="c2",
            alternatives=["b"], consequences="y", status="proposed"))
        result = _run_async(ListADRsTool().execute())
        self.assertTrue(result.success)
        adrs = result.data["adrs"]
        self.assertEqual(len(adrs), 2)
        titles = {a["title"] for a in adrs}
        self.assertEqual(titles, {"ADR-001", "ADR-002"})

    def test_list_adrs_filters_by_status(self) -> None:
        from tools.structured_knowledge_tools import (
            SubmitADRTool, ListADRsTool,
        )
        _run_async(SubmitADRTool().execute(
            title="A1", decision="d", context="c",
            alternatives=["a"], consequences="x", status="accepted"))
        _run_async(SubmitADRTool().execute(
            title="A2", decision="d", context="c",
            alternatives=["a"], consequences="x", status="proposed"))
        result = _run_async(ListADRsTool().execute(status="accepted"))
        adrs = result.data["adrs"]
        self.assertEqual(len(adrs), 1)
        self.assertEqual(adrs[0]["title"], "A1")

    def test_list_runbooks_returns_submitted_runbooks(self) -> None:
        from tools.structured_knowledge_tools import (
            SubmitRunbookTool, ListRunbooksTool,
        )
        _run_async(SubmitRunbookTool().execute(
            title="R1", trigger="t", steps=["a", "b", "c"],
            verification="v", rollback="r"))
        result = _run_async(ListRunbooksTool().execute())
        self.assertTrue(result.success)
        self.assertEqual(len(result.data["runbooks"]), 1)

    def test_list_postmortems_returns_submitted(self) -> None:
        from tools.structured_knowledge_tools import (
            SubmitPostmortemTool, ListPostmortemsTool,
        )
        _run_async(SubmitPostmortemTool().execute(
            title="P1", incident_date="2026-05-23", impact="i",
            timeline=["a", "b", "c"], root_cause="r", action_items=["x"]))
        result = _run_async(ListPostmortemsTool().execute())
        self.assertTrue(result.success)
        self.assertEqual(len(result.data["postmortems"]), 1)


if __name__ == "__main__":
    unittest.main()
