"""Tests for the Phase C M1 WorkHub meeting primitives.

Covers ``create_meeting``, ``add_meeting_decision``, ``close_meeting``
per ``docs/plan_kickoff_refactor.md`` §217-225 and
``docs/pipeline_supervision_charter.md`` §5.

Closed-by-construction:
    * Happy-path create -> add 2 decisions -> close.
    * Atomicity: 10 concurrent ``add_meeting_decision`` calls preserve
      all 10 decisions (the JsonStore update-lambda holds both an
      RLock and an fcntl file lock through the mutator, so the
      read-modify-write inside our ``_mutate`` closure is serialized).
    * Eventhub: ``close_meeting`` emits ``meeting_closed`` with
      ``produced_artifacts`` to a mocked publish_event.
"""
from __future__ import annotations

import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from multi_agent.runtime.hubs.workhub.service import WorkHub  # noqa: E402


def _hub(eventhub=None) -> WorkHub:
    tmp = tempfile.mkdtemp()
    return WorkHub(Path(tmp), eventhub=eventhub)


class TestMeetingHappyPath(unittest.TestCase):
    def test_create_add_decisions_close_cycle(self):
        """create_meeting -> 2x add_meeting_decision -> close_meeting end-state."""
        hub = _hub()
        meeting = hub.create_meeting(
            agenda="Kickoff M1: walking skeleton",
            attendees=["design", "backend", "frontend"],
            milestone_index=1,
            agent="orchestrator",
        )
        self.assertEqual(meeting["kind"], "kickoff")
        self.assertEqual(meeting["status"], "open")
        self.assertEqual(meeting["metadata"]["agenda"], "Kickoff M1: walking skeleton")
        self.assertEqual(meeting["metadata"]["attendees"], ["design", "backend", "frontend"])
        self.assertEqual(meeting["metadata"]["milestone_index"], 1)
        self.assertEqual(meeting["metadata"]["decisions"], [])
        self.assertEqual(meeting["metadata"]["produced_artifacts"], [])
        self.assertEqual(meeting["metadata"]["phase"], "open")
        self.assertEqual(meeting["created_by"], "orchestrator")

        meeting_id = meeting["id"]
        hub.add_meeting_decision(
            meeting_id,
            {"section": "contract", "chosen": "REST /users CRUD"},
            agent="backend",
        )
        hub.add_meeting_decision(
            meeting_id,
            {"section": "design", "chosen": "login + dashboard wireframes"},
            agent="design",
        )

        closed = hub.close_meeting(
            meeting_id,
            produced_artifacts=["plan_xyz", "page_design_1"],
            metadata_extra={"close_reason": "all 7 sections present"},
            agent="orchestrator",
        )
        self.assertEqual(closed["status"], "closed")
        self.assertEqual(closed["metadata"]["phase"], "closed")
        self.assertEqual(closed["metadata"]["produced_artifacts"], ["plan_xyz", "page_design_1"])
        self.assertEqual(closed["metadata"]["close_reason"], "all 7 sections present")
        self.assertEqual(closed["closed_by"], "orchestrator")
        self.assertIn("closed_at", closed)

        decisions = closed["metadata"]["decisions"]
        self.assertEqual(len(decisions), 2)
        sections = [d["section"] for d in decisions]
        self.assertEqual(sections, ["contract", "design"])
        # Identity stamping preserved
        self.assertEqual(decisions[0]["recorded_by"], "backend")
        self.assertEqual(decisions[1]["recorded_by"], "design")

    def test_create_meeting_attendees_invited(self):
        """create_meeting calls invite_attendee for each attendee."""
        hub = _hub()
        meeting = hub.create_meeting(
            agenda="kickoff",
            attendees=["design", "backend"],
            milestone_index=0,
            agent="orchestrator",
        )
        # Attendees become rows in stores.attendees keyed by meeting_id:agent_id
        attendees = hub.stores.attendees.value()
        keys = set(attendees.keys())
        self.assertIn(f"{meeting['id']}:design", keys)
        self.assertIn(f"{meeting['id']}:backend", keys)


class TestMeetingIdentityDiscipline(unittest.TestCase):
    """Per charter §no-back-compat: caller MUST inject identities;
    no phantom defaults — empty values raise ValueError."""

    def test_create_meeting_empty_agent_raises(self):
        hub = _hub()
        with self.assertRaises(ValueError):
            hub.create_meeting(agenda="x", attendees=["a"], milestone_index=0, agent="")

    def test_create_meeting_empty_agenda_raises(self):
        hub = _hub()
        with self.assertRaises(ValueError):
            hub.create_meeting(agenda="", attendees=["a"], milestone_index=0, agent="orchestrator")

    def test_create_meeting_empty_attendees_raises(self):
        hub = _hub()
        with self.assertRaises(ValueError):
            hub.create_meeting(agenda="x", attendees=[], milestone_index=0, agent="orchestrator")

    def test_create_meeting_missing_milestone_index_raises(self):
        """Round-7: milestone_index is a REQUIRED kwarg with no default.

        TypeError (missing required positional) is acceptable; a caller
        that forgets the anchor MUST be rejected — no orphan meetings.
        """
        hub = _hub()
        with self.assertRaises(TypeError):
            hub.create_meeting(agenda="x", attendees=["a"], agent="orch")

    def test_create_meeting_negative_milestone_index_raises(self):
        hub = _hub()
        with self.assertRaises(ValueError):
            hub.create_meeting(
                agenda="x", attendees=["a"], milestone_index=-1, agent="orch",
            )

    def test_create_meeting_non_int_milestone_index_raises(self):
        hub = _hub()
        with self.assertRaises(ValueError):
            hub.create_meeting(
                agenda="x", attendees=["a"], milestone_index="0", agent="orch",
            )

    def test_create_meeting_bool_milestone_index_raises(self):
        """A bool is technically an int subclass but is NOT a milestone."""
        hub = _hub()
        with self.assertRaises(ValueError):
            hub.create_meeting(
                agenda="x", attendees=["a"], milestone_index=True, agent="orch",
            )

    def test_add_meeting_decision_empty_agent_raises(self):
        hub = _hub()
        m = hub.create_meeting(agenda="x", attendees=["a"], milestone_index=0, agent="orchestrator")
        with self.assertRaises(ValueError):
            hub.add_meeting_decision(m["id"], {"section": "x"}, agent="")

    def test_add_meeting_decision_empty_decision_raises(self):
        hub = _hub()
        m = hub.create_meeting(agenda="x", attendees=["a"], milestone_index=0, agent="orchestrator")
        with self.assertRaises(ValueError):
            hub.add_meeting_decision(m["id"], {}, agent="design")

    def test_add_meeting_decision_unknown_meeting_returns_error(self):
        hub = _hub()
        result = hub.add_meeting_decision("page_missing", {"x": 1}, agent="design")
        self.assertIn("error", result)

    def test_add_meeting_decision_bad_milestone_index_raises(self):
        hub = _hub()
        m = hub.create_meeting(agenda="x", attendees=["a"], milestone_index=0, agent="orch")
        with self.assertRaises(ValueError):
            hub.add_meeting_decision(
                m["id"], {"section": "x"}, agent="design", milestone_index=-1,
            )

    def test_close_meeting_empty_agent_raises(self):
        hub = _hub()
        m = hub.create_meeting(agenda="x", attendees=["a"], milestone_index=0, agent="orchestrator")
        with self.assertRaises(ValueError):
            hub.close_meeting(m["id"], produced_artifacts=[], agent="")

    def test_close_meeting_non_list_artifacts_raises(self):
        hub = _hub()
        m = hub.create_meeting(agenda="x", attendees=["a"], milestone_index=0, agent="orchestrator")
        with self.assertRaises(ValueError):
            hub.close_meeting(m["id"], produced_artifacts="not_a_list", agent="orchestrator")

    def test_close_meeting_unknown_meeting_returns_error(self):
        hub = _hub()
        result = hub.close_meeting("page_missing", produced_artifacts=[], agent="orchestrator")
        self.assertIn("error", result)

    def test_close_meeting_bad_milestone_index_raises(self):
        hub = _hub()
        m = hub.create_meeting(agenda="x", attendees=["a"], milestone_index=0, agent="orch")
        with self.assertRaises(ValueError):
            hub.close_meeting(
                m["id"], produced_artifacts=[], agent="orch", milestone_index=-1,
            )


class TestMeetingAtomicity(unittest.TestCase):
    def test_10_concurrent_add_meeting_decision_preserves_all_10(self):
        """10 threads each appending a decision -> final state has all 10.

        The JsonStore.update() lambda holds an RLock + fcntl file lock
        through the mutator, so each thread's read-modify-write of
        metadata['decisions'] is serialized. Without that contract,
        last-writer-wins on the page dict would clobber concurrent
        appends. This guards against future regressions that move the
        list-append outside the lambda.
        """
        hub = _hub()
        meeting = hub.create_meeting(
            agenda="atomicity test",
            attendees=["a"],
            milestone_index=0,
            agent="orchestrator",
        )
        meeting_id = meeting["id"]

        errors: list = []
        barrier = threading.Barrier(10)

        def worker(idx: int) -> None:
            try:
                barrier.wait(timeout=5.0)
                hub.add_meeting_decision(
                    meeting_id,
                    {"section": "s", "idx": idx},
                    agent=f"agent_{idx}",
                )
            except Exception as exc:  # pragma: no cover - reported via errors list
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10.0)

        self.assertEqual(errors, [], f"worker errors: {errors}")
        final = hub.stores.pages.value()[meeting_id]
        decisions = final["metadata"]["decisions"]
        self.assertEqual(len(decisions), 10)
        indices = sorted(d["idx"] for d in decisions)
        self.assertEqual(indices, list(range(10)))

    def test_sequential_add_meeting_decision_independent_writes(self):
        """Sequential appends each preserve prior decisions (LWW-via-lambda)."""
        hub = _hub()
        meeting = hub.create_meeting(
            agenda="seq",
            attendees=["a"],
            milestone_index=0,
            agent="orchestrator",
        )
        mid = meeting["id"]
        for i in range(5):
            hub.add_meeting_decision(mid, {"idx": i}, agent=f"a{i}")
        page = hub.stores.pages.value()[mid]
        self.assertEqual([d["idx"] for d in page["metadata"]["decisions"]], [0, 1, 2, 3, 4])


class TestMeetingEventhubEmission(unittest.TestCase):
    def test_close_meeting_emits_meeting_closed_with_artifacts(self):
        """close_meeting calls eventhub.publish_event('workhub', 'meeting_closed', ...)
        with produced_artifacts in the payload and the meeting's attendees as recipients.
        """
        mock_eventhub = MagicMock()
        hub = _hub(eventhub=mock_eventhub)
        meeting = hub.create_meeting(
            agenda="evt test",
            attendees=["design", "backend"],
            milestone_index=2,
            agent="orchestrator",
        )
        mock_eventhub.reset_mock()  # ignore the meeting_created + attendee_invited calls

        hub.close_meeting(
            meeting["id"],
            produced_artifacts=["plan_a", "page_b"],
            agent="orchestrator",
        )

        close_calls = [
            c for c in mock_eventhub.publish_event.call_args_list
            if len(c.args) >= 2 and c.args[1] == "meeting_closed"
        ]
        self.assertEqual(len(close_calls), 1, f"expected exactly 1 meeting_closed emit; got: {mock_eventhub.publish_event.call_args_list}")
        call = close_calls[0]
        # Positional: source_hub, event_type, payload
        self.assertEqual(call.args[0], "workhub")
        self.assertEqual(call.args[1], "meeting_closed")
        payload = call.args[2]
        self.assertEqual(payload["meeting_id"], meeting["id"])
        self.assertEqual(payload["produced_artifacts"], ["plan_a", "page_b"])
        self.assertEqual(payload["page"]["status"], "closed")
        # recipients passed as kwarg
        self.assertEqual(sorted(call.kwargs.get("recipients", [])), ["backend", "design"])
        # Phase 4.1c caller tag
        self.assertEqual(call.kwargs.get("caller"), "workhub")

    def test_create_meeting_emits_meeting_created(self):
        mock_eventhub = MagicMock()
        hub = _hub(eventhub=mock_eventhub)
        meeting = hub.create_meeting(
            agenda="evt create test",
            attendees=["design"],
            milestone_index=3,
            agent="orchestrator",
        )
        created_calls = [
            c for c in mock_eventhub.publish_event.call_args_list
            if len(c.args) >= 2 and c.args[1] == "meeting_created"
        ]
        self.assertEqual(len(created_calls), 1)
        self.assertEqual(created_calls[0].args[2]["id"], meeting["id"])

    def test_add_meeting_decision_emits_event(self):
        mock_eventhub = MagicMock()
        hub = _hub(eventhub=mock_eventhub)
        meeting = hub.create_meeting(
            agenda="dec evt test",
            attendees=["design"],
            milestone_index=4,
            agent="orchestrator",
        )
        mock_eventhub.reset_mock()
        hub.add_meeting_decision(
            meeting["id"],
            {"section": "contract", "chosen": "REST"},
            agent="backend",
        )
        dec_calls = [
            c for c in mock_eventhub.publish_event.call_args_list
            if len(c.args) >= 2 and c.args[1] == "meeting_decision_added"
        ]
        self.assertEqual(len(dec_calls), 1)
        payload = dec_calls[0].args[2]
        self.assertEqual(payload["meeting_id"], meeting["id"])
        self.assertEqual(payload["decision"]["section"], "contract")
        self.assertEqual(payload["decision"]["recorded_by"], "backend")


class TestMeetingMilestoneIndexPersistence(unittest.TestCase):
    """Round-7: milestone_index threading through all 3 primitives."""

    def test_create_meeting_persists_milestone_index_in_metadata(self):
        """create_meeting embeds milestone_index in page.metadata."""
        hub = _hub()
        meeting = hub.create_meeting(
            agenda="x", attendees=["a"], milestone_index=7, agent="orch",
        )
        self.assertEqual(meeting["metadata"]["milestone_index"], 7)
        # And it round-trips through the store, not just the return value.
        from_store = hub.stores.pages.value()[meeting["id"]]
        self.assertEqual(from_store["metadata"]["milestone_index"], 7)

    def test_create_meeting_milestone_index_zero_is_valid(self):
        """milestone_index=0 (the first milestone) is a valid anchor."""
        hub = _hub()
        meeting = hub.create_meeting(
            agenda="x", attendees=["a"], milestone_index=0, agent="orch",
        )
        self.assertEqual(meeting["metadata"]["milestone_index"], 0)

    def test_create_meeting_caller_metadata_milestone_index_overridden(self):
        """The first-class kwarg WINS over a caller metadata key of the
        same name — single source of truth."""
        hub = _hub()
        meeting = hub.create_meeting(
            agenda="x",
            attendees=["a"],
            milestone_index=5,
            metadata={"milestone_index": 99, "other": "kept"},
            agent="orch",
        )
        self.assertEqual(meeting["metadata"]["milestone_index"], 5)
        self.assertEqual(meeting["metadata"]["other"], "kept")

    def test_add_meeting_decision_milestone_index_optional_omitted(self):
        """When milestone_index is omitted, the decision row has NO
        milestone_index key (caller chose to inherit the meeting's
        anchor)."""
        hub = _hub()
        m = hub.create_meeting(agenda="x", attendees=["a"], milestone_index=1, agent="orch")
        page = hub.add_meeting_decision(
            m["id"], {"section": "s"}, agent="design",
        )
        decision = page["metadata"]["decisions"][0]
        self.assertNotIn("milestone_index", decision)

    def test_add_meeting_decision_milestone_index_round_trip(self):
        """When provided, milestone_index is persisted on the decision row."""
        hub = _hub()
        m = hub.create_meeting(agenda="x", attendees=["a"], milestone_index=1, agent="orch")
        page = hub.add_meeting_decision(
            m["id"], {"section": "s"}, agent="design", milestone_index=2,
        )
        decision = page["metadata"]["decisions"][0]
        self.assertEqual(decision["milestone_index"], 2)
        # And round-trips through the store.
        from_store = hub.stores.pages.value()[m["id"]]
        self.assertEqual(
            from_store["metadata"]["decisions"][0]["milestone_index"], 2,
        )

    def test_close_meeting_milestone_index_optional_omitted(self):
        """Omitting milestone_index at close preserves whatever was
        already on the meeting's metadata."""
        hub = _hub()
        m = hub.create_meeting(agenda="x", attendees=["a"], milestone_index=3, agent="orch")
        closed = hub.close_meeting(m["id"], produced_artifacts=[], agent="orch")
        self.assertEqual(closed["metadata"]["milestone_index"], 3)

    def test_close_meeting_milestone_index_round_trip(self):
        """When provided at close, milestone_index overwrites the
        meeting's existing anchor (audit recovery path)."""
        hub = _hub()
        m = hub.create_meeting(agenda="x", attendees=["a"], milestone_index=3, agent="orch")
        closed = hub.close_meeting(
            m["id"], produced_artifacts=[], agent="orch", milestone_index=4,
        )
        self.assertEqual(closed["metadata"]["milestone_index"], 4)


class TestMeetingEventNamesNoKickoffComplete(unittest.TestCase):
    """Round-7 residue: close_meeting emits 'meeting_closed' NOT
    'kickoff_complete'. The latter is run_kickoff's responsibility
    (round 7b), not the bare close_meeting primitive."""

    def test_close_meeting_never_emits_kickoff_complete(self):
        mock_eventhub = MagicMock()
        hub = _hub(eventhub=mock_eventhub)
        meeting = hub.create_meeting(
            agenda="x", attendees=["a"], milestone_index=0, agent="orch",
        )
        mock_eventhub.reset_mock()
        hub.close_meeting(meeting["id"], produced_artifacts=[], agent="orch")
        kickoff_complete_calls = [
            c for c in mock_eventhub.publish_event.call_args_list
            if len(c.args) >= 2 and c.args[1] == "kickoff_complete"
        ]
        self.assertEqual(
            kickoff_complete_calls,
            [],
            "close_meeting MUST NOT emit kickoff_complete — that is run_kickoff's job",
        )


if __name__ == "__main__":
    unittest.main()
