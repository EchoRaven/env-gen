"""Guard test for the youtube-run claim-gate bug.

THE BUG (confirmed from the youtube run):
``ClaimAssignedTasksPolicy.handle_finish`` blocks ``finish()`` while the
agent has pending, unclaimed, assigned tasks. It has a retry-cap escape:
after ``_MAX_CONSECUTIVE_BLOCKS`` consecutive blocks with the SAME
blocking set, it lets finish through. The OLD logic reset that counter
on ANY set change. Claiming a task REMOVES it from the unclaimed set
(the set shrinks), so an agent that dutifully claims its tasks one-by-one
kept resetting its own escape hatch and was forced to claim EVERY task
(the real run made 46 individual ``claim`` round-trips, then logged that
it was "trapped"). There was also no bulk-claim.

THE FIX:
  1. ``handle_finish`` is now SHRINK-TOLERANT: a same-or-shrinking
     blocking set (subset of the previous set) KEEPS counting toward the
     escape; only a genuinely NEW unclaimed task resets the counter.
  2. ``workhub_task(action="claim_all")`` claims every claimable assigned
     task in one call, skipping dep-blocked ones.

These tests pin both. Setup style mirrors
``test_claim_assigned_tasks_policy.py`` (stub agent + real HubRegistry)
and ``test_hub_tools_plantool_binding.py`` (bound WorkHubTaskTool).
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from multi_agent.workflow_policies import ClaimAssignedTasksPolicy  # noqa: E402
from tools.hub_tools import WorkHubTaskTool  # noqa: E402


def _reset_event_loop():
    try:
        asyncio.set_event_loop(asyncio.new_event_loop())
    except Exception:
        pass


class _StubAgent:
    def __init__(self, agent_id, reg):
        self.agent_id = agent_id
        self._agent_id = agent_id
        self.workspace = MagicMock()
        self._hubs = reg
        self._logger = MagicMock()


class _StubToolCall:
    def __init__(self):
        self.id = "call-1"
        self.function = MagicMock()
        self.function.name = "finish"
        self.function.arguments = "{}"


def _call_finish(policy, agent):
    """One handle_finish round. Returns the policy outcome
    (None == finish allowed; {"action": "continue"} == blocked)."""
    return asyncio.run(policy.handle_finish(
        agent,
        tool_name="finish",
        tool_args={"message": "done"},
        tool_call=_StubToolCall(),
        tool_call_id="call-1",
        messages=[],
        files_created=[],
        files_modified=[],
    ))


class TestShrinkToleranceReleasesGate(unittest.TestCase):
    """Reproduce the loop: an agent with N>=4 pending unclaimed assigned
    tasks claims ONE per round (the unclaimed set shrinks every round).
    The escape hatch must still release after _MAX_CONSECUTIVE_BLOCKS
    blocks even though the set changed (shrank) every round."""

    def tearDown(self):
        _reset_event_loop()

    def test_claiming_one_per_round_still_reaches_escape(self):
        n = 5
        cap = ClaimAssignedTasksPolicy._MAX_CONSECUTIVE_BLOCKS
        self.assertGreaterEqual(n, cap + 1,
                                "need more tasks than the cap so we never empty the "
                                "queue before the escape would fire")
        with tempfile.TemporaryDirectory() as tmp:
            reg = HubRegistry(Path(tmp), project_id="p", project_name="P")
            agent = _StubAgent("backend", reg)
            policy = ClaimAssignedTasksPolicy()
            for i in range(n):
                reg.workhub.create_task(
                    title=f"task-{i}", description="...",
                    agent="orchestrator", assignee="backend", task_id=f"t{i}",
                )

            released_on = None
            # Block 1..cap should all BLOCK; block cap+1 should RELEASE.
            # Between each call we claim one task (set shrinks by one) to
            # simulate the agent dutifully claiming one-by-one.
            for round_no in range(1, cap + 2):
                outcome = _call_finish(policy, agent)
                if outcome is None:
                    released_on = round_no
                    break
                self.assertEqual(outcome.get("action"), "continue",
                                 f"round {round_no} must block (action=continue)")
                # Agent claims one task this round → unclaimed set shrinks.
                # (claim a still-unclaimed one; tolerate if already empty.)
                for tid in (f"t{round_no - 1}",):
                    res = reg.workhub.claim_task(tid, "backend")
                    self.assertNotIn("error", res or {},
                                     f"claim of {tid} should succeed (no deps)")

            self.assertEqual(
                released_on, cap + 1,
                f"gate must release on block {cap + 1} despite the set shrinking "
                f"each round; released_on={released_on}",
            )

    def test_old_reset_on_any_change_would_never_release(self):
        """Non-vacuity guard. Under the OLD logic (reset the counter on
        ANY set change), shrinking the set every round resets the counter
        to 1 each time, so the escape-via-cap NEVER fires while the queue
        is still non-empty. We emulate the old rule against the SAME
        non-empty shrinking-set sequence and assert the counter never
        exceeds the cap — proving the gate would have stayed BLOCKED on
        every round of the test above (so that test is non-vacuous: it
        only passes because of the new shrink-tolerant rule).

        We only emulate rounds with a NON-EMPTY blocking set, because the
        real handle_finish returns early (and resets) the moment the
        unclaimed queue is empty — those rounds never reach the cap
        bookkeeping and would release for the trivial 'queue empty'
        reason, not via the escape hatch."""
        cap = ClaimAssignedTasksPolicy._MAX_CONSECUTIVE_BLOCKS

        # Round k sees ids {k-1 .. n-1}: a strict, non-empty subset each
        # round. Stop before the set would go empty.
        n = 5
        last_set = None
        consecutive = 0
        max_reached = 0
        for k in range(1, n + 1):  # k=1..n; at k=n the set is {t_{n-1}} (size 1)
            current_set = frozenset(f"t{j}" for j in range(k - 1, n))
            self.assertTrue(current_set, "emulate only non-empty blocking sets")
            # OLD rule: reset on ANY change (the bug).
            if last_set == current_set:
                consecutive += 1
            else:
                consecutive = 1
                last_set = current_set
            max_reached = max(max_reached, consecutive)
        self.assertLessEqual(
            max_reached, cap,
            "OLD reset-on-any-change rule never exceeds the cap on a non-empty "
            "shrinking sequence — confirming the shrink-tolerant test is "
            "non-vacuous (the gate would have stayed blocked under the bug).",
        )


class TestNewWorkResetsCounter(unittest.TestCase):
    """A genuinely NEW unclaimed task (the set grows with a new id) must
    reset the counter to 1 — the agent has fresh work to act on."""

    def tearDown(self):
        _reset_event_loop()

    def test_new_task_resets_consecutive_counter(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg = HubRegistry(Path(tmp), project_id="p", project_name="P")
            agent = _StubAgent("backend", reg)
            policy = ClaimAssignedTasksPolicy()
            reg.workhub.create_task(
                title="t0", description="...",
                agent="orchestrator", assignee="backend", task_id="t0",
            )
            # Two blocks with the same set → counter climbs to 2.
            _call_finish(policy, agent)
            _call_finish(policy, agent)
            self.assertEqual(policy._consecutive_blocks["backend"], 2)
            # A NEW unclaimed task enters the queue (set grows) → reset to 1.
            reg.workhub.create_task(
                title="t1-new", description="...",
                agent="orchestrator", assignee="backend", task_id="t1",
            )
            _call_finish(policy, agent)
            self.assertEqual(
                policy._consecutive_blocks["backend"], 1,
                "a new unclaimed task must reset the escape counter to 1",
            )


class TestClaimAll(unittest.TestCase):
    """workhub_task(action='claim_all') claims every claimable assigned
    task in one call and reports dep-blocked ones as skipped."""

    def tearDown(self):
        _reset_event_loop()

    def _bind(self, hubs, agent_id="backend"):
        tool = WorkHubTaskTool()
        tool._hubs = hubs
        tool._agent_id = agent_id
        return tool

    def test_claim_all_claims_claimable_skips_dep_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg = HubRegistry(Path(tmp), project_id="p", project_name="P")
            # 3 claimable, no deps.
            for i in range(3):
                reg.workhub.create_task(
                    title=f"c{i}", description="...",
                    agent="orchestrator", assignee="backend", task_id=f"c{i}",
                )
            # A dep that is NOT completed (it's pending) → blocks its dependent.
            reg.workhub.create_task(
                title="dep", description="...",
                agent="orchestrator", assignee="frontend", task_id="dep",
            )
            # A dep-blocked task assigned to backend (depends on the pending dep).
            reg.workhub.create_task(
                title="blocked", description="...",
                agent="orchestrator", assignee="backend", task_id="blocked",
                depends_on=["dep"],
            )

            tool = self._bind(reg)
            result = asyncio.run(tool._run(action="claim_all"))
            data = result.data or {}
            self.assertEqual(sorted(data["claimed"]), ["c0", "c1", "c2"])
            self.assertEqual(data["claimed_count"], 3)
            self.assertEqual(data["skipped_dep_blocked"], ["blocked"])
            self.assertEqual(data.get("failed"), [])

            # The 3 claimable ones are now in_progress + owned by backend.
            for cid in ("c0", "c1", "c2"):
                t = reg.workhub.stores.tasks.get(cid)
                self.assertEqual(t["status"], "in_progress")
                self.assertEqual(t["claimed_by"], "backend")
            # The dep-blocked one is left untouched (still pending, unclaimed).
            blk = reg.workhub.stores.tasks.get("blocked")
            self.assertEqual(blk["status"], "pending")
            self.assertFalse(blk["claimed_by"])

    def test_claim_all_empty_queue_returns_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg = HubRegistry(Path(tmp), project_id="p", project_name="P")
            tool = self._bind(reg)
            result = asyncio.run(tool._run(action="claim_all"))
            data = result.data or {}
            self.assertEqual(data["claimed_count"], 0)
            self.assertEqual(data["claimed"], [])
            self.assertEqual(data["skipped_dep_blocked"], [])

    def test_claim_all_unblocks_finish_gate(self):
        """End-to-end: an agent with several claimable tasks calls
        claim_all once, then finish() is no longer blocked (the queue is
        empty of unclaimed pending work)."""
        with tempfile.TemporaryDirectory() as tmp:
            reg = HubRegistry(Path(tmp), project_id="p", project_name="P")
            agent = _StubAgent("backend", reg)
            policy = ClaimAssignedTasksPolicy()
            for i in range(4):
                reg.workhub.create_task(
                    title=f"c{i}", description="...",
                    agent="orchestrator", assignee="backend", task_id=f"c{i}",
                )
            # Blocked before claiming.
            self.assertIsNotNone(_call_finish(policy, agent))
            # One bulk claim.
            tool = self._bind(reg)
            res = asyncio.run(tool._run(action="claim_all"))
            self.assertEqual(res.data["claimed_count"], 4)
            # Finish now allowed (no unclaimed pending assigned tasks left).
            self.assertIsNone(_call_finish(policy, agent))


if __name__ == "__main__":
    unittest.main()
