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


class BreakingChangeCreatesTaskTests(unittest.TestCase):
    def test_breaking_change_auto_creates_workhub_task_per_consumer(self):
        with tempfile.TemporaryDirectory() as td:
            ws = HubRegistry(Path(td))
            hubs = ws.hubs

            # backend publishes the endpoint, frontend registers as consumer
            hubs.registryhub.register_endpoint(
                "GET", "/api/feed",
                schema={"response": {"posts": [], "total": 0}},
                provider="backend", agent="backend",
            )
            hubs.registryhub.register_consumer(
                "GET /api/feed", "app/frontend/src/services/api.js", "frontend",
            )

            # backend pushes a breaking schema change
            hubs.registryhub.update_schema(
                "GET /api/feed",
                response={"items": []},   # removes `posts` and `total`
                agent="backend",
            )

            # there must be at least one WorkHub task whose assignee is the affected consumer
            tasks = list(hubs.workhub.snapshot()["tasks"].values())
            fix_tasks = [
                t for t in tasks
                if t.get("assignee") == "frontend"
                and t.get("metadata", {}).get("source") == "registryhub_breaking_change"
                and "GET /api/feed" in (t.get("metadata", {}).get("linked_apis") or [])
            ]
            self.assertEqual(len(fix_tasks), 1, f"expected exactly one frontend fix task, got: {fix_tasks}")
            task = fix_tasks[0]
            self.assertIn("/api/feed", task["title"])
            self.assertEqual(task["status"], "pending")


if __name__ == "__main__":
    unittest.main()


class ABreakingChangeThatReachesNoOneSaysSo1203p4(unittest.TestCase):
    """#1203p4: with no registered consumer, BOTH halves above are no-ops.

    The urgent event goes to an empty recipient list and the per-consumer fix-task loop never
    runs, so a breaking change to a business endpoint passed in complete silence. MEASURED over
    102 runs: 1,887 of 20,970 urgent events have empty `recipients` and every one is this event
    type -- 47% of the corpus's 4,043 `breaking_change_detected` events. Not a spelling
    mismatch: normalising the `/api` prefix on both sides recovers 1 of the 1,887.
    """

    def _break_without_consumer(self, td):
        ws = HubRegistry(Path(td))
        hubs = ws.hubs
        hubs.registryhub.register_endpoint(
            "GET", "/api/feed",
            schema={"response": {"posts": [], "total": 0}},
            provider="backend", agent="backend",
        )
        # NO register_consumer call -- this is the measured case
        hubs.registryhub.update_schema(
            "GET /api/feed", response={"items": []}, agent="backend")
        return hubs

    def test_it_says_the_alert_reached_no_one(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertLogs("multi_agent.runtime.registryhub", level="WARNING") as cap:
                self._break_without_consumer(td)
        said = [r.getMessage() for r in cap.records if "1203p4" in r.getMessage()]
        self.assertEqual(len(said), 1, said)
        self.assertIn("GET /api/feed", said[0])
        self.assertIn("reached NO ONE", said[0])
        self.assertIn("apis_used", said[0],
                      "the actionable half -- where the consumer record comes from -- is missing")

    def test_it_says_how_many_consumers_the_registry_holds(self):
        """So a reader can tell "none registered at all" from "this one endpoint is missing"."""
        with tempfile.TemporaryDirectory() as td:
            with self.assertLogs("multi_agent.runtime.registryhub", level="WARNING") as cap:
                self._break_without_consumer(td)
        said = [r.getMessage() for r in cap.records if "1203p4" in r.getMessage()][0]
        self.assertIn("0 consumer record(s)", said, said)

    def test_a_second_break_on_the_same_endpoint_is_not_repeated(self):
        """#1202bn's number is why: 549 of 2220 breaking tasks are verbatim duplicates."""
        with tempfile.TemporaryDirectory() as td:
            hubs = self._break_without_consumer(td)
            with self.assertLogs("multi_agent.runtime.registryhub", level="WARNING") as cap:
                hubs.registryhub.update_schema(
                    "GET /api/feed", response={"other": []}, agent="backend")
                # keep assertLogs happy even when nothing is emitted
                import logging
                logging.getLogger("multi_agent.runtime.registryhub").warning("probe")
        self.assertEqual([r.getMessage() for r in cap.records if "1203p4" in r.getMessage()], [])

    def test_the_dedupe_set_belongs_to_the_registry_not_the_module(self):
        """#1202gz's own reason: "A module global also leaks between tests", and a new
        HubRegistry is a new run and must start clean."""
        with tempfile.TemporaryDirectory() as td1:
            self._break_without_consumer(td1)
        with tempfile.TemporaryDirectory() as td2:
            with self.assertLogs("multi_agent.runtime.registryhub", level="WARNING") as cap:
                self._break_without_consumer(td2)
        said = [r.getMessage() for r in cap.records if "1203p4" in r.getMessage()]
        self.assertEqual(len(said), 1, "a fresh registry must speak again: %r" % said)

    def test_a_registered_consumer_silences_it(self):
        with tempfile.TemporaryDirectory() as td:
            ws = HubRegistry(Path(td))
            hubs = ws.hubs
            hubs.registryhub.register_endpoint(
                "GET", "/api/feed",
                schema={"response": {"posts": [], "total": 0}},
                provider="backend", agent="backend")
            hubs.registryhub.register_consumer(
                "GET /api/feed", "app/frontend/src/services/api.js", "frontend")
            with self.assertLogs("multi_agent.runtime.registryhub", level="WARNING") as cap:
                hubs.registryhub.update_schema(
                    "GET /api/feed", response={"items": []}, agent="backend")
                import logging
                logging.getLogger("multi_agent.runtime.registryhub").warning("probe")
        self.assertEqual([r.getMessage() for r in cap.records if "1203p4" in r.getMessage()], [])


class TheNoConsumerLineIsFalsifiable1203p4(unittest.TestCase):
    """Mutation said why these exist: with the registry EMPTY the count is 0 either way, and
    nothing drove the `except`. Both branches needed a case that violates them."""

    def test_the_count_is_the_registrys_not_a_constant(self):
        """A consumer for a DIFFERENT endpoint makes the number load-bearing: "1 record, none
        for this one" is a different fact from "nothing is registered at all"."""
        with tempfile.TemporaryDirectory() as td:
            ws = HubRegistry(Path(td))
            hubs = ws.hubs
            for m, path in (("GET", "/api/feed"), ("GET", "/api/other")):
                hubs.registryhub.register_endpoint(
                    m, path, schema={"response": {"posts": [], "total": 0}},
                    provider="backend", agent="backend")
            hubs.registryhub.register_consumer(
                "GET /api/other", "app/frontend/src/services/api.js", "frontend")
            with self.assertLogs("multi_agent.runtime.registryhub", level="WARNING") as cap:
                hubs.registryhub.update_schema(
                    "GET /api/feed", response={"items": []}, agent="backend")
        said = [r.getMessage() for r in cap.records if "1203p4" in r.getMessage()]
        self.assertEqual(len(said), 1, said)
        self.assertIn("1 consumer record(s)", said[0], said[0])

    def test_it_names_where_a_consumer_record_comes_from(self):
        """The line is only actionable if it says the registration is derived from a page's
        declared API list -- that is the thing the lane has to go and fix."""
        with tempfile.TemporaryDirectory() as td:
            ws = HubRegistry(Path(td))
            hubs = ws.hubs
            hubs.registryhub.register_endpoint(
                "GET", "/api/feed", schema={"response": {"posts": []}},
                provider="backend", agent="backend")
            with self.assertLogs("multi_agent.runtime.registryhub", level="WARNING") as cap:
                hubs.registryhub.update_schema(
                    "GET /api/feed", response={"items": []}, agent="backend")
        said = [r.getMessage() for r in cap.records if "1203p4" in r.getMessage()][0]
        self.assertIn("auto-registered from a page", said, said)
        self.assertIn("apis_used", said, said)

    def test_the_failure_path_says_why_rather_than_going_quiet(self):
        """#1202ah. The consumer store is the cheapest injection point: a hostile `.value()`
        makes the guarded block raise deterministically."""
        from multi_agent.runtime import message_format as MF
        MF._WARNED_1201.discard("registryhub.no_consumer_1203p4")
        with tempfile.TemporaryDirectory() as td:
            ws = HubRegistry(Path(td))
            hubs = ws.hubs
            rh = hubs.registryhub
            rh.register_endpoint("GET", "/api/feed", schema={"response": {"posts": []}},
                                 provider="backend", agent="backend")

            class _Hostile:
                """Succeeds on the FIRST read and fails on the second.

                The consumer list is built OUTSIDE #1203p4's try (that is what makes
                `recipient_agents` empty), so a store that raises immediately never reaches
                the guarded block -- it just propagates out of `update_schema`. That is how
                the first version of this test failed, and it is the honest shape: the
                injection point has to be the read INSIDE the guard.
                """
                def __init__(self, real): self._real, self._n = real, 0
                def __getattr__(self, n): return getattr(self._real, n)
                def value(self):
                    self._n += 1
                    if self._n > 1:
                        raise RuntimeError("consumer store unreadable")
                    return self._real.value()

            real = rh._consumers
            # the breaking-change path reads it twice: once for the consumer list (needs the
            # real store so `recipient_agents` is empty) and once inside the #1203p4 line.
            with self.assertLogs(level="WARNING") as cap:
                rh._consumers = _Hostile(real)
                try:
                    rh.update_schema("GET /api/feed", response={"items": []}, agent="backend")
                finally:
                    rh._consumers = real
        msgs = [r.getMessage() for r in cap.records]
        self.assertTrue(any("1201" in m or "reached no consumer" in m for m in msgs),
                        "nothing was announced: %r" % msgs)
