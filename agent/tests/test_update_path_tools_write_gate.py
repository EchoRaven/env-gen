"""Phase 0.2 attempt-3 FIX A — route ``update_json_path`` and
``update_yaml_path`` through the role-write gate.

Reviewer 1 confirmed in the 2026-05-29 audit that
``AgentTooling._enforce_write_permissions``
(``multi_agent/agents/runtime/tooling.py``) only intercepts the names
``{write, delete_file, edit, apply_patch, copy_reference_image}``.
The structured-edit tools ``UpdateJsonPathTool`` / ``UpdateYamlPathTool``
were missing from that set even though both call
``_resolve_workspace_path`` (containment only) and ``_atomic_write_text``.
A verifier agent could mutate ``design/spec.api.json`` (owned by
backend+frontend per ROUTING_TABLE after the Round 8e.1
design+frontend merge) or ``shared/*.json`` (a read-only hub state
route) via ``update_json_path`` even though the same write attempted
with ``write``/``edit`` would have been denied.

These tests pin the fix: with the two tool names added to the gated
set, ``_enforce_write_permissions`` MUST deny the out-of-role writes
and allow the legitimate ones — same shape as the existing canonical
write tools. Coverage matches the three scenarios per tool that the
fix prompt enumerates:

  1. Verifier updating ``design/spec.api.json`` → denied.
  2. Any agent updating ``shared/x.json`` (read-only route) → denied.
  3. Backend updating ``app/backend/config.json`` (legit) → allowed.

The structural invariant test in ``tests/test_write_gate_invariant.py``
also turns green for these two tools once they are added to the
``GATED_TOOL_NAMES`` constant (kept in lock-step with the runtime
gate's enumerated set).
"""

from __future__ import annotations

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

from multi_agent.runtime.path_routed_workspace import PathRoutedWorkspace  # noqa: E402
from multi_agent.workspace_manager import WorkspaceManager  # noqa: E402
from multi_agent.agents.runtime.tooling import AgentTooling  # noqa: E402


class _StubAgent(AgentTooling):
    """Minimal AgentTooling subclass exposing exactly what
    ``_enforce_write_permissions`` reads. Mirrors the stub in
    ``test_write_permission_gate_live.py`` — same wiring, same gate
    surface, just exercises the two newly-gated tool names."""

    def __init__(self, agent_id: str, workspace, routed_workspace=None):
        self.agent_id = agent_id
        self.workspace = workspace
        if routed_workspace is not None:
            self._routed_workspace = routed_workspace
        self._logger = MagicMock()


def _make_agent(tmp: Path, agent_id: str) -> _StubAgent:
    base = tmp
    code = tmp / "worktrees" / agent_id
    code.mkdir(parents=True)
    routed = PathRoutedWorkspace(base_root=base, code_root=code)
    return _StubAgent(agent_id,
                      workspace=WorkspaceManager(base),
                      routed_workspace=routed)


class UpdateJsonPathRoutesThroughGate(unittest.TestCase):
    """Three scenarios per Reviewer 1's enumeration."""

    def test_update_json_path_rejects_out_of_role_write(self):
        """A verifier agent must NOT be able to update
        ``design/spec.api.json`` via ``update_json_path``. After the
        Round 8e.1 design+frontend merge, ``design/`` writers are
        backend+frontend only per ROUTING_TABLE; verifier is out of
        role. This was the bypass Reviewer 1 surfaced — pin it shut."""
        with tempfile.TemporaryDirectory() as tmp:
            agent = _make_agent(Path(tmp), "verifier")
            outcome = agent._enforce_write_permissions(
                "update_json_path",
                {"path": "design/spec.api.json",
                 "json_path": "meta.version",
                 "value": "9.9.9"},
            )
            self.assertIsNotNone(
                outcome,
                "update_json_path on design/* by verifier MUST be "
                "denied — the gate now intercepts the structured-edit "
                "tool just like write/edit",
            )
            self.assertFalse(outcome.success)
            self.assertIn("design/spec.api.json", outcome.error_message)

    def test_update_json_path_rejects_readonly_route(self):
        """``shared/`` has ``allowed_writers=frozenset()`` (read-only)
        in ROUTING_TABLE. NO agent — including admin lanes — may
        write through ``update_json_path``. Hub-state writes go via
        HubRegistry, not through workspace tools."""
        for agent_id in ("frontend", "backend", "database", "verifier"):
            with self.subTest(agent_id=agent_id):
                with tempfile.TemporaryDirectory() as tmp:
                    agent = _make_agent(Path(tmp), agent_id)
                    outcome = agent._enforce_write_permissions(
                        "update_json_path",
                        {"path": "shared/x.json",
                         "json_path": "k",
                         "value": "v"},
                    )
                    self.assertIsNotNone(
                        outcome,
                        f"{agent_id} writing shared/* via "
                        f"update_json_path must be denied — read-only "
                        f"route in ROUTING_TABLE",
                    )
                    self.assertFalse(outcome.success)

    def test_update_json_path_accepts_legit(self):
        """The mirror image: backend updating its own
        ``app/backend/config.json`` is a legitimate per-role write.
        The gate must NOT block it — otherwise the fix degrades into
        a different kind of broken (lanes stuck on their own files)."""
        with tempfile.TemporaryDirectory() as tmp:
            agent = _make_agent(Path(tmp), "backend")
            outcome = agent._enforce_write_permissions(
                "update_json_path",
                {"path": "app/backend/config.json",
                 "json_path": "version",
                 "value": "1.0.0"},
            )
            self.assertIsNone(
                outcome,
                "backend updating its own app/backend/* via "
                "update_json_path must pass the gate cleanly",
            )


class UpdateYamlPathRoutesThroughGate(unittest.TestCase):
    """Mirror of the JSON variant — ``update_yaml_path`` carries the
    same risk profile (same write helper, same containment-only
    resolution). The gate intercepts both tool names per FIX A."""

    def test_update_yaml_path_rejects_out_of_role_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = _make_agent(Path(tmp), "verifier")
            outcome = agent._enforce_write_permissions(
                "update_yaml_path",
                {"path": "design/spec.api.yaml",
                 "yaml_path": "meta.version",
                 "value": "9.9.9"},
            )
            self.assertIsNotNone(
                outcome,
                "update_yaml_path on design/* by verifier MUST be "
                "denied — same gate as update_json_path; after the "
                "Round 8e.1 design+frontend merge, design/ writers "
                "are backend+frontend only.",
            )
            self.assertFalse(outcome.success)
            self.assertIn("design/spec.api.yaml", outcome.error_message)

    def test_update_yaml_path_rejects_readonly_route(self):
        for agent_id in ("frontend", "backend", "database", "verifier"):
            with self.subTest(agent_id=agent_id):
                with tempfile.TemporaryDirectory() as tmp:
                    agent = _make_agent(Path(tmp), agent_id)
                    outcome = agent._enforce_write_permissions(
                        "update_yaml_path",
                        {"path": "shared/x.yaml",
                         "yaml_path": "k",
                         "value": "v"},
                    )
                    self.assertIsNotNone(
                        outcome,
                        f"{agent_id} writing shared/* via "
                        f"update_yaml_path must be denied — read-only "
                        f"route in ROUTING_TABLE",
                    )
                    self.assertFalse(outcome.success)

    def test_update_yaml_path_accepts_legit(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = _make_agent(Path(tmp), "backend")
            outcome = agent._enforce_write_permissions(
                "update_yaml_path",
                {"path": "app/backend/config.yaml",
                 "yaml_path": "version",
                 "value": "1.0.0"},
            )
            self.assertIsNone(
                outcome,
                "backend updating its own app/backend/* via "
                "update_yaml_path must pass the gate cleanly",
            )


if __name__ == "__main__":
    unittest.main()
