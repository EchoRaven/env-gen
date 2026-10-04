"""Tests for RunHub probe planner (pure, no IO)."""

import sys
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hubs.runhub.probes import (  # noqa: E402
    plan_probe, ProbePlan, ProbeSkip, classify_probe_result, ProbeOutcome,
)


class ProbePlanTests(unittest.TestCase):
    def test_get_endpoint_returns_plan_with_empty_body(self) -> None:
        ep = {"method": "GET", "path": "/api/feed", "auth_required": False}
        result = plan_probe(ep, base_url="http://localhost:8000")
        self.assertIsInstance(result, ProbePlan)
        self.assertEqual(result.method, "GET")
        self.assertEqual(result.url, "http://localhost:8000/api/feed")
        self.assertIsNone(result.body)

    def test_get_endpoint_with_auth_required_still_probes(self) -> None:
        # GET with auth: we probe, 401/403 will be tolerated at result-classification time
        ep = {"method": "GET", "path": "/api/me", "auth_required": True}
        result = plan_probe(ep, base_url="http://localhost:8000")
        self.assertIsInstance(result, ProbePlan)

    def test_post_with_auth_required_skipped(self) -> None:
        ep = {"method": "POST", "path": "/api/feed", "auth_required": True}
        result = plan_probe(ep, base_url="http://localhost:8000")
        self.assertIsInstance(result, ProbeSkip)
        self.assertEqual(result.reason, "auth_required")

    def test_post_without_auth_uses_example_body_when_available(self) -> None:
        ep = {"method": "POST", "path": "/api/feed", "auth_required": False}
        example = {"text": "hello"}
        result = plan_probe(ep, base_url="http://localhost:8000", example_body=example)
        self.assertIsInstance(result, ProbePlan)
        self.assertEqual(result.body, example)

    def test_post_without_auth_falls_back_to_empty_json(self) -> None:
        ep = {"method": "POST", "path": "/api/feed", "auth_required": False}
        result = plan_probe(ep, base_url="http://localhost:8000")
        self.assertIsInstance(result, ProbePlan)
        self.assertEqual(result.body, {})

    def test_delete_always_skipped_destructive(self) -> None:
        ep = {"method": "DELETE", "path": "/api/feed/1", "auth_required": False}
        result = plan_probe(ep, base_url="http://localhost:8000")
        self.assertIsInstance(result, ProbeSkip)
        self.assertEqual(result.reason, "destructive")

    def test_undefined_endpoint_skipped(self) -> None:
        """#1203d6: the intent is intact -- a status that is not live stays unprobed -- but the
        reason is now `not_live`, because the old predicate `status != "defined"` swept in
        `implemented`, which is 94% of every endpoint record in the corpus and is exactly the
        status the FRAMEWORK writes after auditing that the route answers.

        ★ This fixture is why that went unnoticed for 169 runs: `draft` appears in no run
        directory anywhere. The test was green against a status the system never produces while
        the real data took the other branch. See test_1203d6_* for the measurement."""
        ep = {"method": "GET", "path": "/api/wip", "status": "draft"}
        result = plan_probe(ep, base_url="http://localhost:8000")
        self.assertIsInstance(result, ProbeSkip)
        self.assertEqual(result.reason, "not_live")

    def test_implemented_endpoint_is_probed(self) -> None:
        """#1203d6: the status this skip used to swallow."""
        ep = {"method": "GET", "path": "/api/videos/feed", "status": "implemented",
              "auth_required": False}
        self.assertIsInstance(plan_probe(ep, base_url="http://localhost:8000"), ProbePlan)


class ProbeOutcomeClassificationTests(unittest.TestCase):
    def test_2xx_is_pass(self) -> None:
        outcome = classify_probe_result(200, "OK", auth_required=False)
        self.assertEqual(outcome.verdict, "pass")

    def test_3xx_is_pass(self) -> None:
        outcome = classify_probe_result(301, "", auth_required=False)
        self.assertEqual(outcome.verdict, "pass")

    def test_5xx_is_fail_high_severity(self) -> None:
        outcome = classify_probe_result(500, "Internal error", auth_required=False)
        self.assertEqual(outcome.verdict, "fail")
        self.assertEqual(outcome.severity, "P1")

    def test_4xx_other_than_401_403_404_is_fail(self) -> None:
        outcome = classify_probe_result(400, "bad request", auth_required=False)
        self.assertEqual(outcome.verdict, "fail")
        self.assertEqual(outcome.severity, "P2")

    def test_401_or_403_pass_when_auth_required(self) -> None:
        for code in (401, 403):
            outcome = classify_probe_result(code, "auth", auth_required=True)
            self.assertEqual(outcome.verdict, "pass")

    def test_401_or_403_fail_when_auth_not_required(self) -> None:
        for code in (401, 403):
            outcome = classify_probe_result(code, "auth", auth_required=False)
            self.assertEqual(outcome.verdict, "fail")

    def test_404_is_fail(self) -> None:
        # 404 on a declared endpoint means the route isn't wired up — that's a bug.
        outcome = classify_probe_result(404, "", auth_required=False)
        self.assertEqual(outcome.verdict, "fail")
        self.assertEqual(outcome.severity, "P1")

    def test_timeout_string_is_fail(self) -> None:
        outcome = classify_probe_result(None, "TIMEOUT", auth_required=False,
                                         transport_error="timeout")
        self.assertEqual(outcome.verdict, "fail")
        self.assertEqual(outcome.severity, "P1")

    def test_connection_refused_is_fail(self) -> None:
        outcome = classify_probe_result(None, "", auth_required=False,
                                         transport_error="connection_refused")
        self.assertEqual(outcome.verdict, "fail")
        self.assertEqual(outcome.severity, "P0")


if __name__ == "__main__":
    unittest.main()
