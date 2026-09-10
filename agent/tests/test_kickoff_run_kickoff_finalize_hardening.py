"""Regression tests for finalize_kickoff partial-failure hardening.

Reviewer round-7b NEW residue #2: finalize_kickoff must

  1. progress the meeting through a phase state machine
     (open -> finalizing -> finalized OR partial_failure),
  2. wrap every hub write in try/except + inspect error-dict returns
     (workhub.create_task returns {"error": ...} on bad input),
  3. NOT emit ``kickoff_complete`` and NOT close the meeting when a
     mid-stream write fails,
  4. be safely re-callable — a second call after a successful
     ``finalized`` short-circuits, a second call after a
     ``partial_failure`` resumes the remaining writes.

Each test pins exactly one invariant the docstring promises. The
mock hubs fixture wires ``add_meeting_decision`` into the same
``decisions`` list that ``get_meeting_decisions`` reads back so the
phase state machine works end-to-end without booting workhub.
"""
from __future__ import annotations

import sys
import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from multi_agent.runtime.kickoff.run_kickoff import (  # noqa: E402
    finalize_kickoff,
    try_synthesize,
)
# #1202kj: load the sibling BY PATH, not as `tests.test_kickoff_run_kickoff`.
#
# `agent/tests/` is not a package, so that import only resolved through a namespace package
# rooted at whatever happened to be on sys.path first — and any test file that puts
# `.../multi_agent` ahead of `agent/` (it has its own `tests/` package) redirected `tests` there
# and this module failed to COLLECT, which pytest turns into "Interrupted: 1 error during
# collection": the ENTIRE suite reports nothing. It passed when run alone and with its sibling;
# only the full run showed it, and the error named this file rather than the one that moved
# sys.path. The only import of its kind in the tree — replaced rather than policed, so no
# future sys.path line can reach it.
_SIB = ROOT / "tests" / "test_kickoff_run_kickoff.py"
_spec = importlib.util.spec_from_file_location("_kickoff_run_kickoff_sibling", _SIB)
_sib_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_sib_mod)
ATTENDEES = _sib_mod.ATTENDEES
_all_clean_decisions = _sib_mod._all_clean_decisions


# ---------------------------------------------------------------------------
# Mock hubs registry — decisions list grows when add_meeting_decision is
# called so the phase state machine + idempotency reads see writes.
# ---------------------------------------------------------------------------


def _mock_hubs_with_live_decisions(
    initial_decisions=None,
    meeting_id="page_meeting_1",
    created_task_ids=None,
):
    """Build a hubs registry whose decisions list grows as the test runs.

    ``created_task_ids`` lets a test pre-seed the workhub task store
    so the recovery-from-partial-failure test can simulate the prior
    run's create_task writes having landed.
    """
    decisions = list(initial_decisions or [])
    task_store = {}
    for tid in created_task_ids or []:
        task_store[tid] = {"id": tid, "status": "pending"}

    workhub = MagicMock(name="workhub")
    workhub.create_meeting.return_value = {
        "id": meeting_id,
        "title": "M1 kickoff: build social app",
        "metadata": {"decisions": decisions},
    }

    def _get_decisions(mid):
        if mid != meeting_id:
            return []
        return list(decisions)

    workhub.get_meeting_decisions.side_effect = _get_decisions

    def _add_decision(**kwargs):
        decisions.append(dict(kwargs.get("decision") or {}))
        return {"id": meeting_id}

    workhub.add_meeting_decision.side_effect = _add_decision

    def _create_task(**kwargs):
        tid = kwargs.get("task_id") or f"task_{len(task_store)}"
        task = {"id": tid, "status": "pending", **kwargs}
        task_store[tid] = task
        return task

    workhub.create_task.side_effect = _create_task

    def _get_task(tid):
        return task_store.get(tid)

    workhub.get_task.side_effect = _get_task

    def _list_tasks(**kwargs):
        return list(task_store.values())

    workhub.list_tasks.side_effect = _list_tasks

    workhub.close_meeting.return_value = {"id": meeting_id, "status": "closed"}
    # No stores attribute -> _current_phase falls back to "open" /
    # phase_transition decisions, which is the production-real path.
    workhub.stores = None

    eventhub = MagicMock(name="eventhub")
    eventhub.publish_event.return_value = {"id": "evt_1"}

    registryhub = MagicMock(name="registryhub")
    registryhub.register_endpoint.return_value = {"id": "GET /api/posts"}

    schema_hub = MagicMock(name="schema_hub")
    schema_hub.register_table.return_value = {"id": "posts"}

    return SimpleNamespace(
        workhub=workhub,
        eventhub=eventhub,
        registryhub=registryhub,
        schema_hub=schema_hub,
    ), decisions, task_store


def _ready_synthesis(hubs, handle):
    """Run try_synthesize against a clean decisions set."""
    synthesis = try_synthesize(hubs, handle)
    assert synthesis["status"] == "ready", synthesis
    return synthesis


def _handle():
    return {
        "meeting_id": "page_meeting_1",
        "milestone_index": 1,
        "expected_attendees": ATTENDEES,
    }


def _phase_decisions(decisions):
    return [
        d for d in decisions
        if d.get("section") == "phase_transition"
    ]


def _phase_sequence(decisions):
    return [
        d["content"]["phase"] for d in _phase_decisions(decisions)
    ]


def _kickoff_event_types(eventhub):
    return [
        call.kwargs.get("event_type")
        for call in eventhub.publish_event.call_args_list
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class HappyPathPhasesTests(unittest.TestCase):
    def test_happy_path_records_finalizing_then_finalized(self):
        """Phase sequence on clean finalize is ['finalizing', 'finalized']."""
        hubs, decisions, _ = _mock_hubs_with_live_decisions(
            initial_decisions=_all_clean_decisions(),
        )
        handle = _handle()
        synthesis = _ready_synthesis(hubs, handle)
        hubs.eventhub.publish_event.reset_mock()

        receipt = finalize_kickoff(hubs, handle, synthesis)

        self.assertEqual(receipt["phase"], "finalized")
        self.assertTrue(receipt["finalized"])
        self.assertEqual(receipt["endpoints_registered"], 1)
        self.assertEqual(receipt["tables_registered"], 1)
        self.assertEqual(receipt["tasks_created"], 2)
        self.assertEqual(receipt["tasks_already_existing"], 0)
        self.assertEqual(receipt["tasks_failed"], 0)
        self.assertEqual(receipt["predicates_persisted"], 1)
        self.assertEqual(receipt["failures"], [])
        self.assertEqual(
            _phase_sequence(decisions), ["finalizing", "finalized"]
        )
        self.assertEqual(
            _kickoff_event_types(hubs.eventhub), ["kickoff_complete"]
        )
        hubs.workhub.close_meeting.assert_called_once()


class RegisterEndpointRaisesTests(unittest.TestCase):
    def test_register_endpoint_failure_aborts_before_tables_and_tasks(self):
        """register_endpoint raise -> phase=partial_failure, no closure."""
        hubs, decisions, _ = _mock_hubs_with_live_decisions(
            initial_decisions=_all_clean_decisions(),
        )
        hubs.registryhub.register_endpoint.side_effect = RuntimeError(
            "actor 'orchestrator' not in allowed_set"
        )
        handle = _handle()
        synthesis = _ready_synthesis(hubs, handle)
        hubs.eventhub.publish_event.reset_mock()

        receipt = finalize_kickoff(hubs, handle, synthesis)

        self.assertEqual(receipt["phase"], "partial_failure")
        self.assertFalse(receipt["finalized"])
        self.assertEqual(receipt["endpoints_registered"], 0)
        self.assertEqual(receipt["endpoints_failed"], 1)
        self.assertEqual(receipt["tables_registered"], 0)
        self.assertEqual(receipt["tasks_created"], 0)
        self.assertEqual(len(receipt["failures"]), 1)
        self.assertEqual(receipt["failures"][0]["hub"], "registryhub")
        self.assertIn("not in allowed_set", receipt["failures"][0]["error"])
        # No table / task / closure calls past the failure point.
        hubs.schema_hub.register_table.assert_not_called()
        hubs.workhub.create_task.assert_not_called()
        hubs.workhub.close_meeting.assert_not_called()
        # kickoff_complete NOT emitted; kickoff_failed IS emitted.
        emitted = _kickoff_event_types(hubs.eventhub)
        self.assertNotIn("kickoff_complete", emitted)
        self.assertIn("kickoff_failed", emitted)
        # Phase recorded as finalizing then partial_failure.
        self.assertEqual(
            _phase_sequence(decisions), ["finalizing", "partial_failure"]
        )


class RegisterTableRaisesTests(unittest.TestCase):
    def test_register_table_failure_after_endpoint_success(self):
        """register_table raise -> endpoints landed, no tasks, no closure."""
        hubs, decisions, _ = _mock_hubs_with_live_decisions(
            initial_decisions=_all_clean_decisions(),
        )
        hubs.schema_hub.register_table.side_effect = RuntimeError(
            "schema_hub: actor not allowed"
        )
        handle = _handle()
        synthesis = _ready_synthesis(hubs, handle)
        hubs.eventhub.publish_event.reset_mock()

        receipt = finalize_kickoff(hubs, handle, synthesis)

        self.assertEqual(receipt["phase"], "partial_failure")
        self.assertFalse(receipt["finalized"])
        self.assertEqual(receipt["endpoints_registered"], 1)
        self.assertEqual(receipt["endpoints_failed"], 0)
        self.assertEqual(receipt["tables_registered"], 0)
        self.assertEqual(receipt["tables_failed"], 1)
        self.assertEqual(receipt["tasks_created"], 0)
        self.assertEqual(len(receipt["failures"]), 1)
        self.assertEqual(receipt["failures"][0]["hub"], "schema_hub")
        # No task / closure past the failure point.
        hubs.workhub.create_task.assert_not_called()
        hubs.workhub.close_meeting.assert_not_called()
        emitted = _kickoff_event_types(hubs.eventhub)
        self.assertNotIn("kickoff_complete", emitted)
        self.assertIn("kickoff_failed", emitted)


class CreateTaskErrorDictTests(unittest.TestCase):
    def test_create_task_error_dict_marks_partial_failure(self):
        """workhub.create_task returning {'error':...} is detected (not raised)."""
        hubs, decisions, _ = _mock_hubs_with_live_decisions(
            initial_decisions=_all_clean_decisions(),
        )
        # Override create_task: first call returns a real task, second
        # returns an error dict (simulates an invalid-priority response).
        call_count = {"n": 0}

        def _create_task(**kwargs):
            call_count["n"] += 1
            if call_count["n"] == 2:
                return {
                    "error": "invalid priority 'P9', must be one of ..."
                }
            return {
                "id": kwargs.get("task_id") or "task_x",
                "status": "pending",
                **kwargs,
            }

        hubs.workhub.create_task.side_effect = _create_task
        handle = _handle()
        synthesis = _ready_synthesis(hubs, handle)
        hubs.eventhub.publish_event.reset_mock()

        receipt = finalize_kickoff(hubs, handle, synthesis)

        self.assertEqual(receipt["phase"], "partial_failure")
        self.assertFalse(receipt["finalized"])
        self.assertEqual(receipt["endpoints_registered"], 1)
        self.assertEqual(receipt["tables_registered"], 1)
        # First task succeeded, second hit the error dict.
        self.assertEqual(receipt["tasks_created"], 1)
        self.assertEqual(receipt["tasks_failed"], 1)
        self.assertEqual(len(receipt["failures"]), 1)
        self.assertEqual(receipt["failures"][0]["hub"], "workhub")
        self.assertIn("invalid priority", receipt["failures"][0]["error"])
        # Meeting NOT closed, kickoff_complete NOT emitted.
        hubs.workhub.close_meeting.assert_not_called()
        emitted = _kickoff_event_types(hubs.eventhub)
        self.assertNotIn("kickoff_complete", emitted)
        self.assertIn("kickoff_failed", emitted)


class IdempotentReCallTests(unittest.TestCase):
    def test_re_call_after_finalized_short_circuits(self):
        """A second finalize_kickoff after success is a no-op replay."""
        hubs, decisions, _ = _mock_hubs_with_live_decisions(
            initial_decisions=_all_clean_decisions(),
        )
        handle = _handle()
        synthesis = _ready_synthesis(hubs, handle)
        hubs.eventhub.publish_event.reset_mock()

        first = finalize_kickoff(hubs, handle, synthesis)
        self.assertEqual(first["phase"], "finalized")

        # Snapshot mock state after the first run.
        endpoint_calls_after_first = hubs.registryhub.register_endpoint.call_count
        table_calls_after_first = hubs.schema_hub.register_table.call_count
        task_calls_after_first = hubs.workhub.create_task.call_count
        close_calls_after_first = hubs.workhub.close_meeting.call_count
        amd_calls_after_first = (
            hubs.workhub.add_meeting_decision.call_count
        )
        event_calls_after_first = hubs.eventhub.publish_event.call_count

        # Re-call with the same synthesis.
        second = finalize_kickoff(hubs, handle, synthesis)

        # Receipt replayed unchanged.
        self.assertEqual(second, first)
        # NO new hub calls — short-circuit is a true no-op.
        self.assertEqual(
            hubs.registryhub.register_endpoint.call_count,
            endpoint_calls_after_first,
        )
        self.assertEqual(
            hubs.schema_hub.register_table.call_count,
            table_calls_after_first,
        )
        self.assertEqual(
            hubs.workhub.create_task.call_count, task_calls_after_first
        )
        self.assertEqual(
            hubs.workhub.close_meeting.call_count, close_calls_after_first
        )
        self.assertEqual(
            hubs.workhub.add_meeting_decision.call_count,
            amd_calls_after_first,
        )
        self.assertEqual(
            hubs.eventhub.publish_event.call_count,
            event_calls_after_first,
        )


class RecoveryFromPartialFailureTests(unittest.TestCase):
    def test_recovery_resumes_remaining_writes_and_skips_present_tasks(self):
        """After partial_failure, fixing the cause + re-calling -> finalized.

        Scenario: first run fails on table registration (after the
        endpoint already landed). Caller fixes schema_hub. Re-call:
        endpoints upsert idempotently (registryhub merges), tables register
        successfully, tasks create (with task_id-based dedup against
        the pre-existing first task), meeting closes, kickoff_complete
        fires, phase ends as 'finalized'.
        """
        hubs, decisions, task_store = _mock_hubs_with_live_decisions(
            initial_decisions=_all_clean_decisions(),
        )
        # First run: schema_hub blows up.
        hubs.schema_hub.register_table.side_effect = RuntimeError(
            "first-run schema failure"
        )
        handle = _handle()
        synthesis = _ready_synthesis(hubs, handle)
        hubs.eventhub.publish_event.reset_mock()

        first = finalize_kickoff(hubs, handle, synthesis)
        self.assertEqual(first["phase"], "partial_failure")
        self.assertEqual(first["endpoints_registered"], 1)
        self.assertEqual(first["tables_registered"], 0)
        self.assertEqual(first["tasks_created"], 0)

        # "Caller fixes the failing input": clear schema_hub side
        # effect so the next call succeeds. Also simulate the first
        # task having landed earlier by seeding the task_store —
        # second run should skip it.
        hubs.schema_hub.register_table.side_effect = None
        hubs.schema_hub.register_table.return_value = {"id": "posts"}
        task_store["t_backend_impl"] = {
            "id": "t_backend_impl",
            "status": "pending",
        }

        endpoint_calls_before_retry = hubs.registryhub.register_endpoint.call_count

        second = finalize_kickoff(hubs, handle, synthesis)

        self.assertEqual(second["phase"], "finalized")
        self.assertTrue(second["finalized"])
        # Endpoints registered again (registryhub merge-upsert is safe).
        self.assertGreater(
            hubs.registryhub.register_endpoint.call_count,
            endpoint_calls_before_retry,
        )
        # Tables registered exactly once on the successful retry.
        self.assertEqual(second["tables_registered"], 1)
        # Tasks: one was already present (skipped), one new.
        self.assertEqual(second["tasks_created"], 1)
        self.assertEqual(second["tasks_already_existing"], 1)
        self.assertEqual(second["tasks_failed"], 0)
        # Meeting closed + kickoff_complete fired this time.
        hubs.workhub.close_meeting.assert_called_once()
        self.assertIn(
            "kickoff_complete", _kickoff_event_types(hubs.eventhub)
        )
        # Phase sequence: finalizing, partial_failure, finalizing, finalized.
        self.assertEqual(
            _phase_sequence(decisions),
            ["finalizing", "partial_failure", "finalizing", "finalized"],
        )


if __name__ == "__main__":
    unittest.main()
