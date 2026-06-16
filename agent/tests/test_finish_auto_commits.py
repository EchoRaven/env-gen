"""Auto-commit on finish: when a code-writing agent's finish() succeeds,
any staged changes in the worktree are committed to ``agent/<id>`` with
author = agent_id."""
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


class TestAutoCommitOnFinishPolicy(unittest.TestCase):
    def tearDown(self):
        _reset_loop()

    def test_policy_commits_staged_changes_with_agent_author(self):
        from multi_agent.workflow_policies import AutoCommitOnFinishPolicy
        from multi_agent.agents.runtime.auto_commit import stage_file

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            reg = HubRegistry(base, project_id="p", project_name="P")
            wt = reg.codehub.register_agent_worktree("backend")
            (wt / "app").mkdir(parents=True, exist_ok=True)
            f = wt / "app/server.js"
            f.write_text("console.log('hi');\n")
            stage_file(wt, f)

            class StubAgent:
                agent_id = "backend"
                _agent_id = "backend"
                _hubs = reg
                _worktree_dir = wt
                _logger = MagicMock()
                workspace = MagicMock(base_dir=base)
                async def _execute_tool(self, name, args):
                    class R: success = True; data = {"summary": "ok"}; error_message = None
                    return R()

            policy = AutoCommitOnFinishPolicy()
            asyncio.run(policy.handle_finish(
                StubAgent(),
                tool_name="finish",
                tool_args={"message": "Backend scaffolded"},
                tool_call=MagicMock(),
                tool_call_id="tc",
                messages=[],
                files_created=["app/server.js"],
                files_modified=[],
            ))
            log = subprocess.run(
                ["git", "log", "-1", "--format=%an|%s", "agent/backend"],
                cwd=base, capture_output=True, text=True,
            )
            line = log.stdout.strip()
            self.assertTrue(line.startswith("backend|"),
                            f"author wrong: {line!r}")
            self.assertIn("[backend]", line)
            self.assertIn("Backend scaffolded", line)

    def test_policy_returns_none_when_not_finish(self):
        from multi_agent.workflow_policies import AutoCommitOnFinishPolicy
        policy = AutoCommitOnFinishPolicy()
        outcome = asyncio.run(policy.handle_finish(
            MagicMock(),
            tool_name="write",
            tool_args={},
            tool_call=None, tool_call_id="",
            messages=[], files_created=[], files_modified=[],
        ))
        self.assertIsNone(outcome)

    def test_policy_quiet_when_nothing_staged(self):
        from multi_agent.workflow_policies import AutoCommitOnFinishPolicy
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            reg = HubRegistry(base, project_id="p", project_name="P")
            wt = reg.codehub.register_agent_worktree("backend")

            class StubAgent:
                agent_id = "backend"
                _agent_id = "backend"
                _hubs = reg
                _worktree_dir = wt
                _logger = MagicMock()
                workspace = MagicMock(base_dir=base)

            policy = AutoCommitOnFinishPolicy()
            outcome = asyncio.run(policy.handle_finish(
                StubAgent(),
                tool_name="finish",
                tool_args={"message": "nothing did"},
                tool_call=MagicMock(),
                tool_call_id="tc",
                messages=[],
                files_created=[],
                files_modified=[],
            ))
            self.assertIsNone(outcome)


class TestAutoCommitOnFinishAlsoMergesToIntegration(unittest.TestCase):
    def tearDown(self):
        _reset_loop()

    def test_finish_merges_agent_branch_into_integration(self):
        """After auto-commit, the policy must also merge the agent's
        branch into ``integration`` so other agents pulling can see
        the work."""
        from multi_agent.workflow_policies import AutoCommitOnFinishPolicy
        from multi_agent.agents.runtime.auto_commit import stage_file

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            reg = HubRegistry(base, project_id="p", project_name="P")
            wt = reg.codehub.register_agent_worktree("backend")
            (wt / "app").mkdir(parents=True, exist_ok=True)
            f = wt / "app/server.js"
            f.write_text("console.log('hi');\n")
            stage_file(wt, f)

            class StubAgent:
                agent_id = "backend"
                _agent_id = "backend"
                _hubs = reg
                _worktree_dir = wt
                _logger = MagicMock()
                workspace = MagicMock(base_dir=base)

            policy = AutoCommitOnFinishPolicy()
            asyncio.run(policy.handle_finish(
                StubAgent(),
                tool_name="finish",
                tool_args={"message": "Backend ready"},
                tool_call=MagicMock(),
                tool_call_id="tc",
                messages=[],
                files_created=["app/server.js"],
                files_modified=[],
            ))

            # The ``integration`` branch must exist and carry the file.
            log = subprocess.run(
                ["git", "show", "integration:app/server.js"],
                cwd=base, capture_output=True, text=True,
            )
            self.assertEqual(log.returncode, 0,
                             f"integration branch missing app/server.js: {log.stderr!r}")
            self.assertIn("console.log", log.stdout)

    def test_merge_conflict_emits_issue_event_via_eventhub(self):
        """On a conflict between agent/<id> and integration, the policy
        must NOT silently swallow — it emits an EventHub event so the
        orchestrator can route resolution."""
        from multi_agent.workflow_policies import AutoCommitOnFinishPolicy
        from multi_agent.agents.runtime.auto_commit import (
            stage_file, commit_worktree, merge_agent_branch_to_main,
        )

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            reg = HubRegistry(base, project_id="p", project_name="P")
            # Two agents, same file, conflicting content.
            wt_backend = reg.codehub.register_agent_worktree("backend")
            wt_frontend = reg.codehub.register_agent_worktree("frontend")

            # Backend commits + merges first.
            (wt_backend / "app").mkdir(parents=True, exist_ok=True)
            (wt_backend / "app/conflict.js").write_text("from backend\n")
            stage_file(wt_backend, wt_backend / "app/conflict.js")
            commit_worktree(worktree_dir=wt_backend, branch="agent/backend",
                            author="backend", message="[backend] conflict")
            merge_agent_branch_to_main(
                repo_root=base, agent_branch="agent/backend",
                main_branch="integration", agent_id="backend",
            )

            # Frontend writes a DIFFERENT line to the SAME file, then commits.
            (wt_frontend / "app").mkdir(parents=True, exist_ok=True)
            (wt_frontend / "app/conflict.js").write_text("from frontend\n")
            stage_file(wt_frontend, wt_frontend / "app/conflict.js")
            commit_worktree(worktree_dir=wt_frontend, branch="agent/frontend",
                            author="frontend", message="[frontend] conflict")

            # Now run policy on frontend → merge should conflict.
            class StubAgent:
                agent_id = "frontend"
                _agent_id = "frontend"
                _hubs = reg
                _worktree_dir = wt_frontend
                _logger = MagicMock()
                workspace = MagicMock(base_dir=base)

            # Record events before the policy runs.
            events_before = len(reg.eventhub._events.value())
            policy = AutoCommitOnFinishPolicy()
            asyncio.run(policy.handle_finish(
                StubAgent(),
                tool_name="finish",
                tool_args={"message": "frontend ready"},
                tool_call=MagicMock(),
                tool_call_id="tc",
                messages=[],
                files_created=["app/conflict.js"],
                files_modified=[],
            ))
            events_after = reg.eventhub._events.value()
            new = [e for e in events_after.values()
                   if e.get("event_type") == "merge_conflict"]
            self.assertEqual(len(new), 1,
                             f"expected 1 merge_conflict event, got {len(new)}")
            payload = new[0].get("payload", {})
            self.assertEqual(payload.get("agent"), "frontend")
            self.assertIn("conflict", str(payload.get("detail", "")).lower())


if __name__ == "__main__":
    unittest.main()
