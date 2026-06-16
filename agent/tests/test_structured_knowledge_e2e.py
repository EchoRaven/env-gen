"""End-to-end: structured submit + list workflow with isolated KnowledgeStore."""

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


class StructuredKnowledgeE2ETests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="sk_e2e_"))
        from multi_agent.knowledge.store import KnowledgeStore
        self.store = KnowledgeStore(db_url=f"sqlite:///{self.tmp}/k.db")
        from tools import knowledge_tools as _kt
        _kt._knowledge_store = self.store

    def tearDown(self) -> None:
        from tools import knowledge_tools as _kt
        _kt._knowledge_store = None
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_full_doc_lifecycle(self) -> None:
        from tools.structured_knowledge_tools import (
            SubmitADRTool, SubmitRunbookTool, SubmitPostmortemTool,
            ListADRsTool, ListRunbooksTool, ListPostmortemsTool,
        )
        # Submit one of each
        _run_async(SubmitADRTool().execute(
            title="ADR-001", decision="d", context="c",
            alternatives=["a", "b"], consequences="x", status="accepted"))
        _run_async(SubmitRunbookTool().execute(
            title="R-001", trigger="t",
            steps=["s1", "s2", "s3"], verification="v", rollback="r"))
        _run_async(SubmitPostmortemTool().execute(
            title="P-001", incident_date="2026-05-23", impact="i",
            timeline=["a", "b", "c"], root_cause="r", action_items=["x"]))

        # List each
        adrs = _run_async(ListADRsTool().execute()).data["adrs"]
        runbooks = _run_async(ListRunbooksTool().execute()).data["runbooks"]
        postmortems = _run_async(ListPostmortemsTool().execute()).data["postmortems"]

        self.assertEqual(len(adrs), 1)
        self.assertEqual(len(runbooks), 1)
        self.assertEqual(len(postmortems), 1)
        self.assertEqual(adrs[0]["structured_fields"]["status"], "accepted")
        self.assertEqual(runbooks[0]["structured_fields"]["steps"],
                         ["s1", "s2", "s3"])
        self.assertEqual(postmortems[0]["structured_fields"]["action_items"],
                         ["x"])

    def test_bad_submissions_reject_and_do_not_persist(self) -> None:
        from tools.structured_knowledge_tools import (
            SubmitADRTool, ListADRsTool,
            SubmitRunbookTool, SubmitPostmortemTool,
        )
        # ADR with empty alternatives
        r1 = _run_async(SubmitADRTool().execute(
            title="x", decision="d", context="c",
            alternatives=[], consequences="x", status="accepted"))
        self.assertFalse(r1.success)
        # Runbook with 2 steps
        r2 = _run_async(SubmitRunbookTool().execute(
            title="x", trigger="t", steps=["a", "b"],
            verification="v", rollback="r"))
        self.assertFalse(r2.success)
        # Postmortem with bad date
        r3 = _run_async(SubmitPostmortemTool().execute(
            title="x", incident_date="yesterday", impact="i",
            timeline=["a", "b", "c"], root_cause="r", action_items=["x"]))
        self.assertFalse(r3.success)

        adrs = _run_async(ListADRsTool().execute()).data["adrs"]
        self.assertEqual(adrs, [])


if __name__ == "__main__":
    unittest.main()
