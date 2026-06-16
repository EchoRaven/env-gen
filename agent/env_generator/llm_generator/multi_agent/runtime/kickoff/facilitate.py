"""Multi-round kickoff meeting facilitation (round 8f.1).

WHY
---
Round 8e and earlier modelled the kickoff as a **parallel paper-submission**:
each attendee independently authored its section, the cross_check_suite
caught conflicts after the fact, and the arbitration table picked a
reviser. That worked but didn't match the word "meeting" — attendees
couldn't see each other's contributions during authoring, and no facilitator
synthesized the discussion into a coherent contract.

Round 8f.1 introduces a **real meeting protocol** with the orchestrator as
the LLM-driven facilitator (mirroring a real software-engineering kickoff
or sprint-planning meeting):

  Round 1 — Initial proposals
    Each attendee (backend / frontend / verifier) authors their section
    blind, via the existing kickoff_response_prompt path. No change.

  Facilitator turn — Orchestrator reviews
    The orchestrator LLM is woken via a new ``kickoff_facilitate_request``
    event. It reads ALL attendee decisions from
    ``meeting.metadata.decisions[]``, runs the cross_check_suite mentally,
    and authors a ``facilitator_note`` decision declaring one of three
    outcomes:
      - ``consensus``     — all sections aligned, ready to finalize
      - ``request_revision`` — specific attendees should revise specific
                               sections; declares the reviser set
      - ``escalate``      — irreconcilable; fail kickoff loud

  Round 2 (only if ``request_revision``) — Revisions
    The flagged revisers wake via a new ``kickoff_revision_request`` event.
    They render the new ``kickoff_revision_prompt`` macro, which lets them
    READ all prior decisions + the facilitator note, then re-author their
    section (kind=``proposal_v2``). Non-flagged attendees do not wake.

  Repeat — Up to ``KICKOFF_MAX_ROUNDS`` (default 3). After the cap, the
    driver falls through to ``synthesize_fallback`` (existing) and aborts
    cleanly with ``kickoff_failed``.

The orchestrator's facilitator turn IS the meeting's chair — its verdict
on each round is the trusted source of truth. ``try_synthesize`` still
runs as a cross-check (it would surface a verdict the facilitator's LLM
missed) but the facilitator's structured decision is the primary signal.

Closed-by-construction discipline (mirrors sibling kickoff modules):
  * Required arguments validated at the function boundary.
  * Each helper returns a structured dict the caller pattern-matches.
  * No LLM call here — the facilitator LLM runs in the orchestrator
    agent's runtime via its kickoff_facilitate_request handler. This
    module's job is the wire protocol: dispatching events, reading
    facilitator decisions, advancing rounds.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

__all__ = [
    "KICKOFF_MAX_ROUNDS",
    "FACILITATOR_ACTIONS",
    "MEETING_PHASES",
    "request_facilitation",
    "read_facilitator_decision",
    "request_revisions",
    "request_comment_phase",
    "request_reply_phase",
    "current_round",
    "current_phase",
    "phase_acked_by",
]


# Maximum number of rounds before the driver gives up. Round 1 (initial
# proposals) + at most KICKOFF_MAX_ROUNDS-1 revision rounds.
#
# Set to 1 (NO revision rounds) by construction: a revision round is a multi-agent
# re-negotiation whose REPLY phase blocks on every attendee posting a phase_ack —
# exactly where resident agents suppress their wakeup and the kickoff hangs to the
# global timeout (instagram M2 died in round 2's reply phase at 1135s). With the
# deterministic reconcile (auto-register undefined endpoints + downgrade a missing
# predicate) now resolving cross-check findings on its own, a round-1 conflict goes
# straight to that reconcile instead of an agent revision round that won't converge.
# Consistency is enforced by the delivery gates (A/B/C), not by re-negotiating to
# consensus.
KICKOFF_MAX_ROUNDS: int = 1

# Round 8h refactor: action vocabulary + coercion live in
# schema_tolerance. Aliases preserve the module-private name used by
# in-module call sites.
from .schema_tolerance import (  # noqa: E402
    FACILITATOR_ACTIONS,
    coerce_facilitator_action as _coerce_invented_action,
)

# Round 8g: phase-aware meeting protocol. Each ROUND iterates through
# these phases sequentially:
#   - "initial"  — attendees author their kickoff section blind
#                  (parallel; emits decision section=<agent>, kind=proposal_v{N})
#   - "comment"  — attendees read all initial drafts and post 0+ comments
#                  on others' sections (parallel; emits section="comment"
#                  decisions; finishes with section="phase_ack",
#                  kind="comment_phase_done")
#   - "reply"    — original authors read comments on their own decisions
#                  and either reply (more comments), revise (new
#                  proposal_v{N+1}), or ack-and-move-on (parallel;
#                  finishes with section="phase_ack", kind="reply_phase_done")
#   - "facilitator" — orchestrator reads everything, decides one of
#                  FACILITATOR_ACTIONS; records section="facilitator_note"
#
# After "facilitator", if action == "request_revision", the listed
# revisers wake into Round N+1 "initial" (only the revisers, not the
# whole attendee set — non-revisers' decisions carry over).
MEETING_PHASES = ("initial", "comment", "reply", "facilitator")


def request_facilitation(
    hubs: Any,
    kickoff_handle: Mapping[str, Any],
    last_synthesis: Mapping[str, Any],
    agent: str = "orchestrator",
) -> Dict[str, Any]:
    """Fire a ``kickoff_facilitate_request`` event to the orchestrator.

    Called by the driver AFTER ``try_synthesize`` returns either
    ``conflict`` or ``ready`` (we want the facilitator's signoff even on
    ready, to give the orchestrator a chance to author the milestone
    documents). The orchestrator agent's ``_handle_kickoff_facilitate_request``
    handler picks it up and renders the ``kickoff_facilitation_prompt``
    macro.

    Args:
        hubs: hub registry with ``hubs.eventhub.publish_event``.
        kickoff_handle: handle from ``start_kickoff``.
        last_synthesis: the most-recent ``try_synthesize`` result. Carries
            cross-check findings / revisers / contract so the facilitator
            doesn't need to re-derive them. Acceptable for the synthesis
            to be ``status='ready'`` too (facilitator can ack consensus).
        agent: caller identity (default 'orchestrator').

    Returns:
        ``{"event_id": <id>, "round": <int>, "meeting_id": <str>}``
    """
    if not isinstance(kickoff_handle, Mapping):
        raise ValueError(
            "kickoff_handle MUST be a Mapping returned by start_kickoff"
        )
    meeting_id = kickoff_handle.get("meeting_id")
    if not isinstance(meeting_id, str) or not meeting_id.strip():
        raise ValueError("kickoff_handle.meeting_id MUST be non-empty str")
    milestone_index = kickoff_handle.get("milestone_index")
    round_n = current_round(hubs, meeting_id)
    findings = list((last_synthesis or {}).get("findings") or [])
    revisers = dict((last_synthesis or {}).get("revisers") or {})
    last_status = (last_synthesis or {}).get("status", "unknown")

    result = hubs.eventhub.publish_event(
        source_hub="orchestrator",
        event_type="kickoff_facilitate_request",
        payload={
            "meeting_id": meeting_id,
            "milestone_index": milestone_index,
            "current_round": round_n,
            "max_rounds": KICKOFF_MAX_ROUNDS,
            "last_synthesis_status": last_status,
            "cross_check_findings": findings,
            "cross_check_revisers": revisers,
        },
        recipients=["orchestrator"],
        priority="high",
        caller=agent,
    )
    return {
        "event_id": (result or {}).get("id") if isinstance(result, Mapping) else None,
        "round": round_n,
        "meeting_id": meeting_id,
    }


def read_facilitator_decision(
    hubs: Any,
    kickoff_handle: Mapping[str, Any],
) -> Optional[Dict[str, Any]]:
    """Return the LATEST ``facilitator_note`` decision for this round.

    The driver polls this after firing ``request_facilitation``. When the
    orchestrator's facilitator LLM finishes and calls
    ``workhub_add_meeting_decision(section='facilitator_note', ...)``,
    the decision lands in ``meeting.metadata.decisions[]`` with a
    ``round`` field. We filter to the LATEST round.

    Returns:
        The full facilitator_note decision dict if found for the current
        round, else None (the orchestrator is still authoring).

    Expected facilitator_note content shape (round 8f.1):
        {
            "section": "facilitator_note",
            "agent": "orchestrator",
            "round": <int, matches current_round>,
            "content": {
                "action": "consensus" | "request_revision" | "escalate",
                "rationale": "<one-paragraph LLM summary>",
                # required when action == "request_revision":
                "revisers": ["backend", "frontend", ...],
                "revision_focus": {
                    "backend": "<what to revise>",
                    ...
                },
                # optional:
                "acks_consensus_on": ["api_endpoints", "ui_pages", ...],
                "open_questions": [...],
            },
            "recorded_at": <float>,
            "recorded_by": "orchestrator",
        }
    """
    if not isinstance(kickoff_handle, Mapping):
        raise ValueError("kickoff_handle MUST be a Mapping")
    meeting_id = kickoff_handle.get("meeting_id")
    if not isinstance(meeting_id, str) or not meeting_id.strip():
        raise ValueError("kickoff_handle.meeting_id MUST be non-empty str")

    # Re-read the meeting page to pick up freshly-added decisions.
    page = _read_meeting_page(hubs, meeting_id)
    decisions = (page.get("metadata") or {}).get("decisions") or []

    target_round = current_round(hubs, meeting_id)
    facilitator_notes = [
        d for d in decisions
        if _decision_section(d) == "facilitator_note"
        and (d.get("agent") or d.get("recorded_by")) == "orchestrator"
        and _decision_round(d) == target_round
    ]
    if not facilitator_notes:
        return None
    # The latest by recorded_at — the orchestrator might amend its note
    # mid-round (allowed but rare); take the most recent.
    return max(facilitator_notes, key=lambda d: d.get("recorded_at") or 0.0)


def request_revisions(
    hubs: Any,
    kickoff_handle: Mapping[str, Any],
    revisers: List[str],
    facilitator_note: Mapping[str, Any],
    agent: str = "orchestrator",
) -> Dict[str, Any]:
    """Broadcast ``kickoff_revision_request`` to the flagged revisers.

    The driver calls this after reading a facilitator_note with
    ``action == 'request_revision'``. Only the listed revisers wake;
    other attendees stay quiet (no churn).

    Each reviser's ``_handle_kickoff_revision_request`` renders the
    ``kickoff_revision_prompt`` macro, which exposes ALL prior decisions
    + the facilitator_note + the per-reviser ``revision_focus`` field.

    Args:
        hubs: hub registry with eventhub.
        kickoff_handle: handle from start_kickoff.
        revisers: list of agent_ids to wake. Must be non-empty.
        facilitator_note: the latest facilitator_note decision (its
            ``content`` field is included in the event payload so revisers
            don't have to re-read it).
        agent: caller identity.

    Returns:
        ``{"event_id": <id>, "new_round": <int>, "revisers": [...]}``
    """
    if not isinstance(kickoff_handle, Mapping):
        raise ValueError("kickoff_handle MUST be a Mapping")
    meeting_id = kickoff_handle.get("meeting_id")
    if not isinstance(meeting_id, str) or not meeting_id.strip():
        raise ValueError("kickoff_handle.meeting_id MUST be non-empty str")
    milestone_index = kickoff_handle.get("milestone_index")
    if not isinstance(revisers, list) or not revisers:
        raise ValueError("revisers MUST be a non-empty list of agent_ids")
    if not all(isinstance(r, str) and r.strip() for r in revisers):
        raise ValueError("every reviser MUST be a non-empty str")

    # The current_round helper reflects the round that just concluded;
    # the revision round is one higher.
    new_round = current_round(hubs, meeting_id) + 1
    fc_content = (facilitator_note or {}).get("content") or {}

    result = hubs.eventhub.publish_event(
        source_hub="orchestrator",
        event_type="kickoff_revision_request",
        payload={
            "meeting_id": meeting_id,
            "milestone_index": milestone_index,
            "current_round": new_round,
            "max_rounds": KICKOFF_MAX_ROUNDS,
            "revisers": list(revisers),
            "revision_focus": fc_content.get("revision_focus") or {},
            "facilitator_rationale": fc_content.get("rationale") or "",
            "acks_consensus_on": fc_content.get("acks_consensus_on") or [],
            "open_questions": fc_content.get("open_questions") or [],
        },
        recipients=list(revisers),
        priority="high",
        caller=agent,
    )
    return {
        "event_id": (result or {}).get("id") if isinstance(result, Mapping) else None,
        "new_round": new_round,
        "revisers": list(revisers),
    }


# Round 8h refactor: protocol-section vocabulary + decision filter
# live in schema_tolerance — see Fix #H rationale there. Aliases
# preserve the module-private name used by current_round below.
from .schema_tolerance import (  # noqa: E402
    PROTOCOL_FIXED_SECTIONS,
    is_protocol_decision as _is_protocol_decision,
)


def current_round(hubs: Any, meeting_id: str) -> int:
    """Return the highest round number recorded across PROTOCOL decisions
    in this meeting (round 8h Fix #H). Round 1 = initial proposals;
    revisions increment.

    Decisions with section names that aren't part of the protocol
    vocabulary (PROTOCOL_FIXED_SECTIONS) are treated as metadata noise
    and do not advance the round counter. This prevents a stray
    off-script LLM decision (e.g. orchestrator writing
    section='orchestrator' round=2 to log a "summary" during its
    facilitator turn) from prematurely bumping the round before the
    legitimate facilitator_note for the current round is written.

    Returns 1 if no protocol decisions yet declare a round (back-compat:
    pre-8f.1 decisions don't carry a round field).
    """
    if not isinstance(meeting_id, str) or not meeting_id.strip():
        return 1
    try:
        page = _read_meeting_page(hubs, meeting_id)
    except Exception:
        return 1
    decisions = (page.get("metadata") or {}).get("decisions") or []
    # We don't have attendee_sections context here — current_round is
    # called by the driver per poll; the per-meeting expected_sections
    # is stable so resolve it once and reuse via a closed-over set.
    # In practice EXPECTED_SECTIONS from run_kickoff is the canonical
    # answer (backend/frontend/verifier). Avoid a circular import by
    # accepting any attendee-shaped section here.
    attendee_sections = _meeting_attendee_sections(page)
    rounds = [
        _decision_round(d)
        for d in decisions
        if isinstance(d, Mapping) and _is_protocol_decision(d, attendee_sections)
    ]
    rounds = [r for r in rounds if isinstance(r, int) and r >= 1]
    return max(rounds) if rounds else 1


def _meeting_attendee_sections(page: Mapping[str, Any]) -> frozenset:
    """Best-effort extraction of attendee section names from the meeting
    page. Looks at metadata.expected_attendees first (canonical, set by
    start_kickoff), then falls back to the union of section names that
    appear in non-phase_ack/non-comment/non-facilitator_note decisions."""
    meta = page.get("metadata") or {}
    expected = meta.get("expected_attendees") or meta.get("attendees") or []
    if isinstance(expected, list) and expected:
        return frozenset(str(a).strip() for a in expected if str(a).strip())
    decisions = meta.get("decisions") or []
    discovered = set()
    for d in decisions:
        if not isinstance(d, Mapping):
            continue
        sec = _decision_section(d)
        if sec and sec not in PROTOCOL_FIXED_SECTIONS:
            discovered.add(sec)
    return frozenset(discovered)


def expected_attendees_for_round(
    decisions: List[Mapping[str, Any]],
    round_n: int,
    fallback: List[str],
) -> List[str]:
    """Return the attendees expected to participate in ``round_n``.

    Round 8h Fix #G: in round 1 every original attendee writes a section;
    in revision rounds (N > 1) ONLY the revisers named by the prior
    round's ``facilitator_note`` are asked to re-author. Counting the
    full attendee set in revision rounds wedges the meeting in
    ``initial`` forever waiting on non-revisers who were correctly not
    woken up (smoke #9-sextus, 2026-06-03 00:48: backend was not a
    reviser, never wrote a round-2 section, current_phase stayed at
    initial until the 1200s driver timeout).

    For round_n >= 2, look up the latest ``facilitator_note`` recorded
    in round_n-1 with action="request_revision" and use its
    ``content.revisers`` list. Fall back to ``fallback`` (typically the
    original attendees from the kickoff_handle) when no qualifying
    facilitator_note exists — that path keeps the function defensive
    for malformed meetings and preserves round-1 behavior.
    """
    if round_n < 2:
        return list(fallback)
    prior_round = round_n - 1
    facilitator_notes: List[Mapping[str, Any]] = []
    for d in decisions:
        if not isinstance(d, Mapping):
            continue
        if _decision_section(d) != "facilitator_note":
            continue
        if _decision_round(d) != prior_round:
            continue
        if (d.get("agent") or d.get("recorded_by")) != "orchestrator":
            continue
        facilitator_notes.append(d)
    if not facilitator_notes:
        return list(fallback)
    latest = max(facilitator_notes, key=lambda d: d.get("recorded_at") or 0.0)
    content = latest.get("content") or {}
    if not isinstance(content, Mapping):
        return list(fallback)
    if content.get("action") != "request_revision":
        # Prior round wasn't a revision dispatch — defensive fallthrough.
        return list(fallback)
    revisers = content.get("revisers")
    if not isinstance(revisers, list) or not revisers:
        return list(fallback)
    out = [str(a).strip() for a in revisers if str(a).strip()]
    return out or list(fallback)


def current_phase(
    hubs: Any,
    meeting_id: str,
    expected_attendees: List[str],
) -> str:
    """Compute which phase of the current round the meeting is in.

    Round 8g: each round iterates through phases initial → comment →
    reply → facilitator. The phase is derived from what's already in
    ``meeting.metadata.decisions[]`` for the current round; no separate
    storage. The driver calls this on every poll to decide what to do
    next.

    Round 8h Fix #G: the per-round expected attendee set is computed
    via :func:`expected_attendees_for_round` so revision rounds only
    count the revisers, not the original full attendee list.

    Returns one of:
      - "initial"     — not all expected_attendees have recorded their
                        section's initial proposal (kind=proposal_v{N})
                        for the current round.
      - "comment"     — initial drafts complete; not all attendees have
                        posted a "phase_ack" for the comment phase yet.
      - "reply"       — comment phase complete; not all attendees have
                        posted "phase_ack" for the reply phase yet.
      - "facilitator" — reply phase complete; no facilitator_note
                        recorded yet for the current round.
      - "consensus"   — facilitator_note recorded with action=consensus;
                        driver should finalize.
      - "request_revision" / "escalate" — facilitator recorded that
                                          action; driver routes accordingly.
    """
    if not isinstance(meeting_id, str) or not meeting_id.strip():
        raise ValueError("meeting_id MUST be non-empty str")
    if not isinstance(expected_attendees, list) or not expected_attendees:
        raise ValueError("expected_attendees MUST be a non-empty list")
    page = _read_meeting_page(hubs, meeting_id)
    decisions = (page.get("metadata") or {}).get("decisions") or []
    round_n = current_round(hubs, meeting_id)

    # Round 8h Fix #G: derive per-round expected attendees so revision
    # rounds (N > 1) only wait on the revisers from prior-round
    # facilitator_note, not the original full attendee list.
    round_attendees = expected_attendees_for_round(
        decisions, round_n, fallback=expected_attendees,
    )

    # Phase 1: initial drafts — every round_attendee must have a decision
    # whose section is in ATTENDEE_SECTIONS for round_n.
    section_authors = {
        a: False for a in round_attendees
    }
    for d in decisions:
        if not isinstance(d, Mapping):
            continue
        if _decision_round(d) != round_n:
            continue
        sec = _decision_section(d)
        if sec in section_authors:
            # SUBSTANCE-GATED phase advance (2026-06-10): an EMPTY decision
            # (gemini shell / null skeleton) must NOT advance the meeting —
            # live race: the meeting finalized on five empty frontend
            # decisions 2s before the author's corrective turn landed a real
            # one. Substantive content advances; an explicit deferred stub
            # (written only after corrective turns are exhausted) advances;
            # empty shells keep the phase at "initial" so corrective turns
            # get their window.
            from .section_substance import decision_advances_phase
            if decision_advances_phase(d, sec):
                section_authors[sec] = True
    if not all(section_authors.values()):
        return "initial"

    # The comment + reply CONSENSUS phases are removed (2026-06-09, by-construction
    # kickoff). They required EVERY attendee to re-read the meeting + post a phase_ack —
    # which produced "No specific concerns raised" in practice while making each agent
    # re-fetch the whole meeting page ~42× (Gemini also has no clean decisions-read
    # tool, so it fumbles) and blocking the whole phase on the slowest/non-acking
    # attendee to the 1200s timeout. backend↔frontend consistency is NOT provided by
    # that discussion — it is enforced by the deterministic cross-check + reconcile
    # (auto-register a frontend call's missing endpoint) + the delivery gates A/B/C +
    # the fixed response-shape convention. So once every attendee has authored its
    # section ONCE, go STRAIGHT to the facilitator (synthesize / deterministic
    # reconcile): declare-once, not negotiate-to-consensus.

    # Phase: facilitator — orchestrator must record facilitator_note
    # for round_n. If recorded, return the facilitator's action so the
    # driver can route (one of consensus / request_revision / escalate).
    facilitator_notes = [
        d for d in decisions
        if _decision_section(d) == "facilitator_note"
        and (d.get("agent") or d.get("recorded_by")) == "orchestrator"
        and _decision_round(d) == round_n
    ]
    if not facilitator_notes:
        return "facilitator"
    latest = max(facilitator_notes, key=lambda d: d.get("recorded_at") or 0.0)
    content = latest.get("content") or {}
    action = content.get("action")
    if action in FACILITATOR_ACTIONS:
        return action
    # Round 8h Fix #O: keyword-based action recovery. Smoke #9-duodecimus
    # (2026-06-03 03:51) caught the orchestrator's facilitator LLM
    # writing ``action="accept_revision_and_recenter"`` with a rationale
    # that clearly meant consensus ("verifier supplied the missing
    # predicates ... proceed without duplicating kickoff task creation").
    # Treating this as "escalate" forces synthesize_fallback / loud
    # abort, which the user has explicitly flagged as a bad outcome.
    # Map invented action strings to the canonical action whose intent
    # they best match via keyword inspection. Fallback remains escalate
    # for genuinely undecipherable strings.
    return _coerce_invented_action(action)


def phase_acked_by(
    hubs: Any,
    meeting_id: str,
    round_n: int,
    phase: str,
) -> List[str]:
    """Return the list of agent_ids that have posted a phase_ack for
    the given (round, phase) tuple.

    Useful for the driver to log "still waiting on X" without re-computing.
    """
    page = _read_meeting_page(hubs, meeting_id)
    decisions = (page.get("metadata") or {}).get("decisions") or []
    kind_key = f"{phase}_phase_done"
    out: List[str] = []
    for d in decisions:
        if not isinstance(d, Mapping):
            continue
        if _decision_section(d) != "phase_ack":
            continue
        if _decision_round(d) != round_n:
            continue
        content = d.get("content") or {}
        if (d.get("kind") or content.get("kind")) != kind_key:
            continue
        agent = d.get("agent") or d.get("recorded_by")
        if agent and agent not in out:
            out.append(agent)
    return out


def request_comment_phase(
    hubs: Any,
    kickoff_handle: Mapping[str, Any],
    agent: str = "orchestrator",
) -> Dict[str, Any]:
    """Broadcast ``kickoff_comment_phase_request`` to all attendees.

    Called after initial drafts are in. Each attendee wakes via its
    ``_handle_kickoff_comment_phase_request`` handler, reads the
    meeting state (including other attendees' initial drafts), and
    posts 0+ comment decisions before ack'ing the phase.
    """
    if not isinstance(kickoff_handle, Mapping):
        raise ValueError("kickoff_handle MUST be a Mapping")
    meeting_id = kickoff_handle.get("meeting_id")
    if not isinstance(meeting_id, str) or not meeting_id.strip():
        raise ValueError("kickoff_handle.meeting_id MUST be non-empty str")
    milestone_index = kickoff_handle.get("milestone_index")
    attendees = list(kickoff_handle.get("expected_attendees") or [])
    if not attendees:
        raise ValueError("kickoff_handle.expected_attendees MUST be non-empty")
    round_n = current_round(hubs, meeting_id)

    result = hubs.eventhub.publish_event(
        source_hub="orchestrator",
        event_type="kickoff_comment_phase_request",
        payload={
            "meeting_id": meeting_id,
            "milestone_index": milestone_index,
            "current_round": round_n,
            "attendees": attendees,
        },
        recipients=attendees,
        priority="high",
        caller=agent,
    )
    return {
        "event_id": (result or {}).get("id") if isinstance(result, Mapping) else None,
        "round": round_n,
        "phase": "comment",
        "recipients": attendees,
    }


def request_reply_phase(
    hubs: Any,
    kickoff_handle: Mapping[str, Any],
    agent: str = "orchestrator",
) -> Dict[str, Any]:
    """Broadcast ``kickoff_reply_phase_request`` to all attendees.

    Called after comment phase completes. Each attendee wakes via its
    ``_handle_kickoff_reply_phase_request`` handler, reads comments
    targeting its own section, and either replies (more comments),
    revises (new proposal_v{N+local}), or acks-and-moves-on. Each
    attendee MUST end with a phase_ack for the reply phase.
    """
    if not isinstance(kickoff_handle, Mapping):
        raise ValueError("kickoff_handle MUST be a Mapping")
    meeting_id = kickoff_handle.get("meeting_id")
    if not isinstance(meeting_id, str) or not meeting_id.strip():
        raise ValueError("kickoff_handle.meeting_id MUST be non-empty str")
    milestone_index = kickoff_handle.get("milestone_index")
    attendees = list(kickoff_handle.get("expected_attendees") or [])
    if not attendees:
        raise ValueError("kickoff_handle.expected_attendees MUST be non-empty")
    round_n = current_round(hubs, meeting_id)

    result = hubs.eventhub.publish_event(
        source_hub="orchestrator",
        event_type="kickoff_reply_phase_request",
        payload={
            "meeting_id": meeting_id,
            "milestone_index": milestone_index,
            "current_round": round_n,
            "attendees": attendees,
        },
        recipients=attendees,
        priority="high",
        caller=agent,
    )
    return {
        "event_id": (result or {}).get("id") if isinstance(result, Mapping) else None,
        "round": round_n,
        "phase": "reply",
        "recipients": attendees,
    }


# ---------------------------------------------------------------------------
# Internal helpers — read the meeting page and decision rounds defensively
# (decisions may be flat dicts OR nested under .decision, per the round-8c
# wire convention from messaging.py / hub_pages.jsx).
# ---------------------------------------------------------------------------


def _read_meeting_page(hubs: Any, meeting_id: str) -> Mapping[str, Any]:
    """Read the meeting page directly from workhub. Returns {} if missing.

    The kickoff coordinator does NOT depend on a tool wrapper — it goes
    straight to the workhub primitive (stores.pages.value) to avoid
    bouncing through a tool registry the driver doesn't need.
    """
    try:
        pages = hubs.workhub.stores.pages.value() or {}
    except Exception:
        return {}
    page = pages.get(meeting_id) or {}
    if not isinstance(page, Mapping):
        return {}
    return page


def _decision_section(d: Mapping[str, Any]) -> Optional[str]:
    if not isinstance(d, Mapping):
        return None
    return (
        d.get("section")
        or (lambda _i: _i.get("section") if isinstance(_i, Mapping) else None)(d.get("decision"))
    )


def _decision_round(d: Mapping[str, Any]) -> Optional[int]:
    """Return the round field on a decision, or None if not declared.

    Decisions may carry round at top level (the round-8f wire convention)
    OR nested under .decision (legacy). Defaults to 1 for pre-8f.1
    decisions that don't have a round at all.
    """
    if not isinstance(d, Mapping):
        return None
    val = d.get("round")
    if val is None:
        val = (lambda _i: _i.get("round") if isinstance(_i, Mapping) else None)(d.get("decision"))
    if val is None:
        # Pre-8f.1 decisions: treat as round 1 (initial proposals).
        return 1
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _all_phase_acked(
    decisions: List[Mapping[str, Any]],
    round_n: int,
    expected_attendees: List[str],
    kind_key: str,
) -> bool:
    """True iff every expected_attendee has posted a phase_ack decision
    for the given (round, kind) pair. ``kind_key`` is e.g.
    ``comment_phase_done`` or ``reply_phase_done``.
    """
    ackers: set = set()
    for d in decisions:
        if not isinstance(d, Mapping):
            continue
        if _decision_section(d) != "phase_ack":
            continue
        if _decision_round(d) != round_n:
            continue
        content = d.get("content") or {}
        if (d.get("kind") or content.get("kind")) != kind_key:
            continue
        agent = d.get("agent") or d.get("recorded_by")
        if agent:
            ackers.add(agent)
    return all(a in ackers for a in expected_attendees)
