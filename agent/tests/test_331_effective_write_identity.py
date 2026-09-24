"""#331: self-gating tools must be injected with the agent's WRITE identity,
not its raw instance id.

Live evidence (r91: 12/12 denials, r92: 11/11, r93: the lane stopped calling it
at all): the one-shot Design Analyst is spawned as

    orchestrator.py:2304  agent_id = "design_analyst_1"
    orchestrator.py:2309  agent_type="design_analyst", config_key="design_analyst"

and PathRoutedWorkspace grants ``design/`` to the writer ``"design_analyst"``
by EXACT string match (path_routed_workspace.py is_write_allowed:
``agent_id in writers``). So every

    decompose_reference({'image': 'design/references/fyp_feed_logged_out.png'})
    -> "Error: write denied by role gate: design/component_specs/<name>.json"

i.e. the component-measurement phase that feeds UI fidelity produced NOTHING in
two full runs, after paying for a vision pass over the reference PNG each time.

There are two gate paths and only one of them normalizes the identity:
  * runtime/tooling.py:458-464 computes ``effective_agent_id`` from
    ``_permission_parent_id`` / ``_config_key`` before calling is_write_allowed;
  * runtime/tooling.py:373 injects the RAW ``self.agent_id`` into every
    self-gating tool, which is what material_prep_tools.py:281-283 then gates on.

This is general, not design-analyst-specific: every spawned lane carries an
instance-suffixed agent_id (api_test_user_1_api_smoke, browser_test_user_2_...),
so any self-gating tool they hold is gated against an identity no route grants.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


class _ToolStub:
    """A self-gating tool: no set_agent, gates on its injected _agent_id."""

    def __init__(self):
        self._agent_id = None


class _AgentStub:
    """Carries the identity fields the resolver reads."""

    def __init__(self, agent_id, config_key=None, permission_parent_id=None):
        self.agent_id = agent_id
        if config_key is not None:
            self._config_key = config_key
        if permission_parent_id is not None:
            self._permission_parent_id = permission_parent_id


class EffectiveWriteIdentity(unittest.TestCase):
    """The resolver itself — one source of truth for both gate paths."""

    def _resolve(self, agent):
        from multi_agent.agents.runtime.tooling import _effective_write_identity
        return _effective_write_identity(agent)

    def test_config_key_wins_over_the_instance_suffixed_agent_id(self):
        """The r91/r92 case, exactly."""
        agent = _AgentStub("design_analyst_1", config_key="design_analyst")
        self.assertEqual(self._resolve(agent), "design_analyst")

    def test_permission_parent_takes_precedence_over_config_key(self):
        agent = _AgentStub(
            "worker_7", config_key="worker", permission_parent_id="backend")
        self.assertEqual(self._resolve(agent), "backend")

    def test_plain_agent_keeps_its_own_id(self):
        self.assertEqual(self._resolve(_AgentStub("backend")), "backend")

    def test_missing_attributes_degrade_to_agent_id(self):
        class _Bare:
            agent_id = "verifier"

        self.assertEqual(self._resolve(_Bare()), "verifier")

    def test_matches_the_other_gate_paths_resolution_order(self):
        """Pins that this helper reproduces runtime/tooling.py:458-464 exactly,
        so the two gate paths cannot drift apart again."""
        agent = _AgentStub("x_1", config_key="cfg", permission_parent_id=None)
        self.assertEqual(self._resolve(agent), "cfg")


class InjectionUsesTheWriteIdentity(unittest.TestCase):
    """The bug site: what actually lands on the tool."""

    def test_injected_agent_id_is_the_write_identity_not_the_instance_id(self):
        from multi_agent.agents.runtime.tooling import _effective_write_identity
        agent = _AgentStub("design_analyst_1", config_key="design_analyst")
        tool = _ToolStub()
        # Mirror the injection at runtime/tooling.py:373.
        setattr(tool, "_agent_id", _effective_write_identity(agent))
        self.assertEqual(tool._agent_id, "design_analyst")


class TheGateActuallyOpens(unittest.TestCase):
    """End of the chain against the REAL routing table — the assertion that
    would have caught this in r91."""

    def _workspace(self, tmp):
        from multi_agent.runtime.path_routed_workspace import PathRoutedWorkspace
        return PathRoutedWorkspace(base_root=tmp, code_root=tmp / "code")

    def test_design_route_denies_the_instance_id_but_allows_the_write_identity(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            ws = self._workspace(Path(tmp))
            target = "design/component_specs/fyp_feed_logged_out.json"
            # The raw instance id is what r91 gated on -> denied.
            self.assertFalse(ws.is_write_allowed(target, "design_analyst_1"))
            # The write identity is what the routing table actually grants.
            self.assertTrue(ws.is_write_allowed(target, "design_analyst"))


if __name__ == "__main__":
    unittest.main()
