"""PROPOSAL #8 Tier-1a (slice 1): DeliveryGate report formatters extracted from
Orchestrator to runtime/delivery_gate.py. They are pure functions of the gate dict;
this pins their behavior + the Orchestrator shim delegation.
"""

import sys
import unittest
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.delivery_gate import (  # noqa: E402
    delivery_gate_suggestions, format_delivery_gate_report,
)


class FormatReportTests(unittest.TestCase):
    def test_passing_gate(self):
        out = format_delivery_gate_report(
            {"ok": True, "hub_counts": {"endpoints": 5, "implemented_endpoints": 5,
                                        "tables": 3, "implemented_tables": 3, "pages": 4}})
        self.assertIn("Delivery gate passed", out)
        self.assertIn("Endpoints: 5", out)

    def test_failing_gate_lists_checks_and_suggestions(self):
        out = format_delivery_gate_report(
            {"ok": False, "failed_checks": ["no_endpoints_in_hub", "frontend_build_not_recorded"]})
        self.assertIn("Delivery gate failed", out)
        self.assertIn("no_endpoints_in_hub", out)
        self.assertIn("Suggested fixes", out)

    def test_waiting_for_retry_state(self):
        out = format_delivery_gate_report({"ok": False, "state": "waiting_for_retry",
                                           "failed_checks": ["validation_retry_pending"]})
        self.assertIn("waiting for automatic retries", out)


class SuggestionsTests(unittest.TestCase):
    def test_maps_failed_checks_to_suggestions(self):
        s = delivery_gate_suggestions({"failed_checks": ["no_endpoints_in_hub"]})
        self.assertTrue(any("Register API endpoints" in x for x in s))

    def test_missing_files_and_dirs(self):
        s = delivery_gate_suggestions({"missing_files": ["docker/docker-compose.yml"],
                                       "missing_dirs": ["app/backend"]})
        self.assertTrue(any("docker-compose.yml" in x for x in s))
        self.assertTrue(any("app/backend" in x for x in s))

    def test_deduplicates_preserving_order(self):
        s = delivery_gate_suggestions({"missing_dirs": ["app/backend"],
                                       "failed_checks": ["backend_code_missing"]})
        # both map to the same backend suggestion → dedup to one
        backend = [x for x in s if "app/backend" in x]
        self.assertEqual(len(backend), 1)

    def test_empty_gate_no_suggestions(self):
        self.assertEqual(delivery_gate_suggestions({}), [])


class ShimDelegationTests(unittest.TestCase):
    def test_orchestrator_shims_delegate(self):
        # The Orchestrator shims must call through to the module functions.
        from multi_agent.orchestrator import Orchestrator
        stub = object.__new__(Orchestrator)
        gate = {"ok": False, "failed_checks": ["no_tables_in_hub"]}
        self.assertEqual(Orchestrator._format_delivery_gate_report(stub, gate),
                         format_delivery_gate_report(gate))
        self.assertEqual(Orchestrator._delivery_gate_suggestions(stub, gate),
                         delivery_gate_suggestions(gate))


if __name__ == "__main__":
    unittest.main()
