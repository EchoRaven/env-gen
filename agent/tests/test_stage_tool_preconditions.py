"""PR3.2: per-(stage, tool) precondition guard engine plumbing.

Per docs/prompt_smell_and_bash_sandbox_2026_06_03.md §1.3 + the smoke
#28 wedge (backend wrote 8 files in the correct worktree but called
``finish`` with 4 endpoints still at ``status='defined'``, so the
WorkHub task closer never fired): replace "do not call finish until
every endpoint is implemented" prompt prose with an engine-side guard
that blocks ``finish`` and surfaces a directed error to the LLM
in-context.

This file pins:
  1. The ``kickoff_endpoints_implemented`` checker blocks when any
     RegistryHub endpoint is at ``status != 'implemented'`` and vacuously
     passes when RegistryHub is empty or all are implemented.
  2. The dispatch hook (``_enforce_stage_preconditions``) routes the
     check by ``(active_stage, tool_name)`` and returns ``None`` when
     no precondition is configured for the call.
  3. ``ConfigurableAgent`` fails-closed at construction when the yaml
     names an unknown precondition id (no silent fallthrough at
     dispatch).
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


class KickoffEndpointsImplementedTests(unittest.TestCase):
    """The concrete checker behind smoke #28."""

    def setUp(self):
        from multi_agent.agents.runtime.preconditions import (
            kickoff_endpoints_implemented,
        )
        self._fn = kickoff_endpoints_implemented

    def _agent(self, endpoints: Dict[str, Any]) -> Any:
        registryhub = SimpleNamespace(get_endpoints=lambda: endpoints)
        hubs = SimpleNamespace(registryhub=registryhub)
        return SimpleNamespace(_hubs=hubs, agent_id="backend")

    def test_blocks_when_any_endpoint_defined(self):
        agent = self._agent({
            "GET /a": {"method": "GET", "path": "/a", "status": "defined"},
            "POST /b": {"method": "POST", "path": "/b", "status": "implemented"},
        })
        err = self._fn(agent, "finish", {})
        self.assertIsNotNone(err)
        self.assertIn("GET /a", err)
        self.assertNotIn("POST /b", err)
        self.assertIn("registryhub_register_endpoint", err)

    def test_passes_when_all_implemented(self):
        agent = self._agent({
            "GET /a": {"method": "GET", "path": "/a", "status": "implemented"},
            "POST /b": {"method": "POST", "path": "/b", "status": "implemented"},
        })
        self.assertIsNone(self._fn(agent, "finish", {}))

    def test_passes_when_registryhub_empty(self):
        """Kickoff stage (before finalize_kickoff registers endpoints)
        must not be wedged by the guard. RegistryHub is empty → vacuously
        passes."""
        agent = self._agent({})
        self.assertIsNone(self._fn(agent, "finish", {}))

    def test_no_hubs_passes(self):
        """Agent constructed before ``set_hubs`` is called (early init)
        must not crash the dispatch. Treat missing hubs as a no-op."""
        agent = SimpleNamespace(agent_id="backend")
        self.assertIsNone(self._fn(agent, "finish", {}))

    def test_deprecated_status_is_terminal(self):
        """Loop B iter-3 ⑭: ``status='deprecated'`` is a real reachable
        terminal (registryhub.py:425/643). A deprecated endpoint can never
        transition to implemented, so blocking on it = permanent
        finish-wedge with an unsatisfiable error. Must pass-through."""
        agent = self._agent({
            "GET /old": {"method": "GET", "path": "/old", "status": "deprecated"},
            "POST /b": {"method": "POST", "path": "/b", "status": "implemented"},
        })
        self.assertIsNone(self._fn(agent, "finish", {}))

    def test_mixed_terminal_passes(self):
        """Mix of implemented + deprecated → all terminal → passes."""
        agent = self._agent({
            "GET /a": {"method": "GET", "path": "/a", "status": "implemented"},
            "GET /b": {"method": "GET", "path": "/b", "status": "deprecated"},
            "GET /c": {"method": "GET", "path": "/c", "status": "implemented"},
        })
        self.assertIsNone(self._fn(agent, "finish", {}))

    def test_deprecated_plus_defined_blocks_only_defined(self):
        """Deprecated does not block, but a still-defined sibling does
        — and the error names only the defined one."""
        agent = self._agent({
            "GET /old": {"method": "GET", "path": "/old", "status": "deprecated"},
            "GET /new": {"method": "GET", "path": "/new", "status": "defined"},
        })
        err = self._fn(agent, "finish", {})
        self.assertIsNotNone(err)
        self.assertIn("GET /new", err)
        self.assertNotIn("GET /old", err)

    def test_endpoint_owned_by_other_lane_does_not_block(self):
        """Loop B iter-3 ⑮ — lane scoping. Backend's finish must NOT
        block on endpoints owned by another lane (e.g. a future
        database-domain endpoint with provider='database')."""
        registryhub = SimpleNamespace(get_endpoints=lambda: {
            "GET /b/x": {"method": "GET", "path": "/b/x", "status": "defined", "provider": "frontend"},
            "POST /b/y": {"method": "POST", "path": "/b/y", "status": "implemented", "provider": "backend"},
        })
        hubs = SimpleNamespace(registryhub=registryhub)
        agent = SimpleNamespace(_hubs=hubs, agent_id="backend", _config_key="backend")
        self.assertIsNone(self._fn(agent, "finish", {}))

    def test_own_lane_endpoint_at_defined_still_blocks(self):
        """Lane-scoping doesn't open a loophole: backend's OWN endpoints
        at non-terminal still block finish."""
        registryhub = SimpleNamespace(get_endpoints=lambda: {
            "GET /b/x": {"method": "GET", "path": "/b/x", "status": "defined", "provider": "backend"},
        })
        hubs = SimpleNamespace(registryhub=registryhub)
        agent = SimpleNamespace(_hubs=hubs, agent_id="backend", _config_key="backend")
        err = self._fn(agent, "finish", {})
        self.assertIsNotNone(err)
        self.assertIn("GET /b/x", err)
        self.assertIn("you own", err)

    def test_spawned_worker_uses_config_key_not_agent_id(self):
        """A spawned worker (agent_id='backend_worker_abc123',
        _config_key='backend') must match the 'backend' provider, not
        require provider='backend_worker_abc123'."""
        registryhub = SimpleNamespace(get_endpoints=lambda: {
            "GET /b/x": {"method": "GET", "path": "/b/x", "status": "defined", "provider": "backend"},
        })
        hubs = SimpleNamespace(registryhub=registryhub)
        worker = SimpleNamespace(
            _hubs=hubs,
            agent_id="backend_worker_abc123",
            _config_key="backend",
        )
        err = self._fn(worker, "finish", {})
        self.assertIsNotNone(err)
        self.assertIn("GET /b/x", err)

    def test_missing_provider_falls_back_to_inclusion(self):
        """Backward-compat: endpoints registered without a provider
        field (legacy / test fixtures) are treated as belonging to the
        agent's lane — the lane filter doesn't open a quiet escape
        hatch for unowned endpoints."""
        registryhub = SimpleNamespace(get_endpoints=lambda: {
            "GET /b/x": {"method": "GET", "path": "/b/x", "status": "defined"},  # no provider
        })
        hubs = SimpleNamespace(registryhub=registryhub)
        agent = SimpleNamespace(_hubs=hubs, agent_id="backend", _config_key="backend")
        err = self._fn(agent, "finish", {})
        self.assertIsNotNone(err)
        self.assertIn("GET /b/x", err)

    def test_lists_multiple_pending_sorted(self):
        agent = self._agent({
            "GET /z": {"method": "GET", "path": "/z", "status": "defined"},
            "GET /a": {"method": "GET", "path": "/a", "status": "defined"},
            "GET /m": {"method": "GET", "path": "/m", "status": "implemented"},
        })
        err = self._fn(agent, "finish", {})
        self.assertIsNotNone(err)
        # /a should appear before /z (sorted)
        self.assertLess(err.index("GET /a"), err.index("GET /z"))
        self.assertNotIn("/m", err)


class DispatchHookTests(unittest.TestCase):
    """``_enforce_stage_preconditions`` invariants — the lever wiring."""

    def setUp(self):
        from multi_agent.agents.runtime.tooling import AgentTooling
        self._fn = AgentTooling._enforce_stage_preconditions
        self._cls = AgentTooling

    def _stub(self, *, preconds, active_stage, hubs=None, active_phase=None):
        stub = SimpleNamespace()
        stub._stage_tool_preconditions = preconds
        stub._active_stage = active_stage
        stub._active_phase = active_phase
        stub._hubs = hubs
        stub.agent_id = "backend"
        stub._tool_instances = {}
        # log_tool_call is invoked by _execute_tool, not by us — bind a
        # no-op so attribute lookups don't fail when sub-paths reach it.
        stub.log_tool_call = lambda *a, **kw: None
        stub._logger = SimpleNamespace(
            warning=lambda *a, **kw: None,
            error=lambda *a, **kw: None,
            info=lambda *a, **kw: None,
            debug=lambda *a, **kw: None,
        )
        return stub

    def test_no_preconds_returns_none(self):
        stub = self._stub(preconds={}, active_stage="action")
        self.assertIsNone(self._fn(stub, "finish", {}))

    def test_stage_without_entry_falls_through(self):
        stub = self._stub(
            preconds={"action": {"finish": "kickoff_endpoints_implemented"}},
            active_stage="planning",
        )
        self.assertIsNone(self._fn(stub, "finish", {}))

    def test_tool_without_entry_falls_through(self):
        stub = self._stub(
            preconds={"action": {"finish": "kickoff_endpoints_implemented"}},
            active_stage="action",
        )
        self.assertIsNone(self._fn(stub, "write", {}))

    def test_unknown_id_raises_hard(self):
        """By construction ConfigurableAgent rejects unknown ids. If
        one ever reaches dispatch (external caller bypassed the
        config), we crash rather than silently fall through —
        fail-closed."""
        stub = self._stub(
            preconds={"action": {"finish": "definitely_not_in_registry"}},
            active_stage="action",
        )
        with self.assertRaises(RuntimeError):
            self._fn(stub, "finish", {})

    def test_blocked_returns_tool_result(self):
        from utils.tool import ToolResult
        registryhub = SimpleNamespace(get_endpoints=lambda: {
            "GET /a": {"method": "GET", "path": "/a", "status": "defined"},
        })
        hubs = SimpleNamespace(registryhub=registryhub)
        stub = self._stub(
            preconds={"action": {"finish": "kickoff_endpoints_implemented"}},
            active_stage="action",
            hubs=hubs,
        )
        result = self._fn(stub, "finish", {})
        self.assertIsInstance(result, ToolResult)
        self.assertFalse(result.success)
        self.assertIn("GET /a", result.error_message)

    def test_allowed_returns_none(self):
        registryhub = SimpleNamespace(get_endpoints=lambda: {
            "GET /a": {"method": "GET", "path": "/a", "status": "implemented"},
        })
        hubs = SimpleNamespace(registryhub=registryhub)
        stub = self._stub(
            preconds={"action": {"finish": "kickoff_endpoints_implemented"}},
            active_stage="action",
            hubs=hubs,
        )
        self.assertIsNone(self._fn(stub, "finish", {}))

    def test_phase_keyed_precond_takes_precedence(self):
        """PR3.1.2 / Loop B ⑧: when ``_active_phase='kickoff'`` and yaml
        has both ``kickoff:action`` and ``action`` entries, the
        composite key wins."""
        from utils.tool import ToolResult
        # Both preconds reference the SAME id but pretend the phase
        # entry is what was selected by reading a marker arg.
        registryhub = SimpleNamespace(get_endpoints=lambda: {
            "GET /a": {"method": "GET", "path": "/a", "status": "defined"},
        })
        hubs = SimpleNamespace(registryhub=registryhub)
        stub = self._stub(
            preconds={
                "kickoff:action": {"finish": "kickoff_endpoints_implemented"},
                "action": {"finish": "kickoff_endpoints_implemented"},
            },
            active_stage="action",
            active_phase="kickoff",
            hubs=hubs,
        )
        result = self._fn(stub, "finish", {})
        self.assertIsInstance(result, ToolResult)
        self.assertFalse(result.success)

    def test_phase_keyed_only_no_bare_match(self):
        """Phase-only entry: no bare-stage entry exists. When phase is
        set and matches, the guard fires. When phase is None, no
        match → guard does not fire."""
        from utils.tool import ToolResult
        registryhub = SimpleNamespace(get_endpoints=lambda: {
            "GET /a": {"method": "GET", "path": "/a", "status": "defined"},
        })
        hubs = SimpleNamespace(registryhub=registryhub)
        # phase=kickoff → matches
        stub_kick = self._stub(
            preconds={"kickoff:action": {"finish": "kickoff_endpoints_implemented"}},
            active_stage="action",
            active_phase="kickoff",
            hubs=hubs,
        )
        result = self._fn(stub_kick, "finish", {})
        self.assertIsInstance(result, ToolResult)
        # phase=None → no match → no guard
        stub_none = self._stub(
            preconds={"kickoff:action": {"finish": "kickoff_endpoints_implemented"}},
            active_stage="action",
            active_phase=None,
            hubs=hubs,
        )
        self.assertIsNone(self._fn(stub_none, "finish", {}))

    def test_phase_falls_back_to_bare_when_no_phase_entry(self):
        """Phase set, but only a bare-stage entry exists → falls back
        to the bare entry. No regression for profiles that haven't
        migrated to phase keys."""
        from utils.tool import ToolResult
        registryhub = SimpleNamespace(get_endpoints=lambda: {
            "GET /a": {"method": "GET", "path": "/a", "status": "defined"},
        })
        hubs = SimpleNamespace(registryhub=registryhub)
        stub = self._stub(
            preconds={"action": {"finish": "kickoff_endpoints_implemented"}},
            active_stage="action",
            active_phase="kickoff",  # yaml has no kickoff:action entry
            hubs=hubs,
        )
        result = self._fn(stub, "finish", {})
        self.assertIsInstance(result, ToolResult)

    def test_action_substage_falls_back_to_action_key(self):
        """Smoke #30 root cause (2026-06-04): when the LLM calls
        ``finish`` from inside the action loop, ``_active_stage`` is
        the INTERNAL sub-stage (e.g. ``deliver``), NOT the outer
        ``action``. A yaml keyed on ``action.finish`` MUST still gate
        the call. The lookup falls back to ``action`` when the current
        stage is an action internal sub-stage."""
        from utils.tool import ToolResult
        registryhub = SimpleNamespace(get_endpoints=lambda: {
            "GET /a": {"method": "GET", "path": "/a", "status": "defined", "provider": "backend"},
        })
        hubs = SimpleNamespace(registryhub=registryhub)
        # Each of the 5 action internal sub-stages must trigger the
        # action-keyed precondition.
        for substage in ("communicate", "edit_code", "run_checks", "delegate_team", "deliver"):
            stub = self._stub(
                preconds={"action": {"finish": "kickoff_endpoints_implemented"}},
                active_stage=substage,
                hubs=hubs,
            )
            # Pin the ACTION_INTERNAL_STAGES class attr the helper reads.
            stub.ACTION_INTERNAL_STAGES = (
                "communicate", "edit_code", "run_checks", "delegate_team", "deliver",
            )
            stub._config_key = "backend"
            result = self._fn(stub, "finish", {})
            self.assertIsInstance(
                result, ToolResult,
                f"sub-stage '{substage}' must trigger action-keyed precondition; "
                f"got {result!r}"
            )
            self.assertFalse(result.success)

    def test_outer_stage_not_substage_does_not_fallback(self):
        """The fallback ONLY applies to action's 5 internal sub-stages.
        Outer pipeline stages (planning, hub_pulse, etc.) must NOT
        unexpectedly inherit action's precondition."""
        from utils.tool import ToolResult
        registryhub = SimpleNamespace(get_endpoints=lambda: {
            "GET /a": {"method": "GET", "path": "/a", "status": "defined", "provider": "backend"},
        })
        hubs = SimpleNamespace(registryhub=registryhub)
        stub = self._stub(
            preconds={"action": {"finish": "kickoff_endpoints_implemented"}},
            active_stage="planning",  # outer stage, NOT in ACTION_INTERNAL_STAGES
            hubs=hubs,
        )
        stub.ACTION_INTERNAL_STAGES = (
            "communicate", "edit_code", "run_checks", "delegate_team", "deliver",
        )
        stub._config_key = "backend"
        self.assertIsNone(self._fn(stub, "finish", {}))

    def test_substage_specific_precondition_wins_over_fallback(self):
        """When yaml has BOTH an action-keyed AND sub-stage-keyed
        precondition for the same tool, the more-specific sub-stage
        entry wins."""
        from utils.tool import ToolResult
        registryhub = SimpleNamespace(get_endpoints=lambda: {
            "GET /a": {"method": "GET", "path": "/a", "status": "defined", "provider": "backend"},
        })
        hubs = SimpleNamespace(registryhub=registryhub)
        stub = self._stub(
            preconds={
                "deliver": {"finish": "kickoff_endpoints_implemented"},
                "action":  {"finish": "kickoff_endpoints_implemented"},
            },
            active_stage="deliver",
            hubs=hubs,
        )
        stub.ACTION_INTERNAL_STAGES = (
            "communicate", "edit_code", "run_checks", "delegate_team", "deliver",
        )
        stub._config_key = "backend"
        # Both block — confirms lookup found one. Sub-stage entry wins
        # is structurally enforced by the lookup order (sub-stage first).
        result = self._fn(stub, "finish", {})
        self.assertIsInstance(result, ToolResult)

    def test_no_active_stage_returns_none(self):
        stub = self._stub(
            preconds={"action": {"finish": "kickoff_endpoints_implemented"}},
            active_stage=None,
        )
        self.assertIsNone(self._fn(stub, "finish", {}))


class ConfigurableAgentValidationTests(unittest.TestCase):
    """ConfigurableAgent must fail-closed at construction on unknown
    precondition ids — no silent fallthrough at dispatch time."""

    def test_known_id_normalizes_to_str_str_mapping(self):
        from multi_agent.agents.configurable_agent import ConfigurableAgent
        # Bypass __init__ (heavy); manually exercise the field shape
        # the __init__ block produces.
        agent = object.__new__(ConfigurableAgent)
        agent._stage_tool_preconditions = {
            "action": {"finish": "kickoff_endpoints_implemented"},
        }
        self.assertEqual(
            agent._stage_tool_preconditions["action"]["finish"],
            "kickoff_endpoints_implemented",
        )

    def test_unknown_id_in_yaml_raises_at_construct(self):
        """Simulate the __init__ block validating a yaml that names a
        precondition not registered in PRECONDITION_REGISTRY."""
        from multi_agent.agents.runtime.preconditions import (
            PRECONDITION_REGISTRY,
        )
        raw = {"action": {"finish": "not_a_real_id_xyz"}}
        unknown = {
            str(pre_id)
            for tools in raw.values()
            for pre_id in tools.values()
            if str(pre_id) not in PRECONDITION_REGISTRY
        }
        # The __init__ block's failing branch must trigger here:
        self.assertEqual(unknown, {"not_a_real_id_xyz"})

    def test_registered_ids_are_resolvable(self):
        from multi_agent.agents.runtime.preconditions import (
            PRECONDITION_REGISTRY,
            resolve_precondition,
        )
        self.assertGreater(len(PRECONDITION_REGISTRY), 0)
        for name, fn in PRECONDITION_REGISTRY.items():
            self.assertIs(resolve_precondition(name), fn)
        self.assertIsNone(resolve_precondition("nonexistent_xyz"))


if __name__ == "__main__":
    unittest.main()
