"""RequiredFilesPolicy — finish-gate tests (B2).

The LLM lanes partially follow their recipe: across smokes #38-49 the
backend lane sometimes shipped only ``src/`` (no Dockerfile / package.json)
and the frontend likewise. Compose's per-service ``build:`` then fails on
the missing Dockerfile, and no env ever reached a working ``docker compose
up``. This gate makes file completeness a HARD precondition for finish —
not a prompt suggestion — paired with ``lane_idle_circuit_breaker`` so it
can't loop forever.
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


def _reset_event_loop():
    try:
        asyncio.set_event_loop(asyncio.new_event_loop())
    except Exception:
        pass


class _StubRoutedWS:
    """Stand-in for PathRoutedWorkspace.is_framework_owned. Mirrors the real
    predicate: ownership is keyed by (prefix, basename) — a basename only
    counts as owned under its lane prefix (path_routed_workspace.py:625),
    so the stub enforces the prefix too and can't paper over a prefix regression."""

    def __init__(self, owned_basenames, prefix="app/frontend/"):
        self._owned = set(owned_basenames)
        self._prefix = prefix

    def is_framework_owned(self, path) -> bool:
        p = str(path)
        return p.startswith(self._prefix) and Path(p).name in self._owned


class _StubAgent:
    """Minimal agent stand-in: agent_id, _worktree_dir, _logger.

    ``bootstrapped`` defaults True (the implementation phase, where the
    gate is meant to enforce). Kickoff-reply phase = bootstrapped False.

    ``routed_ws`` optionally attaches a ``_routed_workspace`` so the
    framework-owned filter (Class-6) is actually exercised — the real bug
    was the gate reading ``agent.workspace`` (bare WorkspaceManager, no
    ownership method) instead of ``_routed_workspace``."""

    def __init__(self, agent_id, worktree_dir, bootstrapped=True, routed_ws=None):
        self.agent_id = agent_id
        self._worktree_dir = worktree_dir
        self._kickoff_bootstrapped = bootstrapped
        self._logger = MagicMock()
        if routed_ws is not None:
            self._routed_workspace = routed_ws


def _touch(root: Path, rel: str):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("x", encoding="utf-8")


def _finish(policy, agent, messages=None):
    return asyncio.run(policy.handle_finish(
        agent,
        tool_name="finish",
        tool_args={},
        tool_call=None,
        tool_call_id="tc1",
        messages=messages if messages is not None else [],
        files_created=[],
        files_modified=[],
    ))


class RequiredFilesPolicyTests(unittest.TestCase):
    def tearDown(self):
        _reset_event_loop()

    def test_allows_finish_when_all_files_present(self):
        from multi_agent.workflow_policies import RequiredFilesPolicy
        policy = RequiredFilesPolicy(paths=[
            "app/backend/Dockerfile", "app/backend/package.json",
        ])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _touch(root, "app/backend/Dockerfile")
            _touch(root, "app/backend/package.json")
            agent = _StubAgent("backend", str(root))
            self.assertIsNone(_finish(policy, agent))

    def test_blocks_finish_and_names_missing_files(self):
        from multi_agent.workflow_policies import RequiredFilesPolicy
        policy = RequiredFilesPolicy(paths=[
            "app/backend/Dockerfile", "app/backend/package.json",
        ])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _touch(root, "app/backend/Dockerfile")  # package.json missing
            agent = _StubAgent("backend", str(root))
            messages: list = []
            outcome = _finish(policy, agent, messages)
            self.assertEqual(outcome, {"action": "continue"})
            # assistant tool_call echo + tool result + user nudge.
            self.assertEqual(len(messages), 3)
            joined = " ".join(str(getattr(m, "content", "")) for m in messages)
            self.assertIn("app/backend/package.json", joined)
            self.assertNotIn("app/backend/Dockerfile", joined)  # present → not listed

    def test_abstains_during_kickoff_phase_when_not_bootstrapped(self):
        # Regression for the smoke deadlock (2026-06-05): the gate must NOT
        # fire on the kickoff-reply finish — that phase exposes no filesystem
        # tools and no app/<domain> files can exist yet, so enforcing impl
        # files there deadlocks the lane (chicken-and-egg, same failure the
        # retired implementation_bootstrap gate caused). required_files
        # applies ONLY to implementation-phase finishes (_kickoff_bootstrapped).
        from multi_agent.workflow_policies import RequiredFilesPolicy
        policy = RequiredFilesPolicy(paths=[
            "app/frontend/Dockerfile", "app/frontend/package.json",
        ])
        with tempfile.TemporaryDirectory() as tmp:
            # Worktree exists, files are genuinely missing — but the lane is
            # still in kickoff phase, so the gate MUST abstain (not block).
            agent = _StubAgent("frontend", tmp, bootstrapped=False)
            self.assertIsNone(_finish(policy, agent))

    def test_abstains_when_no_worktree(self):
        # Charter §8: can't verify without a worktree → abstain (don't
        # false-block), never pretend success.
        from multi_agent.workflow_policies import RequiredFilesPolicy
        policy = RequiredFilesPolicy(paths=["app/backend/Dockerfile"])
        agent = _StubAgent("backend", None)
        self.assertIsNone(_finish(policy, agent))

    def test_returns_none_for_non_finish_tool(self):
        from multi_agent.workflow_policies import RequiredFilesPolicy
        policy = RequiredFilesPolicy(paths=["app/backend/Dockerfile"])
        with tempfile.TemporaryDirectory() as tmp:
            agent = _StubAgent("backend", tmp)
            outcome = asyncio.run(policy.handle_finish(
                agent, tool_name="write", tool_args={}, tool_call=None,
                tool_call_id="", messages=[], files_created=[], files_modified=[],
            ))
            self.assertIsNone(outcome)

    def test_empty_paths_is_noop(self):
        from multi_agent.workflow_policies import RequiredFilesPolicy
        policy = RequiredFilesPolicy(paths=[])
        with tempfile.TemporaryDirectory() as tmp:
            agent = _StubAgent("backend", tmp)
            self.assertIsNone(_finish(policy, agent))


class RequiredFilesAnyOfTests(unittest.TestCase):
    """⚠1 fix: any_of groups — each satisfied if AT LEAST ONE alternative
    exists, so the frontend gate can require 'a src entry' without pinning
    jsx vs tsx."""

    def tearDown(self):
        _reset_event_loop()

    def test_allows_finish_when_one_alternative_per_group_present(self):
        from multi_agent.workflow_policies import RequiredFilesPolicy
        policy = RequiredFilesPolicy(
            paths=["app/frontend/Dockerfile"],
            any_of=[
                ["app/frontend/src/main.jsx", "app/frontend/src/main.tsx"],
                ["app/frontend/src/App.jsx", "app/frontend/src/App.tsx"],
            ],
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _touch(root, "app/frontend/Dockerfile")
            _touch(root, "app/frontend/src/main.tsx")   # tsx alt satisfies group 1
            _touch(root, "app/frontend/src/App.jsx")    # jsx alt satisfies group 2
            agent = _StubAgent("frontend", str(root))
            self.assertIsNone(_finish(policy, agent))

    def test_blocks_when_a_group_has_no_alternative_present(self):
        from multi_agent.workflow_policies import RequiredFilesPolicy
        policy = RequiredFilesPolicy(
            paths=[],
            any_of=[["app/frontend/src/services/api.js", "app/frontend/src/services/api.ts"]],
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agent = _StubAgent("frontend", str(root))
            messages: list = []
            outcome = _finish(policy, agent, messages)
            self.assertEqual(outcome, {"action": "continue"})
            joined = " ".join(str(getattr(m, "content", "")) for m in messages)
            self.assertIn("one of:", joined)
            self.assertIn("app/frontend/src/services/api.js", joined)

    def test_any_of_only_is_not_a_noop(self):
        # paths empty but any_of set → the gate still runs.
        from multi_agent.workflow_policies import RequiredFilesPolicy
        policy = RequiredFilesPolicy(paths=[], any_of=[["a.jsx", "a.tsx"]])
        with tempfile.TemporaryDirectory() as tmp:
            agent = _StubAgent("frontend", tmp)
            self.assertEqual(_finish(policy, agent), {"action": "continue"})

    def test_factory_passes_any_of(self):
        from multi_agent.workflow_policies import create_workflow_policies
        cfg = {"workflow_policies": [
            {"kind": "required_files",
             "paths": ["app/frontend/Dockerfile"],
             "any_of": [["app/frontend/src/main.jsx", "app/frontend/src/main.tsx"]]},
        ]}
        policies = create_workflow_policies(cfg)
        self.assertEqual(policies[0].paths, ["app/frontend/Dockerfile"])
        self.assertEqual(
            policies[0].any_of,
            [["app/frontend/src/main.jsx", "app/frontend/src/main.tsx"]],
        )


class RequiredFilesFrameworkOwnedFilterTests(unittest.TestCase):
    """The Class-6 filter must consult ``_routed_workspace`` (the object that
    implements is_framework_owned), NOT the bare ``agent.workspace``. The
    original fix read the wrong object → filter was dead code → finish demanded
    framework-owned infra files (Dockerfile/package.json/...) the write-gate
    denies → unsatisfiable catch-22 (smoke run, 2026-06-19)."""

    def tearDown(self):
        _reset_event_loop()

    def test_framework_owned_required_files_are_filtered_out(self):
        from multi_agent.workflow_policies import RequiredFilesPolicy
        policy = RequiredFilesPolicy(paths=[
            "app/frontend/Dockerfile", "app/frontend/package.json",
            "app/frontend/src/App.jsx",  # LANE-owned → still demanded
        ])
        owned = _StubRoutedWS({"Dockerfile", "package.json"})  # App.jsx NOT owned
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # NONE of the files exist on disk. The two framework-owned ones must
            # be filtered out; only the lane-owned App.jsx should block finish.
            agent = _StubAgent("frontend", str(root), routed_ws=owned)
            messages: list = []
            outcome = _finish(policy, agent, messages)
            self.assertEqual(outcome, {"action": "continue"})
            joined = " ".join(str(getattr(m, "content", "")) for m in messages)
            self.assertIn("app/frontend/src/App.jsx", joined)
            self.assertNotIn("Dockerfile", joined)
            self.assertNotIn("package.json", joined)

    def test_finish_allowed_when_only_framework_owned_missing(self):
        from multi_agent.workflow_policies import RequiredFilesPolicy
        policy = RequiredFilesPolicy(paths=[
            "app/backend/Dockerfile", "app/backend/pyproject.toml",
        ])
        owned = _StubRoutedWS({"Dockerfile", "pyproject.toml"}, prefix="app/backend/")
        with tempfile.TemporaryDirectory() as tmp:
            # Both demanded files are framework-owned and absent from the lane
            # worktree (framework emits them to the integration root) → finish
            # must NOT block (the prior catch-22).
            agent = _StubAgent("backend", str(tmp), routed_ws=owned)
            self.assertIsNone(_finish(policy, agent))

    def test_any_of_group_dropped_when_an_alternative_is_framework_owned(self):
        from multi_agent.workflow_policies import RequiredFilesPolicy
        policy = RequiredFilesPolicy(
            paths=[],
            any_of=[
                # main.jsx is framework-owned (the pinned entrypoint) → whole
                # group satisfied-by-construction even though nothing on disk.
                ["app/frontend/src/main.jsx", "app/frontend/src/main.tsx"],
                # App.jsx group has no owned member → still demanded.
                ["app/frontend/src/App.jsx", "app/frontend/src/App.tsx"],
            ],
        )
        owned = _StubRoutedWS({"main.jsx"})
        with tempfile.TemporaryDirectory() as tmp:
            agent = _StubAgent("frontend", str(tmp), routed_ws=owned)
            messages: list = []
            outcome = _finish(policy, agent, messages)
            self.assertEqual(outcome, {"action": "continue"})
            joined = " ".join(str(getattr(m, "content", "")) for m in messages)
            self.assertIn("App.jsx", joined)        # lane group still demanded
            self.assertNotIn("main.jsx", joined)    # owned-entry group dropped

    def test_filter_falls_open_safely_without_routed_workspace(self):
        # No _routed_workspace and no workspace → _fw_owned returns False for
        # all, so the gate behaves as a pure existence check (no crash). Proves
        # the `or` fallback and preserves the abstain-don't-crash contract.
        from multi_agent.workflow_policies import RequiredFilesPolicy
        policy = RequiredFilesPolicy(paths=["app/backend/Dockerfile"])
        with tempfile.TemporaryDirectory() as tmp:
            agent = _StubAgent("backend", str(tmp))  # no routed_ws
            self.assertEqual(_finish(policy, agent), {"action": "continue"})


class RequiredFilesFactoryTests(unittest.TestCase):
    def test_factory_builds_required_files_from_config(self):
        from multi_agent.workflow_policies import (
            RequiredFilesPolicy, create_workflow_policies,
        )
        cfg = {"workflow_policies": [
            {"kind": "required_files", "paths": ["app/backend/Dockerfile"]},
        ]}
        policies = create_workflow_policies(cfg)
        self.assertEqual(len(policies), 1)
        self.assertIsInstance(policies[0], RequiredFilesPolicy)
        self.assertEqual(policies[0].paths, ["app/backend/Dockerfile"])

    def test_required_files_is_registered_as_a_starver(self):
        # It has a handle_finish that can return non-None, so it must be
        # listed in STARVER_POLICY_KINDS for the ordering hygiene check.
        from multi_agent.workflow_policies import STARVER_POLICY_KINDS
        self.assertIn("required_files", STARVER_POLICY_KINDS)


if __name__ == "__main__":
    unittest.main()
