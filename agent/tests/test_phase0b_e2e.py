"""Phase 0b end-to-end: backend writes + finish-auto-commits-and-merges;
verifier (in its own worktree) pulls integration and now sees backend's
code locally. This is the critical contract that Phase 0 (per-agent
worktree) broke without 0b: docker_up / read / lint in verifier's
worktree had nothing because each agent's files lived only on its own
branch."""
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

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


def _reset_loop():
    try:
        asyncio.set_event_loop(asyncio.new_event_loop())
    except Exception:
        pass


class TestPhase0bEndToEnd(unittest.TestCase):
    def tearDown(self):
        _reset_loop()

    def test_backend_writes_then_verifier_pulls_and_sees_code(self):
        from multi_agent.runtime.path_routed_workspace import PathRoutedWorkspace
        from multi_agent.workflow_policies import AutoCommitOnFinishPolicy
        from multi_agent.agents.runtime.auto_commit import (
            stage_file, pull_main_into_worktree,
        )

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            reg = HubRegistry(base, project_id="p", project_name="P")
            wt_backend = reg.codehub.register_agent_worktree("backend")
            wt_verifier = reg.codehub.register_agent_worktree("verifier")

            # Backend writes app/backend/src/server.js to its worktree.
            backend_ws = PathRoutedWorkspace(base_root=base, code_root=wt_backend)
            target_rel = "app/backend/src/server.js"
            target_abs = backend_ws.resolve(target_rel)
            target_abs.parent.mkdir(parents=True, exist_ok=True)
            target_abs.write_text("console.log('backend ready');\n")
            stage_file(wt_backend, target_abs)

            # Backend's finish-policy commits + merges to integration.
            class BackendStub:
                agent_id = "backend"
                _agent_id = "backend"
                _hubs = reg
                _worktree_dir = wt_backend
                _logger = MagicMock()
                workspace = backend_ws
            policy = AutoCommitOnFinishPolicy()
            asyncio.run(policy.handle_finish(
                BackendStub(),
                tool_name="finish",
                tool_args={"message": "backend up"},
                tool_call=MagicMock(),
                tool_call_id="tc",
                messages=[],
                files_created=[target_rel],
                files_modified=[],
            ))

            # CRITICAL invariant before pull: verifier's worktree has NOT
            # received backend's file yet (we haven't pulled).
            verifier_view_pre = wt_verifier / target_rel
            self.assertFalse(
                verifier_view_pre.exists(),
                "test setup wrong — verifier already sees the file before pulling",
            )

            # Verifier's step-start pull (Phase 0b) brings integration in.
            ok, info = pull_main_into_worktree(
                worktree_dir=wt_verifier, main_branch="integration",
            )
            self.assertTrue(ok, f"verifier pull failed: {info}")

            # Now verifier CAN see backend's file locally. This is the
            # contract that lets verifier docker_up / read / lint
            # against backend's code without going through codehub_get_*.
            verifier_view_post = wt_verifier / target_rel
            self.assertTrue(
                verifier_view_post.exists(),
                "verifier still doesn't see backend's file after pulling integration",
            )
            self.assertIn(
                "backend ready",
                verifier_view_post.read_text(),
                "verifier got an empty / stale copy",
            )


if __name__ == "__main__":
    unittest.main()
