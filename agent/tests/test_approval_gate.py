"""Guard: the human-in-the-loop approval gate (auto/ask modes).

Pins: auto mode is a no-op; `ask` mode pauses gated structural actions
(task/gate creation) and resolves on the human's decision (approve → proceed,
reject → feedback to the agent); non-gated tools are never gated; a forgotten
approval auto-approves on timeout (no wedge).
"""

import sys
import types
import tempfile
import unittest
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime import approval as A  # noqa: E402


def _hubs(store: Path):
    # Minimal HubRegistry stand-in: only base_dir/_store_dir are used.
    return types.SimpleNamespace(_store_dir=str(store), base_dir=str(store.parent.parent))


def _run(coro):
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class ClassifyTests(unittest.TestCase):
    def test_task_create_is_gated(self):
        self.assertEqual(A.classify("workhub_task", {"action": "create", "title": "X"}), "task")

    def test_task_claim_is_not_gated(self):
        self.assertIsNone(A.classify("workhub_task", {"action": "claim"}))

    def test_gate_creation_is_gated(self):
        self.assertEqual(A.classify("registryhub_register_verification_chain", {"name": "c"}), "gate")

    def test_other_tools_not_gated(self):
        self.assertIsNone(A.classify("read", {"path": "x"}))
        self.assertIsNone(A.classify("registryhub_register_endpoint", {"path": "/x"}))


class ModeTests(unittest.TestCase):
    def setUp(self):
        self.store = Path(tempfile.mkdtemp(prefix="appr_"))

    def test_default_mode_is_auto(self):
        self.assertEqual(A.read_mode(self.store), "auto")

    def test_write_and_read_ask(self):
        A.write_config(self.store, mode="ask")
        self.assertEqual(A.read_mode(self.store), "ask")


class EnforceTests(unittest.TestCase):
    def setUp(self):
        self.store = Path(tempfile.mkdtemp(prefix="appr_"))
        self.hubs = _hubs(self.store)

    def test_auto_mode_is_noop(self):
        # gated action but auto mode → proceed (None), no request written
        out = _run(A.enforce(self.hubs, "orch", "workhub_task", {"action": "create", "title": "T"}))
        self.assertIsNone(out)
        self.assertEqual(A.list_requests(self.store), [])

    def test_non_gated_tool_is_noop_even_in_ask(self):
        A.write_config(self.store, mode="ask")
        out = _run(A.enforce(self.hubs, "orch", "read", {"path": "x"}))
        self.assertIsNone(out)
        self.assertEqual(A.list_requests(self.store), [])

    def test_ask_mode_approve_proceeds(self):
        A.write_config(self.store, mode="ask")

        async def fake_sleep(_):
            # simulate the human approving during the first poll
            pend = A.list_requests(self.store, status="pending")
            if pend:
                A.record_decision(self.store, pend[0]["id"], approve=True, decided_by="alice")

        out = _run(A.enforce(self.hubs, "orch", "workhub_task",
                             {"action": "create", "title": "Build X"}, sleep=fake_sleep))
        self.assertIsNone(out)  # approved → proceed
        done = A.list_requests(self.store, status="approved")
        self.assertEqual(len(done), 1)
        self.assertEqual(done[0]["summary"], "Create task: Build X")

    def test_ask_mode_reject_returns_feedback(self):
        A.write_config(self.store, mode="ask")

        async def fake_sleep(_):
            pend = A.list_requests(self.store, status="pending")
            if pend:
                A.record_decision(self.store, pend[0]["id"], approve=False,
                                  feedback="scope this to videos only")

        out = _run(A.enforce(self.hubs, "orch", "workhub_task",
                             {"action": "create", "title": "Build X"}, sleep=fake_sleep))
        self.assertIsNotNone(out)
        self.assertFalse(out.success)
        self.assertIn("REJECTED", out.error_message)
        self.assertIn("scope this to videos only", out.error_message)

    def test_timeout_auto_approves_no_wedge(self):
        A.write_config(self.store, mode="ask", timeout_sec=0.001)

        async def fast_sleep(_):
            return  # never decide → force timeout

        out = _run(A.enforce(self.hubs, "orch", "workhub_task",
                             {"action": "create", "title": "T"}, poll_sec=0.001, sleep=fast_sleep))
        self.assertIsNone(out)  # auto-approved on timeout, did not wedge
        self.assertTrue(A.list_requests(self.store, status="auto_approved"))


class RequestDecisionTests(unittest.TestCase):
    """The reusable decision call used by the orchestrator's MILESTONE hook
    (milestones aren't a tool, so they bypass classify and call this directly)."""
    def setUp(self):
        self.store = Path(tempfile.mkdtemp(prefix="appr_"))
        self.hubs = _hubs(self.store)

    def test_auto_mode_approves_immediately(self):
        d = _run(A.request_decision(self.hubs, "orchestrator", "milestone", "Start M1"))
        self.assertTrue(d["approved"] and d["auto"])
        self.assertEqual(A.list_requests(self.store), [])  # nothing written in auto

    def test_ask_mode_milestone_approve(self):
        A.write_config(self.store, mode="ask")

        async def fake_sleep(_):
            pend = A.list_requests(self.store, status="pending")
            if pend:
                A.record_decision(self.store, pend[0]["id"], approve=True, decided_by="alice")

        d = _run(A.request_decision(self.hubs, "orchestrator", "milestone",
                                    "Start milestone 1/2: Core @ 1.0.0", sleep=fake_sleep))
        self.assertTrue(d["approved"] and not d["auto"])
        rec = A.list_requests(self.store, status="approved")[0]
        self.assertEqual(rec["action_type"], "milestone")  # shows up as a milestone request in the UI

    def test_ask_mode_milestone_reject_with_feedback(self):
        A.write_config(self.store, mode="ask")

        async def fake_sleep(_):
            pend = A.list_requests(self.store, status="pending")
            if pend:
                A.record_decision(self.store, pend[0]["id"], approve=False, feedback="defer studio to M2")

        d = _run(A.request_decision(self.hubs, "orchestrator", "milestone",
                                    "Start milestone 2/2: Studio @ 1.1.0", sleep=fake_sleep))
        self.assertFalse(d["approved"])
        self.assertEqual(d["feedback"], "defer studio to M2")


if __name__ == "__main__":
    unittest.main()
