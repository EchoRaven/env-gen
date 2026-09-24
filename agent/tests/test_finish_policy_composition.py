"""PR 2.5-fix regression tests (reviewer 2026-05-28).

After PR 2.5 shipped (commit fbf83504), the reviewer's 38-agent
fan-out found a confirmed deadlock regression: the claim-gate was
ordered BEFORE the lane-idle circuit breaker, and the first-match-
wins ``_apply_finish_policies`` loop short-circuits as soon as
claim-gate returns ``{"action": "continue"}``. That made the
breaker's idle counter never advance in gated lanes, so tier-3
(which the previous commit deliberately strengthened to cancel
unclaimed pending tasks) became dead code. The reactive escape
that PR 2.5 was supposed to make obsolete actually got disarmed.

This file pins the fixes:
  * Policy ordering — breaker MUST come first in YAML for every
    gated profile, and the builder MUST preserve YAML order.
  * Breaker still bookkeeps on a blocked finish — the breaker
    returns None unconditionally, so placing it ahead of the
    claim-gate is safe; placing it behind makes it dead.
  * Retry cap — after N consecutive blocks with the same task
    set, the claim-gate auto-cancels and lets finish through.
  * Dep-blocked tasks — claim_task hard-rejects dep-blocked
    tasks (service.py:494-500); the rejection message must
    flag them so the agent picks cancel, not claim.
  * deliver_project / report_completion now route through
    ``_apply_finish_policies`` so RetroBeforeDeliverPolicy fires
    in production (it never did before — its trigger tools were
    never the ones the lifecycle hook was called on).
"""

from __future__ import annotations

import ast
import asyncio
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

import yaml

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from multi_agent.workflow_policies import (  # noqa: E402
    ClaimAssignedTasksPolicy,
    LaneIdleCircuitBreakerPolicy,
    RetroBeforeDeliverPolicy,
    create_workflow_policies,
)

AGENTS_YAML = LLM_DIR / "multi_agent" / "agents" / "agents_config.yaml"
STEP_PIPELINE_TOOLING = (
    LLM_DIR / "multi_agent" / "agents" / "runtime" / "step_pipeline" / "tooling.py"
)


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


# --- Section 1: YAML ordering ---------------------------------------

class TestYamlOrderingBreakerFirst(unittest.TestCase):
    """For every gated lane in agents_config.yaml, the breaker must
    come BEFORE claim_assigned_tasks. The reviewer's primary
    finding: with the order inverted, the breaker is starved
    (claim-gate short-circuits the first-match-wins finish-policy
    loop), tier-3 never fires, the deadlock escape is dead code."""

    @classmethod
    def setUpClass(cls):
        cls.data = yaml.safe_load(AGENTS_YAML.read_text())

    def _kinds(self, profile_name):
        profile = self.data["profiles"][profile_name]
        return [
            (entry or {}).get("kind", "")
            for entry in (profile.get("workflow_policies") or [])
        ]

    def test_backend_breaker_before_claim_gate(self):
        kinds = self._kinds("backend")
        if "claim_assigned_tasks" not in kinds:
            self.skipTest("backend profile has no claim_assigned_tasks")
        self.assertLess(
            kinds.index("lane_idle_circuit_breaker"),
            kinds.index("claim_assigned_tasks"),
        )

    def test_frontend_breaker_before_claim_gate(self):
        kinds = self._kinds("frontend")
        if "claim_assigned_tasks" not in kinds:
            self.skipTest("frontend profile has no claim_assigned_tasks")
        self.assertLess(
            kinds.index("lane_idle_circuit_breaker"),
            kinds.index("claim_assigned_tasks"),
        )


class TestNoStarverBeforeBreakerInYaml(unittest.TestCase):
    """PR 2.5-fix-2 (reviewer follow-up): the previous version of
    this test class only checked the breaker-vs-claim-gate pair.
    The adversarial review found that ``hub_consistency_gate`` (also
    a starver) was still ordered BEFORE the breaker in all four
    gated profiles, recreating the EXACT same dead-tier-3 deadlock
    via a different policy. The structural two-pass dispatcher
    fixes this regardless of YAML order, but this hygiene test
    pins the convention: no starver kind (anything in
    ``workflow_policies.STARVER_POLICY_KINDS``) should appear
    BEFORE ``lane_idle_circuit_breaker`` in YAML."""

    @classmethod
    def setUpClass(cls):
        cls.data = yaml.safe_load(AGENTS_YAML.read_text())

    def _check_profile(self, profile_name: str):
        from multi_agent.workflow_policies import STARVER_POLICY_KINDS
        profile = self.data["profiles"].get(profile_name)
        if profile is None:
            self.skipTest(f"profile {profile_name!r} not in YAML")
        kinds = [
            (e or {}).get("kind", "") for e in
            (profile.get("workflow_policies") or [])
        ]
        if "lane_idle_circuit_breaker" not in kinds:
            self.skipTest(
                f"profile {profile_name!r} has no breaker — "
                "ordering rule doesn't apply"
            )
        breaker_idx = kinds.index("lane_idle_circuit_breaker")
        before = kinds[:breaker_idx]
        starvers_before = [k for k in before if k in STARVER_POLICY_KINDS]
        self.assertFalse(
            starvers_before,
            f"profile {profile_name!r}: starver kind(s) "
            f"{starvers_before} appear BEFORE "
            f"lane_idle_circuit_breaker in YAML. The two-pass "
            f"dispatcher structurally guarantees the breaker still "
            f"runs, but the YAML carries the old first-match-wins "
            f"mental model and is misleading. Move bookkeeping "
            f"policies (e.g. lane_idle_circuit_breaker) to the "
            f"front of workflow_policies.",
        )

    def test_design_no_starver_before_breaker(self):
        self._check_profile("design")

    def test_backend_no_starver_before_breaker(self):
        self._check_profile("backend")

    def test_frontend_no_starver_before_breaker(self):
        self._check_profile("frontend")


class TestBuilderPreservesYamlOrder(unittest.TestCase):
    """create_workflow_policies must instantiate policies in YAML
    order. If the builder ever sorted or deduplicated, the YAML
    ordering above would be silently undone — pin the contract."""

    def test_order_preserved(self):
        cfg = {
            "workflow_policies": [
                {"kind": "lane_idle_circuit_breaker",
                 "warn_after_idle_steps": 1,
                 "failforward_after_idle_steps": 2,
                 "halt_after_idle_steps": 3},
                {"kind": "claim_assigned_tasks"},
            ],
        }
        ps = create_workflow_policies(cfg)
        # Drop any auto-appended policies (depends_on, etc.) and
        # keep only the two we configured.
        kinds = []
        for p in ps:
            if isinstance(p, LaneIdleCircuitBreakerPolicy):
                kinds.append("lane_idle_circuit_breaker")
            elif isinstance(p, ClaimAssignedTasksPolicy):
                kinds.append("claim_assigned_tasks")
        self.assertEqual(
            kinds,
            ["lane_idle_circuit_breaker", "claim_assigned_tasks"],
            "builder reordered policies — the YAML ordering "
            "contract is broken. Check create_workflow_policies.",
        )


# --- Section 2: Breaker bookkeeps even when claim-gate would block --

class TestBreakerStillCountsViaRealDispatcher(unittest.TestCase):
    """PR 2.5-fix-2 (reviewer follow-up): the previous version of
    this test called the breaker and the gate IN ISOLATION; it
    proved their individual contracts but bypassed
    ``_apply_finish_policies`` entirely. That test would have
    passed even if the dispatcher was deleted. This test runs the
    real two-pass dispatcher with a starver registered BEFORE the
    breaker in the policy list, and asserts the breaker's idle
    counter advanced on each round — the exact regression vector
    we're guarding against. Verifies the structural fix, not just
    the policies' individual contracts."""

    def tearDown(self):
        _reset_event_loop()

    def test_breaker_advances_when_starver_is_first_in_dispatcher(self):
        """The deliberately-pathological order. Even with a starver
        first in the list, pass-1 bookkeeping runs the breaker
        before pass-2 ever asks the starver for a gate outcome."""

        from multi_agent.agents.runtime.tooling import (  # noqa: E402
            AgentTooling,
        )

        with tempfile.TemporaryDirectory() as tmp:
            reg = HubRegistry(Path(tmp), project_id="p", project_name="P")

            # Build a thin agent that owns _apply_finish_policies
            # via ToolingMixin — that's the real dispatcher under
            # test, not a unit-test reimplementation.
            class _RealishAgent(AgentTooling):
                def __init__(self, agent_id, reg, policies):
                    self.agent_id = agent_id
                    self._agent_id = agent_id
                    self._hubs = reg
                    self._logger = MagicMock()
                    self._workflow_policies = policies
                    self.workspace = MagicMock()
                    # impl-phase: the idle breaker is suppressed during kickoff
                    # (smoke #4 guard) — this test exercises impl-phase dispatch.
                    self._kickoff_bootstrapped = True

            # Plant an unclaimed assigned task so the claim-gate
            # really fires.
            reg.workhub.create_task(
                title="never claimed", description="...",
                agent="orchestrator", assignee="backend",
            )

            breaker = LaneIdleCircuitBreakerPolicy(
                warn_after_idle_steps=1,
                failforward_after_idle_steps=2,
                halt_after_idle_steps=3,
            )
            claim_gate = ClaimAssignedTasksPolicy()

            # DELIBERATELY ORDER STARVER FIRST. If pass-1 isn't
            # working, the breaker is starved here.
            agent = _RealishAgent("backend", reg, [claim_gate, breaker])

            for _ in range(2):
                outcome = asyncio.run(agent._apply_finish_policies(
                    tool_name="finish",
                    tool_args={"message": "done"},
                    tool_call=_StubToolCall(),
                    tool_call_id="call-1",
                    messages=[],
                    files_created=[],
                    files_modified=[],
                ))
                # The starver still gates correctly in pass 2.
                self.assertEqual(
                    outcome, {"action": "continue"},
                    "dispatcher should still surface the gate's "
                    "blocking outcome",
                )

            # And the breaker's idle counter advanced. With
            # halt_after_idle_steps=3 and 2 rounds, we expect
            # _consecutive_idle_steps >= 1 (first round seeds
            # prev_owned, subsequent rounds count idle).
            self.assertGreaterEqual(
                getattr(agent, "_consecutive_idle_steps", 0), 1,
                "breaker idle counter did not advance even when "
                "wired through the REAL _apply_finish_policies "
                "dispatcher — the two-pass structural fix failed.",
            )


# --- Section 3: claim-gate retry cap --------------------------------

class TestClaimGateRetryCap(unittest.TestCase):
    """After N consecutive blocks with the same task set, the
    claim-gate must auto-cancel and let finish proceed. Defence in
    depth: even if some future commit re-inverts policy ordering,
    this caps the cost of the regression at N rounds, not
    indefinite."""

    def tearDown(self):
        _reset_event_loop()

    def _run(self, policy, agent):
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

    def test_cap_leaves_tasks_pending_and_passes(self):
        """After the retry cap, the gate stops enforcing (finish passes) but
        the tasks stay PENDING — the RegistryHub→WorkHub sync completes them when
        the contract flips implemented. (They were auto-cancelled before
        2026-06-10, which raced the by-construction pipeline and littered
        every run with cancelled ghosts.)"""
        with tempfile.TemporaryDirectory() as tmp:
            reg = HubRegistry(Path(tmp), project_id="p", project_name="P")
            agent = _StubAgent("backend", reg)
            task = reg.workhub.create_task(
                title="never claimed", description="...",
                agent="orchestrator", assignee="backend",
            )
            policy = ClaimAssignedTasksPolicy()
            cap = policy._MAX_CONSECUTIVE_BLOCKS
            for i in range(cap):
                outcome = self._run(policy, agent)
                self.assertEqual(outcome, {"action": "continue"},
                                  f"round {i+1}/{cap}: expected block")
            outcome = self._run(policy, agent)
            self.assertIsNone(outcome, "after the cap, finish must pass")
            stored = reg.workhub.get_task(task["id"])
            self.assertEqual(stored.get("status"), "pending",
                              "tasks must stay pending for the contract-sync")


    def test_counter_resets_when_blocking_set_changes(self):
        """If the agent makes progress (cancels one task, gets a
        new assignment), the retry counter resets — only a STABLE
        blocking set should escalate. Otherwise an active queue
        that happens to be busy gets falsely auto-cancelled."""
        with tempfile.TemporaryDirectory() as tmp:
            reg = HubRegistry(Path(tmp), project_id="p", project_name="P")
            agent = _StubAgent("backend", reg)
            t1 = reg.workhub.create_task(
                title="t1", description="...",
                agent="orchestrator", assignee="backend",
            )
            policy = ClaimAssignedTasksPolicy()
            # Block 2 rounds — counter goes 1, 2.
            self._run(policy, agent)
            self._run(policy, agent)
            self.assertEqual(policy._consecutive_blocks["backend"], 2)
            # Cancel t1, add t2 — different set → counter resets.
            reg.workhub.cancel_task(t1["id"], "backend", reason="manual")
            reg.workhub.create_task(
                title="t2", description="...",
                agent="orchestrator", assignee="backend",
            )
            self._run(policy, agent)
            self.assertEqual(policy._consecutive_blocks["backend"], 1,
                              "blocking set changed but counter did "
                              "not reset — progress is being penalized.")


# --- Section 4: dep-blocked tasks routed to cancel hint -------------

class TestDepBlockedTagging(unittest.TestCase):
    """``claim_task`` hard-rejects on incomplete deps (service.py:
    494-500), so dep-blocked tasks are NOT actionable.

    instagram_v8 fix (2026-06-10, workflow_policies.py:848-863): a
    dep-blocked task is LEGITIMATE work waiting on its deps — it must
    never be a cancel target (a lane that couldn't cancel escalated
    "please cancel my dep-blocked tasks" to the orchestrator, which
    complied and PERMANENTLY LOST 4 core instagram pages whose deps
    completed seconds later). So the gate now:
      * lets finish THROUGH when the only unclaimed tasks are
        dep-blocked (no false block, no cancel hint), and
      * when there ARE claimable tasks, blocks on those and merely
        NOTES the dep-blocked ones as "leave pending" (never cancel)."""

    def tearDown(self):
        _reset_event_loop()

    def test_dep_blocked_only_queue_allows_finish(self):
        # instagram_v8 fix: when the lane's ONLY unclaimed task is
        # dep-blocked (no claimable/actionable work), the gate must let
        # finish through (return None) rather than block and hint cancel.
        # The lane re-wakes and claims the task the moment its deps
        # complete — cancellation is for work that should NOT be done at
        # all, never for "waiting on deps".
        with tempfile.TemporaryDirectory() as tmp:
            reg = HubRegistry(Path(tmp), project_id="p", project_name="P")
            agent = _StubAgent("backend", reg)
            # Parent task — pending, blocks the child.
            parent = reg.workhub.create_task(
                title="parent", description="...",
                agent="orchestrator", assignee="orchestrator",
            )
            reg.workhub.create_task(
                title="child", description="...",
                agent="orchestrator", assignee="backend",
                depends_on=[parent["id"]],
            )
            policy = ClaimAssignedTasksPolicy()
            msgs = []
            outcome = asyncio.run(policy.handle_finish(
                agent,
                tool_name="finish",
                tool_args={"message": "done"},
                tool_call=_StubToolCall(),
                tool_call_id="call-1",
                messages=msgs,
                files_created=[],
                files_modified=[],
            ))
            self.assertIsNone(
                outcome,
                "a dep-blocked-only queue must NOT block finish — the "
                "gate only binds on CLAIMABLE work (instagram_v8 fix).",
            )
            # No block message is appended when finish is allowed through.
            self.assertEqual(msgs, [])

    def test_actionable_and_dep_blocked_counts_in_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg = HubRegistry(Path(tmp), project_id="p", project_name="P")
            agent = _StubAgent("backend", reg)
            parent = reg.workhub.create_task(
                title="parent", description="...",
                agent="orchestrator", assignee="orchestrator",
            )
            reg.workhub.create_task(
                title="dep-blocked-child", description="...",
                agent="orchestrator", assignee="backend",
                depends_on=[parent["id"]],
            )
            reg.workhub.create_task(
                title="claimable-task", description="...",
                agent="orchestrator", assignee="backend",
            )
            policy = ClaimAssignedTasksPolicy()
            msgs = []
            asyncio.run(policy.handle_finish(
                agent,
                tool_name="finish",
                tool_args={"message": "done"},
                tool_call=_StubToolCall(),
                tool_call_id="call-1",
                messages=msgs,
                files_created=[],
                files_modified=[],
            ))
            blob = " ".join(getattr(m, "content", "") or "" for m in msgs)
            # The gate blocks on the CLAIMABLE task and merely NOTES the
            # dep-blocked one as "leave pending" (never a cancel target).
            # Assertions match the shipped message wording
            # (workflow_policies.py:960, :967).
            self.assertIn("1 CLAIMABLE task(s)", blob)
            self.assertIn("1 more assigned task(s) are DEP-BLOCKED", blob)


# --- Section 5: deliver_project routes through lifecycle policies ---

class TestDeliverProjectRoutesThroughLifecyclePolicies(unittest.TestCase):
    """The fix that made RetroBeforeDeliverPolicy actually live in
    production. Before this PR, _apply_finish_policies was only
    called when tool_name=='finish' (step_pipeline/tooling.py:172);
    the deliver_project branch (:204) executed the tool directly.
    Result: RetroBeforeDeliverPolicy's finish hook early-exited on
    every finish call (tool not in trigger set) and never ran on
    any deliver_project call (hook never invoked). Two failure
    modes; same outcome: a policy that test green and shipped
    code-dead for an entire round of work.

    Pin the fix at TWO levels:
      * Source guard — the deliver_project branch in
        step_pipeline/tooling.py contains a call to
        ``self._apply_finish_policies``. Regression-proof against
        a future refactor that drops the wiring.
      * Behaviour — RetroBeforeDeliverPolicy.handle_finish with
        tool_name='deliver_project' returns a blocking outcome
        (was already true, but combined with the source guard
        proves the full path).
    """

    def tearDown(self):
        _reset_event_loop()

    def test_step_pipeline_calls_finish_policies_on_deliver_project(self):
        """Structural: parse the dispatch site and walk its
        deliver_project branch, asserting it contains a call to
        _apply_finish_policies. A regression that re-bypasses the
        hook will fail this test immediately."""
        text = STEP_PIPELINE_TOOLING.read_text()
        tree = ast.parse(text)
        # Walk every ast.If; find the one whose test references
        # tool_name == "deliver_project" or `in ("deliver_project",
        # ...)`. The branch body must contain a Call to
        # _apply_finish_policies.
        found = False
        for node in ast.walk(tree):
            if not isinstance(node, ast.If):
                continue
            cond_src = ""
            try:
                cond_src = ast.unparse(node.test)
            except Exception:
                continue
            if "deliver_project" not in cond_src:
                continue
            body_src = ""
            try:
                body_src = "\n".join(ast.unparse(s) for s in node.body)
            except Exception:
                continue
            if "_apply_finish_policies" in body_src:
                found = True
                break
        self.assertTrue(found,
                          "step_pipeline/tooling.py: deliver_project "
                          "branch does not call _apply_finish_policies. "
                          "RetroBeforeDeliverPolicy will be dead code "
                          "until this wiring is restored.")

    def test_retro_policy_blocks_deliver_project_when_no_retro(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg = HubRegistry(Path(tmp), project_id="p", project_name="P")
            reg.attach_generation_id("gen_test_no_retro")
            agent = _StubAgent("verifier", reg)
            policy = RetroBeforeDeliverPolicy()
            msgs = []
            outcome = asyncio.run(policy.handle_finish(
                agent,
                tool_name="deliver_project",
                tool_args={"delivery_summary": "ship"},
                tool_call=_StubToolCall(),
                tool_call_id="call-1",
                messages=msgs,
                files_created=[],
                files_modified=[],
            ))
            self.assertEqual(outcome, {"action": "continue"},
                              "retro gate should have blocked "
                              "deliver_project — no retro for this "
                              "generation should have been recorded.")
            blob = " ".join(getattr(m, "content", "") or "" for m in msgs)
            self.assertIn("submit_retro", blob)

    def test_retro_policy_does_not_intercept_finish_calls(self):
        """The retro gate's whole reason for existing is to block
        deliver/report calls — it explicitly opts out of finish.
        Pin that behaviour so a future refactor that overloads
        retro for finish-time doesn't surprise verifier agents."""
        with tempfile.TemporaryDirectory() as tmp:
            reg = HubRegistry(Path(tmp), project_id="p", project_name="P")
            reg.attach_generation_id("gen_test_finish")
            agent = _StubAgent("verifier", reg)
            policy = RetroBeforeDeliverPolicy()
            outcome = asyncio.run(policy.handle_finish(
                agent,
                tool_name="finish",
                tool_args={"message": "done"},
                tool_call=_StubToolCall(),
                tool_call_id="call-1",
                messages=[],
                files_created=[],
                files_modified=[],
            ))
            self.assertIsNone(outcome,
                               "retro gate intercepted a plain finish — "
                               "it must only fire on the deliver/report "
                               "lifecycle tools.")


if __name__ == "__main__":
    unittest.main()
