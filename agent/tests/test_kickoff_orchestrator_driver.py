"""Round-8c regression tests for Orchestrator._drive_kickoff_to_completion.

Round-8b smoke surfaced that start_kickoff() fired but nothing
advanced the meeting. Round-8c fixes this with a pure-Python driver
on the orchestrator — these tests pin its contract closed-by-construction
WITHOUT requiring a real LLM run.

Round 8f.1 update: the driver now runs the facilitator-led meeting
loop. Every non-awaiting status now consults
``facilitate.read_facilitator_decision`` before either finalizing
(``action=consensus``), requesting revision, or escalating. To keep
these tests pinned to the driver state machine (and not the
orchestrator's LLM lane), each happy-path/conflict test monkey-patches
``read_facilitator_decision`` to short-circuit the facilitator turn.

Coverage matrix:

  * happy path: try_synthesize=ready + facilitator=consensus -> finalize;
  * awaiting -> ready transition: driver sleeps between polls and does
    NOT call finalize_kickoff or the facilitator while status==awaiting;
  * conflict path with max_rounds reached: facilitator asks for
    revision but ``current_round`` is already at the cap -> fallback;
  * facilitator escalate -> fallback;
  * timeout path: elapsed > KICKOFF_TIMEOUT_SEC -> fallback (regardless
    of facilitator state);
  * try_synthesize raising re-raises (it's read-only, exceptions are
    bugs not transients).

We instantiate a tiny stub Orchestrator subset rather than booting the
full class to keep the test pinned to the driver method alone.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from multi_agent.runtime.kickoff import facilitate, run_kickoff  # noqa: E402


# ---------------------------------------------------------------------------
# Helper: build a fake facilitator_note decision dict that
# ``read_facilitator_decision`` would normally return.
# ---------------------------------------------------------------------------


def _consensus_note() -> Dict[str, Any]:
    return {
        "section": "facilitator_note",
        "agent": "orchestrator",
        "round": 1,
        "content": {
            "action": "consensus",
            "rationale": "All sections aligned.",
        },
        "recorded_at": time.time(),
        "recorded_by": "orchestrator",
    }


def _revision_note(revisers: List[str]) -> Dict[str, Any]:
    return {
        "section": "facilitator_note",
        "agent": "orchestrator",
        "round": 1,
        "content": {
            "action": "request_revision",
            "rationale": "frontend missed an endpoint.",
            "revisers": list(revisers),
            "revision_focus": {r: "re-author your section" for r in revisers},
        },
        "recorded_at": time.time(),
        "recorded_by": "orchestrator",
    }


def _escalate_note() -> Dict[str, Any]:
    return {
        "section": "facilitator_note",
        "agent": "orchestrator",
        "round": 1,
        "content": {
            "action": "escalate",
            "rationale": "Irreconcilable conflict.",
        },
        "recorded_at": time.time(),
        "recorded_by": "orchestrator",
    }


# ---------------------------------------------------------------------------
# Stub orchestrator-like object exposing exactly what _drive_kickoff... uses.
#
# We import the unbound method from the real class via __func__ and bind it
# to a stub instance. This is the cheapest way to test the driver without
# booting the multi-agent runtime + MessageBus + checkpoint manager.
# ---------------------------------------------------------------------------


class _StubOrchestrator:
    def __init__(self, hubs: Any) -> None:
        self.hubs = hubs
        self._logger = logging.getLogger("stub_orchestrator")
        # Bind the real abort-site reconcile helpers so the driver's fallback
        # branches resolve. In these tests try_synthesize is monkeypatched to a
        # fake that returns conflict even under reconcile=True, so reconcile
        # yields None and the original synthesize_fallback assertions hold.
        from multi_agent.orchestrator import Orchestrator
        self._kickoff_fallback_or_reconcile = (
            Orchestrator._kickoff_fallback_or_reconcile.__get__(self)
        )
        self._attempt_reconciled_finalize = (
            Orchestrator._attempt_reconciled_finalize.__get__(self)
        )


def _make_handle(started_at: float | None = None) -> Dict[str, Any]:
    """Build a kickoff handle. Default ``started_at`` is "now" so the
    driver's elapsed-time check sees a fresh meeting; tests that want
    the timeout path pass an explicit value in the distant past."""
    if started_at is None:
        started_at = time.time()
    return {
        "meeting_id": "mtg-1",
        "milestone_index": 1,
        "expected_attendees": ["design", "backend", "frontend", "verifier"],
        "started_at": started_at,
        "phase": "awaiting_decisions",
    }


def _drive_method():
    """Pull the unbound driver method off the real Orchestrator class."""
    # Import here so import-time failures land on a single test rather
    # than the whole module collection.
    from multi_agent.orchestrator import Orchestrator
    return Orchestrator._drive_kickoff_to_completion


def _run(coro):
    """Run an async coroutine in a fresh event loop per test."""
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        asyncio.set_event_loop(None)
        loop.close()


# ---------------------------------------------------------------------------
# Happy path: try_synthesize returns "ready" immediately -> finalize is called
# exactly once and the receipt's phase is "finalized".
# ---------------------------------------------------------------------------


def test_driver_happy_path_finalizes_on_first_ready(monkeypatch):
    ready_synthesis = {
        "status": "ready",
        "contract": {"endpoints": []},
        "task_tree": [],
        "predicates": [],
        "milestone_index": 1,
    }
    finalize_calls: List[Dict[str, Any]] = []

    def fake_try_synthesize(hubs, handle, reconcile=False):
        return ready_synthesis

    def fake_finalize_kickoff(*, hubs, kickoff_handle, synthesis, agent):
        finalize_calls.append({
            "kickoff_handle": kickoff_handle,
            "synthesis": synthesis,
            "agent": agent,
        })
        return {
            "phase": "finalized",
            "endpoints_registered": 0,
            "tables_registered": 0,
            "tasks_created": 0,
            "tasks_already_existing": 0,
            "predicates_persisted": 0,
            "failures": [],
            "meeting_id": "mtg-1",
            "milestone_index": 1,
        }

    monkeypatch.setattr(run_kickoff, "try_synthesize", fake_try_synthesize)
    monkeypatch.setattr(run_kickoff, "finalize_kickoff", fake_finalize_kickoff)
    # Round 8g: driver consults current_phase first; force a "consensus"
    # phase so the test exercises the consensus → finalize branch
    # without iterating through comment / reply / facilitator phases.
    monkeypatch.setattr(
        facilitate, "current_phase",
        lambda hubs, meeting_id, attendees: "consensus",
    )
    monkeypatch.setattr(
        facilitate, "current_round",
        lambda hubs, meeting_id: 1,
    )
    monkeypatch.setattr(
        facilitate, "read_facilitator_decision",
        lambda hubs, handle: _consensus_note(),
    )

    stub = _StubOrchestrator(hubs=MagicMock())
    receipt = _run(_drive_method()(stub, _make_handle()))

    assert receipt["phase"] == "finalized"
    assert len(finalize_calls) == 1
    assert finalize_calls[0]["agent"] == "orchestrator"
    assert finalize_calls[0]["synthesis"] is ready_synthesis


# ---------------------------------------------------------------------------
# Awaiting -> ready transition: driver polls multiple times. Verifies the
# driver does NOT call finalize_kickoff while status == "awaiting" and
# the asyncio.sleep delay matches KICKOFF_POLL_INTERVAL_SEC.
# ---------------------------------------------------------------------------


def test_driver_polls_until_ready(monkeypatch):
    # Round 8g phase sequence: initial → initial → consensus.
    # (Comment + reply + facilitator phases are skipped — they're
    # exercised in dedicated tests; this one pins the polling cadence.)
    phase_seq = ["initial", "initial", "consensus"]
    poll_count = {"n": 0}
    finalize_called = {"n": 0}

    def fake_current_phase(hubs, meeting_id, attendees):
        i = min(poll_count["n"], len(phase_seq) - 1)
        poll_count["n"] += 1
        return phase_seq[i]

    def fake_try_synthesize(hubs, handle, reconcile=False):
        return {
            "status": "ready",
            "contract": {},
            "task_tree": [],
            "predicates": [],
            "milestone_index": 1,
        }

    def fake_finalize_kickoff(*, hubs, kickoff_handle, synthesis, agent):
        finalize_called["n"] += 1
        return {"phase": "finalized", "meeting_id": "mtg-1", "milestone_index": 1}

    monkeypatch.setattr(run_kickoff, "try_synthesize", fake_try_synthesize)
    monkeypatch.setattr(run_kickoff, "finalize_kickoff", fake_finalize_kickoff)
    monkeypatch.setattr(facilitate, "current_phase", fake_current_phase)
    monkeypatch.setattr(facilitate, "current_round", lambda h, m: 1)
    monkeypatch.setattr(
        facilitate, "read_facilitator_decision",
        lambda hubs, handle: _consensus_note(),
    )
    monkeypatch.setattr(run_kickoff, "KICKOFF_POLL_INTERVAL_SEC", 0.001)

    stub = _StubOrchestrator(hubs=MagicMock())
    receipt = _run(_drive_method()(stub, _make_handle()))

    assert receipt["phase"] == "finalized"
    assert finalize_called["n"] == 1
    # Polled 3 times total (2 initial + 1 consensus).
    assert poll_count["n"] == 3


# ---------------------------------------------------------------------------
# Conflict + revision-at-max-rounds: facilitator asks for revision but the
# meeting is already at KICKOFF_MAX_ROUNDS, so the driver falls back rather
# than dispatching another revision request.
# ---------------------------------------------------------------------------


def test_driver_conflict_at_max_rounds_falls_back(monkeypatch):
    conflict_synthesis = {
        "status": "conflict",
        "findings": [{"check": "api_vs_frontend", "status": "fail"}],
        "revisers": {"design": [{"check": "api_vs_frontend"}]},
        "milestone_index": 1,
    }
    fallback_calls: List[Dict[str, Any]] = []
    finalize_called = {"n": 0}
    revisions_dispatched = {"n": 0}

    def fake_try_synthesize(hubs, handle, reconcile=False):
        return conflict_synthesis

    def fake_finalize_kickoff(*, hubs, kickoff_handle, synthesis, agent):
        finalize_called["n"] += 1
        return {"phase": "finalized"}

    def fake_synthesize_fallback(*, hubs, kickoff_handle, last_synthesis, agent):
        fallback_calls.append({
            "kickoff_handle": kickoff_handle,
            "last_synthesis": last_synthesis,
            "agent": agent,
        })
        return {
            "phase": "timeout_fallback",
            "kickoff_fallback_used": True,
            "meeting_id": "mtg-1",
            "milestone_index": 1,
            "last_status": "conflict",
        }

    def fake_request_revisions(hubs, handle, revisers, note, agent="orchestrator"):
        revisions_dispatched["n"] += 1
        return {"event_id": "evt-1", "new_round": 99, "revisers": revisers}

    monkeypatch.setattr(run_kickoff, "try_synthesize", fake_try_synthesize)
    monkeypatch.setattr(run_kickoff, "finalize_kickoff", fake_finalize_kickoff)
    monkeypatch.setattr(run_kickoff, "synthesize_fallback", fake_synthesize_fallback)
    # Round 8g: force the driver into the facilitator-action branch
    # (current_phase=="request_revision") so it short-circuits the
    # phase progression and goes straight to the action handler.
    monkeypatch.setattr(
        facilitate, "current_phase",
        lambda hubs, meeting_id, attendees: "request_revision",
    )
    # Facilitator always asks for revision, but pretend the meeting is
    # already at the max-rounds cap. The driver must NOT dispatch a new
    # revision round in that case — it must fall through to fallback.
    monkeypatch.setattr(
        facilitate, "read_facilitator_decision",
        lambda hubs, handle: _revision_note(["backend"]),
    )
    monkeypatch.setattr(
        facilitate, "current_round",
        lambda hubs, meeting_id: facilitate.KICKOFF_MAX_ROUNDS,
    )
    monkeypatch.setattr(facilitate, "request_revisions", fake_request_revisions)

    stub = _StubOrchestrator(hubs=MagicMock())
    receipt = _run(_drive_method()(stub, _make_handle()))

    assert receipt["phase"] == "timeout_fallback"
    assert receipt["kickoff_fallback_used"] is True
    # finalize_kickoff MUST NOT be called when the facilitator hasn't
    # declared consensus.
    assert finalize_called["n"] == 0
    # The driver MUST NOT dispatch yet another revision when we're at
    # the max-rounds cap — the whole point of the cap is to bail.
    assert revisions_dispatched["n"] == 0
    assert len(fallback_calls) == 1
    assert fallback_calls[0]["last_synthesis"] is conflict_synthesis


# ---------------------------------------------------------------------------
# Facilitator escalate -> immediate fallback (no revisions, no finalize).
# ---------------------------------------------------------------------------


def test_driver_facilitator_escalate_falls_back(monkeypatch):
    conflict_synthesis = {
        "status": "conflict",
        "findings": [{"check": "irreconcilable"}],
        "milestone_index": 1,
    }
    fallback_calls: List[Dict[str, Any]] = []
    finalize_called = {"n": 0}

    def fake_try_synthesize(hubs, handle, reconcile=False):
        return conflict_synthesis

    def fake_finalize_kickoff(*, hubs, kickoff_handle, synthesis, agent):
        finalize_called["n"] += 1
        return {"phase": "finalized"}

    def fake_synthesize_fallback(*, hubs, kickoff_handle, last_synthesis, agent):
        fallback_calls.append({"last_synthesis": last_synthesis})
        return {
            "phase": "timeout_fallback",
            "kickoff_fallback_used": True,
            "meeting_id": "mtg-1",
            "milestone_index": 1,
            "last_status": "conflict",
        }

    monkeypatch.setattr(run_kickoff, "try_synthesize", fake_try_synthesize)
    monkeypatch.setattr(run_kickoff, "finalize_kickoff", fake_finalize_kickoff)
    monkeypatch.setattr(run_kickoff, "synthesize_fallback", fake_synthesize_fallback)
    monkeypatch.setattr(
        facilitate, "current_phase",
        lambda hubs, meeting_id, attendees: "escalate",
    )
    monkeypatch.setattr(facilitate, "current_round", lambda h, m: 1)
    monkeypatch.setattr(
        facilitate, "read_facilitator_decision",
        lambda hubs, handle: _escalate_note(),
    )

    stub = _StubOrchestrator(hubs=MagicMock())
    receipt = _run(_drive_method()(stub, _make_handle()))

    assert receipt["phase"] == "timeout_fallback"
    assert finalize_called["n"] == 0
    assert len(fallback_calls) == 1
    assert fallback_calls[0]["last_synthesis"] is conflict_synthesis


# ---------------------------------------------------------------------------
# Timeout path: driver elapses past KICKOFF_TIMEOUT_SEC -> fallback.
# Uses a handle with started_at set far in the past so the very first
# poll exceeds the timeout.
# ---------------------------------------------------------------------------


def test_driver_timeout_falls_through_to_fallback(monkeypatch):
    # awaiting + handle.started_at = far past -> timeout on first poll.
    awaiting_synthesis = {
        "status": "awaiting",
        "missing": ["frontend", "verifier"],
        "milestone_index": 1,
    }
    fallback_calls: List[Dict[str, Any]] = []

    def fake_try_synthesize(hubs, handle, reconcile=False):
        return awaiting_synthesis

    def fake_synthesize_fallback(*, hubs, kickoff_handle, last_synthesis, agent):
        fallback_calls.append({"last_synthesis": last_synthesis})
        return {
            "phase": "timeout_fallback",
            "kickoff_fallback_used": True,
            "meeting_id": "mtg-1",
            "milestone_index": 1,
            "last_status": "awaiting",
        }

    monkeypatch.setattr(run_kickoff, "try_synthesize", fake_try_synthesize)
    monkeypatch.setattr(run_kickoff, "synthesize_fallback", fake_synthesize_fallback)

    # Set started_at = 0 (1970) so elapsed > KICKOFF_TIMEOUT_SEC instantly.
    handle = _make_handle(started_at=0.0)
    stub = _StubOrchestrator(hubs=MagicMock())
    receipt = _run(_drive_method()(stub, handle))

    assert receipt["phase"] == "timeout_fallback"
    assert receipt["kickoff_fallback_used"] is True
    assert len(fallback_calls) == 1
    # Driver did NOT call asyncio.sleep before falling through — the
    # timeout check fires before the sleep branch.


# ---------------------------------------------------------------------------
# try_synthesize raising MUST re-raise (it's pure + read-only). Silent
# swallow would hide a runtime bug behind an infinite poll loop.
# ---------------------------------------------------------------------------


def test_driver_propagates_try_synthesize_exception(monkeypatch):
    class _Boom(Exception):
        pass

    def fake_try_synthesize(hubs, handle, reconcile=False):
        raise _Boom("simulated")

    monkeypatch.setattr(run_kickoff, "try_synthesize", fake_try_synthesize)
    # Round 8g: force the driver past phase progression into the
    # facilitator-action branch where try_synthesize gets called.
    monkeypatch.setattr(
        facilitate, "current_phase",
        lambda hubs, meeting_id, attendees: "consensus",
    )
    monkeypatch.setattr(facilitate, "current_round", lambda h, m: 1)
    monkeypatch.setattr(
        facilitate, "read_facilitator_decision",
        lambda hubs, handle: _consensus_note(),
    )

    stub = _StubOrchestrator(hubs=MagicMock())
    with pytest.raises(_Boom):
        _run(_drive_method()(stub, _make_handle()))


# ---------------------------------------------------------------------------
# Sanity: validation_failed routes through fallback too once the facilitator
# escalates. Round 8f.1 still treats validation_failed as a non-awaiting
# status, so the driver wakes the facilitator who in turn escalates.
# ---------------------------------------------------------------------------


def test_driver_validation_failed_with_escalate_falls_back(monkeypatch):
    vfail = {
        "status": "validation_failed",
        "findings": [{"validator": "roadmap", "rule": "no_dangling_dependency"}],
        "milestone_index": 1,
    }
    fallback_seen: List[str] = []

    def fake_try_synthesize(hubs, handle, reconcile=False):
        return vfail

    def fake_synthesize_fallback(*, hubs, kickoff_handle, last_synthesis, agent):
        fallback_seen.append(last_synthesis.get("status", ""))
        return {
            "phase": "timeout_fallback",
            "kickoff_fallback_used": True,
            "meeting_id": "mtg-1",
            "milestone_index": 1,
            "last_status": "validation_failed",
        }

    monkeypatch.setattr(run_kickoff, "try_synthesize", fake_try_synthesize)
    monkeypatch.setattr(run_kickoff, "synthesize_fallback", fake_synthesize_fallback)
    monkeypatch.setattr(
        facilitate, "current_phase",
        lambda hubs, meeting_id, attendees: "escalate",
    )
    monkeypatch.setattr(facilitate, "current_round", lambda h, m: 1)
    monkeypatch.setattr(
        facilitate, "read_facilitator_decision",
        lambda hubs, handle: _escalate_note(),
    )

    stub = _StubOrchestrator(hubs=MagicMock())
    receipt = _run(_drive_method()(stub, _make_handle()))

    assert receipt["phase"] == "timeout_fallback"
    assert receipt["last_status"] == "validation_failed"
    assert fallback_seen == ["validation_failed"]


# ---------------------------------------------------------------------------
# Round 8h adversarial-review follow-up: when the facilitator writes an
# invented action like "accept_revision_and_recenter", the driver MUST
# coerce it to a canonical FACILITATOR_ACTIONS value before branching.
# Pre-fix, ``facilitate.current_phase()`` coerced the action when computing
# ``phase`` but the orchestrator then re-read the raw uncoerced action
# from note_content, falling through to the "Unknown facilitator action"
# handler -> synthesize_fallback. This pins the consensus-path equivalent.
# ---------------------------------------------------------------------------


def _invented_consensus_note() -> Dict[str, Any]:
    return {
        "section": "facilitator_note",
        "agent": "orchestrator",
        "round": 1,
        "content": {
            "action": "accept_revision_and_recenter",
            "rationale": "All sections aligned after revision; finalize.",
        },
        "recorded_at": time.time(),
        "recorded_by": "orchestrator",
    }


def test_driver_coerces_invented_action_to_consensus(monkeypatch):
    """An invented action that coerces to ``consensus`` MUST take the
    finalize branch, not fall through to the unknown-action fallback."""
    ready_synthesis = {
        "status": "ready",
        "contract": {"endpoints": []},
        "task_tree": [],
        "predicates": [],
        "milestone_index": 1,
    }
    finalize_called = {"n": 0}
    fallback_called = {"n": 0}

    def fake_try_synthesize(hubs, handle, reconcile=False):
        return ready_synthesis

    def fake_finalize_kickoff(*, hubs, kickoff_handle, synthesis, agent):
        finalize_called["n"] += 1
        return {
            "phase": "finalized",
            "endpoints_registered": 0,
            "tables_registered": 0,
            "tasks_created": 0,
            "predicates_persisted": 0,
            "failures": [],
            "meeting_id": "mtg-1",
            "milestone_index": 1,
        }

    def fake_synthesize_fallback(*, hubs, kickoff_handle, last_synthesis, agent):
        fallback_called["n"] += 1
        return {"phase": "timeout_fallback"}

    monkeypatch.setattr(run_kickoff, "try_synthesize", fake_try_synthesize)
    monkeypatch.setattr(run_kickoff, "finalize_kickoff", fake_finalize_kickoff)
    monkeypatch.setattr(run_kickoff, "synthesize_fallback", fake_synthesize_fallback)
    monkeypatch.setattr(
        facilitate, "current_phase",
        lambda hubs, meeting_id, attendees: "consensus",
    )
    monkeypatch.setattr(facilitate, "current_round", lambda h, m: 1)
    monkeypatch.setattr(
        facilitate, "read_facilitator_decision",
        lambda hubs, handle: _invented_consensus_note(),
    )

    stub = _StubOrchestrator(hubs=MagicMock())
    receipt = _run(_drive_method()(stub, _make_handle()))

    assert receipt["phase"] == "finalized"
    assert finalize_called["n"] == 1
    assert fallback_called["n"] == 0


def _invented_revision_note() -> Dict[str, Any]:
    return {
        "section": "facilitator_note",
        "agent": "orchestrator",
        "round": 1,
        "content": {
            "action": "rework_design_section",
            "revisers": ["design"],
            "rationale": "design block needs rework.",
        },
        "recorded_at": time.time(),
        "recorded_by": "orchestrator",
    }


def test_driver_coerces_invented_action_to_request_revision(monkeypatch):
    """An invented action that coerces to ``request_revision`` MUST hit
    the revision dispatch branch (not fallback). Force max_rounds on
    the SECOND poll so the driver exits via fallback after exactly
    one revision dispatch — otherwise the loop never terminates."""
    conflict_synthesis = {
        "status": "conflict",
        "findings": [{"check": "api_vs_frontend"}],
        "revisers": {"design": [{"check": "api_vs_frontend"}]},
        "milestone_index": 1,
    }
    revisions_dispatched = {"n": 0}
    fallback_called = {"n": 0}

    def fake_try_synthesize(hubs, handle, reconcile=False):
        return conflict_synthesis

    def fake_synthesize_fallback(*, hubs, kickoff_handle, last_synthesis, agent):
        fallback_called["n"] += 1
        return {"phase": "timeout_fallback", "kickoff_fallback_used": True}

    def fake_request_revisions(hubs, handle, revisers, note, agent="orchestrator"):
        revisions_dispatched["n"] += 1
        return {"event_id": "evt-1", "new_round": 2, "revisers": revisers}

    monkeypatch.setattr(run_kickoff, "try_synthesize", fake_try_synthesize)
    monkeypatch.setattr(run_kickoff, "synthesize_fallback", fake_synthesize_fallback)
    monkeypatch.setattr(facilitate, "request_revisions", fake_request_revisions)
    monkeypatch.setattr(
        facilitate, "current_phase",
        lambda hubs, meeting_id, attendees: "request_revision",
    )
    # Gate on revisions_dispatched (NOT a per-call counter) — the
    # driver invokes current_round both at the top of the outer loop
    # AND inside the revision branch, so a naive per-call counter
    # races with the outer-loop call. Using the dispatch count makes
    # the budget logic crisp: while no revision has shipped, round=1
    # (drive through the action handler); after exactly one ships,
    # report MAX so the next iteration short-circuits to fallback.
    def fake_current_round(hubs, meeting_id):
        if revisions_dispatched["n"] == 0:
            return 1
        return facilitate.KICKOFF_MAX_ROUNDS

    monkeypatch.setattr(facilitate, "current_round", fake_current_round)
    monkeypatch.setattr(
        facilitate, "read_facilitator_decision",
        lambda hubs, handle: _invented_revision_note(),
    )
    monkeypatch.setattr(run_kickoff, "KICKOFF_POLL_INTERVAL_SEC", 0.001)

    stub = _StubOrchestrator(hubs=MagicMock())
    receipt = _run(_drive_method()(stub, _make_handle()))

    # The invented action is COERCED to request_revision (not "Unknown
    # facilitator action" → escalate). With KICKOFF_MAX_ROUNDS=1 (no revision
    # rounds — by-construction "no re-negotiation"), that request_revision is
    # already at the cap, so the driver goes straight to the deterministic
    # reconcile and then fallback WITHOUT dispatching a revision round.
    assert revisions_dispatched["n"] == 0
    assert fallback_called["n"] == 1
    assert receipt["phase"] == "timeout_fallback"


def test_driver_unknown_uncoerceable_action_defaults_to_escalate(monkeypatch):
    """An empty / non-string action defaults to ``escalate`` via
    coerce_facilitator_action, so the driver MUST fall back rather
    than hitting "Unknown facilitator action"."""
    synthesis = {"status": "conflict", "findings": [], "milestone_index": 1}
    fallback_called = {"n": 0}
    finalize_called = {"n": 0}

    def fake_try_synthesize(hubs, handle, reconcile=False):
        return synthesis

    def fake_synthesize_fallback(*, hubs, kickoff_handle, last_synthesis, agent):
        fallback_called["n"] += 1
        return {"phase": "timeout_fallback"}

    def fake_finalize_kickoff(*, hubs, kickoff_handle, synthesis, agent):
        finalize_called["n"] += 1
        return {"phase": "finalized"}

    monkeypatch.setattr(run_kickoff, "try_synthesize", fake_try_synthesize)
    monkeypatch.setattr(run_kickoff, "synthesize_fallback", fake_synthesize_fallback)
    monkeypatch.setattr(run_kickoff, "finalize_kickoff", fake_finalize_kickoff)
    monkeypatch.setattr(
        facilitate, "current_phase",
        lambda hubs, meeting_id, attendees: "escalate",
    )
    monkeypatch.setattr(facilitate, "current_round", lambda h, m: 1)
    monkeypatch.setattr(
        facilitate, "read_facilitator_decision",
        lambda hubs, handle: {
            "section": "facilitator_note",
            "agent": "orchestrator",
            "round": 1,
            "content": {"action": "", "rationale": "blank"},
            "recorded_at": time.time(),
            "recorded_by": "orchestrator",
        },
    )

    stub = _StubOrchestrator(hubs=MagicMock())
    receipt = _run(_drive_method()(stub, _make_handle()))

    # Empty action coerces to escalate, which routes through fallback.
    assert receipt["phase"] == "timeout_fallback"
    assert fallback_called["n"] == 1
    assert finalize_called["n"] == 0
