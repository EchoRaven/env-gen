"""Phase 0 end-to-end smoke: drive an agent through write → finish and
assert (a) the file landed in the agent's worktree (not the shared base),
(b) ``git log agent/backend`` shows a new commit with author=backend.
"""
from __future__ import annotations

import asyncio
import subprocess
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

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


def _reset_loop():
    try:
        asyncio.set_event_loop(asyncio.new_event_loop())
    except Exception:
        pass


class TestPhase0EndToEnd(unittest.TestCase):
    def tearDown(self):
        _reset_loop()

    def test_write_then_finish_commits_to_agent_branch(self):
        from multi_agent.runtime.path_routed_workspace import PathRoutedWorkspace
        from multi_agent.workflow_policies import AutoCommitOnFinishPolicy
        from multi_agent.agents.runtime.auto_commit import stage_file

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            reg = HubRegistry(base, project_id="p", project_name="P")
            wt = reg.codehub.register_agent_worktree("backend")
            ws = PathRoutedWorkspace(base_root=base, code_root=wt)

            target_rel = "app/backend/src/routes/auth.js"
            target_abs = ws.resolve(target_rel)
            self.assertTrue(str(target_abs).startswith(str(wt)),
                            "code path must resolve under the agent's worktree")
            target_abs.parent.mkdir(parents=True, exist_ok=True)
            target_abs.write_text("module.exports = function auth(){};\n")
            stage_file(wt, target_abs)

            # File MUST NOT exist under shared base.
            self.assertFalse(
                (base / target_rel).exists(),
                "code write leaked into shared base — worktree isolation broken",
            )

            class StubAgent:
                agent_id = "backend"
                _agent_id = "backend"
                _hubs = reg
                _worktree_dir = wt
                _logger = MagicMock()
                workspace = ws
            policy = AutoCommitOnFinishPolicy()
            asyncio.run(policy.handle_finish(
                StubAgent(),
                tool_name="finish",
                tool_args={"message": "Backend ready"},
                tool_call=MagicMock(),
                tool_call_id="tc",
                messages=[],
                files_created=[target_rel],
                files_modified=[],
            ))

            log = subprocess.run(
                ["git", "log", "agent/backend", "--format=%an|%s"],
                cwd=base, capture_output=True, text=True,
            )
            commits = [line for line in log.stdout.strip().split("\n") if line]
            self.assertTrue(
                any(c.startswith("backend|") for c in commits),
                f"no backend-authored commit on agent/backend; log: {commits}",
            )


if __name__ == "__main__":
    unittest.main()
