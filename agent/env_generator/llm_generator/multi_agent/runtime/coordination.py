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
import time
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
            # FRESHNESS, not a one-time liveness anchor (V30 dead-turn blind spot).
            # The old test `last_at > kickoff_finalized_at` is a FIXED past anchor: the
            # moment a lane emits ONE agent_status after finalize it is classified alive
            # for the WHOLE rest of the run, even if its turn then died mid-step. V30: the
            # frontend wedged in a re-entrant agentic loop and went silent for 13min, yet
            # the watchdog nudged ZERO lanes because every lane had a stale-but-present
            # heartbeat. A lane is "provably alive" only if it emitted a heartbeat
            # RECENTLY — otherwise fall through to the work-check + nudge below so a
            # dead-mid-turn lane holding in_progress work gets re-driven. The nudge counter
            # resets only while the lane stays fresh (each new stall episode starts clean).
            _now = time.time()
            _stall = float(os.environ.get("ENVGEN_LANE_STALL_SEC", "150"))
            if last_at and last_at > kickoff_finalized_at and (_now - last_at) < _stall:
                self._orch._silent_lane_nudges.pop(lane_id, None)
                continue

            # #1202mz: A LANE THAT IS WORKING IS NOT SILENT. Freshness above is read from
            # `agent_status` heartbeats only, and a lane can work for many minutes without
            # emitting one — it calls tools, broadcasts, finishes. Across the run logs, 2950 of
            # 3216 stall re-drives (92%, in 106 runs) went to a lane that had logged a tool call
            # within the previous 150s; tiktok-r125's verifier was re-driven as "never-woke" 104s
            # after its last tool call, in the middle of a validation pass. Each re-drive is an
            # urgent persisted task_ready: queued while the lane is busy (72 in that verifier),
            # then replayed as a full work loop, and meanwhile part of the inbox every step
            # re-reads.
            # The agent object already carries the liveness #147's wedge watchdog trusts:
            # `_last_step_activity`, stamped at loop entry, every action round and after every
            # stage LLM call. A loop that has really stopped stops stamping and is still nudged.
            try:
                _stepped_1202mz = getattr((self._orch._agents or {}).get(lane_id),
                                          "_last_step_activity", None)
                if (isinstance(_stepped_1202mz, (int, float))
                        and 0 <= _now - float(_stepped_1202mz) < _stall):
                    self._orch._silent_lane_nudges.pop(lane_id, None)
                    continue
            except Exception:
                pass

            # #1202aa: a STOPPED lane is not a slow one, and nudging it cannot work. This
            # loop reads heartbeat freshness only, so a lane whose run loop has exited looks
            # exactly like a lane that is merely busy — and r32 ended on that confusion:
            #
            #     00:31:38  Stopping agent: Frontend Engineer Agent
            #     ...       Stall escalation (5560s -> 5778s), urgent task_ready to
            #               silent resident lanes ['frontend'], over and over
            #     Status: FAIL — cannot complete task
            #
            # 95 minutes of urgent dispatch at a lane whose queue had no reader (#1202z is
            # the other half: the wakeup that claimed it had been scheduled). The agent
            # object is right here and knows. Say which it is — a nudge that cannot be
            # received should not be counted as a nudge that was.
            _agent_obj = (self._orch._agents or {}).get(lane_id)
            if _agent_obj is not None and getattr(_agent_obj, "is_running", True) is False:
                self._orch._logger.error(
                    "Stall escalation: lane %r is STOPPED, not slow — its run loop has "
                    "exited, so nothing consumes its queue and an urgent task_ready cannot "
                    "reach it. Nudging is skipped; this lane needs restarting or the run "
                    "will wait on it until the no-deliver abort (#1202aa).", lane_id)
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
            _stale = bool(last_at and last_at > kickoff_finalized_at)
            self._orch._logger.warning(
                "Stall escalation: re-driving %s lane %s (last activity %s, holds work).",
                "STALE-mid-turn" if _stale else "never-woke", lane_id,
                (f"{int(_now - last_at)}s ago" if last_at else "none since finalize"),
            )
            message = _create_message(
                source_agent_id="orchestrator",
                target_agent_id=lane_id,
                content=(
                    ("Stall escalation: you went SILENT mid-task — last activity "
                     f"{int(_now - last_at)}s ago, but you still hold pending/in-progress "
                     "work. Resume it NOW: continue (or re-claim) your assigned WorkHub "
                     "task and run your step_contract. Do not ack and wait.")
                    if _stale else
                    ("Stall escalation: kickoff_complete fired but you "
                     "have produced no agent_status events since finalize. "
                     "Pick up your assigned kickoff task_tree entries from "
                     "WorkHub and start executing. Do not ack and wait — "
                     "run your one-pass step_contract NOW.")
                ),
                msg_type="task_ready",
                priority="urgent",
                persist=True,
                tags=["stall_escalation", "kickoff_followup"],
            )
            # The verifier's VerifierValidationTriggerPolicy SUPPRESSES a resident
            # wakeup unless the task_ready carries validation_phase / a known tag /
            # keyword — so a bare stall nudge is thrown away and an idle verifier is
            # never re-driven. Two sibling wake paths already stamp this
            # (remediation_dispatcher.py, framework_validation.py); this third path
            # (nudge_silent_resident_lanes) missed it → latent STUCK-ABORT cause.
            if lane_id == "verifier":
                try:
                    message.metadata["validation_phase"] = True
                except Exception:
                    pass
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
