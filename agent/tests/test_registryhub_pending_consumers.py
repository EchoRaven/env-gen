"""Pending consumer queue + auto-promotion + endpoint_implemented urgent
notification. Closes Bug-3 (no "I'm waiting on your endpoint" signal)
and Bug-6 (register_consumer rejected before endpoint exists)."""
from __future__ import annotations

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

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


class TestPendingConsumerFlow(unittest.TestCase):
    def test_register_consumer_pending_when_endpoint_missing(self):
        """``pending=True`` queues instead of rejecting."""
        with tempfile.TemporaryDirectory() as tmp:
            reg = HubRegistry(Path(tmp), project_id="p", project_name="P")
            result = reg.registryhub.register_consumer(
                endpoint_id="GET /api/users",
                file_path="app/backend/src/routes/posts.js",
                agent="backend",
                pending=True,
            )
            self.assertEqual(result.get("status"), "pending")
            self.assertEqual(result.get("queued_for"), "backend")
            # Pending store carries the entry.
            queued = reg.registryhub._pending_consumers.value()
            keys = [k for k in queued.keys() if not str(k).startswith("_")]
            self.assertEqual(len(keys), 1)

    def test_register_consumer_without_pending_still_rejects(self):
        """Default behaviour unchanged — backward compat."""
        with tempfile.TemporaryDirectory() as tmp:
            reg = HubRegistry(Path(tmp), project_id="p", project_name="P")
            result = reg.registryhub.register_consumer(
                endpoint_id="GET /api/users",
                file_path="x",
                agent="backend",
            )
            self.assertEqual(result.get("error"), "endpoint_not_registered")

    def test_pending_promoted_on_endpoint_registration(self):
        """When the producer registers the endpoint, the queued consumer
        is auto-promoted to a real consumer and the requesting agent
        receives an ``endpoint_implemented`` urgent event."""
        with tempfile.TemporaryDirectory() as tmp:
            reg = HubRegistry(Path(tmp), project_id="p", project_name="P")
            # Backend queues consumer intent first.
            reg.registryhub.register_consumer(
                endpoint_id="GET /api/users",
                file_path="app/backend/src/routes/posts.js",
                agent="backend",
                pending=True,
            )

            # Backend registers the endpoint as implemented.
            reg.registryhub.register_endpoint(
                method="GET",
                path="/api/users",
                schema={"response": {"items": []}},
                provider="backend",
                agent="backend",
                status="implemented",
            )

            # Pending queue should be empty for this endpoint.
            queued = reg.registryhub._pending_consumers.value()
            remaining = [
                v for v in queued.values()
                if isinstance(v, dict) and v.get("endpoint_id") == "GET /api/users"
            ]
            self.assertEqual(len(remaining), 0,
                             "pending consumer not flushed after endpoint registered")

            # Consumer is now a real consumer.
            real = reg.registryhub.get_consumers("GET /api/users")
            self.assertEqual(len(real), 1)
            self.assertEqual(real[0]["agent"], "backend")

            # And backend received an urgent endpoint_implemented event.
            backend_inbox = reg.eventhub.list_inbox("backend", unread_only=False)
            implemented_events = [
                e for e in backend_inbox
                if e.get("event_type") == "endpoint_implemented"
            ]
            self.assertEqual(len(implemented_events), 1,
                             f"backend inbox missing endpoint_implemented event; "
                             f"got: {[e.get('event_type') for e in backend_inbox]}")
            payload = implemented_events[0].get("payload", {})
            self.assertEqual(payload.get("path"), "/api/users")
            self.assertEqual(payload.get("status"), "implemented")

    def test_endpoint_defined_event_fires_separately_from_implemented(self):
        """Status transition matters: ``endpoint_defined`` for initial
        declaration; ``endpoint_implemented`` for the implemented
        transition. Same endpoint going defined→implemented fires both
        in sequence (but only the implemented one is urgent)."""
        with tempfile.TemporaryDirectory() as tmp:
            reg = HubRegistry(Path(tmp), project_id="p", project_name="P")
            reg.registryhub.register_endpoint(
                method="POST", path="/api/things", schema={},
                provider="backend", agent="backend", status="defined",
            )
            # Initial declaration → endpoint_defined.
            store = reg.eventhub._events.value()
            defined = [e for e in store.values()
                       if e.get("event_type") == "endpoint_defined"
                       and e.get("payload", {}).get("path") == "/api/things"]
            self.assertEqual(len(defined), 1,
                             f"expected 1 endpoint_defined event, got {len(defined)}")

            # Transition to implemented → endpoint_implemented.
            reg.registryhub.register_endpoint(
                method="POST", path="/api/things", schema={},
                provider="backend", agent="backend", status="implemented",
            )
            store = reg.eventhub._events.value()
            implemented = [e for e in store.values()
                           if e.get("event_type") == "endpoint_implemented"
                           and e.get("payload", {}).get("path") == "/api/things"]
            self.assertEqual(len(implemented), 1,
                             f"expected 1 endpoint_implemented event, got {len(implemented)}")


if __name__ == "__main__":
    unittest.main()
