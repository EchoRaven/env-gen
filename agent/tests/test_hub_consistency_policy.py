"""HubConsistencyPolicy — Phase A finish-gate tests."""
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


def _reset_event_loop():
    try:
        asyncio.set_event_loop(asyncio.new_event_loop())
    except Exception:
        pass


class _StubAgent:
    """Minimal agent stand-in: agent_id, workspace.base_dir, _hubs, _logger."""

    def __init__(self, agent_id, reg, workspace_dir):
        self.agent_id = agent_id
        self._agent_id = agent_id
        self.workspace = MagicMock()
        self.workspace.base_dir = Path(workspace_dir)
        self._hubs = reg
        self._logger = MagicMock()


class TestHubConsistencyPolicyShape(unittest.TestCase):
    def tearDown(self):
        _reset_event_loop()

    def test_returns_none_when_tool_is_not_finish(self):
        from multi_agent.workflow_policies import HubConsistencyPolicy
        policy = HubConsistencyPolicy(
            expect_hub_kinds=["registryhub_endpoints"],
            file_patterns=["routes/"],
        )
        with tempfile.TemporaryDirectory() as tmp:
            reg = HubRegistry(Path(tmp), project_id="p", project_name="P")
            agent = _StubAgent("backend", reg, tmp)
            outcome = asyncio.run(policy.handle_finish(
                agent,
                tool_name="write",  # not finish
                tool_args={},
                tool_call=None,
                tool_call_id="",
                messages=[],
                files_created=[],
                files_modified=[],
            ))
            self.assertIsNone(outcome)

    def test_returns_none_when_no_code_evidence(self):
        """If the agent didn't write anything matching the gate's
        file_patterns, the policy must not block."""
        from multi_agent.workflow_policies import HubConsistencyPolicy
        policy = HubConsistencyPolicy(
            expect_hub_kinds=["registryhub_endpoints"],
            file_patterns=["routes/"],
        )
        with tempfile.TemporaryDirectory() as tmp:
            reg = HubRegistry(Path(tmp), project_id="p2", project_name="P2")
            agent = _StubAgent("backend", reg, tmp)
            outcome = asyncio.run(policy.handle_finish(
                agent,
                tool_name="finish",
                tool_args={"message": "done"},
                tool_call=None,
                tool_call_id="",
                messages=[],
                files_created=["docs/notes.md"],   # not a route file
                files_modified=[],
            ))
            self.assertIsNone(outcome)


class TestApihubEndpointsGate(unittest.TestCase):
    def tearDown(self):
        _reset_event_loop()

    def test_blocks_when_routes_written_but_no_endpoints_registered(self):
        from multi_agent.workflow_policies import HubConsistencyPolicy
        policy = HubConsistencyPolicy(
            expect_hub_kinds=["registryhub_endpoints"],
            file_patterns=["routes/", "controllers/"],
        )
        with tempfile.TemporaryDirectory() as tmp:
            reg = HubRegistry(Path(tmp), project_id="p", project_name="P")
            agent = _StubAgent("backend", reg, tmp)
            tool_call = MagicMock()
            messages = []
            outcome = asyncio.run(policy.handle_finish(
                agent,
                tool_name="finish",
                tool_args={"message": "all routes done"},
                tool_call=tool_call,
                tool_call_id="tc1",
                messages=messages,
                files_created=["app/backend/src/routes/auth.js", "app/backend/src/routes/feed.js"],
                files_modified=[],
            ))
            self.assertEqual(outcome, {"action": "continue"})
            # Messages list should now have: assistant-toolcall, tool-result (block text), user follow-up
            self.assertEqual(len(messages), 3)
            tool_msg_text = str(messages[1].content)
            self.assertIn("registryhub_register_endpoint", tool_msg_text)
            # Step A: message specifically says "0 endpoints ... as their
            # provider", since the gate now checks per-agent ownership
            # instead of total RegistryHub state.
            self.assertIn("registered 0 endpoints", tool_msg_text)
            self.assertIn("provider", tool_msg_text)

    def test_passes_when_at_least_one_endpoint_registered(self):
        from multi_agent.workflow_policies import HubConsistencyPolicy
        policy = HubConsistencyPolicy(
            expect_hub_kinds=["registryhub_endpoints"],
            file_patterns=["routes/"],
        )
        with tempfile.TemporaryDirectory() as tmp:
            reg = HubRegistry(Path(tmp), project_id="p", project_name="P")
            # Step A: the gate now counts endpoints owned by this agent
            # (provider == agent_id), so seed with provider='backend'.
            reg.registryhub._endpoints.set(
                "POST /api/auth/login",
                {"method": "POST", "path": "/api/auth/login",
                 "status": "implemented", "provider": "backend"},
                agent="backend",
            )
            agent = _StubAgent("backend", reg, tmp)
            outcome = asyncio.run(policy.handle_finish(
                agent,
                tool_name="finish",
                tool_args={"message": "ok"},
                tool_call=MagicMock(),
                tool_call_id="tc1",
                messages=[],
                files_created=["app/backend/src/routes/auth.js"],
                files_modified=[],
            ))
            self.assertIsNone(outcome)


class TestApihubEndpointsGatePerAgentOwnership(unittest.TestCase):
    """Step A: the gate counts per-agent ownership, not total RegistryHub
    state. design registering one endpoint must NOT let backend
    finish without registering its own."""

    def tearDown(self):
        _reset_event_loop()

    def test_other_agents_endpoints_do_not_satisfy_backends_gate(self):
        from multi_agent.workflow_policies import HubConsistencyPolicy
        policy = HubConsistencyPolicy(
            expect_hub_kinds=["registryhub_endpoints"],
            file_patterns=["routes/"],
        )
        with tempfile.TemporaryDirectory() as tmp:
            reg = HubRegistry(Path(tmp), project_id="p", project_name="P")
            # Design registered an endpoint at spec time.
            reg.registryhub._endpoints.set(
                "POST /api/auth/login",
                {"method": "POST", "path": "/api/auth/login",
                 "status": "defined", "provider": "design"},
                agent="design",
            )
            # Backend writes a route file but never registers as provider.
            agent = _StubAgent("backend", reg, tmp)
            outcome = asyncio.run(policy.handle_finish(
                agent,
                tool_name="finish",
                tool_args={"message": "implementations done"},
                tool_call=MagicMock(),
                tool_call_id="tc",
                messages=[],
                files_created=["app/backend/src/routes/auth.js"],
                files_modified=[],
            ))
            self.assertEqual(outcome, {"action": "continue"},
                              "Backend's gate must NOT be satisfied by design's "
                              "endpoint registration — backend has to register "
                              "as provider too.")


class TestApihubTablesAndPagesGates(unittest.TestCase):
    def tearDown(self):
        _reset_event_loop()

    def test_blocks_when_schema_written_but_no_tables_registered(self):
        from multi_agent.workflow_policies import HubConsistencyPolicy
        policy = HubConsistencyPolicy(
            expect_hub_kinds=["registryhub_tables"],
            file_patterns=[".sql", "migration"],
        )
        with tempfile.TemporaryDirectory() as tmp:
            reg = HubRegistry(Path(tmp), project_id="p", project_name="P")
            agent = _StubAgent("database", reg, tmp)
            messages = []
            outcome = asyncio.run(policy.handle_finish(
                agent,
                tool_name="finish",
                tool_args={"message": "schema in"},
                tool_call=MagicMock(),
                tool_call_id="tc",
                messages=messages,
                files_created=["app/database/init/01_schema.sql"],
                files_modified=[],
            ))
            self.assertEqual(outcome, {"action": "continue"})
            self.assertIn("registryhub_register_table", str(messages[1].content))

    def test_blocks_when_pages_written_but_workhub_pages_empty(self):
        from multi_agent.workflow_policies import HubConsistencyPolicy
        policy = HubConsistencyPolicy(
            expect_hub_kinds=["workhub_pages"],
            file_patterns=[".jsx", ".tsx", ".vue"],
        )
        with tempfile.TemporaryDirectory() as tmp:
            reg = HubRegistry(Path(tmp), project_id="p", project_name="P")
            agent = _StubAgent("frontend", reg, tmp)
            messages = []
            outcome = asyncio.run(policy.handle_finish(
                agent,
                tool_name="finish",
                tool_args={"message": "ui done"},
                tool_call=MagicMock(),
                tool_call_id="tc",
                messages=messages,
                files_created=[
                    "app/frontend/src/pages/Login.jsx",
                    "app/frontend/src/pages/Home.jsx",
                ],
                files_modified=[],
            ))
            self.assertEqual(outcome, {"action": "continue"})
            self.assertIn("registryhub_register_ui_page", str(messages[1].content))


class TestCodehubCommitsGate(unittest.TestCase):
    def tearDown(self):
        _reset_event_loop()

    def test_blocks_finish_when_many_writes_zero_commits(self):
        from multi_agent.workflow_policies import HubConsistencyPolicy
        policy = HubConsistencyPolicy(
            expect_hub_kinds=["codehub_commits"],
            file_patterns=[],   # any file counts
            min_modifications_for_codehub=5,
        )
        with tempfile.TemporaryDirectory() as tmp:
            reg = HubRegistry(Path(tmp), project_id="p", project_name="P")
            agent = _StubAgent("backend", reg, tmp)
            messages = []
            outcome = asyncio.run(policy.handle_finish(
                agent,
                tool_name="finish",
                tool_args={"message": "done"},
                tool_call=MagicMock(),
                tool_call_id="tc",
                messages=messages,
                files_created=[f"app/backend/file{i}.js" for i in range(6)],
                files_modified=[],
            ))
            self.assertEqual(outcome, {"action": "continue"})
            self.assertIn("codehub_commit", str(messages[1].content))

    def test_passes_below_threshold_even_with_zero_commits(self):
        from multi_agent.workflow_policies import HubConsistencyPolicy
        policy = HubConsistencyPolicy(
            expect_hub_kinds=["codehub_commits"],
            file_patterns=[],
            min_modifications_for_codehub=5,
        )
        with tempfile.TemporaryDirectory() as tmp:
            reg = HubRegistry(Path(tmp), project_id="p", project_name="P")
            agent = _StubAgent("backend", reg, tmp)
            outcome = asyncio.run(policy.handle_finish(
                agent,
                tool_name="finish",
                tool_args={"message": "tiny tweak"},
                tool_call=MagicMock(),
                tool_call_id="tc",
                messages=[],
                files_created=["a", "b"],
                files_modified=["c"],
            ))
            self.assertIsNone(outcome)


class TestFilePatternCoverage(unittest.TestCase):
    """The gate must cover ANY file under an agent's domain — not just
    files matching narrow path heuristics. Phase A originally listed
    only ``routes/, controllers/, handlers/`` for backend, which missed
    Django/FastAPI flat layouts (``views.py``, ``models.py``) and any
    file under ``app/backend/`` that isn't in a recognised subdir."""

    def tearDown(self):
        _reset_event_loop()

    def test_django_flat_layout_views_py_triggers_gate(self):
        """A Django-style backend writing ``app/backend/views.py`` MUST
        trigger the gate even though the path doesn't contain
        ``routes/`` or ``controllers/``."""
        import yaml
        cfg_path = (
            Path(__file__).resolve().parents[1]
            / "env_generator" / "llm_generator"
            / "multi_agent" / "agents" / "agents_config.yaml"
        )
        cfg = yaml.safe_load(cfg_path.read_text())
        backend_policies = cfg["profiles"]["backend"]["workflow_policies"]
        gate_cfg = next(p for p in backend_policies if p["kind"] == "hub_consistency_gate")
        from multi_agent.workflow_policies import HubConsistencyPolicy
        policy = HubConsistencyPolicy(
            expect_hub_kinds=gate_cfg["expect_hub_kinds"],
            file_patterns=gate_cfg["file_patterns"],
            min_modifications_for_codehub=gate_cfg.get("min_modifications_for_codehub", 5),
        )
        with tempfile.TemporaryDirectory() as tmp:
            reg = HubRegistry(Path(tmp), project_id="p", project_name="P")
            agent = _StubAgent("backend", reg, tmp)
            outcome = asyncio.run(policy.handle_finish(
                agent,
                tool_name="finish",
                tool_args={"message": "django done"},
                tool_call=MagicMock(),
                tool_call_id="tc",
                messages=[],
                files_created=["app/backend/views.py", "app/backend/urls.py", "app/backend/models.py"],
                files_modified=[],
            ))
            self.assertEqual(outcome, {"action": "continue"},
                             "Backend gate must fire on Django flat-layout writes (views.py/urls.py/models.py).")

    def test_test_and_config_files_are_excluded(self):
        """Tests, configs, lockfiles, docs must NOT trigger the gate
        even if they live in the agent's domain."""
        from multi_agent.workflow_policies import HubConsistencyPolicy
        policy = HubConsistencyPolicy(
            expect_hub_kinds=["registryhub_endpoints"],
            file_patterns=["app/backend/"],
        )
        with tempfile.TemporaryDirectory() as tmp:
            reg = HubRegistry(Path(tmp), project_id="p", project_name="P")
            agent = _StubAgent("backend", reg, tmp)
            outcome = asyncio.run(policy.handle_finish(
                agent,
                tool_name="finish",
                tool_args={"message": "scaffolding done"},
                tool_call=MagicMock(),
                tool_call_id="tc",
                messages=[],
                files_created=[
                    "app/backend/package.json",          # config
                    "app/backend/package-lock.json",     # lockfile
                    "app/backend/Dockerfile",            # config
                    "app/backend/test_auth.py",          # test
                    "app/backend/tests/test_routes.py",  # test
                    "app/backend/README.md",             # doc
                ],
                files_modified=[],
            ))
            self.assertIsNone(
                outcome,
                "Gate must NOT fire when only configs / tests / docs were touched.",
            )

    def test_custom_file_patterns_exclude_overrides_defaults(self):
        """Operators can supplement the default exclude list via yaml."""
        from multi_agent.workflow_policies import HubConsistencyPolicy
        policy = HubConsistencyPolicy(
            expect_hub_kinds=["registryhub_endpoints"],
            file_patterns=["app/backend/"],
            file_patterns_exclude=["generated/", "vendor/"],
        )
        # The custom excludes must be retained AND defaults still apply.
        self.assertIn("generated/", policy.file_patterns_exclude)
        self.assertIn("README", policy.file_patterns_exclude)


class TestPolicyMemoryFallback(unittest.TestCase):
    """When the caller forgets to pass files_created/modified (e.g. a
    bare integration test) but the agent's GeneratorMemory has session
    tracking, the policy should still detect work-was-done."""

    def tearDown(self):
        _reset_event_loop()

    def test_memory_files_used_when_explicit_lists_empty(self):
        from multi_agent.workflow_policies import HubConsistencyPolicy
        policy = HubConsistencyPolicy(
            expect_hub_kinds=["registryhub_endpoints"],
            file_patterns=["routes/"],
        )

        class FakeMem:
            _files_created = ["app/backend/src/routes/auth.js"]
            _files_modified = []

        with tempfile.TemporaryDirectory() as tmp:
            reg = HubRegistry(Path(tmp), project_id="p", project_name="P")
            agent = _StubAgent("backend", reg, tmp)
            agent.memory = FakeMem()
            outcome = asyncio.run(policy.handle_finish(
                agent,
                tool_name="finish",
                tool_args={"message": "done"},
                tool_call=MagicMock(),
                tool_call_id="tc",
                messages=[],
                files_created=[],
                files_modified=[],
            ))
            # Memory says agent wrote a route file; registryhub empty → gate must fire.
            self.assertEqual(outcome, {"action": "continue"},
                             "Policy must fall back to agent.memory file tracking.")


class TestCodehubGateScopedToRelevantFiles(unittest.TestCase):
    """Regression: codehub_commits threshold uses len(relevant), not
    len(touched). Otherwise unrelated edits (README, configs) inflate
    the count and trigger false-positive "you changed N files" blocks."""

    def tearDown(self):
        _reset_event_loop()

    def test_unrelated_edits_do_not_inflate_codehub_modification_count(self):
        from multi_agent.workflow_policies import HubConsistencyPolicy
        policy = HubConsistencyPolicy(
            expect_hub_kinds=["codehub_commits"],
            file_patterns=["routes/"],   # scope: only route files matter
            min_modifications_for_codehub=5,
        )
        with tempfile.TemporaryDirectory() as tmp:
            reg = HubRegistry(Path(tmp), project_id="p", project_name="P")
            agent = _StubAgent("backend", reg, tmp)
            # 1 in-scope route + 10 unrelated edits. Threshold is 5, so
            # if the gate (incorrectly) counts ALL files it fires (11>=5);
            # if it counts only relevant ones (1<5), it stays silent.
            outcome = asyncio.run(policy.handle_finish(
                agent,
                tool_name="finish",
                tool_args={"message": "done"},
                tool_call=MagicMock(),
                tool_call_id="tc",
                messages=[],
                files_created=["app/backend/src/routes/foo.js"],
                files_modified=[f"docs/note{i}.md" for i in range(10)],
            ))
            self.assertIsNone(
                outcome,
                "Codehub gate must scope its 'you've changed N files' "
                "count to in-pattern files only, not total churn.",
            )


class TestHubConsistencyFactoryWiring(unittest.TestCase):
    def test_factory_builds_policy_from_yaml_shaped_dict(self):
        from multi_agent.workflow_policies import (
            create_workflow_policies,
            HubConsistencyPolicy,
        )
        cfg = {
            "workflow_policies": [
                {
                    "kind": "hub_consistency_gate",
                    "expect_hub_kinds": ["registryhub_endpoints", "codehub_commits"],
                    "file_patterns": ["routes/", "controllers/"],
                    "min_modifications_for_codehub": 5,
                },
            ],
        }
        policies = create_workflow_policies(cfg)
        matching = [p for p in policies if isinstance(p, HubConsistencyPolicy)]
        self.assertEqual(len(matching), 1)
        p = matching[0]
        self.assertEqual(p.expect_hub_kinds, ["registryhub_endpoints", "codehub_commits"])
        self.assertIn("routes/", p.file_patterns)
        self.assertEqual(p.min_modifications_for_codehub, 5)

    def test_factory_raises_on_unknown_kind(self):
        from multi_agent.workflow_policies import create_workflow_policies
        with self.assertRaises(ValueError):
            create_workflow_policies({
                "workflow_policies": [{"kind": "nonsense_gate"}],
            })


if __name__ == "__main__":
    unittest.main()
