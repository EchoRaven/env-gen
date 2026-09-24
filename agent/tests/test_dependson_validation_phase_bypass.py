"""PROPOSAL #20 (C-i) — DependsOnPolicy honors the framework validation-phase marker.

youtube run #3 deadlock: run_validation was permanently BLOCKED on "no verification
chains registered" → no api_smoke → no delivery. The framework's deterministic
Design-A self-trigger (framework_validation.py:236 sets metadata["validation_phase"]
=True, source "orchestrator") fired 4× and was ADMITTED by VerifierValidationTriggerPolicy
— but VETOED by DependsOnPolicy ("waiting on depends_on=['frontend','backend']"), which
had no validation_phase escape. The verifier's _upstream_ready_agents never gained
frontend/backend (it received 0 task_ready from them — lane finish-notifies went to the
orchestrator), so DependsOnPolicy blocked EVERY trigger all run, framework + LLM alike.

Fix (reviewer-prescribed C-i, conditions C1-C8): add a framework-marker bypass to
DependsOnPolicy.allow_task_ready — honor metadata["validation_phase"]==True (the
framework-only BOOLEAN, never the lane-reachable `tags` membership). Do NOT edit
VerifierValidationTriggerPolicy (it already admits — fix A was a no-op).

C3 (unit) + C4 (full verifier chain). LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "env_generator" / "llm_generator")):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.workflow_policies import (  # noqa: E402
    DependsOnPolicy, create_workflow_policies)


def _msg(source, metadata=None, payload="task_ready"):
    return types.SimpleNamespace(
        header=types.SimpleNamespace(source_agent_id=source),
        metadata=metadata or {}, payload=payload)


def _verifier(upstreams=()):
    return types.SimpleNamespace(agent_id="verifier",
                                 _upstream_ready_agents=set(upstreams))


def _chain_decision(policies, agent, msg):
    """Mirror messaging._should_start_from_task_ready: suppress on the FIRST
    policy that returns (False, …); else admit."""
    for pol in policies:
        decision = pol.allow_task_ready(agent, msg)
        if decision is None:
            continue
        ok, reason = decision
        if not ok:
            return False, reason
    return True, "ok"


class DependsOnValidationPhaseBypass(unittest.TestCase):
    """C3 — the single-policy gate."""

    def setUp(self):
        self.dep = DependsOnPolicy(["frontend", "backend"])

    def test_framework_marker_bypasses_depends_on_with_empty_upstreams(self):
        # the run-#3 trigger: orchestrator-sourced, validation_phase=True, verifier
        # has NEITHER upstream ready → must now ADMIT (return None).
        m = _msg("orchestrator",
                 {"validation_phase": True, "msg_type": "task_ready"},
                 "run your validation pass now")
        self.assertIsNone(self.dep.allow_task_ready(_verifier(), m))

    def test_bare_trigger_still_blocked(self):
        # no validation_phase marker, empty upstreams → STILL "waiting on depends_on"
        m = _msg("orchestrator", {"msg_type": "task_ready"}, "run your validation pass")
        decision = self.dep.allow_task_ready(_verifier(), m)
        self.assertIsNotNone(decision)
        self.assertFalse(decision[0])
        self.assertIn("depends_on", decision[1])

    def test_tag_validation_phase_does_NOT_bypass(self):
        # ANTI-FORGE (C2): a lane CAN put "validation_phase" in `tags`
        # (orchestrator_agent.j2). The tag must NOT bypass — only the framework-set
        # metadata BOOLEAN does. ("validation_phase" the tag is also not the
        # validation_ready signal, so the :130 escape doesn't fire either.)
        m = _msg("backend",
                 {"tags": ["validation_phase"], "msg_type": "task_ready"},
                 "please validate")
        decision = self.dep.allow_task_ready(_verifier(), m)
        self.assertIsNotNone(decision)
        self.assertFalse(decision[0])  # still blocked

    def test_falsey_marker_does_not_bypass(self):
        m = _msg("orchestrator", {"validation_phase": False, "msg_type": "task_ready"}, "x")
        decision = self.dep.allow_task_ready(_verifier(), m)
        self.assertFalse(decision[0])

    def test_satisfied_upstreams_admits_as_before(self):
        # REGRESSION: the satisfied path is unchanged (no marker needed).
        m = _msg("orchestrator", {"msg_type": "task_ready"}, "x")
        self.assertIsNone(self.dep.allow_task_ready(
            _verifier(["frontend", "backend"]), m))

    def test_no_depends_on_is_always_open(self):
        self.assertIsNone(DependsOnPolicy([]).allow_task_ready(_verifier(), _msg("x")))

    def test_resident_wakeup_inherits_bypass(self):
        # allow_resident_wakeup delegates → the idle verifier wakes on the marker too.
        m = _msg("orchestrator", {"validation_phase": True}, "x")
        self.assertIsNone(self.dep.allow_resident_wakeup(_verifier(), m, {}))


class FullVerifierChain(unittest.TestCase):
    """C4 — the REAL verifier policy chain (DependsOnPolicy + VerifierValidationTriggerPolicy)
    built via create_workflow_policies, exercised the way messaging does."""

    def _chain(self):
        return create_workflow_policies({
            "flags": {"depends_on": ["frontend", "backend"]},
            "workflow_policies": [
                {"kind": "verifier_validation_trigger",
                 "allowed_sender": "orchestrator",
                 "accepted_tags": ["validation_phase"]},
            ],
        })

    def test_chain_has_both_gates(self):
        kinds = {type(p).__name__ for p in self._chain()}
        self.assertIn("DependsOnPolicy", kinds)
        self.assertIn("VerifierValidationTriggerPolicy", kinds)

    def test_framework_trigger_admitted_by_full_chain_empty_upstreams(self):
        # the run-#3 scenario end-to-end: framework validation_phase trigger, empty
        # upstreams → the FULL chain admits (both gates return None).
        m = _msg("orchestrator",
                 {"validation_phase": True, "msg_type": "task_ready"},
                 "run your validation pass now")
        ok, why = _chain_decision(self._chain(), _verifier(), m)
        self.assertTrue(ok, f"chain should admit the framework trigger, got: {why}")

    def test_llm_messagebus_trigger_still_rejected(self):
        # the secondary LLM send_message path (source rewritten to "messagebus", no
        # validation_phase marker) → the chain still REJECTS it (no spurious admit).
        m = _msg("messagebus", {"msg_type": "task_ready"}, "go register the chains")
        ok, _why = _chain_decision(self._chain(), _verifier(), m)
        self.assertFalse(ok)

    def test_satisfied_upstreams_chain_admits(self):
        m = _msg("orchestrator", {"msg_type": "task_ready", "validation_phase": True},
                 "validate")
        ok, why = _chain_decision(self._chain(), _verifier(["frontend", "backend"]), m)
        self.assertTrue(ok, why)


if __name__ == "__main__":
    unittest.main()
