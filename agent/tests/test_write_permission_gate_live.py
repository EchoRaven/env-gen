"""Reviewer re-audit (2026-05-29): the write-permission gate
(``AgentTooling._enforce_write_permissions``) was landed-but-dead.

Mechanism that the reviewer surfaced:
  * ``_enforce_write_permissions`` reads ``self.workspace`` and calls
    ``ws.is_write_allowed(...)``, but ``self.workspace`` is the bare
    ``WorkspaceManager`` (only owns ``base_dir`` + ``_init_directories``).
    WorkspaceManager has NO ``is_write_allowed`` method.
  * The ``hasattr(ws, "is_write_allowed")`` guard therefore returned
    False every call → the gate silently no-op'd → role-based write
    scope was unenforced. Backend could write ``design/``, "read-only"
    routes like ``screenshots/`` / ``shared/`` were writable, etc.
  * The actual permission decision lives on ``PathRoutedWorkspace``
    (built inside ``_register_env_gen_tools`` as a LOCAL VARIABLE that
    feeds tool assembly). It was never attached back to the agent, so
    no caller could reach it.

Fix: pin the routed workspace as ``self._routed_workspace`` and have
``_enforce_write_permissions`` consult that first. Fallback to
``self.workspace`` is preserved so early-init / stub agents continue
to degrade to "no gate" rather than raising.

These tests cover:
  * The dead-gate regression — a stub that mirrors the historic
    "only self.workspace" wiring must still return None (degraded
    fallback by design).
  * The LIVE gate — a stub with the new ``_routed_workspace``
    attached must DENY out-of-scope writes and ALLOW in-scope ones,
    matching ``ROUTING_TABLE``'s ``allowed_writers``.
  * Tool-shape coverage — write / edit / delete_file / apply_patch
    (whose targets live inside the patch text) / copy_reference_image
    all reach the gate.
  * Wiring closure — ``_register_env_gen_tools`` actually attaches
    ``_routed_workspace`` after a worktree is registered. The
    "integration test" the reviewer specifically asked for —
    previous tests only unit-tested ``PathRoutedWorkspace`` in
    isolation, never confirmed the agent path reaches it.
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

from multi_agent.runtime.path_routed_workspace import PathRoutedWorkspace  # noqa: E402
from multi_agent.workspace_manager import WorkspaceManager  # noqa: E402
from multi_agent.agents.runtime.tooling import AgentTooling  # noqa: E402


class _StubAgent(AgentTooling):
    """Minimal AgentTooling subclass exposing exactly what
    ``_enforce_write_permissions`` reads — nothing more.

    The historic bug was that ``self.workspace`` (on every real
    agent) returns a ``WorkspaceManager``. This stub reproduces
    that exact wiring so the regression assertion is faithful."""

    def __init__(self, agent_id: str, workspace, routed_workspace=None):
        self.agent_id = agent_id
        self.workspace = workspace
        if routed_workspace is not None:
            self._routed_workspace = routed_workspace
        self._logger = MagicMock()


class HistoricBugReproduces(unittest.TestCase):
    """Pin the LANDED-BUT-DEAD failure mode. Without the routed
    workspace attached, the gate degrades to None — same as it did
    historically. We KEEP this behaviour (early-init / stub) but
    document it loudly so a future reviewer doesn't confuse the
    fallback with a live deny."""

    def test_workspace_manager_has_no_is_write_allowed(self):
        """The bug at the root: WorkspaceManager doesn't implement the
        method the gate looked for. ``hasattr`` returns False, gate
        falls through. Pin this so a future commit that secretly adds
        ``is_write_allowed`` to WorkspaceManager (and silently
        re-enables the dead path) fails the test."""
        with tempfile.TemporaryDirectory() as tmp:
            wm = WorkspaceManager(Path(tmp))
            self.assertFalse(
                hasattr(wm, "is_write_allowed"),
                "WorkspaceManager grew an is_write_allowed method. "
                "Routing/permission ownership is supposed to live on "
                "PathRoutedWorkspace per ROUTING_TABLE. Either remove "
                "the new method or update this test plus the gate "
                "docstring.",
            )

    def test_gate_silently_no_ops_when_only_workspace_manager_is_wired(self):
        """The historic path: agent had only ``self.workspace=
        WorkspaceManager``, no ``_routed_workspace``. The gate
        returned None on every call. We keep that as the degraded
        fallback (early init), but pin it so the difference between
        "gate is dead" and "gate is live" is testable."""
        with tempfile.TemporaryDirectory() as tmp:
            wm = WorkspaceManager(Path(tmp))
            agent = _StubAgent("backend", workspace=wm,
                                routed_workspace=None)
            outcome = agent._enforce_write_permissions(
                "write",
                {"file_path": "shared/foo.json"},
            )
            self.assertIsNone(
                outcome,
                "without a routed workspace the gate must degrade "
                "silently — not raise — so test bootstrap and the "
                "orchestrator's pre-hub init still work. The "
                "production fix attaches _routed_workspace so the "
                "live path replaces this fallback.",
            )


class RoutedGateDeniesOutOfScopeWrites(unittest.TestCase):
    """When ``_routed_workspace`` IS attached, the gate must deny
    writes that ROUTING_TABLE forbids. These are the writes that
    were silently allowed during the entire landed-but-dead period."""

    def _make_agent(self, tmp: Path, agent_id: str):
        base = tmp
        code = tmp / "worktrees" / agent_id
        code.mkdir(parents=True)
        routed = PathRoutedWorkspace(base_root=base, code_root=code)
        wm = WorkspaceManager(base)
        return _StubAgent(agent_id, workspace=wm, routed_workspace=routed)

    def test_database_cannot_write_design_dir(self):
        """Round 8e.1 post-merge: design/ writers are now
        ``_writers("backend", "frontend")`` — backend owns
        spec.api.json + spec.database.json + README.md and frontend
        owns spec.ui.json + reference_image_manifest (after absorbing
        the design agent's role). Other lanes — database, verifier —
        must still be denied. Pin that the deny path stays live for
        lanes that are NOT in the new writer set."""
        with tempfile.TemporaryDirectory() as tmp:
            agent = self._make_agent(Path(tmp), "database")
            outcome = agent._enforce_write_permissions(
                "write",
                {"file_path": "design/spec.api.json"},
            )
            self.assertIsNotNone(outcome,
                                  "database writing design/* must be "
                                  "denied — backend+frontend are the "
                                  "only allowed writers post-merge")
            self.assertFalse(outcome.success)
            self.assertIn("design/spec.api.json", outcome.error_message)
            self.assertIn("ROUTING_TABLE", outcome.error_message)

    def test_frontend_cannot_write_backend_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = self._make_agent(Path(tmp), "frontend")
            outcome = agent._enforce_write_permissions(
                "edit",
                {"file_path": "app/backend/routes/users.py"},
            )
            self.assertIsNotNone(outcome)
            self.assertFalse(outcome.success)

    def test_screenshots_are_read_only_for_everyone(self):
        """``screenshots/`` has ``allowed_writers=frozenset()`` in
        ROUTING_TABLE — nobody writes it. Pin that the historic
        "anyone could overwrite a reference screenshot" mode is
        now closed."""
        for agent_id in ("backend", "frontend", "database", "verifier"):
            with self.subTest(agent_id=agent_id):
                with tempfile.TemporaryDirectory() as tmp:
                    agent = self._make_agent(Path(tmp), agent_id)
                    outcome = agent._enforce_write_permissions(
                        "write",
                        {"file_path": "screenshots/login.png"},
                    )
                    self.assertIsNotNone(
                        outcome,
                        f"{agent_id} must NOT be able to write "
                        f"screenshots/ — historic landed-but-dead "
                        f"gate let everyone through",
                    )
                    self.assertFalse(outcome.success)

    def test_shared_dir_is_read_only_for_agents(self):
        """``shared/`` exists for hub-state writes that go through
        HubRegistry. Agents must not bypass the hub by writing it
        directly."""
        with tempfile.TemporaryDirectory() as tmp:
            agent = self._make_agent(Path(tmp), "backend")
            outcome = agent._enforce_write_permissions(
                "write",
                {"file_path": "shared/foo.json"},
            )
            self.assertIsNotNone(outcome)
            self.assertFalse(outcome.success)


class RoutedGateAllowsInScopeWrites(unittest.TestCase):
    """The mirror image — the gate must NOT block legitimate writes,
    otherwise it becomes a different kind of broken (lane stuck on
    its own files). Pin that ROUTING_TABLE's allow-list is honoured."""

    def _make_agent(self, tmp: Path, agent_id: str):
        base = tmp
        code = tmp / "worktrees" / agent_id
        code.mkdir(parents=True)
        routed = PathRoutedWorkspace(base_root=base, code_root=code)
        wm = WorkspaceManager(base)
        return _StubAgent(agent_id, workspace=wm, routed_workspace=routed)

    def test_backend_can_write_its_own_app_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = self._make_agent(Path(tmp), "backend")
            outcome = agent._enforce_write_permissions(
                "write",
                {"file_path": "app/backend/routes/users.py"},
            )
            self.assertIsNone(outcome,
                               "backend writing its own app/backend "
                               "path must pass the gate cleanly")

    def test_frontend_can_write_its_own_app_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = self._make_agent(Path(tmp), "frontend")
            outcome = agent._enforce_write_permissions(
                "write",
                {"file_path": "app/frontend/src/App.tsx"},
            )
            self.assertIsNone(outcome)

    def test_backend_can_write_design_dir(self):
        """Round 8e.1 post-merge: design/ is co-owned by backend
        (spec.api.json + spec.database.json + README.md) and frontend
        (spec.ui.json + reference_image_manifest). The standalone
        ``design`` agent was deleted in the merge — its role was
        absorbed by frontend. Pin that backend can write its
        spec.api.json without tripping the gate."""
        with tempfile.TemporaryDirectory() as tmp:
            agent = self._make_agent(Path(tmp), "backend")
            outcome = agent._enforce_write_permissions(
                "write",
                {"file_path": "design/spec.api.json"},
            )
            self.assertIsNone(outcome)

    def test_frontend_can_write_design_dir(self):
        """Mirror image of backend: frontend writes spec.ui.json into
        design/ after absorbing the design agent's role."""
        with tempfile.TemporaryDirectory() as tmp:
            agent = self._make_agent(Path(tmp), "frontend")
            outcome = agent._enforce_write_permissions(
                "write",
                {"file_path": "design/spec.ui.json"},
            )
            self.assertIsNone(outcome)

    def test_memory_is_ungated(self):
        """``.memory/`` has ``allowed_writers=None`` (ungated) so
        every agent writes its own knowledge file there."""
        with tempfile.TemporaryDirectory() as tmp:
            agent = self._make_agent(Path(tmp), "frontend")
            outcome = agent._enforce_write_permissions(
                "write",
                {"file_path": ".memory/frontend.knowledge.jsonl"},
            )
            self.assertIsNone(outcome)


class GateCoversAllWriteToolShapes(unittest.TestCase):
    """The gate intercepts a fixed enumerated set of tool names. Pin
    each shape so a future tool-name rename (e.g. ``apply_patch`` ->
    ``apply_diff``) doesn't silently disarm the gate for that tool."""

    def _make_agent(self, tmp: Path, agent_id: str = "backend"):
        base = tmp
        code = tmp / "worktrees" / agent_id
        code.mkdir(parents=True)
        routed = PathRoutedWorkspace(base_root=base, code_root=code)
        return _StubAgent(agent_id,
                          workspace=WorkspaceManager(base),
                          routed_workspace=routed)

    # Tool-shape coverage uses ``shared/`` as the gated target because
    # it's read-only to ALL agents (``allowed_writers=frozenset()``),
    # so every tool shape MUST deny regardless of who's calling. We
    # used to use ``design/`` here, but Round 8e.1 merged the design
    # agent into frontend and opened design/ writes to both backend
    # and frontend — making the default ``agent_id="backend"`` stub
    # an ALLOWED writer there and silently turning these tool-shape
    # tests into pass-by-accident. ``shared/`` keeps the gate-must-fire
    # invariant agnostic to future writer-set changes.

    def test_write_tool_path_is_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = self._make_agent(Path(tmp))
            outcome = agent._enforce_write_permissions(
                "write", {"file_path": "shared/x.json"},
            )
            self.assertIsNotNone(outcome)

    def test_edit_tool_path_is_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = self._make_agent(Path(tmp))
            outcome = agent._enforce_write_permissions(
                "edit", {"file_path": "shared/x.json"},
            )
            self.assertIsNotNone(outcome)

    def test_delete_file_path_is_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = self._make_agent(Path(tmp))
            outcome = agent._enforce_write_permissions(
                "delete_file", {"file_path": "shared/x.json"},
            )
            self.assertIsNotNone(outcome)

    def test_apply_patch_paths_inside_patch_text_are_checked(self):
        """``apply_patch`` doesn't have a single ``file_path``; the
        files live as ``*** Add File: X`` / ``*** Update File: Y``
        markers inside the patch text. The gate must parse those
        out, otherwise a patch could write anywhere as long as it
        omitted ``file_path``."""
        with tempfile.TemporaryDirectory() as tmp:
            agent = self._make_agent(Path(tmp))
            patch = (
                "*** Begin Patch\n"
                "*** Update File: shared/secret.json\n"
                "@@\n"
                "-old\n"
                "+new\n"
                "*** End Patch\n"
            )
            outcome = agent._enforce_write_permissions(
                "apply_patch", {"patch": patch},
            )
            self.assertIsNotNone(outcome,
                                  "apply_patch must parse Add/Update "
                                  "File markers and gate them — "
                                  "otherwise the patch tool is a "
                                  "write-permission bypass")

    def test_copy_reference_image_destination_is_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = self._make_agent(Path(tmp))
            outcome = agent._enforce_write_permissions(
                "copy_reference_image",
                {"destination": "shared/cover.png"},
            )
            self.assertIsNotNone(outcome)

    def test_non_write_tool_is_skipped(self):
        """Reading tools (``read``, ``grep``, ``git_status``, etc.)
        must not be gated — they have no write targets."""
        with tempfile.TemporaryDirectory() as tmp:
            agent = self._make_agent(Path(tmp))
            outcome = agent._enforce_write_permissions(
                "read", {"file_path": "shared/secret.json"},
            )
            self.assertIsNone(
                outcome,
                "the gate must only intercept the write/edit/"
                "delete_file/apply_patch/copy_reference_image set. "
                "A blanket-intercept would break read paths.",
            )


class WiringIntegration(unittest.TestCase):
    """The "integration test" the reviewer specifically asked for —
    previous coverage only unit-tested ``PathRoutedWorkspace`` in
    isolation. This test confirms ``_register_env_gen_tools``
    actually pins ``_routed_workspace`` on the agent so the gate's
    read can find it. If the wiring is ever lost (e.g. someone
    inlines the construction and forgets the assignment), the gate
    silently goes back to dead — this test catches that."""

    def test_register_env_gen_tools_attaches_routed_workspace(self):
        """A stub that mimics the AgentTooling subclass contract
        (workspace + worktree + the few attributes
        ``_register_env_gen_tools`` reads) must end up with
        ``_routed_workspace`` populated after the registration call.
        Pinning the side-effect, not the tool list itself —
        which is exercised elsewhere."""
        from multi_agent.tools import Workspace

        class _WiringStub(AgentTooling):
            def __init__(self, agent_id, workspace, worktree):
                self.agent_id = agent_id
                self.workspace = workspace
                self._worktree_dir = worktree
                self._include_vision = False
                self.allowed_tool_categories = set()
                self.llm = MagicMock()
                self._tool_instances = {}
                self._allow_tools = []
                self._deny_tools = []
                self._tool_bundle_ids = []
                self._config_key = agent_id
                self._tool_profile_agent_type = agent_id
                self._logger = MagicMock()
                # ``_tools`` is the registry tool registration writes
                # into; we don't care about its contents, just that
                # the registration call doesn't blow up.
                self._tools = MagicMock()
                self._tools.to_openai_tools = lambda: []

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            code = base / "worktrees" / "backend"
            code.mkdir(parents=True)
            wm = WorkspaceManager(base)
            stub = _WiringStub("backend", wm, code)
            # Pre-registration: no routed workspace.
            self.assertFalse(
                hasattr(stub, "_routed_workspace")
                and stub._routed_workspace is not None,
                "stub should start without _routed_workspace",
            )
            stub._register_env_gen_tools()
            # Post-registration: _routed_workspace must be a
            # PathRoutedWorkspace pointed at base + code.
            self.assertTrue(hasattr(stub, "_routed_workspace"))
            self.assertIsInstance(
                stub._routed_workspace, PathRoutedWorkspace,
                "_register_env_gen_tools must pin the routed "
                "workspace on the agent so the gate can reach it. "
                "If this fails, the gate silently degrades to None "
                "and role-based write scope is unenforced again.",
            )
            self.assertEqual(
                stub._routed_workspace.code_root,
                code.resolve(),
            )
            self.assertEqual(
                stub._routed_workspace.base_root,
                base.resolve(),
            )

    def test_register_without_worktree_attaches_plain_workspace(self):
        """No worktree (early init, stub tests): ``_routed_workspace``
        gets a plain ``Workspace`` — which exposes
        ``is_write_allowed`` returning True for everything. So the
        gate still no-ops there, by design (no role gate before the
        worktree exists)."""
        from multi_agent.tools import Workspace

        class _WiringStub(AgentTooling):
            def __init__(self, agent_id, workspace):
                self.agent_id = agent_id
                self.workspace = workspace
                self._worktree_dir = None
                self._include_vision = False
                self.allowed_tool_categories = set()
                self.llm = MagicMock()
                self._tool_instances = {}
                self._allow_tools = []
                self._deny_tools = []
                self._tool_bundle_ids = []
                self._config_key = agent_id
                self._tool_profile_agent_type = agent_id
                self._logger = MagicMock()
                self._tools = MagicMock()
                self._tools.to_openai_tools = lambda: []

        with tempfile.TemporaryDirectory() as tmp:
            wm = WorkspaceManager(Path(tmp))
            stub = _WiringStub("backend", wm)
            stub._register_env_gen_tools()
            self.assertTrue(hasattr(stub, "_routed_workspace"))
            self.assertIsInstance(stub._routed_workspace, Workspace)


if __name__ == "__main__":
    unittest.main()
