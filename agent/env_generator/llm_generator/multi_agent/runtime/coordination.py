"""Resident-lane coordination cadence + stall-nudge, extracted from the
Orchestrator (PROPOSAL #8 — Coordination, the final decomposition slice).

Two pure cadence predicates (``coordination_tick_due`` /
``should_attempt_silent_lane_nudge``) + the stateful stall escalation
(``Coordination.nudge_silent_resident_lanes``). The run() coordination-tick
BLOCK itself stays in the orchestrator spine — only these leaf helpers move.

The pures are module-level (testable in isolation, like the fwval/visual pures).
``Coordination`` is stateless: the per-episode nudge counter
``_silent_lane_nudges`` is init/reset by run() and stays ON the orchestrator, so
the orchestrator shim constructs a fresh ``Coordination(self)`` per call.
"""

from __future__ import annotations

import os
from typing import Any, List


def coordination_tick_due(
    *,
    event_set: bool,
    now: float,
    last_tick_at: float,
    loop_start: float,
    stuck_sec: float,
) -> bool:
    """Pure gate for the resident coordination-tick re-dispatch (Defect B,
    YOUTUBE_RUN_STALL_REVIEW).

    Fires when EITHER the lane's done-event is set (a clean tick finish) OR a
    wall-clock ``stuck_sec`` window has elapsed since the last tick. The latter
    is the decouple: the done-event stays False forever when the resident
    orchestrator's tick LLM-loops without finishing, which wedged the run
    (smoke #19 fixed this for the nudge but missed the tick). Bounded to one
    tick per stuck window (no flood). ``max(last_tick_at, loop_start)`` makes
    the first tick fire within ``stuck_sec`` even if the event never sets.
    Kept pure so the cadence is testable in isolation."""
    if event_set:
        return True
    return (now - max(last_tick_at, loop_start)) >= stuck_sec


def should_attempt_silent_lane_nudge(
    now: float,
    kickoff_finalized_at: float,
    last_nudge_attempt_at: float,
    grace_sec: float,
    interval_sec: float,
) -> bool:
    """Round 8h Patch B v2: pure decision for whether the
    coordination loop should run a silent-lane nudge attempt on
    the current wait_for-timeout iteration.

    Returns True iff BOTH:
      * At least ``grace_sec`` has elapsed since
        ``kickoff_finalized_at`` (lets kickoff_complete subscribers
        wake naturally before we assume bug).
      * At least ``interval_sec`` has elapsed since the previous
        nudge attempt (don't spam the bus / inbox).

    Kept pure so the wall-clock cadence is testable in isolation
    without booting the full coordination loop. Smoke #19 surfaced
    the v1 wiring bug (nested inside `if task_done.is_set()` which
    was False forever when the orchestrator lane LLM-looped on
    inbox reads) — this helper guarantees v2 cannot regress to
    the same gating mistake by accident.
    """
    if now - kickoff_finalized_at < grace_sec:
        return False
    if now - last_nudge_attempt_at < interval_sec:
        return False
    return True


class Coordination:
    """Resident-lane stall escalation. Stateless; the per-episode nudge counter
    ``_silent_lane_nudges`` lives on the orchestrator (init/reset by run())."""

    def __init__(self, orch: Any) -> None:
        self._orch = orch

    async def nudge_silent_resident_lanes(
        self,
        kickoff_finalized_at: float,
    ) -> List[str]:
        """Round 8h Patch B: dispatch urgent task_ready to any resident
        lane that has produced ZERO ``agent_status`` events since
        ``kickoff_finalized_at`` — the structural fix for the smoke #18
        Frontend/Verifier never-woke pathology.

        The orchestrator coordination loop calls this at
        ``idle_tick_count >= 3``. Pre-fix the only escalation was a
        textual instruction on the resident_coordination_tick prompt
        ("you've been idle 3 ticks; escalate") which had no effect
        when the OTHER lanes were the ones never waking — the
        orchestrator lane is the one reading that prompt, and it
        cannot wake a peer by reading text.

        Behavior:
          * Reads ``eventhub.get_all_agent_statuses()`` and finds the
            last agent_status timestamp per resident lane id.
          * A lane is "silent" if it has NO agent_status entry OR
            its latest entry is older than ``kickoff_finalized_at``.
          * For each silent lane (excluding the orchestrator itself,
            which is by design the polling coordinator), construct a
            ``msg_type=task_ready`` message with URGENT priority and
            send it through the message bus.
          * Increment ``self._orch._silent_lane_nudges[lane_id]`` so a
            future iteration can detect "still silent after N nudges"
            and escalate further (loud log; structural failure of the
            subscription path).

        Returns the list of lane ids that were nudged this call. An
        empty list means every lane has emitted at least one
        agent_status since finalize — no escalation needed.

        Charter §8: this is closed-by-construction (the orchestrator
        either gets evidence of liveness or sends a structured wake
        signal — no "log and hope" path).
        """
        from tools.communication_tools import _create_message
        try:
            all_statuses = self._orch.hubs.eventhub.get_all_agent_statuses() or {}
        except Exception as exc:
            self._orch._logger.warning(
                "Could not read agent statuses for stall escalation: %s",
                exc,
            )
            return []

        nudged: List[str] = []
        for lane_id in self._orch._agents:
            if lane_id == "orchestrator":
                continue
            status = all_statuses.get(lane_id) or {}
            last_at = status.get("_event_created_at", 0.0)
            if last_at and last_at > kickoff_finalized_at:
                # Lane has emitted an agent_status post-finalize, so
                # it is provably alive. Reset its nudge counter so the
                # next stall episode starts clean.
                self._orch._silent_lane_nudges.pop(lane_id, None)
                continue

            # Don't nudge a lane that has NO actionable work. The nudge orders the lane to
            # "pick up your assigned kickoff task_tree entries" — but idle-BY-DESIGN lanes
            # (knowledge = observer; debugger before any bug_found) have ZERO assigned
            # tasks, so the instruction is provably impossible to act on and just burns a
            # full LLM step + floods the inbox (audit #8 / run v12: knowledge 133s, debugger
            # 3513s on an impossible instruction; kickoff_driver already models knowledge as
            # an observer + impl_lanes={backend,frontend}). Only nudge a silent lane that
            # actually holds claimable / in-progress work. Best-effort: never let the
            # work-check break escalation.
            try:
                _wh = self._orch.hubs.workhub
                _has_work = bool(
                    (_wh.list_tasks(assignee=lane_id, status="pending") or [])
                    or (_wh.list_tasks(assignee=lane_id, status="in_progress") or [])
                )
                if not _has_work:
                    self._orch._logger.debug(
                        "Stall escalation: lane %s has no assigned pending/in_progress "
                        "tasks — idle by design; not nudging.", lane_id,
                    )
                    continue
            except Exception:
                pass

            prior_nudges = self._orch._silent_lane_nudges.get(lane_id, 0)
            # FIX #41 (speed): cap stall nudges per lane per stall-episode. A lane
            # silent after several urgent nudges is STUCK (long LLM self-loop or
            # genuinely wedged) — re-sending an urgent persist=True task_ready every
            # 60s for the rest of the run just FLOODS its inbox (163-msg inboxes
            # observed), and since every lane re-scans its whole inbox each step,
            # the flood slows the ENTIRE run (good runs hit the 2h wall-clock cap
            # this way) without ever un-sticking the lane. The counter resets the
            # moment the lane emits any agent_status (line above), so this caps per
            # episode, not for the whole run.
            _MAX_SILENT_NUDGES = int(os.environ.get("ENVGEN_MAX_SILENT_NUDGES", "4"))
            if prior_nudges >= _MAX_SILENT_NUDGES:
                if prior_nudges == _MAX_SILENT_NUDGES:
                    self._orch._silent_lane_nudges[lane_id] = prior_nudges + 1  # bump once so we log once
                    self._orch._logger.warning(
                        "Stall escalation: lane %s still silent after %d nudges — "
                        "SUPPRESSING further nudges this episode (avoid inbox flood "
                        "that stalls the whole run).",
                        lane_id, prior_nudges,
                    )
                continue
            message = _create_message(
                source_agent_id="orchestrator",
                target_agent_id=lane_id,
                content=(
                    "Stall escalation: kickoff_complete fired but you "
                    "have produced no agent_status events since finalize. "
                    "Pick up your assigned kickoff task_tree entries from "
                    "WorkHub and start executing. Do not ack and wait — "
                    "run your one-pass step_contract NOW."
                ),
                msg_type="task_ready",
                priority="urgent",
                persist=True,
                tags=["stall_escalation", "kickoff_followup"],
            )
            try:
                delivered = await self._orch.message_bus.send(message)
            except Exception as exc:
                self._orch._logger.error(
                    "Stall escalation: bus.send to %s raised %s",
                    lane_id, exc,
                )
                continue
            if not delivered:
                self._orch._logger.error(
                    "Stall escalation: bus.send to %s returned False "
                    "(target not registered with bus). Lane "
                    "spawn-time wiring is broken upstream.",
                    lane_id,
                )
                continue
            self._orch._silent_lane_nudges[lane_id] = prior_nudges + 1
            nudged.append(lane_id)
        return nudged
