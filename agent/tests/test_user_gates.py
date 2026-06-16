import sys
import tempfile
import unittest
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry
from multi_agent.runtime.user_gates import (
    evaluate_gate,
    validate_gate,
    VALID_GATE_TYPES,
)


class TestValidateGate(unittest.TestCase):
    def test_known_type_passes(self):
        for t in VALID_GATE_TYPES:
            err = validate_gate({"type": t, "name": "x", "params": {}})
            # Some types require params; the validator should at least accept the type
            self.assertNotEqual(err, "unknown gate type", f"Type {t} rejected: {err}")

    def test_unknown_type_rejected(self):
        err = validate_gate({"type": "bogus", "name": "x", "params": {}})
        self.assertEqual(err, "unknown gate type")

    def test_file_exists_missing_path(self):
        err = validate_gate({"type": "file_exists", "name": "x", "params": {}})
        self.assertIn("path", err)

    def test_endpoint_exists_missing_path(self):
        err = validate_gate({"type": "endpoint_exists", "name": "x", "params": {"method": "GET"}})
        self.assertIn("path", err)

    def test_visual_similarity_validates_min(self):
        err = validate_gate({"type": "visual_similarity", "name": "x", "params": {"page_id": "p"}})
        self.assertIn("min_similarity", err)
        err = validate_gate({"type": "visual_similarity", "name": "x",
                             "params": {"page_id": "p", "min_similarity": 2.0}})
        self.assertIn("between", err)
        err = validate_gate({"type": "visual_similarity", "name": "x",
                             "params": {"page_id": "p", "min_similarity": 0.8}})
        self.assertIsNone(err)


class TestFileExistsGate(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self._tmp.name)
        self.reg = HubRegistry(self.workspace, project_id="p", project_name="P")

    def tearDown(self):
        self._tmp.cleanup()

    def test_passes_when_file_present(self):
        (self.workspace / "README.md").write_text("hi")
        result = evaluate_gate({"type": "file_exists", "params": {"path": "README.md"}},
                               self.reg, self.workspace)
        self.assertTrue(result["passed"])

    def test_fails_when_file_absent(self):
        result = evaluate_gate({"type": "file_exists", "params": {"path": "nope.txt"}},
                               self.reg, self.workspace)
        self.assertFalse(result["passed"])
        self.assertIn("nope.txt", result["message"])

    def test_rejects_path_traversal(self):
        result = evaluate_gate({"type": "file_exists", "params": {"path": "../outside.txt"}},
                               self.reg, self.workspace)
        self.assertFalse(result["passed"])
        self.assertIn("invalid", result["message"].lower())


class TestEndpointExistsGate(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self._tmp.name)
        self.reg = HubRegistry(self.workspace, project_id="p", project_name="P")

    def tearDown(self):
        self._tmp.cleanup()

    def test_passes_when_endpoint_registered(self):
        self.reg.registryhub.register_endpoint("GET", "/api/users", schema={},
                                          provider="backend", agent="backend")
        result = evaluate_gate({"type": "endpoint_exists",
                                "params": {"method": "GET", "path": "/api/users"}},
                               self.reg, self.workspace)
        self.assertTrue(result["passed"])

    def test_fails_when_endpoint_missing(self):
        result = evaluate_gate({"type": "endpoint_exists",
                                "params": {"method": "POST", "path": "/api/login"}},
                               self.reg, self.workspace)
        self.assertFalse(result["passed"])

    def test_fails_when_endpoint_deprecated(self):
        self.reg.registryhub.register_endpoint("DELETE", "/api/users", schema={},
                                          provider="backend", agent="backend")
        self.reg.registryhub.deprecate_endpoint("DELETE /api/users", agent="backend")
        result = evaluate_gate({"type": "endpoint_exists",
                                "params": {"method": "DELETE", "path": "/api/users"}},
                               self.reg, self.workspace)
        self.assertFalse(result["passed"])


class TestMcpToolExistsGate(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self._tmp.name)
        self.reg = HubRegistry(self.workspace, project_id="p", project_name="P")

    def tearDown(self):
        self._tmp.cleanup()

    def test_passes_when_mcp_tool_registered(self):
        # Adapted: RegistryHub.register_mcp_server signature is
        # (name, transport, endpoint, ...), and register_mcp_tool uses
        # server_name + schema (not server_id + input_schema).
        # Use agent="backend" to satisfy the Phase 4 role gate on
        # register_mcp_server / register_mcp_tool; this test exercises
        # the downstream mcp_tool_exists evaluation, not the role gate.
        self.reg.mcp_registry.register_mcp_server(name="srv1", transport="stdio",
                                            endpoint="/tmp/srv1", agent="backend")
        self.reg.mcp_registry.register_mcp_tool(server_name="srv1", tool_name="search",
                                          schema={}, agent="backend")
        result = evaluate_gate({"type": "mcp_tool_exists",
                                "params": {"name": "search"}},
                               self.reg, self.workspace)
        self.assertTrue(result["passed"])

    def test_fails_when_missing(self):
        result = evaluate_gate({"type": "mcp_tool_exists",
                                "params": {"name": "nonexistent"}},
                               self.reg, self.workspace)
        self.assertFalse(result["passed"])


class TestVisualSimilarityGate(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self._tmp.name)
        self.reg = HubRegistry(self.workspace, project_id="p", project_name="P")

    def tearDown(self):
        self._tmp.cleanup()

    def test_passes_when_similarity_above_min(self):
        # Adapted: register_visual_review_task requires reference_path, and
        # WorkHub.submit_visual_review with state="approve" requires >=3
        # substantive deviations + >=20-char summary. We satisfy both.
        page = self.reg.gate_registry.register_visual_review_task(
            route="/home", screenshot_path="/tmp/foo.png",
            reference_path="/tmp/ref.png", agent="backend",
        )
        deviations = [
            {"aspect": "color", "expected": "blue", "actual": "navy", "severity": "low"},
            {"aspect": "spacing", "expected": "8px", "actual": "7px", "severity": "low"},
            {"aspect": "font", "expected": "Inter", "actual": "Helvetica", "severity": "low"},
        ]
        # Phase 4.5 review-verdict gate: reviewer must be 'verifier'
        # at phase>=4.5. This test exercises downstream evaluate_gate
        # behavior, not the role gate itself.
        res = self.reg.gate_registry.submit_visual_review(
            page_id=page["id"], reviewer="verifier", state="approve",
            summary="looks good and matches reference closely overall",
            similarity_score=0.9, deviations=deviations,
        )
        self.assertNotIn("error", res, res)
        result = evaluate_gate({"type": "visual_similarity",
                                "params": {"page_id": page["id"], "min_similarity": 0.8}},
                               self.reg, self.workspace)
        self.assertTrue(result["passed"], result)

    def test_fails_when_similarity_below_min(self):
        # Adapted: state="needs_revision" requires >=1 deviation.
        page = self.reg.gate_registry.register_visual_review_task(
            route="/home", screenshot_path="/tmp/foo.png",
            reference_path="/tmp/ref.png", agent="backend",
        )
        res = self.reg.gate_registry.submit_visual_review(
            page_id=page["id"], reviewer="verifier", state="needs_revision",
            summary="similarity is too low for approval",
            similarity_score=0.5,
            deviations=[{"aspect": "layout", "expected": "grid",
                         "actual": "flow", "severity": "high"}],
        )
        self.assertNotIn("error", res, res)
        result = evaluate_gate({"type": "visual_similarity",
                                "params": {"page_id": page["id"], "min_similarity": 0.8}},
                               self.reg, self.workspace)
        self.assertFalse(result["passed"])
        self.assertIn("0.5", result["message"])

    def test_fails_when_no_review_yet(self):
        result = evaluate_gate({"type": "visual_similarity",
                                "params": {"page_id": "page_nope", "min_similarity": 0.8}},
                               self.reg, self.workspace)
        self.assertFalse(result["passed"])


if __name__ == "__main__":
    unittest.main()
