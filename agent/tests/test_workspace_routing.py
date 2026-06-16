"""Regression for the live-run screenshot bug: an agent running in a
per-agent worktree must still see project-root shared assets
(screenshots/, design/, references/) through ``workspace.resolve()``.

Background:
* PR 1 killed every bypass ``Workspace(output_dir)`` constructor
* PR 2 (this) converted ``workspace.root / "screenshots"`` style
  concatenations to ``workspace.resolve("screenshots")`` so the
  routing table decides where the path lives.

Before PR 2, ``view_image("screenshots/login.png")`` resolved against
the worktree (always empty for shared assets) and silently fell
back to the bundled screenshot library, confusing the agent. After
PR 2 it routes to the base root and finds the actual file."""

from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from workspace import Workspace  # noqa: E402
from multi_agent.runtime.path_routed_workspace import PathRoutedWorkspace  # noqa: E402


class NamedAccessorsExposeCorrectRoots(unittest.TestCase):
    """Plain ``Workspace`` collapses code_root / base_root to ``root``;
    ``PathRoutedWorkspace`` diverges them. Callers can rely on the
    accessor names to mean the same thing on both types."""

    def test_plain_workspace_collapses_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Workspace(Path(tmp))
            self.assertEqual(ws.code_root, ws.root)
            self.assertEqual(ws.base_root, ws.root)

    def test_routed_workspace_diverges_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            code = base / "worktrees/design"
            code.mkdir(parents=True)
            ws = PathRoutedWorkspace(base_root=base, code_root=code)
            self.assertEqual(ws.code_root, code.resolve())
            self.assertEqual(ws.base_root, base.resolve())
            self.assertNotEqual(ws.code_root, ws.base_root)


class ResolveRoutesSharedAssetsToBaseRoot(unittest.TestCase):
    """``screenshots/``, ``design/``, ``references/`` etc. are project-
    shared. The routing table sends them to base_root regardless of
    which agent's worktree is the active code root."""

    def _setup(self, tmp: Path):
        sshots = tmp / "screenshots"
        sshots.mkdir()
        (sshots / "login.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
        code = tmp / "worktrees/design"
        code.mkdir(parents=True)
        return PathRoutedWorkspace(base_root=tmp, code_root=code)

    def test_resolve_screenshots_goes_to_base(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            ws = self._setup(base)
            resolved = ws.resolve("screenshots/login.png")
            self.assertTrue(resolved.exists(),
                              f"resolve() didn't reach the project-root screenshot: {resolved}")
            self.assertEqual(resolved.parent.name, "screenshots")

    def test_resolve_app_path_goes_to_code(self):
        """Routing isn't one-way — ``app/*`` correctly stays in the
        per-agent worktree."""
        with tempfile.TemporaryDirectory() as tmp:
            ws = self._setup(Path(tmp))
            resolved = ws.resolve("app/backend/server.js")
            self.assertEqual(
                resolved.parent.parent.parent.name, "design",
                "app/* should resolve under the agent's worktree, not project root",
            )

    def test_view_image_from_worktree_finds_project_screenshot(self):
        """The live-run regression: ``view_image('screenshots/login.png')``
        called by an agent in a worktree previously failed because the
        tool concatenated ``workspace.root / 'screenshots'`` and got
        the empty worktree path. After PR 2 it goes through
        ``resolve()`` and lands at the project root."""
        from tools.file_tools import ViewImageTool
        with tempfile.TemporaryDirectory() as tmp:
            ws = self._setup(Path(tmp))
            tool = ViewImageTool(workspace=ws)
            result = tool.execute(path="screenshots/login.png")
            self.assertTrue(result.success,
                              f"view_image failed unexpectedly: {result.error_message}")
            self.assertIn("login.png", result.data.get("path", ""))


class ResolveRoutesSharedStateToBaseRoot(unittest.TestCase):
    """Non-screenshot shared paths (``design/``, ``shared/``,
    ``.memory/``) also resolve to base_root, while ``app/*`` stays in
    the worktree. ``.memory/`` in particular MUST land at base so the
    file tools and the memory module (which writes via base_dir) agree
    on one location — routing it to the worktree would split-brain the
    knowledge store. Migrated from the retired test_path_routed_workspace.py."""

    def _ws(self, tmp: Path):
        code = tmp / "worktrees" / "backend"
        code.mkdir(parents=True)
        return PathRoutedWorkspace(base_root=tmp, code_root=code), code

    def test_design_resolves_to_base(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            ws, _ = self._ws(base)
            self.assertEqual(ws.resolve("design/spec.api.json"),
                             base / "design/spec.api.json")

    def test_shared_resolves_to_base(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            ws, _ = self._ws(base)
            self.assertEqual(ws.resolve("shared/hubs/eventhub_events.json"),
                             base / "shared/hubs/eventhub_events.json")

    def test_memory_resolves_to_base(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            ws, _ = self._ws(base)
            self.assertEqual(ws.resolve(".memory/design.knowledge.jsonl"),
                             base / ".memory/design.knowledge.jsonl")

    def test_app_resolves_to_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            ws, code = self._ws(base)
            self.assertEqual(ws.resolve("app/backend/src/routes/auth.js"),
                             code / "app/backend/src/routes/auth.js")

    def test_contains_checks_either_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            ws, code = self._ws(base)
            self.assertTrue(ws.contains(base / "design/spec.api.json"))
            self.assertTrue(ws.contains(code / "app/backend/src/server.js"))
            self.assertFalse(ws.contains(Path("/etc/passwd")))


class WriteScopeRoutedByTable(unittest.TestCase):
    """Step 4 FOLD: ``is_write_allowed`` consults ``ROUTING_TABLE``.

    Replaces ``WorkspaceManager._can_write`` + ``AGENT_WRITE_DIRS``.
    Single source of truth for both routing and write-scope decisions."""

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp(prefix="ws_scope_"))
        code = self.tmp / "worktrees/design"
        code.mkdir(parents=True)
        self.ws = PathRoutedWorkspace(base_root=self.tmp, code_root=code)

    def test_role_owner_can_write_own_path(self):
        # Round 8e.1: design/ is owned by backend + frontend (design
        # agent role was absorbed). spec.api.json is the backend's
        # artifact; spec.ui.json (and the design/ tree generally) is
        # the frontend's. Both roles can write under design/.
        self.assertTrue(self.ws.is_write_allowed("app/backend/server.js", "backend"))
        self.assertTrue(self.ws.is_write_allowed("design/spec.api.json", "backend"))
        self.assertTrue(self.ws.is_write_allowed("design/spec.ui.json", "frontend"))
        self.assertTrue(self.ws.is_write_allowed("app/frontend/App.jsx", "frontend"))
        self.assertTrue(self.ws.is_write_allowed("app/database/init/01_schema.sql", "database"))

    def test_cross_role_write_denied(self):
        """Roles must not write outside their own routed prefixes.

        Round 8e.1: the design agent role was absorbed into
        backend/frontend, so ``design/`` is now writable by
        backend + frontend (plus broad writers). Cross-role denials
        therefore exercise non-writers like ``knowledge`` / ``verifier``
        / ``debugger`` against design/, not ``design`` as an actor.
        """
        # Knowledge / verifier / debugger are not in the design/ writer set.
        self.assertFalse(self.ws.is_write_allowed("design/spec.api.json", "knowledge"))
        self.assertFalse(self.ws.is_write_allowed("design/spec.api.json", "verifier"))
        self.assertFalse(self.ws.is_write_allowed("design/spec.api.json", "debugger"))
        # Frontend doesn't own backend code, and vice versa.
        self.assertFalse(self.ws.is_write_allowed("app/backend/server.js", "frontend"))
        self.assertFalse(self.ws.is_write_allowed("app/frontend/App.jsx", "backend"))

    def test_orchestrator_and_workers_have_broad_write(self):
        """Orchestrator + worker-flavoured agents are broad writers."""
        for agent in ("orchestrator", "worker", "analysis_worker", "review_worker"):
            self.assertTrue(self.ws.is_write_allowed("app/backend/server.js", agent),
                              f"{agent} should be allowed under app/backend/")
            self.assertTrue(self.ws.is_write_allowed("design/spec.api.json", agent),
                              f"{agent} should be allowed under design/")

    def test_read_only_routes_block_everyone(self):
        """``screenshots/``, ``references/``, ``mockups/``, ``images/``,
        ``shared/`` are read-only via tools. Writes go through different
        channels (orchestrator init / HubRegistry / monitor UI)."""
        for path in ("screenshots/login.png", "references/x.svg",
                      "mockups/feed.png", "images/avatar.jpg",
                      "shared/hubs/x.json"):
            for agent in ("design", "orchestrator", "backend", "verifier"):
                self.assertFalse(
                    self.ws.is_write_allowed(path, agent),
                    f"{agent} should NOT be able to write {path}",
                )

    def test_app_catchall_only_broad_writers(self):
        """Paths under ``app/`` but not a specific role dir fall to
        the ``app/`` catch-all → broad writers only. Backend writing
        ``app/random/foo.txt`` is rejected; orchestrator is allowed."""
        self.assertFalse(self.ws.is_write_allowed("app/random/foo.txt", "backend"))
        self.assertFalse(self.ws.is_write_allowed("app/random/foo.txt", "design"))
        self.assertTrue(self.ws.is_write_allowed("app/random/foo.txt", "orchestrator"))

    def test_default_target_is_code_ungated(self):
        """attempt-7 R1 round-7: ``_DEFAULT_TARGET = "code"`` and the
        code-default writer set is ungated — paths not in the routing
        table fall through to the per-agent worktree where the agent
        owns its scratch space.

        This preserves the agent-owns-worktree model (legit writes:
        README.md, STRUCTURE.md, scratch.txt, .gitignore at worktree
        root). The security fix lives in _DEFAULT_BASE_WRITERS =
        frozenset(): unrouted ABSOLUTE paths landing in base_root are
        read-only by default, which catches the base-poisoning attacks
        without breaking the worktree model.

        R1 round-6 → round-7 iteration: an initial attempt-7 also flipped
        ``_DEFAULT_TARGET`` to "base", which R1 caught as over-reach
        (broke legitimate non-routed worktree writes). Reverted in
        attempt-7.1 commit (this commit). The bi-directional acceptance:
        unrouted relative → True (worktree), unrouted absolute base →
        False (fail-closed)."""
        for agent in ("design", "backend", "frontend", "verifier"):
            # Unrouted relative paths land in the worktree (ungated).
            self.assertTrue(
                self.ws.is_write_allowed("notes.md", agent),
                f"unrouted relative path 'notes.md' must remain "
                f"agent-writable in worktree for {agent!r} (R1 round-7).",
            )
            # ``.memory/`` still ungated (the one legit per-agent base route)
            self.assertTrue(
                self.ws.is_write_allowed(".memory/scratch.json", agent),
                f".memory/ stays writable for {agent!r} — the one explicit "
                f"ungated base route per the routing table.",
            )

    def test_plain_workspace_is_ungated(self):
        """Plain ``Workspace`` (test contexts, orchestrator early init)
        has no per-route gate — ``is_write_allowed`` returns True for
        everything. The routed gate only matters once worktree
        isolation is in place."""
        plain = Workspace(self.tmp)
        for path in ("screenshots/x.png", "app/backend/server.js", "anything.txt"):
            self.assertTrue(plain.is_write_allowed(path, "design"))


class TrashIsolatedPerAgent(unittest.TestCase):
    """The safe-delete trash root is per-agent scratch — must live
    under the worktree, not the project root, so two agents deleting
    files don't collide."""

    def test_trash_lives_under_code_root_not_base(self):
        import time
        # The relevant helper is private; assert via the documented
        # location instead.
        from tools.file_tools import _move_to_trash
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            code = base / "worktrees/design"
            code.mkdir(parents=True)
            ws = PathRoutedWorkspace(base_root=base, code_root=code)
            # Drop a file in the worktree and trash it.
            victim = code / "scratch.txt"
            victim.write_text("bye")
            trash_path = _move_to_trash(ws, victim)
            # Trash should be under code root (worktree), not base.
            self.assertTrue(
                str(trash_path).startswith(str(ws.code_root)),
                f"Trash {trash_path} not under code_root {ws.code_root}",
            )


if __name__ == "__main__":
    unittest.main()
