"""PROPOSAL #27 — tool surface ≠ permission ≠ need.

User-found (live run #26): the verifier (a) burned turns calling
registryhub_register_endpoint/register_table → "restricted to ['backend',...]" actor
errors, and (b) reported registryhub_register_verification_chain "missing" though
run_validation requires it → blocked → never delivered.

Root (reviewer-corrected): the chain tool IS verifier-only (verifier_contract_tools),
but it was NOT in the force-offered _VALIDATION_FLOW always-include set the way
run_validation is — so when the verifier validates with _active_phase=None (task_ready →
run_agentic_loop, no phase pin → impl:action allowlist doesn't bind), the global ranker
surfaced run_validation but never the register tool. Fix: add it to _VALIDATION_FLOW.
Plus: deny the backend/database-owned registryhub WRITE tools on the non-owner lanes
(verifier/frontend/debugger) so they stop surfacing as dead actor-error calls — WITHOUT
removing each lane's own owned tools (over-restriction has wedged kickoff before).

LOCAL-ONLY (agent/tests/ gitignored).
"""

from __future__ import annotations

import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

import yaml  # noqa: E402

CFG = LLM_DIR / "multi_agent" / "agents" / "agents_config.yaml"

# backend/database-owned registryhub WRITE tools (role-gated out of non-owner lanes)
_OWNER_WRITES = {
    "registryhub_register_endpoint", "registryhub_register_table",
    "registryhub_register_table_consumer", "registryhub_update_table_schema",
    "registryhub_deprecate_endpoint",
}


class ValidationFlowSurfacesChainTool(unittest.TestCase):
    def test_register_verification_chain_force_offered(self):
        from multi_agent.agents.base import EnvGenAgent
        self.assertIn("registryhub_register_verification_chain", EnvGenAgent._VALIDATION_FLOW,
                      "the chain register tool must be force-offered like run_validation, else "
                      "the verifier never surfaces it (phase=None → no allowlist → ranker)")
        # it sits with the other api-smoke tools the verifier always needs
        self.assertIn("run_validation", EnvGenAgent._VALIDATION_FLOW)
        self.assertIn("registryhub_record_contract_test", EnvGenAgent._VALIDATION_FLOW)


class DenyLists(unittest.TestCase):
    def setUp(self):
        with open(CFG) as f:
            self.profiles = yaml.safe_load(f)["profiles"]

    def _deny(self, lane):
        return set(self.profiles[lane].get("deny_tools") or [])

    def test_verifier_denies_owner_writes_keeps_its_own(self):
        d = self._deny("verifier")
        self.assertTrue(_OWNER_WRITES <= d, f"verifier must deny owner writes; missing {_OWNER_WRITES - d}")
        self.assertIn("registryhub_update_schema", d)
        # KEEP the verifier's own tools (over-restriction guard)
        self.assertNotIn("registryhub_register_verification_chain", d)
        self.assertNotIn("registryhub_record_contract_test", d)

    def test_frontend_denies_owner_writes_keeps_consumer_and_uipage(self):
        d = self._deny("frontend")
        self.assertTrue(_OWNER_WRITES <= d, f"frontend must deny owner writes; missing {_OWNER_WRITES - d}")
        # OVER-RESTRICTION GUARDS: these would wedge the frontend's documented flows
        self.assertNotIn("registryhub_register_consumer", d,
                         "frontend mandates early-consumption declaration")
        self.assertNotIn("registryhub_register_ui_page", d,
                         "frontend's hub_consistency_gate blocks finish on 0 owned ui_pages and names this tool")

    def test_debugger_denies_all_registryhub_writes(self):
        d = self._deny("debugger")
        for t in _OWNER_WRITES | {"registryhub_register_consumer", "registryhub_update_schema",
                                  "registryhub_register_ui_page"}:
            self.assertIn(t, d, f"debugger (read-only) must deny {t}")

    def test_backend_is_NOT_denied_its_owned_writes(self):
        # backend OWNS endpoint/table registration — must keep them
        d = self._deny("backend")
        self.assertNotIn("registryhub_register_endpoint", d)
        self.assertNotIn("registryhub_register_table", d)

    def test_orchestrator_is_NOT_denied_registry_writes(self):
        # orchestrator registers the full contract at finalize_kickoff
        d = self._deny("orchestrator")
        self.assertEqual(d & _OWNER_WRITES, set())

    def test_denied_tools_not_in_any_kickoff_allowlist(self):
        # deny is pool-level (all phases); ensure we didn't remove a kickoff tool
        for lane in ("verifier", "frontend", "debugger"):
            allow = self.profiles[lane].get("stage_tool_allowlist") or {}
            ka = set(allow.get("kickoff:action") or [])
            self.assertEqual(ka & self._deny(lane), set(),
                             f"{lane}: a denied tool is in its kickoff allowlist")


if __name__ == "__main__":
    unittest.main()
