"""PR2.3 / Loop B ⑪: workspace-local HOME sandbox.

PR2/PR2.1 dropped ``HOME`` from the subprocess passthrough so agent
commands cannot read host identity (``~/.ssh``, ``~/.aws/credentials``,
``~/.gitconfig``). The trade-off: anything hard-coding ``~`` (npm
config writes, ``pip --user``, ad-hoc ``git commit`` without
``GIT_AUTHOR_*``) breaks or writes to ``/``. PR2.3 restores ``HOME``
but points it at a workspace-local sandbox so containment holds.

This file pins:
  1. ``_ensure_workspace_home`` creates the sandbox dir + a minimal
     ``.gitconfig`` (so direct ``git commit`` works) and is
     idempotent.
  2. The sandbox HOME lives INSIDE the workspace (not the host's
     real HOME) — the containment invariant.
  3. ``_workspace_env`` returns the minimal env + ``HOME``/``USER``
     pointing at the sandbox.
  4. ``ExecuteBashTool._build_env`` and ``RunBackgroundTool``'s
     ``bg_env`` both route through ``_workspace_env`` (no host
     identity leak).
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


class EnsureWorkspaceHomeTests(unittest.TestCase):
    def setUp(self):
        from tools.runtime_tools import _ensure_workspace_home
        self._fn = _ensure_workspace_home

    def test_creates_sandbox_under_code_root(self):
        """Test-stub callers without agent_id keep the legacy layout
        (``<root>/.agent_home/``) — backward-compat for unit tests."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            ws = SimpleNamespace(code_root=str(root), base_root=str(root))
            home = self._fn(ws)
            self.assertIsNotNone(home)
            self.assertTrue(home.is_dir())
            self.assertEqual(home.parent.resolve(), root)
            self.assertEqual(home.name, ".agent_home")

    def test_production_layout_is_above_worktree(self):
        """PR2.3.1 — Smoke #29 root cause fix. When workspace exposes
        BOTH ``base_root`` AND ``agent_id`` (the production
        PathRoutedWorkspace case), the sandbox lives at
        ``<base_root>/.agent_homes/<agent_id>/``, NOT inside
        ``<base_root>/worktrees/<agent_id>/``. The worktree's
        ``git status --porcelain`` then never sees the sandbox as
        dirty — so the orchestrator's commit_gate doesn't fire
        integrity_check on it, doesn't chase cleanup, and doesn't
        starve the kickoff facilitate handler."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            # The PROD layout PathRoutedWorkspace builds:
            #   base_root = <project>/
            #   code_root = <project>/worktrees/<agent_id>/
            worktree = base / "worktrees" / "backend"
            worktree.mkdir(parents=True)
            ws = SimpleNamespace(
                base_root=str(base),
                code_root=str(worktree),
                agent_id="backend",
            )
            home = self._fn(ws)
            self.assertIsNotNone(home)
            # The home MUST live in .agent_homes (plural) under base,
            # not under the worktree.
            self.assertEqual(home, base / ".agent_homes" / "backend")
            # And critically: the home MUST NOT be a child of the
            # worktree, else git inside the worktree sees it.
            self.assertNotIn(
                "worktrees",
                home.relative_to(base).parts,
                "sandbox HOME must be sibling of worktrees/, not inside it",
            )

    def test_path_routed_workspace_agent_id_property_routes_sandbox(self):
        """Smoke #34 regression: PR2.3.1 production fix relied on
        ``workspace.agent_id`` resolving to the owning lane. The real
        ``PathRoutedWorkspace`` stored it as ``_self_agent`` but did
        NOT expose an ``agent_id`` property — so ``getattr(workspace,
        'agent_id', None)`` returned None and the helper silently fell
        back to the legacy ``<code_root>/.agent_home/`` layout, which
        is exactly the worktree-dirtying that PR2.3.1 was supposed to
        prevent. This test pins the property + verifies the helper
        picks the above-worktree path."""
        from multi_agent.runtime.path_routed_workspace import PathRoutedWorkspace
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            worktree = base / "worktrees" / "backend"
            worktree.mkdir(parents=True)
            ws = PathRoutedWorkspace(
                base_root=base,
                code_root=worktree,
                agent_id="backend",
            )
            # Property surface is now public.
            self.assertEqual(ws.agent_id, "backend")
            self.assertEqual(ws.base_root, base)
            self.assertEqual(ws.code_root, worktree)
            # And the helper resolves to .agent_homes/<lane> above the
            # worktree, NOT <worktree>/.agent_home.
            home = self._fn(ws)
            self.assertIsNotNone(home)
            self.assertEqual(home, base / ".agent_homes" / "backend")
            # Critically: home is OUTSIDE the worktree.
            self.assertFalse(
                str(home).startswith(str(worktree)),
                f"sandbox HOME {home} must not be inside worktree {worktree}",
            )

    def test_per_agent_isolation(self):
        """Each agent gets its own sandbox dir under .agent_homes —
        spawned workers and resident lanes never share HOME."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            ws_be = SimpleNamespace(base_root=str(base), agent_id="backend")
            ws_fe = SimpleNamespace(base_root=str(base), agent_id="frontend")
            be_home = self._fn(ws_be)
            fe_home = self._fn(ws_fe)
            self.assertNotEqual(be_home, fe_home)
            self.assertEqual(be_home.parent, fe_home.parent)
            self.assertEqual(be_home.parent.name, ".agent_homes")

    def test_seeds_gitconfig_with_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            ws = SimpleNamespace(code_root=str(root), base_root=str(root))
            home = self._fn(ws)
            gitconfig = home / ".gitconfig"
            self.assertTrue(gitconfig.exists())
            text = gitconfig.read_text(encoding="utf-8")
            self.assertIn("[user]", text)
            self.assertIn("env-gen agent", text)
            self.assertIn("agent@env-gen.local", text)

    def test_idempotent(self):
        """Second call is a no-op — doesn't overwrite a manually-edited
        gitconfig, doesn't fail if the dir already exists."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            ws = SimpleNamespace(code_root=str(root), base_root=str(root))
            home = self._fn(ws)
            gitconfig = home / ".gitconfig"
            gitconfig.write_text("custom user override\n", encoding="utf-8")
            home2 = self._fn(ws)
            self.assertEqual(home, home2)
            self.assertEqual(
                gitconfig.read_text(encoding="utf-8"),
                "custom user override\n",
            )

    def test_falls_back_to_base_root_when_code_root_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            ws = SimpleNamespace(base_root=str(root))
            home = self._fn(ws)
            self.assertIsNotNone(home)
            self.assertEqual(home.parent.resolve(), root)

    def test_none_workspace_returns_none(self):
        self.assertIsNone(self._fn(None))

    def test_no_root_attr_returns_none(self):
        ws = SimpleNamespace()
        self.assertIsNone(self._fn(ws))


class WorkspaceEnvTests(unittest.TestCase):
    def setUp(self):
        from tools.runtime_tools import _workspace_env
        self._fn = _workspace_env

    def test_env_includes_workspace_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            ws = SimpleNamespace(code_root=str(root), base_root=str(root))
            env = self._fn(ws)
            self.assertIn("HOME", env)
            self.assertEqual(Path(env["HOME"]).parent.resolve(), root)
            self.assertEqual(env.get("USER"), "agent")

    def test_home_is_not_host_home(self):
        """Loop B ⑪ containment invariant: sandbox HOME must NOT be
        the host's real HOME."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            ws = SimpleNamespace(code_root=str(root), base_root=str(root))
            env = self._fn(ws)
            host_home = os.environ.get("HOME", "/root")
            self.assertNotEqual(env["HOME"], host_home)

    def test_env_preserves_minimal_passthrough(self):
        """PR2.1's minimal env (PATH/LANG/TZ/etc.) is still respected
        — we only ADD HOME + USER, never remove anything."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            ws = SimpleNamespace(code_root=str(root), base_root=str(root))
            env = self._fn(ws)
            # PYTHONUNBUFFERED is set unconditionally by
            # _DEFAULT_SUBPROCESS_ENV — its presence pins that we still
            # build atop the minimal env.
            self.assertEqual(env.get("PYTHONUNBUFFERED"), "1")

    def test_env_drops_sudo_user_and_logname(self):
        """Sanity: these host-identity vars must NOT survive (PR2.1
        invariant)."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            ws = SimpleNamespace(code_root=str(root), base_root=str(root))
            env = self._fn(ws)
            self.assertNotIn("SUDO_USER", env)
            self.assertNotIn("LOGNAME", env)

    def test_no_workspace_root_returns_minimal_env_unchanged(self):
        """If sandbox HOME can't be created (no workspace root), we
        return the minimal env as-is — no host HOME leak via
        os.environ passthrough."""
        env = self._fn(None)
        self.assertNotIn("HOME", env)
        # And still has the base minimal env.
        self.assertEqual(env.get("PYTHONUNBUFFERED"), "1")


class BashToolsRouteThroughWorkspaceEnvTests(unittest.TestCase):
    """ExecuteBashTool._build_env and RunBackgroundTool's bg_env
    construction must BOTH use _workspace_env so the HOME sandbox
    applies uniformly to foreground + background commands."""

    def test_execute_bash_tool_build_env_routes_through_workspace_env(self):
        import tools.runtime_tools as rt_mod
        from tools.runtime_tools import ExecuteBashTool

        captured = {}
        orig = rt_mod._workspace_env

        def spy(ws):
            captured["called"] = True
            captured["ws"] = ws
            return {"PYTHONUNBUFFERED": "1", "HOME": "/sentinel"}

        rt_mod._workspace_env = spy
        try:
            inst = object.__new__(ExecuteBashTool)
            inst.workspace = SimpleNamespace()
            env = inst._build_env()
        finally:
            rt_mod._workspace_env = orig
        self.assertTrue(captured.get("called"))
        self.assertEqual(env.get("HOME"), "/sentinel")

    def test_runtime_tools_no_longer_bare_default_env_in_bash_sites(self):
        """Source-level invariant: the two bash tool sites (foreground
        and background) must NOT call ``_DEFAULT_SUBPROCESS_ENV()``
        directly — they must use ``_workspace_env`` so the HOME
        sandbox applies. The ProcessManager standalone default
        (line 333) is allowed to keep using ``_DEFAULT_SUBPROCESS_ENV``
        since callers can pass an explicit ``env``."""
        import tools.runtime_tools as rt_mod
        src = Path(rt_mod.__file__).read_text(encoding="utf-8")
        # bg_env in RunBackgroundTool must be _workspace_env
        self.assertIn("bg_env = _workspace_env(self.workspace)", src)
        # ExecuteBashTool._build_env must return _workspace_env
        self.assertIn("return _workspace_env(self.workspace)", src)


if __name__ == "__main__":
    unittest.main()
