"""End-to-end: backend writes app/shared.js → merges → integration has it.
Frontend writes a DIFFERENT app/shared.js → finish-policy detects
conflict → emits merge_conflict urgent event to orchestrator →
orchestrator calls codehub_resolve_merge_conflict(strategy="agent") →
integration now reflects frontend's version → next agent pull sees the
resolved state."""
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


class TestConflictResolutionEndToEnd(unittest.TestCase):
    def tearDown(self):
        _reset_loop()

    def test_conflict_event_then_orchestrator_resolves_integration_progresses(self):
        from multi_agent.workflow_policies import AutoCommitOnFinishPolicy
        from multi_agent.agents.runtime.auto_commit import (
            stage_file, resolve_merge_conflict_via_strategy,
        )

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            reg = HubRegistry(base, project_id="p", project_name="P")
            wt_backend = reg.codehub.register_agent_worktree("backend")
            wt_frontend = reg.codehub.register_agent_worktree("frontend")

            # Backend writes + finishes → integration has backend's version.
            (wt_backend / "app").mkdir(parents=True, exist_ok=True)
            (wt_backend / "app/shared.js").write_text(
                "// from backend\nmodule.exports = 'backend';\n"
            )
            stage_file(wt_backend, wt_backend / "app/shared.js")

            class BackendStub:
                agent_id = "backend"
                _agent_id = "backend"
                _hubs = reg
                _worktree_dir = wt_backend
                _logger = MagicMock()
                workspace = MagicMock(base_dir=base)

            policy = AutoCommitOnFinishPolicy()
            asyncio.run(policy.handle_finish(
                BackendStub(),
                tool_name="finish",
                tool_args={"message": "shared from backend"},
                tool_call=MagicMock(), tool_call_id="tc1",
                messages=[], files_created=["app/shared.js"], files_modified=[],
            ))

            # Frontend writes a CONFLICTING version of the same file.
            (wt_frontend / "app").mkdir(parents=True, exist_ok=True)
            (wt_frontend / "app/shared.js").write_text(
                "// from frontend\nmodule.exports = 'frontend';\n"
            )
            stage_file(wt_frontend, wt_frontend / "app/shared.js")

            class FrontendStub:
                agent_id = "frontend"
                _agent_id = "frontend"
                _hubs = reg
                _worktree_dir = wt_frontend
                _logger = MagicMock()
                workspace = MagicMock(base_dir=base)

            # Frontend's finish triggers commit + merge → conflict → event.
            asyncio.run(policy.handle_finish(
                FrontendStub(),
                tool_name="finish",
                tool_args={"message": "shared from frontend"},
                tool_call=MagicMock(), tool_call_id="tc2",
                messages=[], files_created=["app/shared.js"], files_modified=[],
            ))

            # Verify the merge_conflict event was emitted to orchestrator.
            events = list(reg.eventhub._events.value().values())
            conflicts = [e for e in events
                         if e.get("event_type") == "merge_conflict"]
            self.assertEqual(len(conflicts), 1,
                             f"expected 1 merge_conflict event, got {len(conflicts)}")
            payload = conflicts[0].get("payload", {})
            self.assertEqual(payload.get("agent"), "frontend")
            self.assertEqual(payload.get("source_branch"), "agent/frontend")

            # Before resolution, integration still has backend's version.
            r_pre = subprocess.run(
                ["git", "show", "integration:app/shared.js"],
                cwd=base, capture_output=True, text=True,
            )
            self.assertIn("from backend", r_pre.stdout)

            # Orchestrator calls the resolver with strategy="agent"
            # (frontend's incoming work wins).
            ok, info = resolve_merge_conflict_via_strategy(
                repo_root=base,
                agent_branch="agent/frontend",
                main_branch="integration",
                strategy="agent",
                agent_id="frontend",
            )
            self.assertTrue(ok, f"resolution failed: {info}")

            # After resolution, integration has frontend's version.
            r_post = subprocess.run(
                ["git", "show", "integration:app/shared.js"],
                cwd=base, capture_output=True, text=True,
            )
            self.assertIn("from frontend", r_post.stdout)
            self.assertNotIn("from backend", r_post.stdout)


if __name__ == "__main__":
    unittest.main()
