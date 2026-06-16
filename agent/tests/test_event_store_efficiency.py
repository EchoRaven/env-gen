"""Guard tests for the event-store efficiency changes (#4, #5, #6).

These pin three append-only / O(n^2) bloat fixes in the EventHub /
RegistryHub runtime so they can't silently regress:

  #4 contract-test records upsert by endpoint_id and only emit
     ``api_test_recorded`` when the verdict actually changes.
  #5 the agent_status heartbeat persists a small summary, NOT the full
     step_trace.
  #6 the events store is bounded: publishing past the cap evicts the
     oldest non-pinned events.
"""

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


class TestContractTestUpsert(unittest.TestCase):
    """#4: upsert by endpoint_id + emit only on verdict change."""

    def setUp(self):
        from multi_agent.runtime.hub_registry import HubRegistry
        self._td = tempfile.mkdtemp()
        self.hubs = HubRegistry(Path(self._td))
        self.reg = self.hubs.registryhub
        self.eventhub = self.hubs.eventhub

    def _emits(self):
        return self.eventhub.list_events_by_type("api_test_recorded")

    def test_identical_reverdict_is_one_row_and_one_emit(self):
        ep = "GET /api/items"
        # First record: a row + one emit.
        self.reg.record_api_test(
            ep, result={"passed": True, "status_code": 200}, agent="verifier",
        )
        # Re-record the SAME verdict twice more (the bloat case).
        self.reg.record_api_test(
            ep, result={"passed": True, "status_code": 200}, agent="verifier",
        )
        self.reg.record_api_test(
            ep, result={"passed": True, "status_code": 200}, agent="verifier",
        )

        rows = self.reg.get_contract_test_results(ep)
        self.assertEqual(len(rows), 1, "identical re-records must upsert to ONE row")
        self.assertEqual(len(self._emits()), 1, "identical re-records must emit ONCE")

    def test_changed_verdict_yields_second_emit(self):
        ep = "GET /api/items"
        self.reg.record_api_test(
            ep, result={"passed": True, "status_code": 200}, agent="verifier",
        )
        # Verdict flips pass -> fail: a second emit, still one row.
        self.reg.record_api_test(
            ep, result={"passed": False, "status_code": 500}, agent="verifier",
        )
        rows = self.reg.get_contract_test_results(ep)
        self.assertEqual(len(rows), 1, "still one current row per endpoint")
        self.assertEqual(rows[0]["verdict"], "fail", "latest verdict wins")
        self.assertEqual(len(self._emits()), 2, "a changed verdict must emit again")


class TestAgentStatusHeartbeatNoFullTrace(unittest.TestCase):
    """#5: persisted agent_status payload carries a summary, not the trace."""

    def test_summary_keeps_full_step_trace_out_of_payload(self):
        from multi_agent.agents.runtime.step_pipeline.helpers import (
            _summarize_step_trace,
        )

        # A realistic, large step_trace as built by the step runner.
        step_trace = {
            "step": 7,
            "mode_before": "direct",
            "mode_after": "direct",
            "stages": {
                f"stage_{i}": {
                    "executed": (i % 2 == 0),
                    "duration_ms": 1234,
                    "metadata": {"blob": "x" * 2000},
                }
                for i in range(20)
            },
        }

        summary = _summarize_step_trace(step_trace)

        # The summary is small and does NOT contain the heavy stage payloads.
        self.assertNotIn("stages", summary)
        self.assertEqual(summary["step"], 7)
        self.assertEqual(summary["stage_count"], 20)
        self.assertEqual(summary["executed_stage_count"], 10)
        # Bounded: a handful of scalar keys, not the nested trace.
        import json
        self.assertLess(len(json.dumps(summary)), 500)
        self.assertNotIn("blob", json.dumps(summary))


class TestEventStoreRetentionCap(unittest.TestCase):
    """#6: bounded ring-buffer retention on the events store."""

    def setUp(self):
        from multi_agent.runtime.hub_registry import HubRegistry
        self._td = tempfile.mkdtemp()
        self.hubs = HubRegistry(Path(self._td))
        self.eventhub = self.hubs.eventhub

    def test_publishing_past_cap_evicts_oldest_keeps_newest(self):
        import multi_agent.runtime.eventhub as eh

        cap = 20
        orig = eh._events_retention_cap
        eh._events_retention_cap = lambda: cap
        try:
            for i in range(cap + 15):
                self.eventhub.publish_event(
                    source_hub="eventhub",
                    event_type="noise",
                    payload={"i": i},
                    recipients=[],
                )
            events = list(self.eventhub._events.value().values())
            self.assertLessEqual(len(events), cap, "store must stay <= cap")

            payload_is = {e["payload"]["i"] for e in events}
            # Newest retained, oldest evicted.
            self.assertIn(cap + 14, payload_is)
            self.assertNotIn(0, payload_is)
        finally:
            eh._events_retention_cap = orig

    def test_pinned_events_are_never_evicted(self):
        import multi_agent.runtime.eventhub as eh

        cap = 10
        orig = eh._events_retention_cap
        eh._events_retention_cap = lambda: cap
        try:
            # Pin the very first event.
            self.eventhub.publish_event(
                source_hub="eventhub",
                event_type="anchor",
                payload={"i": -1, "pinned": True},
                recipients=[],
            )
            for i in range(cap + 20):
                self.eventhub.publish_event(
                    source_hub="eventhub",
                    event_type="noise",
                    payload={"i": i},
                    recipients=[],
                )
            events = list(self.eventhub._events.value().values())
            self.assertLessEqual(len(events), cap)
            pinned = [e for e in events if (e.get("payload") or {}).get("pinned")]
            self.assertEqual(len(pinned), 1, "pinned event must survive eviction")
        finally:
            eh._events_retention_cap = orig


if __name__ == "__main__":
    unittest.main()
