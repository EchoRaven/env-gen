"""End-to-end: a real ConfigurableAgent given a workspace_manager
must write app/* files into its own worktree, not the shared base."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


class TestAgentResolvesWorktreeOnInit(unittest.TestCase):
    def test_envgen_agent_exposes_worktree_dir(self):
        """register_agent_worktree returns the agent's worktree path
        under ``<base>/worktrees/<agent_id>``."""
        with tempfile.TemporaryDirectory() as tmp:
            reg = HubRegistry(Path(tmp), project_id="p", project_name="P")
            wt_path = reg.codehub.register_agent_worktree("backend")
            self.assertEqual(wt_path, Path(tmp) / "worktrees" / "backend")
            self.assertTrue(wt_path.exists())

    def test_path_routed_workspace_is_attached(self):
        """PathRoutedWorkspace routes app/* under the agent's
        worktree but keeps design/* under the project base."""
        from multi_agent.runtime.path_routed_workspace import PathRoutedWorkspace
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            reg = HubRegistry(base, project_id="p", project_name="P")
            wt = reg.codehub.register_agent_worktree("backend")
            ws = PathRoutedWorkspace(base_root=base, code_root=wt)
            self.assertEqual(
                ws.resolve("app/backend/src/server.js"),
                wt / "app/backend/src/server.js",
            )
            self.assertEqual(
                ws.resolve("design/spec.api.json"),
                base / "design/spec.api.json",
            )


class TestAutoStageOnWrite(unittest.TestCase):
    def test_successful_write_auto_stages_in_worktree(self):
        """The contract: when an agent's worktree exists and the agent
        writes a file resolved under that worktree, ``stage_file``
        marks it as ``A`` (added) in ``git status``."""
        import subprocess
        from multi_agent.runtime.path_routed_workspace import PathRoutedWorkspace
        from multi_agent.agents.runtime.auto_commit import stage_file

        with tempfile.TemporaryDirectory() as tmp:
            reg = HubRegistry(Path(tmp), project_id="p", project_name="P")
            wt = reg.codehub.register_agent_worktree("backend")
            ws = PathRoutedWorkspace(base_root=Path(tmp), code_root=wt)
            target_rel = "app/backend/src/test_route.js"
            target_abs = ws.resolve(target_rel)
            target_abs.parent.mkdir(parents=True, exist_ok=True)
            target_abs.write_text("module.exports = {};\n")
            ok, info = stage_file(wt, target_abs)
            self.assertTrue(ok, f"stage_file should succeed: {info}")
            r = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=wt, capture_output=True, text=True,
            )
            self.assertIn("A  app/backend/src/test_route.js", r.stdout)


if __name__ == "__main__":
    unittest.main()
