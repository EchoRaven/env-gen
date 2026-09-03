"""Default EventHub subscriptions per agent profile (Cutover 12).

`ensure_default_subscriptions(hubs, agent_id)` is called at the top of
`collect_hub_pulse` to install (idempotently) the subscriptions an agent
needs to receive cross-hub events. EventHub.subscribe is keyed by
`(agent, source_hub, event_type)` so calling this every step is cheap.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

# (source_hub, event_type, priority_floor)
#
# These wire core agents to push-events they previously could only see
# by polling. ``publish_event`` already fans out by subscription, so an
# event whose explicit ``recipients=[]`` (e.g. ``endpoint_defined`` from
# a brand-new endpoint with no consumers) still lands in subscribed
# agents' inboxes — fixing the "frontend finishes but backend never
# wakes" gap.
DEFAULT_SUBSCRIPTIONS: Dict[str, List[Tuple[str, str, str]]] = {
    "orchestrator": [
        # Stuck merges + failed agent tasks must reach orchestrator.
        ("codehub", "merge_conflict", "high"),
        ("workhub", "task_failed", "high"),
        # COMPLETION DISCIPLINE (2026-06-11, user policy): every
        # cancellation must reach the orchestrator — a creator cancelling
        # its own task is legitimate but never silent.
        ("workhub", "task_cancelled", "high"),
        ("workhub", "task_completed", "normal"),
        ("workhub", "task_stale", "high"),
        ("runhub", "run_completed", "normal"),
        ("runhub", "run_failed", "high"),
        # NOTE: endpoint_implemented moved to INBOX_ONLY (F2 wake-storm fix, 2026-07-21):
        # it fired on every contract-surface registration during design/kickoff and woke the
        # orchestrator into idle "ineligible during kickoff" LLM steps. Still surfaced at the
        # next pulse; no resident wakeup.
        # Generic comment/mention surfacing so the orchestrator sees
        # cross-agent escalation comments.
        ("workhub", "comment_created", "normal"),
        # Kickoff loop — attendee decisions are surfaced INBOX-ONLY (see below, F2 fix).
        # Synthesis is driven deterministically by _drive_kickoff_to_completion; the
        # orchestrator is actively chaired via kickoff_facilitate_request / kickoff_detail_request
        # (live, below), so the live meeting_decision_added wake was vestigial churn.
        # Round-8f.1 facilitator: the kickoff driver
        # (``runtime/kickoff/facilitate.py:request_facilitation``)
        # fires this event after ``try_synthesize`` returns
        # ``ready``/``conflict``, asking the orchestrator's LLM
        # to chair the meeting (read attendee decisions, author
        # ONE ``facilitator_note`` decision declaring consensus /
        # request_revision / escalate). Handled by
        # ``_handle_kickoff_facilitate_request`` in messaging.py.
        ("orchestrator", "kickoff_facilitate_request", "high"),
        # Per-milestone KICKOFF-DETAIL turn (2026-06-24): fired at milestone entry
        # (run_kickoff.author_milestone_detail) BEFORE the lanes draft. The orchestrator
        # reviews the roadmap, may revise FUTURE phases + sets THIS phase's detailed
        # detail via the milestone_* tools. Handled by _handle_kickoff_detail_request.
        ("orchestrator", "kickoff_detail_request", "high"),
        # Step B circuit-breaker escalation. Use "*" for source_hub
        # because each lane publishes from its own agent_id.
        ("*", "lane_idle_warning", "normal"),
        ("*", "lane_stuck_failforward", "high"),
        ("*", "lane_halted_human", "urgent"),
        # Tier-3 deterministic action: the breaker auto-failed the
        # lane's in-progress task and emits this so the orchestrator
        # can re-evaluate downstream depends_on and decide on retry.
        ("*", "lane_task_auto_failed", "urgent"),
    ],
    "backend": [
        # Wake up when an endpoint is defined OR when a consumed
        # endpoint's status changes. Backend owns DB + API.
        ("registryhub", "endpoint_defined", "normal"),
        ("registryhub", "endpoint_implemented", "normal"),
        ("registryhub", "endpoint_schema_changed", "high"),
        # PROPOSAL #25 B1: the backend hears ``table_registered`` (the emitted name;
        # ``table_defined`` was a DEAD sub). PRE-LAUNCH AUDIT R2: moved to
        # INBOX_ONLY_SUBSCRIPTIONS below — ``table_registered`` fires on EVERY
        # register_table (incl. idempotent re-registration in the per-tick heal/scaffold
        # loop), so a LIVE sub re-woke the backend each tick (amplification). inbox_only
        # keeps the backend INFORMED (seen at next hub_pulse) without the wakeup churn.
        ("registryhub", "table_implemented", "normal"),
        # NOTE: NO broad ("workhub","task_created") subscription. create_task already
        # emits task_created with recipients=[assignee], so the OWNING lane is woken
        # directly. A blanket subscription re-delivered EVERY lane's task_created to
        # backend (run v11: 93 items, only 42 its own — 51 pure noise) and the
        # for-self wakeup gate then suppressed the rest anyway. The 1-in-94 unassigned
        # task is surfaced in the workhub pulse (pending tasks), not via inbox flood.
        ("codehub", "review_requested", "high"),
        # Kickoff loop.
        ("orchestrator", "kickoff_request", "high"),
        # Round-8f.1 facilitator-driven revision: backend is flagged
        # by the facilitator_note when its draft section needs changes
        # for consensus. Handled by
        # ``_handle_kickoff_revision_request`` in messaging.py.
        ("orchestrator", "kickoff_revision_request", "high"),
        # Round-8g phase-aware meeting: comment + reply phases.
        ("orchestrator", "kickoff_comment_phase_request", "high"),
        ("orchestrator", "kickoff_reply_phase_request", "high"),
        ("orchestrator", "kickoff_complete", "high"),
    ],
    "frontend": [
        # Same wakeup pattern as backend, plus UI-page updates.
        ("registryhub", "endpoint_defined", "normal"),
        ("registryhub", "endpoint_implemented", "normal"),
        ("registryhub", "endpoint_schema_changed", "high"),
        # A3 (2026-06-12): ui_pages moved to registryhub (sole owner); the
        # workhub ``ui_page_updated`` event no longer exists. Subscribe to the
        # registryhub-emitted ui_page lifecycle events instead (same admit rule
        # as the endpoint_* registryhub subscriptions above).
        ("registryhub", "ui_page_registered", "normal"),
        ("registryhub", "ui_page_implemented", "normal"),
        # NOTE: NO broad ("workhub","task_created") subscription — see backend above.
        # create_task emits task_created with recipients=[assignee], so the frontend is
        # woken for its OWN tasks directly; the blanket sub only re-delivered other
        # lanes' tasks (run v11: 93 items, 24 its own) which the for-self gate suppressed.
        ("codehub", "review_requested", "high"),
        # Kickoff loop.
        ("orchestrator", "kickoff_request", "high"),
        # Round-8f.1 facilitator-driven revision (see backend).
        ("orchestrator", "kickoff_revision_request", "high"),
        # Round-8g phase-aware meeting: comment + reply phases.
        ("orchestrator", "kickoff_comment_phase_request", "high"),
        ("orchestrator", "kickoff_reply_phase_request", "high"),
        ("orchestrator", "kickoff_complete", "high"),
    ],
    "verifier": [
        # Once an endpoint is implemented, verifier can plan a contract
        # test; once a PR opens, verifier reviews.
        ("registryhub", "endpoint_implemented", "normal"),
        ("codehub", "pr_opened", "high"),
        ("runhub", "run_completed", "normal"),
        ("runhub", "run_failed", "high"),
        # Kickoff loop — verifier authors the predicate set draft.
        ("orchestrator", "kickoff_request", "high"),
        # Round-8f.1 facilitator-driven revision (see backend).
        ("orchestrator", "kickoff_revision_request", "high"),
        # Round-8g phase-aware meeting: comment + reply phases.
        ("orchestrator", "kickoff_comment_phase_request", "high"),
        ("orchestrator", "kickoff_reply_phase_request", "high"),
        ("orchestrator", "kickoff_complete", "high"),
    ],
    "debugger": [
        # Bug-level orchestrator. Wakes on bug_found + runhub failures; analyzes root
        # cause, assigns remediation tasks. Source is "*" not "verifier": bug_create emits
        # bug_found with source_hub=<source> (e.g. "business_chain"/"api_smoke"), so a
        # ("verifier","bug_found") sub silently missed every chain-filed bug and the
        # debugger never woke (run v14: DELETE FK-500 bug went untriaged → no delivery).
        ("*", "bug_found", "low"),
        ("runhub", "run_failed", "low"),
        ("runhub", "run_completed", "normal"),
        # Kickoff_complete is informational — debugger learns which
        # tasks were spawned so root-cause assignment downstream is
        # aware of the milestone's task_tree.
        ("orchestrator", "kickoff_complete", "high"),
    ],
}


# PROPOSAL #26 — INBOX-ONLY subscriptions. These are delivered ``delivery="inbox_only"``:
# the event lands in the agent's inbox (surfaced at its next hub_pulse) but the bridge
# EXCLUDES inbox_only-subscribed agents from live WAKEUP targets, so it NEVER triggers a
# resident wakeup. This is the ONLY no-wakeup lever (priority does not gate the wakeup —
# #25 reviewer's blocking finding), so framework-decision notices that must NOT churn the
# lanes (#24) live HERE and ONLY here. ``framework_decision`` must never appear in
# DEFAULT_SUBSCRIPTIONS (a live sub would reintroduce the wakeup it exists to avoid).
INBOX_ONLY_SUBSCRIPTIONS: Dict[str, List[Tuple[str, str, str]]] = {
    # F2 (wake-storm fix, 2026-07-21): these fire heavily during the design/kickoff window
    # (contract-surface registration + attendee decisions). As LIVE subs they woke the
    # orchestrator into full LLM steps that only concluded "ineligible during kickoff",
    # burning model quota (r3: 146 idle stop-cycles). Delivered inbox_only they are still
    # surfaced at the next hub_pulse / coordination tick, but never trigger a resident wakeup.
    # The live kickoff_facilitate_request / kickoff_detail_request subs (DEFAULT_SUBSCRIPTIONS)
    # keep the orchestrator chairing kickoff.
    "orchestrator": [
        ("registryhub", "endpoint_implemented", "normal"),
        ("workhub", "meeting_decision_added", "normal"),
    ],
    "backend": [
        ("registryhub", "framework_decision", "normal"),
        # PRE-LAUNCH AUDIT R2: table_registered fires on every (idempotent)
        # register_table; inbox_only keeps the backend informed at its next pulse
        # without re-waking it each heal-loop tick (the #25 B1 intent, minus the churn).
        ("registryhub", "table_registered", "normal"),
    ],
    "frontend": [
        ("registryhub", "framework_decision", "normal"),
    ],
}


def ensure_default_subscriptions(hubs, agent_id: str) -> None:
    """Idempotently register the agent's default subscriptions.

    Wrapped in try/except so a subscription failure can never break the
    pulse. EventHub.subscribe is idempotent by (agent, source, type).
    """
    eventhub = getattr(hubs, "eventhub", None)
    if eventhub is None or not hasattr(eventhub, "subscribe"):
        return
    for source_hub, event_type, priority_floor in (DEFAULT_SUBSCRIPTIONS.get(agent_id) or []):
        try:
            # O14/Phase 4.1: agent subscribing on its own behalf at
            # bootstrap — self-mutation, gate falls through.
            eventhub.subscribe(
                agent=agent_id,
                source_hub=source_hub,
                event_type=event_type,
                priority_floor=priority_floor,
                delivery="live",
                caller=agent_id,
            )
        except Exception:
            # never let a subscription failure break the caller
            pass
    # PROPOSAL #26: inbox_only subscriptions — no-wakeup framework-decision notices.
    for source_hub, event_type, priority_floor in (INBOX_ONLY_SUBSCRIPTIONS.get(agent_id) or []):
        try:
            eventhub.subscribe(
                agent=agent_id,
                source_hub=source_hub,
                event_type=event_type,
                priority_floor=priority_floor,
                delivery="inbox_only",
                caller=agent_id,
            )
        except Exception:
            pass


__all__ = ["DEFAULT_SUBSCRIPTIONS", "INBOX_ONLY_SUBSCRIPTIONS",
           "ensure_default_subscriptions"]
