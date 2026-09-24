"""Round-8g regression tests: kickoff phase handlers MUST guarantee a
phase_ack for (this agent, round, phase) when the agentic loop exits,
whether the LLM wrote one or not.

Smoke #9 (2026-06-02 23:30) showed the failure mode this guards: the
frontend's comment-phase agentic loop called ``finish()`` after only
9 seconds without writing the phase_ack decision the driver polls
for. The driver then waited on frontend indefinitely; the meeting
hung until the 1200s synthesize_fallback timeout.

The fix is closed-by-construction: each phase handler's ``finally``
block calls ``_ensure_phase_ack`` which:
  * checks ``facilitate.phase_acked_by`` for an existing ack from
    this agent for this (round, phase) — if present, no-op (the
    LLM-written ack is preserved verbatim);
  * otherwise writes ``workhub.add_meeting_decision`` with
    ``section='phase_ack' kind='<phase>_phase_done'`` and a
    ``content.source='auto_backup'`` marker so audit logs can
    distinguish LLM-acked vs auto-acked rounds.

These tests pin that contract without a real LLM run.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))


class _StubMessage:
    def __init__(self, payload: Dict[str, Any], msg_type: str, source: str = "orchestrator"):
        self.payload = payload
        self.metadata = {"msg_type": msg_type}
        self.header = SimpleNamespace(source_agent_id=source, message_id="m1")


class _FakeWorkhub:
    """Records add_meeting_decision calls for assertion."""

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    def add_meeting_decision(
        self,
        meeting_id: str,
        decision: dict,
        agent: str = "",
        milestone_index: Optional[int] = None,
    ) -> dict:
        self.calls.append({
            "meeting_id": meeting_id,
            "decision": dict(decision),
            "agent": agent,
            "milestone_index": milestone_index,
        })
        return {"ok": True}


class _StubAgent:
    """Minimal stub of an attendee for the phase handlers."""

    def __init__(self, agent_id: str = "frontend", render_result: str = "RENDERED"):
        self.agent_id = agent_id
        self._prompt_cfg = {"template": f"{agent_id}_agent.j2"}
        self._render_result = render_result
        self._render_macro_calls: List[Dict[str, Any]] = []
        self._agentic_loop_calls: List[Dict[str, Any]] = []
        self._processing_state = None
        self._focus_hub = None
        self._deferred_task_ready_messages: List[Any] = []
        self.workhub = _FakeWorkhub()
        # _hubs is the canonical attribute set by base.EnvGenAgent.set_hubs.
        # Smoke #9-bis caught us using ``self.hubs`` (non-existent) and
        # silently no-op'ing the backup ack — pin the canonical name here.
        self._hubs = SimpleNamespace(workhub=self.workhub)
        import logging
        self._logger = logging.getLogger("stub")

    def _compose_system_prompt(self) -> str:
        return "SYS"

    def render_macro(self, template: str, macro: str, **ctx: Any) -> str:
        self._render_macro_calls.append({"template": template, "macro": macro, "ctx": ctx})
        return self._render_result

    async def run_agentic_loop(self, *, system_prompt: str, initial_prompt: str, max_steps: int) -> None:
        self._agentic_loop_calls.append({
            "system_prompt": system_prompt,
            "initial_prompt": initial_prompt,
            "max_steps": max_steps,
        })
        # Default: LLM does NOT write phase_ack (mimics the smoke-9
        # frontend bug). Tests that want a pre-existing ack monkeypatch
        # facilitate.phase_acked_by separately.

    async def _drain_deferred_task_ready_messages(self) -> None:
        pass


def _bind_messaging_methods(stub: "_StubAgent") -> None:
    """Bind the real ``_ensure_phase_ack`` helper to the stub so the
    handler's finally block exercises the real fix (not a stub stand-in).
    Tests assert what the real helper does, not what a stub returns.
    """
    from multi_agent.agents.runtime.messaging import AgentMessaging
    import types
    stub._ensure_phase_ack = types.MethodType(  # type: ignore[attr-defined]
        AgentMessaging._ensure_phase_ack, stub,
    )


def _comment_handler():
    from multi_agent.agents.runtime.messaging import AgentMessaging
    return AgentMessaging._handle_kickoff_comment_phase_request


def _reply_handler():
    from multi_agent.agents.runtime.messaging import AgentMessaging
    return AgentMessaging._handle_kickoff_reply_phase_request


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        asyncio.set_event_loop(None)
        loop.close()


def _payload(round_n: int = 1, meeting_id: str = "mtg-1") -> Dict[str, Any]:
    return {
        "meeting_id": meeting_id,
        "milestone_index": 1,
        "current_round": round_n,
        "attendees": ["backend", "frontend", "verifier"],
    }


# ---------------------------------------------------------------------------
# Closed-by-construction: lazy LLM that never writes phase_ack → handler
# auto-writes a backup ack so the meeting can advance.
# ---------------------------------------------------------------------------


def test_comment_handler_auto_writes_ack_when_llm_skips_it(monkeypatch):
    from multi_agent.runtime.kickoff import facilitate
    # No agent has acked yet — phase_acked_by returns [].
    monkeypatch.setattr(facilitate, "phase_acked_by", lambda h, m, r, p: [])

    stub = _StubAgent(agent_id="frontend")
    _bind_messaging_methods(stub)
    _run(_comment_handler()(stub, _StubMessage(_payload(), "kickoff_comment_phase_request")))

    # The LLM stub does NOT write a phase_ack; handler's finally block
    # MUST write one via workhub.add_meeting_decision.
    assert len(stub.workhub.calls) == 1
    call = stub.workhub.calls[0]
    assert call["meeting_id"] == "mtg-1"
    assert call["agent"] == "frontend"
    assert call["milestone_index"] == 1
    dec = call["decision"]
    assert dec["section"] == "phase_ack"
    assert dec["round"] == 1
    assert dec["kind"] == "comment_phase_done"
    assert dec["content"]["phase"] == "comment"
    assert dec["content"]["ack"] is True
    # Audit marker so downstream can tell LLM-acked from auto-acked.
    assert dec["content"]["source"] == "auto_backup"


def test_reply_handler_auto_writes_ack_when_llm_skips_it(monkeypatch):
    from multi_agent.runtime.kickoff import facilitate
    monkeypatch.setattr(facilitate, "phase_acked_by", lambda h, m, r, p: [])

    stub = _StubAgent(agent_id="backend")
    _bind_messaging_methods(stub)
    _run(_reply_handler()(stub, _StubMessage(_payload(round_n=2), "kickoff_reply_phase_request")))

    assert len(stub.workhub.calls) == 1
    dec = stub.workhub.calls[0]["decision"]
    assert dec["section"] == "phase_ack"
    assert dec["round"] == 2
    assert dec["kind"] == "reply_phase_done"
    assert dec["content"]["phase"] == "reply"
    assert dec["content"]["source"] == "auto_backup"


# ---------------------------------------------------------------------------
# Preserve LLM-written ack: if facilitate.phase_acked_by already lists
# this agent, the handler MUST NOT write a duplicate backup ack.
# ---------------------------------------------------------------------------


def test_comment_handler_does_not_double_ack_when_llm_already_acked(monkeypatch):
    from multi_agent.runtime.kickoff import facilitate
    # Simulate the LLM having already acked: phase_acked_by returns this agent.
    monkeypatch.setattr(facilitate, "phase_acked_by", lambda h, m, r, p: ["frontend"])

    stub = _StubAgent(agent_id="frontend")
    _bind_messaging_methods(stub)
    _run(_comment_handler()(stub, _StubMessage(_payload(), "kickoff_comment_phase_request")))

    # No backup write — the LLM's own ack is preserved.
    assert stub.workhub.calls == []


def test_reply_handler_does_not_double_ack_when_llm_already_acked(monkeypatch):
    from multi_agent.runtime.kickoff import facilitate
    monkeypatch.setattr(facilitate, "phase_acked_by", lambda h, m, r, p: ["backend"])

    stub = _StubAgent(agent_id="backend")
    _bind_messaging_methods(stub)
    _run(_reply_handler()(stub, _StubMessage(_payload(round_n=3), "kickoff_reply_phase_request")))

    assert stub.workhub.calls == []


# ---------------------------------------------------------------------------
# Exception in agentic loop MUST still trigger the backup ack — the
# meeting must advance even when an attendee crashes mid-phase.
# ---------------------------------------------------------------------------


def test_comment_handler_writes_ack_even_when_agentic_loop_raises(monkeypatch):
    from multi_agent.runtime.kickoff import facilitate
    monkeypatch.setattr(facilitate, "phase_acked_by", lambda h, m, r, p: [])

    class _Boom(Exception):
        pass

    stub = _StubAgent(agent_id="verifier")
    _bind_messaging_methods(stub)

    async def _raising_loop(*, system_prompt, initial_prompt, max_steps):
        raise _Boom("simulated lane crash")

    stub.run_agentic_loop = _raising_loop  # type: ignore[assignment]

    _run(_comment_handler()(stub, _StubMessage(_payload(), "kickoff_comment_phase_request")))

    # The loop crashed but the finally block still wrote the backup ack.
    assert len(stub.workhub.calls) == 1
    assert stub.workhub.calls[0]["decision"]["kind"] == "comment_phase_done"
    assert stub.workhub.calls[0]["decision"]["content"]["source"] == "auto_backup"


# ---------------------------------------------------------------------------
# Missing meeting_id is the documented early-return path and must NOT
# write a backup ack (there's no meeting to ack into).
# ---------------------------------------------------------------------------


def test_comment_handler_no_ack_when_meeting_id_missing(monkeypatch):
    from multi_agent.runtime.kickoff import facilitate
    monkeypatch.setattr(facilitate, "phase_acked_by", lambda h, m, r, p: [])

    stub = _StubAgent(agent_id="frontend")
    _bind_messaging_methods(stub)
    bad_payload = _payload()
    bad_payload["meeting_id"] = ""  # malformed

    _run(_comment_handler()(stub, _StubMessage(bad_payload, "kickoff_comment_phase_request")))

    assert stub.workhub.calls == []
    # Also: no agentic loop ran (early return).
    assert stub._agentic_loop_calls == []


# ---------------------------------------------------------------------------
# Round 8g Fix #C: initial-phase section decision must be guaranteed.
# Smoke #9-ter caught verifier finish()ing without writing its section,
# stalling the driver in initial phase forever.
# ---------------------------------------------------------------------------


def _kickoff_request_handler():
    from multi_agent.agents.runtime.messaging import AgentMessaging
    return AgentMessaging._handle_kickoff_request


def _bind_initial_section_helper(stub: "_StubAgent") -> None:
    from multi_agent.agents.runtime.messaging import AgentMessaging
    import types
    stub._ensure_initial_section_decision = types.MethodType(  # type: ignore[attr-defined]
        AgentMessaging._ensure_initial_section_decision, stub,
    )


class _FakePagesStore:
    """Mirror enough of workhub.stores.documents.value() shape for the
    section-presence walk in _ensure_initial_section_decision."""

    def __init__(self, pages_data):
        self._data = pages_data

    def value(self):
        return self._data


class _FakeWorkhubWithPages(_FakeWorkhub):
    def __init__(self, pages_data):
        super().__init__()
        # ui_page→registryhub rename: the section-presence walk reads
        # workhub.stores.documents.value() (was .pages).
        self.stores = SimpleNamespace(documents=_FakePagesStore(pages_data))


def _kickoff_payload_full(meeting_id: str = "mtg-1") -> Dict[str, Any]:
    return {
        "meeting_id": meeting_id,
        "milestone_index": 1,
        "requirements": ["Build a minimal blog."],
        "expected_sections": ["backend", "frontend", "verifier"],
    }


def test_initial_handler_auto_writes_section_when_llm_skips_it():
    """Smoke #9-ter regression: verifier finished without authoring its
    initial section. Handler's finally block MUST write a backup stub."""
    # Meeting page exists, no decisions yet.
    pages = {"mtg-1": {"metadata": {"decisions": []}}}
    stub = _StubAgent(agent_id="verifier")
    stub.workhub = _FakeWorkhubWithPages(pages)
    stub._hubs = SimpleNamespace(workhub=stub.workhub)
    _bind_messaging_methods(stub)
    _bind_initial_section_helper(stub)

    _run(_kickoff_request_handler()(stub, _StubMessage(_kickoff_payload_full(), "kickoff_request")))

    # One backup write — section matches agent_id, marked auto_backup.
    assert len(stub.workhub.calls) == 1
    call = stub.workhub.calls[0]
    assert call["meeting_id"] == "mtg-1"
    assert call["agent"] == "verifier"
    assert call["milestone_index"] == 1
    dec = call["decision"]
    assert dec["section"] == "verifier"
    assert dec["kind"] == "draft_section"
    assert dec["content"]["section"] == "verifier"
    assert dec["content"]["deferred"] is True
    assert dec["content"]["source"] == "auto_backup"


def test_initial_handler_does_not_double_write_when_llm_already_authored():
    """LLM-written section MUST be preserved verbatim; no duplicate backup."""
    pages = {"mtg-1": {"metadata": {"decisions": [
        {"section": "backend", "recorded_by": "backend",
         "kind": "draft_section",
         "content": {"endpoints": [{"path": "/api/posts", "method": "GET"}]}},
    ]}}}
    stub = _StubAgent(agent_id="backend")
    stub.workhub = _FakeWorkhubWithPages(pages)
    stub._hubs = SimpleNamespace(workhub=stub.workhub)
    _bind_messaging_methods(stub)
    _bind_initial_section_helper(stub)

    _run(_kickoff_request_handler()(stub, _StubMessage(_kickoff_payload_full(), "kickoff_request")))

    # No backup write — the LLM's own decision is preserved.
    assert stub.workhub.calls == []


def test_initial_handler_writes_backup_even_if_agentic_loop_raises():
    """Exception in agentic loop must still trigger the backup section."""
    pages = {"mtg-1": {"metadata": {"decisions": []}}}
    stub = _StubAgent(agent_id="frontend")
    stub.workhub = _FakeWorkhubWithPages(pages)
    stub._hubs = SimpleNamespace(workhub=stub.workhub)
    _bind_messaging_methods(stub)
    _bind_initial_section_helper(stub)

    async def _raise(*, system_prompt, initial_prompt, max_steps):
        raise RuntimeError("simulated lane crash")
    stub.run_agentic_loop = _raise  # type: ignore[assignment]

    _run(_kickoff_request_handler()(stub, _StubMessage(_kickoff_payload_full(), "kickoff_request")))

    assert len(stub.workhub.calls) == 1
    assert stub.workhub.calls[0]["decision"]["section"] == "frontend"
    assert stub.workhub.calls[0]["decision"]["content"]["source"] == "auto_backup"


# ---------------------------------------------------------------------------
# Round 8h Fix #F: revision handler MUST guarantee a section decision
# for the current revision round. Smoke #9-sextus showed the gap.
# ---------------------------------------------------------------------------


def _revision_handler():
    from multi_agent.agents.runtime.messaging import AgentMessaging
    return AgentMessaging._handle_kickoff_revision_request


def _bind_revision_section_helper(stub: "_StubAgent") -> None:
    from multi_agent.agents.runtime.messaging import AgentMessaging
    import types
    stub._ensure_revision_section_decision = types.MethodType(  # type: ignore[attr-defined]
        AgentMessaging._ensure_revision_section_decision, stub,
    )


def _revision_payload(
    *, round_n: int = 2, agent_id: str = "frontend",
    meeting_id: str = "mtg-1",
) -> Dict[str, Any]:
    return {
        "meeting_id": meeting_id,
        "milestone_index": 1,
        "current_round": round_n,
        "max_rounds": 3,
        "revisers": [agent_id, "verifier"] if agent_id != "verifier" else ["frontend", agent_id],
        "revision_focus": {agent_id: "tweak endpoint /api/posts response_key"},
        "facilitator_rationale": "Test rationale",
        "acks_consensus_on": [],
        "open_questions": [],
    }


def test_revision_handler_auto_writes_section_when_llm_skips_it():
    """Smoke #9-sextus regression: frontend received the revision
    request but ended its agentic loop without authoring the new
    round-2 section. Handler's finally block MUST write the backup
    so current_phase can advance past initial in the revision round."""
    pages = {"mtg-1": {"metadata": {"decisions": []}}}
    stub = _StubAgent(agent_id="frontend")
    stub.workhub = _FakeWorkhubWithPages(pages)
    stub._hubs = SimpleNamespace(workhub=stub.workhub)
    _bind_messaging_methods(stub)
    _bind_revision_section_helper(stub)

    _run(_revision_handler()(stub, _StubMessage(_revision_payload(), "kickoff_revision_request")))

    assert len(stub.workhub.calls) == 1
    dec = stub.workhub.calls[0]["decision"]
    assert dec["section"] == "frontend"
    assert dec["round"] == 2
    assert dec["kind"] == "draft_section"
    assert dec["content"]["section"] == "frontend"
    assert dec["content"]["deferred"] is True
    assert dec["content"]["source"] == "auto_backup"


def test_revision_handler_preserves_llm_authored_section():
    """If the LLM authored a real round-N section, no backup write."""
    pages = {"mtg-1": {"metadata": {"decisions": [
        {"section": "verifier", "recorded_by": "verifier", "round": 2,
         "kind": "draft_section",
         "content": {"predicates": [{"kind": "api_smoke", "assert_": "200"}]}},
    ]}}}
    stub = _StubAgent(agent_id="verifier")
    stub.workhub = _FakeWorkhubWithPages(pages)
    stub._hubs = SimpleNamespace(workhub=stub.workhub)
    _bind_messaging_methods(stub)
    _bind_revision_section_helper(stub)

    _run(_revision_handler()(stub, _StubMessage(_revision_payload(agent_id="verifier"), "kickoff_revision_request")))

    # No backup write — LLM's own decision preserved.
    assert stub.workhub.calls == []


def test_revision_handler_non_reviser_skips_handler_entirely():
    """Defensive: an agent receiving the broadcast but not in revisers
    must early-return BEFORE the agentic loop runs AND before the
    backup helper writes anything. We don't want to scribble auto-backup
    stubs for agents that were intentionally skipped."""
    pages = {"mtg-1": {"metadata": {"decisions": []}}}
    stub = _StubAgent(agent_id="backend")  # NOT in revisers (frontend + verifier)
    stub.workhub = _FakeWorkhubWithPages(pages)
    stub._hubs = SimpleNamespace(workhub=stub.workhub)
    _bind_messaging_methods(stub)
    _bind_revision_section_helper(stub)

    _run(_revision_handler()(stub, _StubMessage(_revision_payload(), "kickoff_revision_request")))

    # No agentic loop, no backup write.
    assert stub._agentic_loop_calls == []
    assert stub.workhub.calls == []


# ---------------------------------------------------------------------------
# Round 8h Fix #G: expected_attendees_for_round + current_phase
# ---------------------------------------------------------------------------


def test_expected_attendees_round1_returns_fallback():
    """Round 1: there's no prior facilitator_note; expected_attendees
    is the full original list (the caller's fallback)."""
    from multi_agent.runtime.kickoff.facilitate import expected_attendees_for_round
    assert expected_attendees_for_round([], 1, ["backend", "frontend", "verifier"]) == ["backend", "frontend", "verifier"]


def test_expected_attendees_round2_uses_revisers_from_facilitator_note():
    """Round 2 must derive attendees from round-1 facilitator_note's
    revisers list, NOT the full original attendee list. This is the
    smoke #9-sextus fix: backend was excluded from revisers but
    current_phase kept waiting on it."""
    from multi_agent.runtime.kickoff.facilitate import expected_attendees_for_round
    decisions = [
        {"section": "facilitator_note", "recorded_by": "orchestrator",
         "round": 1, "recorded_at": 1.0,
         "content": {"action": "request_revision",
                     "revisers": ["frontend", "verifier"]}},
    ]
    out = expected_attendees_for_round(decisions, 2, ["backend", "frontend", "verifier"])
    assert out == ["frontend", "verifier"]


def test_expected_attendees_round2_consensus_falls_back_to_full_set():
    """Defensive: if round-1 facilitator_note action != request_revision
    (e.g. an explicit consensus that the driver shouldn't be polling
    on anyway), fall back to the full set rather than returning empty
    or invalid. The driver normally shouldn't reach round 2 in that
    case, but the function MUST stay defensive."""
    from multi_agent.runtime.kickoff.facilitate import expected_attendees_for_round
    decisions = [
        {"section": "facilitator_note", "recorded_by": "orchestrator",
         "round": 1, "recorded_at": 1.0,
         "content": {"action": "consensus", "rationale": "all good"}},
    ]
    out = expected_attendees_for_round(decisions, 2, ["backend", "frontend", "verifier"])
    assert out == ["backend", "frontend", "verifier"]


def test_expected_attendees_round2_uses_latest_note_when_multiple():
    """If the orchestrator amended its round-1 facilitator_note (rare
    but allowed), the LATEST recorded_at wins."""
    from multi_agent.runtime.kickoff.facilitate import expected_attendees_for_round
    decisions = [
        {"section": "facilitator_note", "recorded_by": "orchestrator",
         "round": 1, "recorded_at": 1.0,
         "content": {"action": "request_revision",
                     "revisers": ["backend"]}},  # earlier
        {"section": "facilitator_note", "recorded_by": "orchestrator",
         "round": 1, "recorded_at": 2.0,
         "content": {"action": "request_revision",
                     "revisers": ["frontend", "verifier"]}},  # later — wins
    ]
    out = expected_attendees_for_round(decisions, 2, ["backend", "frontend", "verifier"])
    assert out == ["frontend", "verifier"]


# ---------------------------------------------------------------------------
# Round 8h Fix #H: current_round MUST ignore decisions with sections
# outside the protocol vocabulary. Smoke #9-septimus regression:
# orchestrator's facilitator LLM wrote section='orchestrator' round=2
# BEFORE its real round-1 facilitator_note, bumping current_round
# prematurely and making the driver skip the request_revisions dispatch.
# ---------------------------------------------------------------------------


class _StubHubsWithDecisions:
    def __init__(self, decisions):
        self.workhub = _FakeWorkhubWithPages({
            "mtg-1": {"metadata": {
                "decisions": decisions,
                "expected_attendees": ["backend", "frontend", "verifier"],
            }},
        })


def test_current_round_ignores_stray_section_decision():
    """Smoke #9-septimus regression: orchestrator wrote an off-script
    decision with section='orchestrator' round=2 (kind='kickoff_facilitation',
    a "summary" entry) during its facilitator turn. The real round-1
    facilitator_note arrived 13 seconds later. Pre-Fix-H, current_round
    saw round=2 immediately and the driver skipped request_revisions
    because phase progressed past 'facilitator' before
    read_facilitator_decision was called.

    Fix #H: only count decisions whose section is in the protocol
    vocabulary (phase_ack / comment / facilitator_note / attendee names)."""
    from multi_agent.runtime.kickoff import facilitate
    hubs = _StubHubsWithDecisions([
        # round-1 attendee section: legit
        {"section": "backend", "recorded_by": "backend", "round": 1,
         "kind": "draft_section", "content": {"section": "backend"}},
        # round-1 facilitator_note: legit
        {"section": "facilitator_note", "recorded_by": "orchestrator", "round": 1,
         "kind": "facilitator_decision",
         "content": {"action": "request_revision", "revisers": ["frontend"]}},
        # STRAY: orchestrator wrote section='orchestrator' round=2 off-script.
        # MUST NOT bump current_round.
        {"section": "orchestrator", "recorded_by": "orchestrator", "round": 2,
         "kind": "kickoff_facilitation",
         "content": {"status": "revisions_requested", "summary": "..."}},
    ])
    r = facilitate.current_round(hubs, "mtg-1")
    assert r == 1, (
        f"current_round must ignore stray sections outside the protocol "
        f"vocabulary. Got {r}; expected 1 (the round of the only "
        "protocol-relevant decisions). Pre-Fix-H this returned 2 and the "
        "driver skipped the request_revisions dispatch."
    )


def test_current_round_advances_when_a_real_round2_section_lands():
    """Sanity: when a legit round-2 attendee section is written
    (the reviser actually re-submitted), current_round SHOULD advance."""
    from multi_agent.runtime.kickoff import facilitate
    hubs = _StubHubsWithDecisions([
        {"section": "backend", "recorded_by": "backend", "round": 1,
         "kind": "draft_section"},
        {"section": "facilitator_note", "recorded_by": "orchestrator", "round": 1,
         "kind": "facilitator_decision",
         "content": {"action": "request_revision", "revisers": ["frontend"]}},
        # Real round-2 reviser section (frontend re-submission):
        {"section": "frontend", "recorded_by": "frontend", "round": 2,
         "kind": "draft_section", "content": {"section": "frontend"}},
    ])
    assert facilitate.current_round(hubs, "mtg-1") == 2


def test_current_round_counts_phase_ack_and_comment_as_protocol():
    """Defensive: phase_ack + comment decisions count toward
    round-tracking even though they're not attendee sections per se."""
    from multi_agent.runtime.kickoff import facilitate
    hubs = _StubHubsWithDecisions([
        # Only a single round-3 phase_ack (no attendee sections at all).
        # Still bumps current_round to 3 because phase_ack is protocol vocab.
        {"section": "phase_ack", "recorded_by": "verifier", "round": 3,
         "kind": "comment_phase_done",
         "content": {"ack": True, "phase": "comment"}},
    ])
    assert facilitate.current_round(hubs, "mtg-1") == 3


def test_current_round_attendee_section_alone_bumps_round():
    """Sanity: an attendee section decision IS protocol-relevant."""
    from multi_agent.runtime.kickoff import facilitate
    hubs = _StubHubsWithDecisions([
        {"section": "verifier", "recorded_by": "verifier", "round": 5,
         "kind": "draft_section"},
    ])
    assert facilitate.current_round(hubs, "mtg-1") == 5


# ---------------------------------------------------------------------------
# Round 8h Fix #O: invented-action coercion. Smoke #9-duodecimus
# (2026-06-03 03:51) caught the facilitator LLM writing action=
# "accept_revision_and_recenter" with a clearly-consensus rationale;
# strict matching pushed it to escalate→fallback. Keyword-based
# coercion recovers the LLM's intent for the common variants.
# ---------------------------------------------------------------------------


def test_coerce_invented_action_accept_recenter_maps_to_consensus():
    """The exact smoke #9-duodecimus regression as a unit test."""
    from multi_agent.runtime.kickoff.facilitate import _coerce_invented_action
    assert _coerce_invented_action("accept_revision_and_recenter") == "consensus"


def test_coerce_invented_action_consensus_keywords():
    from multi_agent.runtime.kickoff.facilitate import _coerce_invented_action
    for variant in (
        "approve",
        "ready_to_finalize",
        "PROCEED",
        "Finalize",
        "confirm_contract",
        "align_and_proceed",
    ):
        assert _coerce_invented_action(variant) == "consensus", variant


def test_coerce_invented_action_revision_keywords():
    from multi_agent.runtime.kickoff.facilitate import _coerce_invented_action
    for variant in (
        "revise_again",
        "request_revision_v2",
        "rework_predicates",
        "amend_contract",
        "redo_round",
    ):
        assert _coerce_invented_action(variant) == "request_revision", variant


def test_coerce_invented_action_escalate_keywords():
    from multi_agent.runtime.kickoff.facilitate import _coerce_invented_action
    for variant in (
        "escalate_to_fallback",
        "abort_kickoff",
        "abandon_contract",
        "fail_loud",
    ):
        assert _coerce_invented_action(variant) == "escalate", variant


def test_coerce_invented_action_escalate_keyword_wins_over_revision():
    """If both escalate + revision keywords appear, escalate wins
    (conservative: the LLM is flagging both failure + need-revision, but
    the failure signal is the dominant one)."""
    from multi_agent.runtime.kickoff.facilitate import _coerce_invented_action
    assert _coerce_invented_action("fail_and_revise") == "escalate"


def test_coerce_invented_action_undecipherable_defaults_to_escalate():
    """Conservative fallback for genuinely unknown action strings."""
    from multi_agent.runtime.kickoff.facilitate import _coerce_invented_action
    for variant in (None, "", "asdf", "xyz_123"):
        assert _coerce_invented_action(variant) == "escalate", variant


def test_current_phase_round2_only_waits_on_revisers():
    """Integration: current_phase in a revision round must transition
    out of 'initial' as soon as the revisers (NOT the full attendee
    set) have written their round-2 section decisions. This is the
    smoke #9-sextus regression in a unit test."""
    from multi_agent.runtime.kickoff import facilitate

    # Meeting state: round 1 fully done with facilitator_note=request_revision
    # for [frontend, verifier]. Round 2: frontend + verifier wrote their
    # revised sections; backend did NOT (correctly, backend wasn't a reviser).
    round1_baseline = []
    for sec in ("backend", "frontend", "verifier"):
        _substance = {"backend": {"endpoints": [{"method": "GET", "path": "/api/x"}]},
                      "frontend": {"ui_pages": [{"id": "feed"}]},
                      "verifier": {"predicates": [{"id": "p"}]}}[sec]
        round1_baseline.append({"section": sec, "recorded_by": sec, "round": 1,
                                "kind": "draft_section",
                                "content": {"section": sec, **_substance}})
        for kind in ("comment_phase_done", "reply_phase_done"):
            round1_baseline.append({"section": "phase_ack", "recorded_by": sec,
                                    "round": 1, "kind": kind,
                                    "content": {"ack": True, "phase": kind.split("_")[0]}})
    round1_baseline.append({
        "section": "facilitator_note", "recorded_by": "orchestrator", "round": 1,
        "recorded_at": 100.0,
        "content": {"action": "request_revision",
                    "revisers": ["frontend", "verifier"],
                    "revision_focus": {"frontend": "x", "verifier": "y"}},
    })
    # Round 2: revisers wrote sections. NO acks yet.
    # content carries SUBSTANCE — empty shells no longer advance the phase
    # (substance-gated advance, 2026-06-10).
    round2_sections = [
        {"section": "frontend", "recorded_by": "frontend", "round": 2,
         "kind": "draft_section",
         "content": {"section": "frontend", "ui_pages": [{"id": "feed", "route": "/feed"}]}},
        {"section": "verifier", "recorded_by": "verifier", "round": 2,
         "kind": "draft_section",
         "content": {"section": "verifier", "predicates": [{"id": "p1", "description": "feed works"}]}},
    ]
    pages = {"mtg-1": {"metadata": {"decisions": round1_baseline + round2_sections}}}
    stub_hubs = SimpleNamespace(workhub=_FakeWorkhubWithPages(pages))

    # With the fix: round-2 expected attendees = [frontend, verifier] only.
    # Both wrote round-2 sections; phase advances past "initial" → "facilitator"
    # (the comment/reply consensus phases were removed 2026-06-09; once every
    # round-attendee has authored, the driver synthesizes directly).
    phase = facilitate.current_phase(stub_hubs, "mtg-1", ["backend", "frontend", "verifier"])
    assert phase == "facilitator", (
        f"round-2 current_phase must use facilitator_note.revisers (not "
        f"the full attendee list) as the expected set, then advance past "
        f"'initial'. Got {phase!r}. Before Fix #G this returned 'initial' "
        "forever because backend never wrote a round-2 section (correctly — "
        "backend wasn't a reviser)."
    )


# ---------------------------------------------------------------------------
# Round 8g Fix #D: facilitator phase MUST guarantee a facilitator_note.
# Smoke #9-quater caught the orchestrator's chairing LLM finishing with
# a prose summary instead of a structured facilitator_note decision; the
# driver then waited forever for a decision that never arrived.
# ---------------------------------------------------------------------------


def _facilitate_handler():
    from multi_agent.agents.runtime.messaging import AgentMessaging
    return AgentMessaging._handle_kickoff_facilitate_request


def _bind_facilitator_helper(stub: "_StubAgent") -> None:
    from multi_agent.agents.runtime.messaging import AgentMessaging
    import types
    stub._ensure_facilitator_note = types.MethodType(  # type: ignore[attr-defined]
        AgentMessaging._ensure_facilitator_note, stub,
    )


def _facilitate_payload(round_n: int = 1) -> Dict[str, Any]:
    return {
        "meeting_id": "mtg-1",
        "milestone_index": 1,
        "current_round": round_n,
        "max_rounds": 3,
        "last_synthesis_status": "conflict",
        "cross_check_findings": [],
        "cross_check_revisers": {},
    }


def test_facilitate_handler_auto_writes_escalate_when_llm_skips_note(monkeypatch):
    """Smoke #9-quater regression: orchestrator chaired but finish()d
    without writing a structured facilitator_note. Handler's finally
    block MUST write a backup escalate so the driver can fall through
    to synthesize_fallback rather than waiting forever."""
    from multi_agent.runtime.kickoff import facilitate
    monkeypatch.setattr(facilitate, "read_facilitator_decision",
                        lambda h, kh: None)

    stub = _StubAgent(agent_id="orchestrator")
    _bind_messaging_methods(stub)
    _bind_facilitator_helper(stub)

    _run(_facilitate_handler()(stub, _StubMessage(_facilitate_payload(), "kickoff_facilitate_request")))

    assert len(stub.workhub.calls) == 1
    call = stub.workhub.calls[0]
    assert call["agent"] == "orchestrator"
    assert call["milestone_index"] == 1
    dec = call["decision"]
    assert dec["section"] == "facilitator_note"
    assert dec["round"] == 1
    assert dec["content"]["action"] == "escalate"
    assert dec["content"]["source"] == "auto_backup"
    # The rationale should mention the upstream synthesis status so
    # downstream audit can correlate the auto-escalate with the LLM's
    # last-known view of the meeting.
    assert "conflict" in dec["content"]["rationale"]


def test_facilitate_handler_does_not_double_write_when_llm_already_wrote_note():
    """LLM-written facilitator_note MUST be preserved verbatim.

    Round 8h Fix #D-bis: smoke #9-quindecimus showed the old
    monkey-patch-based check insufficient because Fix #D-bis now
    scans pages.value() directly. Build a hub with a pre-existing
    LLM-written note and verify no backup is added."""
    pages = {"mtg-1": {"metadata": {"decisions": [
        {"section": "facilitator_note", "recorded_by": "orchestrator",
         "round": 1, "kind": "facilitator_decision",
         "content": {"action": "consensus", "rationale": "LLM said go"}},
    ]}}}
    stub = _StubAgent(agent_id="orchestrator")
    stub.workhub = _FakeWorkhubWithPages(pages)
    stub._hubs = SimpleNamespace(workhub=stub.workhub)
    _bind_messaging_methods(stub)
    _bind_facilitator_helper(stub)

    _run(_facilitate_handler()(stub, _StubMessage(_facilitate_payload(), "kickoff_facilitate_request")))

    # No backup write — the LLM's own facilitator_note is preserved.
    assert stub.workhub.calls == []


def test_facilitate_handler_does_not_overwrite_multiple_llm_notes_with_invented_actions():
    """Smoke #9-quindecimus regression: LLM wrote 2 facilitator_notes
    in one turn (one with canonical action, one with invented
    'request_revision_followup' action). Both should be preserved;
    Fix #D-bis must NOT write a backup escalate over them."""
    pages = {"mtg-1": {"metadata": {"decisions": [
        {"section": "facilitator_note", "recorded_by": "orchestrator",
         "round": 1, "kind": "facilitator_decision", "recorded_at": 1.0,
         "content": {"action": "request_revision",
                     "revisers": ["backend"]}},
        # Same round, slightly later, invented action — would coerce
        # to "request_revision" via Fix #O.
        {"section": "facilitator_note", "recorded_by": "orchestrator",
         "round": 1, "kind": "facilitator_decision", "recorded_at": 2.0,
         "content": {"action": "request_revision_followup",
                     "revisers": ["backend", "frontend"]}},
    ]}}}
    stub = _StubAgent(agent_id="orchestrator")
    stub.workhub = _FakeWorkhubWithPages(pages)
    stub._hubs = SimpleNamespace(workhub=stub.workhub)
    _bind_messaging_methods(stub)
    _bind_facilitator_helper(stub)

    _run(_facilitate_handler()(stub, _StubMessage(_facilitate_payload(), "kickoff_facilitate_request")))

    # No backup write — both LLM notes are preserved verbatim.
    assert stub.workhub.calls == []


def test_facilitate_handler_writes_backup_when_only_auto_backups_exist():
    """Defensive: if the only "facilitator_notes" present are prior
    auto_backup entries (from an earlier handler invocation), Fix
    #D-bis still writes a fresh backup so the driver has a current-
    round decision to act on. The intent of the auto_backup filter
    is to ignore the OWN auto_backup writes when assessing whether
    the LLM authored a real note."""
    pages = {"mtg-1": {"metadata": {"decisions": [
        # Only an auto_backup exists — pre-existing from a stale run
        # or a previous attempt at the same round.
        {"section": "facilitator_note", "recorded_by": "orchestrator",
         "round": 1, "kind": "facilitator_decision", "recorded_at": 0.5,
         "content": {"action": "escalate", "source": "auto_backup"}},
    ]}}}
    stub = _StubAgent(agent_id="orchestrator")
    stub.workhub = _FakeWorkhubWithPages(pages)
    stub._hubs = SimpleNamespace(workhub=stub.workhub)
    _bind_messaging_methods(stub)
    _bind_facilitator_helper(stub)

    _run(_facilitate_handler()(stub, _StubMessage(_facilitate_payload(), "kickoff_facilitate_request")))

    # A fresh backup is written (only auto_backup exists, not a real LLM note).
    assert len(stub.workhub.calls) == 1
    assert stub.workhub.calls[0]["decision"]["content"]["action"] == "escalate"


def test_facilitate_handler_writes_backup_even_if_agentic_loop_raises(monkeypatch):
    """Exception in agentic loop must still trigger the backup escalate."""
    from multi_agent.runtime.kickoff import facilitate
    monkeypatch.setattr(facilitate, "read_facilitator_decision",
                        lambda h, kh: None)

    stub = _StubAgent(agent_id="orchestrator")
    _bind_messaging_methods(stub)
    _bind_facilitator_helper(stub)

    async def _raise(*, system_prompt, initial_prompt, max_steps):
        raise RuntimeError("simulated chair crash")
    stub.run_agentic_loop = _raise  # type: ignore[assignment]

    _run(_facilitate_handler()(stub, _StubMessage(_facilitate_payload(), "kickoff_facilitate_request")))

    assert len(stub.workhub.calls) == 1
    assert stub.workhub.calls[0]["decision"]["content"]["action"] == "escalate"
    assert stub.workhub.calls[0]["decision"]["content"]["source"] == "auto_backup"
