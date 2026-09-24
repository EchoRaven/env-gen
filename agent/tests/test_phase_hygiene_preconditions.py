"""PROPOSAL #24 — run-phase hygiene: agents do out-of-stage work during kickoff
because there's no authoritative run-global phase (`_active_phase` is transient/None
in the resident loops where the orchestrator + debugger live).

The reviewer-prescribed fix EXTENDS the existing hub-derived gates (NOT a new helper):
- Orchestrator: gate deliverability_check/run_start/run_validation on
  `kickoff_finalized` (blocks while `not _kickoff_bootstrapped`). Keyed on the bare
  `action` stage so it fires in the resident loop where `_active_phase` is None
  (an allowlist keyed on `kickoff:action` would NOT bite there — review §5/cond 2).
- Debugger: KickoffBootstrapGate policy (suppresses the premature run_completed
  WAKEUP) + gate bug_create/bug_triage on `validation_phase_reached` (blocks the bug
  TOOLS until every business endpoint is implemented — the IMPL→VALIDATION boundary).

Non-interference (review §7/Q5): the deterministic framework validate/deliver drivers
run on a separate run()-loop path and never call these LLM tools, so the gates can't
choke them — asserted by source inspection.

LOCAL-ONLY (agent/tests/ gitignored).
"""

from __future__ import annotations

import inspect
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.agents.runtime.preconditions import (  # noqa: E402
    kickoff_finalized, validation_phase_reached, resolve_precondition)


def _agent(*, bootstrapped=False, endpoints=None, has_hub=True):
    """Stub agent: _kickoff_bootstrapped flag + _hubs.registryhub.get_endpoints()."""
    hubs = None
    if has_hub:
        registryhub = SimpleNamespace(get_endpoints=lambda: (endpoints or {}))
        hubs = SimpleNamespace(registryhub=registryhub)
    return SimpleNamespace(_kickoff_bootstrapped=bootstrapped, _hubs=hubs,
                           agent_id="t")


def _biz(status):
    # a business endpoint = no fixed kind (auth/oauth/infra/spine)
    return {"path": "/notes", "status": status}


class KickoffFinalized(unittest.TestCase):
    def test_registered(self):
        self.assertIs(resolve_precondition("kickoff_finalized"), kickoff_finalized)

    def test_blocks_during_kickoff(self):
        for tool in ("deliverability_check", "run_start", "run_validation"):
            msg = kickoff_finalized(_agent(bootstrapped=False), tool, {})
            self.assertIsNotNone(msg, f"{tool} must be blocked pre-finalize")
            self.assertIn(tool, msg)
            self.assertIn("KICKOFF", msg)

    def test_allows_post_finalize(self):
        for tool in ("deliverability_check", "run_start", "run_validation"):
            self.assertIsNone(
                kickoff_finalized(_agent(bootstrapped=True), tool, {}),
                f"{tool} must be allowed once kickoff is bootstrapped")

    def test_monotonic_no_hub_read(self):
        # purely flag-driven; never touches hubs (resident-loop safe, cheap)
        a = _agent(bootstrapped=True, has_hub=False)
        self.assertIsNone(kickoff_finalized(a, "run_start", {}))


class ValidationPhaseReached(unittest.TestCase):
    def test_registered(self):
        self.assertIs(resolve_precondition("validation_phase_reached"),
                      validation_phase_reached)

    def test_blocks_with_no_endpoints(self):
        # kickoff: no contract yet → premature
        msg = validation_phase_reached(_agent(endpoints={}), "bug_create", {})
        self.assertIsNotNone(msg)
        self.assertIn("bug_create", msg)
        self.assertIn("VALIDATION", msg)

    def test_blocks_when_endpoints_not_all_implemented(self):
        eps = {"e1": _biz("implemented"), "e2": _biz("defined")}
        for tool in ("bug_create", "bug_triage"):
            self.assertIsNotNone(
                validation_phase_reached(_agent(endpoints=eps), tool, {}),
                f"{tool} must block while an endpoint is unimplemented")

    def test_allows_when_all_business_endpoints_implemented(self):
        eps = {"e1": _biz("implemented"), "e2": _biz("implemented")}
        for tool in ("bug_create", "bug_triage"):
            self.assertIsNone(
                validation_phase_reached(_agent(endpoints=eps), tool, {}),
                f"{tool} must open once all business endpoints implemented")

    def test_uses_same_predicate_as_drivers(self):
        # the gate must reuse all_business_endpoints_implemented (review Q2) — not a
        # parallel encoding — so it never diverges from the deterministic drivers.
        from multi_agent.runtime.lifecycle import all_business_endpoints_implemented
        src = inspect.getsource(validation_phase_reached)
        self.assertIn("all_business_endpoints_implemented", src)
        # auth/infra endpoints (fixed surface) don't count → an app with only an
        # auth endpoint is still pre-validation
        auth_only = {"a": {"path": "/auth/login", "status": "implemented",
                           "kind": "auth"}}
        self.assertFalse(all_business_endpoints_implemented(auth_only))
        self.assertIsNotNone(
            validation_phase_reached(_agent(endpoints=auth_only), "bug_create", {}))

    def test_no_hub_does_not_block(self):
        # can't determine phase → fail OPEN (don't wedge on a missing hub)
        self.assertIsNone(
            validation_phase_reached(_agent(has_hub=False), "bug_create", {}))


class ConfigWiring(unittest.TestCase):
    def setUp(self):
        import yaml
        cfg_path = (LLM_DIR / "multi_agent" / "agents" / "agents_config.yaml")
        with open(cfg_path) as f:
            self.cfg = yaml.safe_load(f)
        self.profiles = self.cfg["profiles"]

    def test_orchestrator_gates_the_three_tools(self):
        action = self.profiles["orchestrator"]["stage_tool_preconditions"]["action"]
        # PRE-LAUNCH AUDIT F1: these now gate on the STICKY validation-ready signal
        # (delivery_phase_reached) rather than kickoff_finalized — they were polled all
        # through implementation otherwise (nothing built). Validation-ready subsumes
        # kickoff-finalized, so the #24 kickoff block is preserved.
        for tool in ("deliverability_check", "run_start", "run_validation"):
            self.assertEqual(action.get(tool), "delivery_phase_reached",
                             f"orchestrator must gate {tool} on delivery_phase_reached")

    def test_debugger_has_kickoff_bootstrap_gate(self):
        pols = self.profiles["debugger"].get("workflow_policies") or []
        kinds = [p.get("kind") for p in pols if isinstance(p, dict)]
        self.assertIn("kickoff_bootstrap_gate", kinds,
                      "debugger must carry KickoffBootstrapGate (wakeup suppression)")

    def test_debugger_gates_bug_tools(self):
        # STALE-TEST drift: bug_triage was originally gated too, but FIX #2 (see the debugger
        # stage_tool_preconditions comment in agents_config.yaml) DELIBERATELY removed the gate
        # from bug_triage — triage runs on an ALREADY-FILED real defect, and gating it on
        # validation_phase_reached self-wedged the debugger (it woke on a bug it could never act
        # on). bug_create stays gated (kickoff spurious-bug suppression); bug_triage must NOT be.
        action = (self.profiles["debugger"].get("stage_tool_preconditions") or {}).get("action", {})
        self.assertEqual(action.get("bug_create"), "validation_phase_reached",
                         "debugger must gate bug_create on validation_phase_reached")
        self.assertIsNone(action.get("bug_triage"),
                          "bug_triage must NOT be phase-gated (FIX #2: it triages a filed defect)")


class DriverNonInterference(unittest.TestCase):
    """Regression (subtlety 1 / Q5): the deterministic post-kickoff drivers must NOT
    be reachable by the new gates — they run on a separate run()-loop path and never
    call deliverability_check/run_start/run_validation/bug_create. Proven by: the
    driver source does not reference the new precondition ids, and the gates are pure
    functions of hub/flag state with no driver side effects."""

    def test_drivers_do_not_reference_new_preconditions(self):
        from multi_agent.runtime import framework_validation
        src = inspect.getsource(framework_validation)
        self.assertNotIn("kickoff_finalized", src)
        self.assertNotIn("validation_phase_reached", src)

    def test_gate_ids_not_route_or_validation_tools(self):
        # sanity: the gated tools are the LLM coordination tools, NOT the framework
        # drivers' own helpers — so gating them cannot stop maybe_run/_maybe_deliver.
        gated = {"deliverability_check", "run_start", "run_validation",
                 "bug_create", "bug_triage"}
        driver_calls = {"_maybe_run_framework_validation", "_maybe_framework_deliver",
                        "create_release", "all_business_endpoints_implemented"}
        self.assertEqual(gated & driver_calls, set())


if __name__ == "__main__":
    unittest.main()
