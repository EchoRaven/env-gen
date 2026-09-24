"""Edge cases surfaced by walking the orchestrator → design → backend →
verifier flow with adversarial assumptions:

  * Committed-but-unregistered code (self-audit must catch even when
    dirty_files is empty because the agent already committed).
  * Pending consumer waits forever (must be surfaced when stale).
  * Spec changed after implementation (provider + consumers re-notified).
  * Clock skew / bogus timestamps must not flag fresh tasks as stale.
"""

from __future__ import annotations

import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from multi_agent.runtime.agent_subscriptions import (  # noqa: E402
    DEFAULT_SUBSCRIPTIONS, ensure_default_subscriptions,
)


class PendingConsumerStaleness(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="pending_stale_"))
        self.hubs = HubRegistry(self.tmp)

    def test_fresh_pending_consumer_not_stale(self) -> None:
        # Queue a pending consumer (no endpoint yet).
        self.hubs.registryhub.register_consumer(
            "GET /api/posts", "src/api/posts.ts", "frontend", pending=True,
        )
        self.assertEqual(
            self.hubs.registryhub.list_stale_pending_consumers(ttl_seconds=1800),
            [],
        )

    def test_old_pending_consumer_is_stale(self) -> None:
        self.hubs.registryhub.register_consumer(
            "GET /api/posts", "src/api/posts.ts", "frontend", pending=True,
        )
        future = time.time() + 5000.0
        stale = self.hubs.registryhub.list_stale_pending_consumers(
            ttl_seconds=1800, now_ts=future,
        )
        self.assertEqual(len(stale), 1)
        self.assertEqual(stale[0]["endpoint_id"], "GET /api/posts")
        self.assertGreaterEqual(stale[0]["age_seconds"], 1800)

    def test_promoted_consumer_removed_from_pending(self) -> None:
        """Once the producer registers the endpoint, the pending entry
        flushes — it should no longer appear in list_pending_consumers."""
        self.hubs.registryhub.register_consumer(
            "GET /api/posts", "src/api/posts.ts", "frontend", pending=True,
        )
        self.assertEqual(len(self.hubs.registryhub.list_pending_consumers()), 1)
        self.hubs.registryhub.register_endpoint(
            "GET", "/api/posts", schema={"response": {"posts": []}},
            provider="backend", agent="backend", status="defined",
        )
        self.assertEqual(self.hubs.registryhub.list_pending_consumers(), [])

    def test_zero_or_negative_queued_at_skipped(self) -> None:
        """Malformed entry (queued_at == 0) must not show up as ancient."""
        # Inject a malformed pending entry directly.
        bad = {
            "id": "bad", "endpoint_id": "GET /x",
            "file_path": "f", "agent": "frontend",
            "metadata": {}, "queued_at": 0.0,
        }
        self.hubs.registryhub._pending_consumers.update(
            lambda m: m.set("bad", bad, "test"),
            change_info={"agent": "test"},
        )
        future = time.time() + 99999.0
        self.assertEqual(
            self.hubs.registryhub.list_stale_pending_consumers(now_ts=future),
            [],
        )


class EndpointSchemaChangedEvent(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="schema_changed_"))
        self.hubs = HubRegistry(self.tmp)

    def test_re_register_implemented_endpoint_with_new_schema_emits_event(self) -> None:
        # Backend implements the endpoint.
        self.hubs.registryhub.register_endpoint(
            "POST", "/api/posts",
            schema={"response": {"id": "string", "title": "string"}},
            provider="backend", agent="backend", status="implemented",
        )
        # Design later changes the response shape.
        self.hubs.registryhub.register_endpoint(
            "POST", "/api/posts",
            schema={"response": {"id": "string", "title": "string", "slug": "string"}},
            provider="backend", agent="backend", status="implemented",
        )
        # Look for endpoint_schema_changed event in eventhub.
        # eventhub doesn't have a global "list_all" public, but events
        # are stored — walk inboxes / events store.
        events = list(self.hubs.eventhub._events.value().values())
        schema_changes = [e for e in events if e.get("event_type") == "endpoint_schema_changed"]
        self.assertEqual(len(schema_changes), 1,
                          "Re-registering an implemented endpoint with a "
                          "different schema must emit endpoint_schema_changed")
        self.assertIn("backend", schema_changes[0].get("recipients") or [],
                       "Provider (backend) must be a recipient of schema-change")

    def test_no_schema_change_event_when_schema_identical(self) -> None:
        self.hubs.registryhub.register_endpoint(
            "POST", "/api/posts",
            schema={"response": {"id": "string"}},
            provider="backend", agent="backend", status="implemented",
        )
        # Re-register identical
        self.hubs.registryhub.register_endpoint(
            "POST", "/api/posts",
            schema={"response": {"id": "string"}},
            provider="backend", agent="backend", status="implemented",
        )
        events = list(self.hubs.eventhub._events.value().values())
        self.assertEqual(
            [e for e in events if e.get("event_type") == "endpoint_schema_changed"],
            [],
        )

    def test_default_subscriptions_include_schema_changed(self) -> None:
        backend_types = {(s[0], s[1]) for s in DEFAULT_SUBSCRIPTIONS["backend"]}
        self.assertIn(("registryhub", "endpoint_schema_changed"), backend_types)
        frontend_types = {(s[0], s[1]) for s in DEFAULT_SUBSCRIPTIONS["frontend"]}
        self.assertIn(("registryhub", "endpoint_schema_changed"), frontend_types)


class StaleTaskClockSkewDefense(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="skew_"))
        self.hubs = HubRegistry(self.tmp)

    def test_zero_created_at_not_flagged(self) -> None:
        """A task whose created_at is 0 (malformed) must not appear as
        an ancient stale task."""
        t = self.hubs.workhub.create_task(
            title="x", assignee="design", agent="orchestrator",
        )
        # Corrupt the timestamp.
        tasks = self.hubs.workhub.stores.tasks.value()
        tasks[t["id"]]["created_at"] = 0.0
        self.hubs.workhub.stores.tasks.update(
            lambda m: m.set(t["id"], tasks[t["id"]], "test"),
            change_info={"agent": "test"},
        )
        future = time.time() + 99999.0
        self.assertEqual(
            self.hubs.workhub.list_stale_tasks(now_ts=future),
            [],
        )

    def test_future_created_at_not_flagged(self) -> None:
        """Clock skew sometimes lands a created_at in the future. Negative
        age must not trigger staleness."""
        t = self.hubs.workhub.create_task(
            title="x", assignee="design", agent="orchestrator",
        )
        tasks = self.hubs.workhub.stores.tasks.value()
        tasks[t["id"]]["created_at"] = time.time() + 99999.0  # year in future
        self.hubs.workhub.stores.tasks.update(
            lambda m: m.set(t["id"], tasks[t["id"]], "test"),
            change_info={"agent": "test"},
        )
        self.assertEqual(self.hubs.workhub.list_stale_tasks(), [])


class RegistryHubRequestReviewLifecycleGate(unittest.TestCase):
    """Hard lifecycle rule: implementation agents (backend, frontend,
    database, verifier) start AFTER design completes. Design must NOT
    be able to invite them as reviewers before they exist — those
    requests land in dead inboxes."""

    def setUp(self) -> None:
        import tempfile as _t
        from pathlib import Path as _P
        self.tmp = _P(_t.mkdtemp(prefix="apirev_live_"))
        self.hubs = HubRegistry(self.tmp)
        # Register one real endpoint so the endpoint-exists check passes.
        self.hubs.registryhub.register_endpoint(
            "POST", "/api/posts", schema={}, provider="backend", agent="backend",
        )

    def test_default_no_provider_passes_through(self):
        """With no provider attached (test bootstrap), the gate is a
        no-op — endpoint existence is still validated, reviewer
        liveness is not."""
        res = self.hubs.registryhub.request_api_review(
            endpoint_id="POST /api/posts",
            reviewers=["backend", "frontend"],
            agent="design",
        )
        self.assertNotIn("error", res)

    def test_provider_rejects_unspawned_reviewer(self):
        """During design phase only orchestrator/design/verifier/knowledge
        are alive (post-roster-reduction). Inviting backend must fail."""
        self.hubs.attach_live_agents_provider(
            lambda: ["orchestrator", "design", "verifier", "knowledge"]
        )
        res = self.hubs.registryhub.request_api_review(
            endpoint_id="POST /api/posts",
            reviewers=["backend"], agent="design",
        )
        self.assertIn("error", res)
        self.assertIn("not currently running", res["error"])
        self.assertIn("backend", res["error"])

    def test_provider_accepts_live_reviewer(self):
        self.hubs.attach_live_agents_provider(
            lambda: ["orchestrator", "design", "verifier"]
        )
        res = self.hubs.registryhub.request_api_review(
            endpoint_id="POST /api/posts",
            reviewers=["verifier"], agent="design",
            reason="design-time approval",
        )
        self.assertNotIn("error", res)
        self.assertEqual(res["status"], "pending")

    def test_provider_with_mixed_reviewers_reports_only_missing(self):
        self.hubs.attach_live_agents_provider(
            lambda: ["orchestrator", "design", "verifier"]
        )
        res = self.hubs.registryhub.request_api_review(
            endpoint_id="POST /api/posts",
            reviewers=["verifier", "backend", "frontend"],
            agent="design",
        )
        self.assertIn("error", res)
        # error lists the dead ones, not the live one
        self.assertIn("backend", res["error"])
        self.assertIn("frontend", res["error"])
        self.assertNotIn("'verifier'", res["error"].split("Currently")[0])

    def test_provider_callable_raising_falls_back_safe(self):
        def boom():
            raise RuntimeError("agent_manager unavailable")
        self.hubs.attach_live_agents_provider(boom)
        # A broken provider must not block the call — degrade to "no liveness check".
        res = self.hubs.registryhub.request_api_review(
            endpoint_id="POST /api/posts",
            reviewers=["backend"], agent="design",
        )
        self.assertNotIn("error", res)


class RegistryHubRequestReviewValidation(unittest.TestCase):
    """request_api_review must reject unknown endpoints. The live
    Facebook smoke run showed design poisoning the registryhub_reviews store
    with rows for ``placeholder``, ``placeholder2``, ``placeholder3``,
    ``placeholder_cleanup_a/b/c/d``, ``users`` (no endpoint registered)
    — backend / frontend received high-priority review requests for
    non-existent endpoints. Hard validation here turns the bad call
    into a clear error instead of a silent fan-out."""

    def setUp(self) -> None:
        import tempfile as _t
        from pathlib import Path as _P
        self.tmp = _P(_t.mkdtemp(prefix="apirev_"))
        self.hubs = HubRegistry(self.tmp)

    def test_request_review_for_unregistered_endpoint_errors(self) -> None:
        res = self.hubs.registryhub.request_api_review(
            endpoint_id="placeholder",
            reviewers=["backend"],
            agent="design",
            reason="design done",
        )
        self.assertIn("error", res)
        self.assertIn("unknown endpoint_id", res["error"])
        self.assertIn("kickoff meeting", res["error"],
                       "Error should point operators at the orchestrator-hosted "
                       "kickoff meeting for design-phase approval")

    def test_request_review_with_empty_endpoint_id_errors(self) -> None:
        res = self.hubs.registryhub.request_api_review(
            endpoint_id="  ", reviewers=["backend"], agent="design",
        )
        self.assertIn("error", res)

    def test_request_review_with_empty_reviewers_errors(self) -> None:
        self.hubs.registryhub.register_endpoint(
            "GET", "/api/feed", schema={}, provider="backend", agent="backend",
        )
        res = self.hubs.registryhub.request_api_review(
            endpoint_id="GET /api/feed",
            reviewers=[], agent="design",
        )
        self.assertIn("error", res)

    def test_request_review_for_registered_endpoint_succeeds(self) -> None:
        self.hubs.registryhub.register_endpoint(
            "GET", "/api/feed", schema={}, provider="backend", agent="backend",
        )
        res = self.hubs.registryhub.request_api_review(
            endpoint_id="GET /api/feed",
            reviewers=["frontend"], agent="design",
            reason="review the contract",
        )
        self.assertNotIn("error", res)
        self.assertEqual(res["status"], "pending")
        self.assertIn("frontend", res["reviewers"])


if __name__ == "__main__":
    unittest.main()
