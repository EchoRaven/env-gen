"""Kickoff driver — facilitator-led kickoff meeting loop + finalize/author/dispatch,
extracted from the Orchestrator (PROPOSAL #8 — KickoffDriver; reviewed PASS as PROPOSAL #16).

Stateless: the cluster writes ZERO orchestrator state and calls no orchestrator methods
outside its own 6 siblings, so KickoffDriver borrows the orchestrator via a back-ref and
the orchestrator keeps 6 fresh-construct shims. Every ``self.X`` from the original is
``self._orch.X`` here — INCLUDING sibling kickoff calls, which therefore route back through
the orchestrator shims (preserving dispatch + any test stub on an intermediate method).
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


# PROPOSAL #32: kickoff attendees whose section is NON-essential to the contract — it is
# either DERIVED by synthesis or done POST-impl — so a stalled kickoff may finalize by
# DEFERRING them rather than failing. Currently just the verifier: its acceptance
# predicates are derived from the frontend's user_flows + the roadmap floor, and its real
# work (verification chains) is designed at the validation phase from the registered
# contract. Backend/frontend are ESSENTIAL (no contract without them) → never deferred.
_DEFERRABLE_KICKOFF_ATTENDEES = frozenset({"verifier"})


# The code-writing impl lanes (verifier validates later; orchestrator coordinates;
# knowledge is an observer).
_IMPL_LANES_1076 = ("backend", "frontend")


def _impl_dispatch_targets_1076(agents) -> list:
    """Which lanes the implementation-phase dispatch wakes. See the #1076 note at
    the call site: unconditional by design, in the orchestrator's own order."""
    try:
        return [lane for lane in (agents or []) if lane in _IMPL_LANES_1076]
    except Exception:
        return []


def _provider_terminal_1202ec() -> str:
    """The latched provider-abort reason, or "" -- never raises.

    #1202ec: a broken import here must not be able to break kickoff, which is what this
    check exists to protect. It warns rather than swallowing, per #1201.
    """
    try:
        from utils.llm import terminal_llm_error
        return str(terminal_llm_error() or "")
    except Exception as _err_1202ec:
        from .message_format import warn_once_1201
        warn_once_1201("kickoff_driver._provider_terminal_1202ec",
                       "kickoff cannot tell whether the provider has gone terminal",
                       _err_1202ec)
        return ""


def _lane_log_activity_1202fg(output_dir: Any) -> dict:
    """{lane: bytes written to its .agent_logs} — the evidence #862's line asked for.

    Best-effort: an unreadable tree returns {} and the caller says it could not look,
    which is the honest answer and never "never started".
    """
    out = {}
    try:
        root = Path(output_dir) / ".agent_logs"
        if not root.is_dir():
            return {}
        for d in sorted(root.iterdir()):
            if not d.is_dir():
                continue
            try:
                out[d.name] = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
            except Exception:
                continue
    except Exception:
        return {}
    return out


class KickoffDriver:
    """Drives the kickoff meeting to completion + finalize/author/dispatch.
    Stateless; reads the orchestrator's collaborators live via the back-ref."""

    def __init__(self, orch: Any) -> None:
        self._orch = orch

    def _finalize_kickoff_and_author(
        self,
        kickoff_handle: Dict[str, Any],
        synthesis: Dict[str, Any],
        *,
        poll_count: int,
        elapsed: float,
    ) -> Dict[str, Any]:
        """Register a READY synthesis (finalize_kickoff) + author the
        milestone/roadmap/briefing docs, returning the finalize receipt.

        Shared by the two finalize sites in ``_drive_kickoff_to_completion``:
        the deterministic synth=ready fast-path and the LLM-facilitator
        ``consensus`` branch. finalize_kickoff is a pure §8 function — it is
        the single writer of the registered contract + task_ready dispatch —
        so a ready synthesis NEVER needs the LLM to bless it; centralizing the
        finalize keeps both paths byte-identical. Doc authoring failures are
        non-fatal (the contract has already shipped).
        """
        from .kickoff import run_kickoff
        receipt = run_kickoff.finalize_kickoff(
            hubs=self._orch.hubs,
            kickoff_handle=kickoff_handle,
            synthesis=synthesis,
            agent="orchestrator",
        )
        self._orch._logger.info(
            "Kickoff finalize receipt: phase=%s endpoints=%d tables=%d "
            "tasks=%d predicates=%d failures=%d",
            receipt.get("phase"),
            receipt.get("endpoints_registered", 0),
            receipt.get("tables_registered", 0),
            receipt.get("tasks_created", 0),
            receipt.get("predicates_persisted", 0),
            len(receipt.get("failures") or []),
        )
        try:
            self._orch._author_kickoff_docs(synthesis)
        except Exception as _auth_err:
            self._orch._logger.warning(
                "kickoff authoring failed (non-fatal): %s", _auth_err,
            )
        return receipt

    async def _drive_kickoff_to_completion(
        self,
        kickoff_handle: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Round-8f.1 driver: pure-Python facilitator-led meeting loop.

        Background (round-8c → 8f.1): the original 8c driver polled
        ``try_synthesize`` and short-circuited any non-``ready`` status
        straight to ``synthesize_fallback``. That treated the kickoff as
        a one-shot paper-submission rather than a real meeting. Round-8f
        introduces the orchestrator-as-facilitator turn (see
        ``runtime/kickoff/facilitate.py``):

          Round 1: attendees author initial proposals (no change).
          Facilitator turn: orchestrator LLM reads all decisions, emits a
            ``facilitator_note`` whose ``content.action`` is one of
            ``consensus``, ``request_revision``, or ``escalate``.
          Round N>1 (only on request_revision): the flagged revisers
            re-author their sections, then the facilitator runs again.
          After ``KICKOFF_MAX_ROUNDS`` rounds the driver falls back.

        This driver is the pure-Python state machine that wires those
        events together; it does NOT call the LLM directly. The
        facilitator LLM runs inside the orchestrator's resident lane via
        its ``_handle_kickoff_facilitate_request`` handler.

        Returns the kickoff receipt (finalize_kickoff's normal return
        shape) on consensus; a ``synthesize_fallback`` dict on
        timeout / escalate / max_rounds. Caller inspects ``phase``.
        """
        from .kickoff import run_kickoff
        from .kickoff import facilitate
        from .kickoff.schema_tolerance import (
            coerce_facilitator_action,
        )
        # NOTE: use ``is None`` not ``or`` — 0.0 is a valid (if degenerate)
        # started_at and ``or`` would silently replace it with time.time(),
        # masking a timeout-driven abort in tests/production alike.
        started_at = kickoff_handle.get("started_at")
        if started_at is None:
            started_at = time.time()
        poll_count = 0
        expected_attendees = list(kickoff_handle.get("expected_attendees") or [])
        meeting_id = kickoff_handle.get("meeting_id")
        # Round-8g: track which (round, phase) broadcasts have fired so
        # we don't re-broadcast on every poll. In-memory state — only
        # valid for the lifetime of this driver call. If the driver
        # restarts mid-meeting (it doesn't today), we'd have to persist
        # this in workhub but for now in-process is fine.
        broadcasts_fired: set = set()
        # FIX (deep-review 🟡#3): re-nudge the facilitator. The facilitator turn fires
        # kickoff_facilitate_request once; if the orchestrator-LLM hangs/drops it the
        # note never lands and the loop polls silently to the 1200s outer timeout. Track
        # the poll at which we last (re-)requested facilitation per round and RE-FIRE
        # every _FACILITATOR_RENUDGE_POLLS (request_facilitation just re-publishes the
        # event — idempotent), so a stuck facilitator recovers in ~150s, not ~1200s.
        _facilitator_fired_poll: dict = {}
        _FACILITATOR_RENUDGE_POLLS = 30  # × KICKOFF_POLL_INTERVAL_SEC (5s) ≈ 150s
        # PROPOSAL #28 (C-recovery): track substantive-section progress while the
        # meeting is stuck in phase=initial, so a lane that can never emit a clean
        # section doesn't pin the run for the full 1200s timeout.
        _initial_fewest_missing: Optional[int] = None
        _initial_progress_poll = 0

        while True:
            poll_count += 1
            elapsed = time.time() - started_at

            # Timeout check FIRST — overrides any other state machine
            # decision. Matches the 8c contract that ``test_driver_timeout
            # _falls_through_to_fallback`` pins.
            if elapsed > run_kickoff.KICKOFF_TIMEOUT_SEC:
                try:
                    last_synth = run_kickoff.try_synthesize(self._orch.hubs, kickoff_handle)
                except Exception:
                    last_synth = {"status": "unknown"}
                self._orch._logger.error(
                    "Kickoff timed out after %.0fs (poll %s); attempting "
                    "deterministic reconcile before kickoff_failed.",
                    elapsed, poll_count,
                )
                return self._orch._kickoff_fallback_or_reconcile(
                    kickoff_handle, last_synth, "timeout",
                )

            # #1202ec: STOP WAITING FOR A SYNTHESIS THE PROVIDER CANNOT PRODUCE.
            #
            # `terminal_llm_error()` exists, in its own words, so "a run loop should poll
            # this and abort instead of spinning". The orchestrator's coordination loop
            # does poll it (#326) -- but kickoff runs BEFORE that loop, so the one phase
            # ahead of the poller was the one phase without a poller. This file had zero
            # references to it.
            #
            # googlemaps-r15: the provider latched terminal at 03:32:12 and this loop kept
            # polling until 03:38:41 -- 389s spent waiting on a meeting whose every
            # participant was getting HTTP 429. It then aborted with `Missing=[]
            # last_status='validation_failed'`, a diagnostic that names nothing, because
            # nothing had failed except every LLM call. Bad timing costs more: an outage
            # at second 10 burns the full KICKOFF_TIMEOUT_SEC of 1200s.
            #
            # Aborting early loses no work. This returns down the same path as the
            # timeout, and that path's deterministic reconcile-and-finalize needs no LLM
            # at all -- it synthesizes from whatever WAS decided. Same outcome, sooner.
            #
            # This inherits #1174's grace window for free: the reason only latches once
            # quota failure has PERSISTED past it, so r16's 57-second blip -- which killed
            # a run sitting at one failing gate check with $262 spent -- cannot trip it.
            _term_1202ec = _provider_terminal_1202ec()
            if _term_1202ec:
                try:
                    last_synth = run_kickoff.try_synthesize(self._orch.hubs, kickoff_handle)
                except Exception:
                    last_synth = {"status": "unknown"}
                # #1202hv: the latch is shared with our OWN ENVGEN_MAX_SPEND_USD guard
                # (#1163), so "the provider is terminally unavailable" was the wrong
                # sentence for every budget stop -- and it points at a fresh key rather
                # than at the one knob that would help.
                try:
                    from utils.llm import terminal_stop_is_own_budget_1202hv
                    _own_cap = terminal_stop_is_own_budget_1202hv(_term_1202ec)
                except Exception:
                    _own_cap = False
                self._orch._logger.error(
                    "Kickoff abandoned after %.0fs (poll %s): %s, so no synthesis can "
                    "arrive. %s",
                    elapsed, poll_count,
                    ("this run's OWN spend ceiling stopped it (the provider is fine) — "
                     "raise ENVGEN_MAX_SPEND_USD or unset it" if _own_cap
                     else "the LLM provider is terminally unavailable"),
                    _term_1202ec,
                )
                # Two calls, each with a LITERAL reason, rather than one call with a
                # conditional: #1202ed guards the abort vocabulary by scanning for the
                # first quoted reason per call site, so a ternary here hides whichever
                # branch it puts second -- and `provider_terminal` was the one that
                # vanished from `test_all_nine_reasons_still_reach_the_stamp`. The
                # duplication is the price of keeping that check able to see both.
                if _own_cap:
                    return self._orch._kickoff_fallback_or_reconcile(
                        kickoff_handle, last_synth, "own_budget_cap",
                    )
                return self._orch._kickoff_fallback_or_reconcile(
                    kickoff_handle, last_synth, "provider_terminal",
                )

            # Round-8g: derive the meeting's current phase from
            # decisions[]. Phases iterate per round:
            #   initial → comment → reply → facilitator
            #   → (consensus | request_revision | escalate)
            phase = facilitate.current_phase(
                self._orch.hubs, meeting_id, expected_attendees,
            )
            cur_round = facilitate.current_round(self._orch.hubs, meeting_id)

            if phase == "initial":
                # Initial drafts still being authored (kickoff_request
                # was broadcast by start_kickoff for round 1; revisions
                # are dispatched via kickoff_revision_request when a
                # facilitator says request_revision).
                # PROPOSAL #28 (C-recovery): measure substantive-section progress via
                # try_synthesize's ``missing`` (attendees lacking a substantive
                # decision). A SHRINKING missing-set = progress; if it stops shrinking
                # for KICKOFF_INITIAL_STALL_POLLS while in initial (past the grace
                # window), a lane is stuck (e.g. Gemini re-mangling its draft) — stop
                # waiting for the full 1200s and finalize via the existing fallback,
                # which synthesizes/reconciles from whatever WAS recorded.
                try:
                    _synth = run_kickoff.try_synthesize(self._orch.hubs, kickoff_handle)
                except Exception:
                    _synth = {"status": "unknown", "missing": list(expected_attendees)}
                _missing = len(_synth.get("missing") or [])
                if _initial_fewest_missing is None or _missing < _initial_fewest_missing:
                    _initial_fewest_missing = _missing
                    _initial_progress_poll = poll_count
                stalled_polls = poll_count - _initial_progress_poll
                # #1202ko: SILENCE IN THE MEETING IS NOT SILENCE FROM THE LANE.
                #
                # #28's premise is "a lane that can never emit a clean section" — Gemini
                # re-mangling its draft — and for that the 242s escape is right. It reads only
                # the meeting document, so a lane that is BUSY looks identical to one that is
                # broken, and the run is killed with ~958s of kickoff budget unspent.
                #
                # tiktok-r115: M2 kickoff opened 17:15:03; the request reached frontend at
                # 17:15:05 (priority high) and it READ it at 17:18:46 — then claimed the P0 the
                # framework had just dispatched (`coord_frontend_gate_..._m2`) and worked it.
                # Across that window it made FIVE commits (17:17:23, 17:18:00, 17:18:54, ...)
                # and completed a task at 17:21:33, all visible in the hubs. The driver called
                # it `initial_stall` at 17:23:15 and aborted a run that had already DELIVERED
                # milestone 1. The framework told the lane to do two things at once and then
                # punished it for finishing the urgent one.
                #
                # So ask the hubs whether the missing attendee is working, and if it is, decline
                # the FAST escape only — `KICKOFF_TIMEOUT_SEC` still bounds the wait, which is
                # what that 1200s is for.
                #
                # HONEST ABOUT THE SCOPE: this is a LOOSER escape, not a smarter one. Over the
                # corpus's two `initial_stall` deaths it declines BOTH — r115 (frontend: a
                # completed task + 2 commits) and r112 (backend: 1 endpoint re-registration).
                # A first draft of this comment claimed it still released r112 on "0 writes";
                # that was measured wrong (two stores instead of five) and is false.
                #
                # It is still the right trade, for a reason that does not depend on
                # discriminating between them: declining only DELAYS, it never changes the
                # outcome path — at 1200s the driver runs the SAME
                # `_kickoff_fallback_or_reconcile`. So the worst case is ~16 extra minutes,
                # against r115's actual cost of a run that had already delivered milestone 1.
                # And the case #28 was written for — a lane re-mangling its draft and emitting
                # nothing — writes to no hub either, so it still escapes at 242s.
                _busy_1202ko = self._missing_attendee_is_working_1202ko(_synth, elapsed)
                if _busy_1202ko:
                    self._orch._logger.warning(
                        "#1202ko NOT taking the %.0fs stall escape: %s has not recorded a "
                        "section but IS working (%s recent hub write(s)). Silence in the "
                        "meeting is not silence from the lane; waiting for the real %.0fs "
                        "timeout instead.",
                        run_kickoff.KICKOFF_INITIAL_STALL_MIN_SEC, _busy_1202ko[0],
                        _busy_1202ko[1], run_kickoff.KICKOFF_TIMEOUT_SEC)
                if (not _busy_1202ko
                        and elapsed >= run_kickoff.KICKOFF_INITIAL_STALL_MIN_SEC
                        and stalled_polls >= run_kickoff.KICKOFF_INITIAL_STALL_POLLS):
                    self._orch._logger.error(
                        "Kickoff STALLED in phase=initial (round %d, poll %s, %.0fs): "
                        "no new substantive section for %s polls (%s attendee(s) still "
                        "missing). Finalizing early via deterministic reconcile instead "
                        "of waiting for the %.0fs timeout.",
                        cur_round, poll_count, elapsed, stalled_polls,
                        _initial_fewest_missing, run_kickoff.KICKOFF_TIMEOUT_SEC,
                    )
                    return self._orch._kickoff_fallback_or_reconcile(
                        kickoff_handle, _synth, "initial_stall",
                    )
                # #862: NAME the attendees, and say when NOBODY has spoken.
                #
                # This line reported a COUNT, and "3 missing" reads identically whether three
                # lanes are slow or three lanes never started. 7 of 151 corpus runs (r19, r35,
                # r38, r42, r44, r136, r140 — spread over 9 days, so not one bad afternoon) are
                # the second case: `.agent_logs/` shows backend, frontend, verifier and debugger
                # with EMPTY directories while orchestrator, knowledge and design_analyst logged
                # normally. The orchestrator then idles on `ACTION_STATUS: stop` reporting
                # "endpoints=0, tasks=0" and the run ends after 3-4 minutes having built nothing:
                # no DDL, no seed, no frontend, no capture.
                #
                # ★ The framework already has the salvage for this — `_derive_missing_essential_
                # sections` reconstructs a silent essential lane's section from the milestone
                # slice — but it is reached only through the stall escape above, which cannot fire
                # before KICKOFF_INITIAL_STALL_MIN_SEC (240s). Five of those seven runs were over
                # at or before 240s. The recovery exists and its precondition is unreachable in
                # the case it was written for.
                #
                # Nothing here changes that; tuning the floor without knowing why the lanes never
                # spawned would be a guess. What this does is make the state legible: the class
                # was invisible until an artifact-tree census turned it up, because every poll
                # printed the same count a healthy slow kickoff prints.
                _names = ", ".join(sorted(str(m) for m in (_synth.get("missing") or []))) or "-"
                _nobody = (_initial_fewest_missing is not None
                           and _initial_fewest_missing >= len(expected_attendees))
                if _nobody and elapsed >= 60.0 and not getattr(self, "_said_silent_862", False):
                    self._said_silent_862 = True
                    self._orch._logger.warning(
                        "Kickoff: NO attendee has recorded anything after %.0fs — missing %s "
                        "(of %s expected). %s The stall escape cannot act before %.0fs (#862).",
                        elapsed, _names, len(expected_attendees),
                        self._lane_activity_1202fg(),
                        run_kickoff.KICKOFF_INITIAL_STALL_MIN_SEC,
                    )
                self._orch._logger.info(
                    "Kickoff phase=initial (round %d, poll %s, %.0fs); "
                    "waiting for attendees to record initial proposals "
                    "(%s missing: %s, %s polls since progress).",
                    cur_round, poll_count, elapsed, _missing, _names, stalled_polls,
                )
                await asyncio.sleep(run_kickoff.KICKOFF_POLL_INTERVAL_SEC)
                continue

            if phase == "comment":
                # Initial drafts done — fire kickoff_comment_phase_request
                # once for this (round, phase), then wait for all
                # attendees to ack the comment phase.
                key = (cur_round, "comment")
                if key not in broadcasts_fired:
                    self._orch._logger.info(
                        "Kickoff phase=comment (round %d, poll %s, "
                        "%.0fs); broadcasting kickoff_comment_phase_request.",
                        cur_round, poll_count, elapsed,
                    )
                    facilitate.request_comment_phase(
                        self._orch.hubs, kickoff_handle,
                    )
                    broadcasts_fired.add(key)
                else:
                    acked = facilitate.phase_acked_by(
                        self._orch.hubs, meeting_id, cur_round, "comment",
                    )
                    self._orch._logger.info(
                        "Kickoff phase=comment (round %d, poll %s, "
                        "%.0fs); waiting on %s.",
                        cur_round, poll_count, elapsed,
                        [a for a in expected_attendees if a not in acked],
                    )
                await asyncio.sleep(run_kickoff.KICKOFF_POLL_INTERVAL_SEC)
                continue

            if phase == "reply":
                # Comment phase done — fire kickoff_reply_phase_request
                # once, then wait for all attendees to ack reply phase.
                key = (cur_round, "reply")
                if key not in broadcasts_fired:
                    self._orch._logger.info(
                        "Kickoff phase=reply (round %d, poll %s, %.0fs); "
                        "broadcasting kickoff_reply_phase_request.",
                        cur_round, poll_count, elapsed,
                    )
                    facilitate.request_reply_phase(
                        self._orch.hubs, kickoff_handle,
                    )
                    broadcasts_fired.add(key)
                else:
                    acked = facilitate.phase_acked_by(
                        self._orch.hubs, meeting_id, cur_round, "reply",
                    )
                    self._orch._logger.info(
                        "Kickoff phase=reply (round %d, poll %s, "
                        "%.0fs); waiting on %s.",
                        cur_round, poll_count, elapsed,
                        [a for a in expected_attendees if a not in acked],
                    )
                await asyncio.sleep(run_kickoff.KICKOFF_POLL_INTERVAL_SEC)
                continue

            if phase == "facilitator":
                # synth=ready is TERMINAL — finalize deterministically rather
                # than waiting for the LLM facilitator to record a "consensus"
                # note. The facilitation pass exists only to RESOLVE non-ready
                # statuses (conflict / validation_failed); an already-ready
                # synthesis has cleared every gate (quorum + cross-checks +
                # roadmap validation), so gating its finalize on the
                # orchestrator-LLM behaving is pure fragility. youtube run #12
                # (2026-06-16): synthesis reached ready but the orchestrator-
                # facilitator was handed backend implementation context, never
                # recorded a consensus note, and a fully-ready kickoff polled to
                # its 1200s timeout with the lanes stuck in kickoff:action stage.
                # Finalize here; the LLM only sees facilitation when there is an
                # actual conflict to adjudicate (the consensus branch below
                # remains for the after-revisions-became-ready case).
                try:
                    ready_synth = run_kickoff.try_synthesize(
                        self._orch.hubs, kickoff_handle,
                    )
                except Exception as exc:
                    self._orch._logger.error(
                        "try_synthesize raised at facilitator ready-check "
                        "(round %d, poll %s): %s", cur_round, poll_count, exc,
                    )
                    ready_synth = {"status": "unknown"}
                if ready_synth.get("status") == "ready":
                    self._orch._logger.info(
                        "synth=ready at facilitator phase — finalizing "
                        "deterministically (poll %s, %.0fs); no LLM consensus "
                        "required.", poll_count, elapsed,
                    )
                    return self._orch._finalize_kickoff_and_author(
                        kickoff_handle, ready_synth,
                        poll_count=poll_count, elapsed=elapsed,
                    )
                # Not ready — fire kickoff_facilitate_request once, then wait
                # for orchestrator's facilitator_note to resolve the conflict.
                key = (cur_round, "facilitator")
                _last_fired = _facilitator_fired_poll.get(key)
                if _last_fired is None or (poll_count - _last_fired) >= _FACILITATOR_RENUDGE_POLLS:
                    try:
                        synthesis = run_kickoff.try_synthesize(
                            self._orch.hubs, kickoff_handle,
                        )
                    except Exception as exc:
                        self._orch._logger.error(
                            "try_synthesize raised before facilitator "
                            "turn (round %d, poll %s): %s",
                            cur_round, poll_count, exc,
                        )
                        raise
                    self._orch._logger.info(
                        "Kickoff phase=facilitator (round %d, poll %s, "
                        "%.0fs, synth=%s); %s facilitation.",
                        cur_round, poll_count, elapsed,
                        synthesis.get("status"),
                        "re-requesting" if _last_fired is not None else "requesting",
                    )
                    facilitate.request_facilitation(
                        self._orch.hubs, kickoff_handle, synthesis,
                    )
                    _facilitator_fired_poll[key] = poll_count
                    broadcasts_fired.add(key)
                await asyncio.sleep(run_kickoff.KICKOFF_POLL_INTERVAL_SEC)
                continue

            # phase ∈ {consensus, request_revision, escalate} — the
            # facilitator has spoken. Read the actual note for content.
            note = facilitate.read_facilitator_decision(
                self._orch.hubs, kickoff_handle,
            )
            if note is None:
                # current_phase said facilitator-action but the note was
                # racy — give it one more poll.
                self._orch._logger.warning(
                    "Kickoff phase=%s but no facilitator_note found yet "
                    "for round %d; one more poll.",
                    phase, cur_round,
                )
                await asyncio.sleep(run_kickoff.KICKOFF_POLL_INTERVAL_SEC)
                continue

            note_content = note.get("content") or {}
            # Round 8h follow-up: facilitate.current_phase() already
            # coerced any invented action string (e.g.
            # "accept_revision_and_recenter") to a canonical
            # FACILITATOR_ACTIONS value when deciding ``phase`` above.
            # Re-coerce here so this branch sees the SAME canonical
            # action — otherwise the if/elif chain below would
            # fall through to "Unknown facilitator action" and
            # synthesize_fallback, exactly the failure mode Fix #O
            # was meant to prevent.
            action = coerce_facilitator_action(note_content.get("action"))
            # Re-run try_synthesize so the rest of the loop (consensus
            # → finalize, escalate → fallback) has fresh state.
            try:
                synthesis = run_kickoff.try_synthesize(self._orch.hubs, kickoff_handle)
            except Exception as exc:
                self._orch._logger.error(
                    "try_synthesize raised post-facilitator (round %d): %s",
                    cur_round, exc,
                )
                raise

            if action == "consensus":
                # Trust the facilitator's verdict, but re-poll
                # try_synthesize once more — the latest revisions may
                # have just made it ready. If still not ready, fall back
                # rather than finalize with a bad synthesis.
                if synthesis.get("status") != "ready":
                    synthesis = run_kickoff.try_synthesize(
                        self._orch.hubs, kickoff_handle
                    )
                if synthesis.get("status") == "ready":
                    self._orch._logger.info(
                        "Facilitator declared consensus (poll %s, "
                        "%.0fs); finalizing.",
                        poll_count, elapsed,
                    )
                    return self._orch._finalize_kickoff_and_author(
                        kickoff_handle, synthesis,
                        poll_count=poll_count, elapsed=elapsed,
                    )
                self._orch._logger.warning(
                    "Facilitator declared consensus but try_synthesize "
                    "still %r; attempting reconcile before fallback.",
                    synthesis.get("status"),
                )
                return self._orch._kickoff_fallback_or_reconcile(
                    kickoff_handle, synthesis, "consensus_not_ready",
                )

            if action == "request_revision":
                cur_round = facilitate.current_round(
                    self._orch.hubs, kickoff_handle["meeting_id"]
                )
                if cur_round >= facilitate.KICKOFF_MAX_ROUNDS:
                    self._orch._logger.error(
                        "Kickoff hit max_rounds=%d; attempting reconcile "
                        "before fallback",
                        facilitate.KICKOFF_MAX_ROUNDS,
                    )
                    return self._orch._kickoff_fallback_or_reconcile(
                        kickoff_handle, synthesis, "max_rounds",
                    )
                revisers = note_content.get("revisers") or []
                if not revisers:
                    self._orch._logger.error(
                        "Facilitator requested revision but listed no "
                        "revisers; attempting reconcile before fallback."
                    )
                    return self._orch._kickoff_fallback_or_reconcile(
                        kickoff_handle, synthesis, "no_revisers",
                    )
                self._orch._logger.info(
                    "Facilitator requested revision from %s (round %d "
                    "-> %d).",
                    revisers, cur_round, cur_round + 1,
                )
                facilitate.request_revisions(
                    self._orch.hubs, kickoff_handle, revisers, note,
                )
                # broadcasts_fired keys are (round, phase) tuples — the
                # new round will use fresh keys (round+1, *), so no
                # explicit reset needed. The current_phase computation
                # for round+1 will see no decisions yet for that round
                # and return "initial".
                await asyncio.sleep(run_kickoff.KICKOFF_POLL_INTERVAL_SEC)
                continue

            if action == "escalate":
                self._orch._logger.error(
                    "Facilitator escalated kickoff; attempting reconcile "
                    "before fallback. rationale=%r",
                    note_content.get("rationale"),
                )
                return self._orch._kickoff_fallback_or_reconcile(
                    kickoff_handle, synthesis, "escalate",
                )

            # Unknown action — fail loud (do NOT keep polling: an
            # unrecognized verdict means a contract drift, not a
            # transient state).
            self._orch._logger.error(
                "Unknown facilitator action %r; attempting reconcile before "
                "fallback", action,
            )
            return self._orch._kickoff_fallback_or_reconcile(
                kickoff_handle, synthesis, "unknown_action",
            )

    # #1202ko: how recently a missing attendee touched a hub. Stores whose records carry
    # `_updated_by` + `_updated_at` — the two the lanes actually write through during a
    # kickoff. Deliberately NOT the agent log: the driver runs in the orchestrator process and
    # the hubs are the shared, durable record both sides already agree on.
    _WORK_STORES_1202KO = ("workhub_tasks", "codehub_commits", "registryhub_endpoints",
                           "registryhub_ui_pages", "registryhub_tables")

    def _missing_attendee_is_working_1202ko(self, synth, elapsed):
        """``(agent, n_writes)`` if a MISSING attendee wrote to a hub during this kickoff.

        Returns None when nobody is missing, nothing is known, or every missing attendee has
        been silent — in which case #28's fast escape is correct and proceeds unchanged.

        Best-effort by construction: any fault returns None, so a fault can only restore the
        old behaviour, never extend a wait.
        """
        try:
            missing = [str(a) for a in (synth or {}).get("missing") or [] if str(a).strip()]
            if not missing:
                return None
            import json as _json
            import time as _time
            from pathlib import Path as _Path
            base = _Path(str(getattr(self._orch.hubs, "base_dir", "") or "")) / "shared" / "hubs"
            if not base.is_dir():
                return None
            since = _time.time() - float(elapsed or 0)
            for agent in missing:
                n = 0
                for store in self._WORK_STORES_1202KO:
                    f = base / (store + ".json")
                    if not f.exists():
                        continue
                    try:
                        j = _json.loads(f.read_text(encoding="utf-8"))
                    except Exception:
                        continue
                    for k, r in (j.items() if isinstance(j, dict) else []):
                        if k == "_meta" or not isinstance(r, dict):
                            continue
                        if str(r.get("_updated_by") or "") != agent:
                            continue
                        # ONLY `_updated_at`. The two spellings are written by different
                        # things: `_updated_by`/`_updated_at` are stamped together by the hub
                        # write boundary, while a bare `updated_at` is the record's own domain
                        # field. Pairing this agent's NAME with that other clock is how the
                        # first draft of this read 13 "backend writes" for r112 where there was
                        # exactly one — the same two-spellings trap that once made a CodeHub
                        # check read a field nothing writes.
                        try:
                            ts = float(r.get("_updated_at") or 0)
                        except Exception:
                            continue
                        if ts >= since:
                            n += 1
                if n:
                    return (agent, n)
            return None
        except Exception:
            return None


    def _derive_missing_essential_sections(self, kickoff_handle, missing, reason: str):
        """Record deterministically-DERIVED sections for ESSENTIAL lanes
        (frontend/backend) that never authored a meeting decision in time (slow
        Gemini lane → kickoff stall/timeout → missing essential lane → today the
        run ABORTS because backend/frontend are non-deferrable). The milestone
        slice already LISTS the endpoints/tables (``- METHOD /path`` / ``- table:
        col,col``), so extract them and author the lane's section attributed to
        that lane — clearing quorum so synthesis can finalize. The implementation
        lane then builds these declared pages/endpoints properly. Returns the list
        of lanes salvaged ([] → nothing derivable; caller falls through to the
        honest fallback). Only ever fires for a lane that recorded NOTHING (it's in
        ``missing``), so it never fights a lane that already declared. General +
        deterministic; never manufactures a contract from an empty slice."""
        from .kickoff import run_kickoff
        description = str(kickoff_handle.get("description") or "")
        extracted = run_kickoff.extract_contract_from_description(description)
        eps = extracted.get("endpoints") or []
        tbls = extracted.get("tables") or []
        # Prefer endpoints the BACKEND lane ALREADY declared this milestone over the
        # slice extraction — the common stall is "backend declared, frontend didn't"
        # (youtube run #17), and the declared set is richer + format-independent.
        try:
            _decisions = run_kickoff._read_meeting_decisions(
                self._orch.hubs, kickoff_handle.get("meeting_id"))
            _drafts = run_kickoff._collect_drafts(_decisions)
            _be = _drafts.get("backend") or {}
            _declared_eps = list(_be.get("api_endpoints") or _be.get("endpoints") or [])
            _dm = _be.get("data_model") if isinstance(_be.get("data_model"), dict) else {}
            _declared_tbls = list(_dm.get("tables") or [])
        except Exception:
            _declared_eps, _declared_tbls = [], []
        fe_source_eps = _declared_eps or eps
        fe_source_tbls = _declared_tbls or tbls
        salvaged: List[str] = []
        _mi = kickoff_handle.get("milestone_index")
        _m2plus = isinstance(_mi, int) and not isinstance(_mi, bool) and _mi >= 2
        for lane in missing:
            if lane == "backend":
                # GUARD (milestone 1): require BOTH endpoints AND tables —
                # roadmap_validator hard-requires non-empty data_model.tables on the
                # FIRST milestone, so deriving a table-less backend section would
                # just re-fail validation while misleadingly logging "authored"
                # (reviewer-caught). Without both, honest fallback.
                # FIX #115 (run-31, live): at MILESTONE 2+ this guard is STALE —
                # #96/#108 made empty tables / missing data_model a WARNING there
                # (cumulative contract). run-31 had M1+M2 DELIVERED; the M3 kickoff
                # burned its window AND the #95 retry inside a 142-strong Gemini
                # MALFORMED storm, the slice parsed neither endpoints nor tables →
                # this guard `continue`d → salvage [] → abort at 15:29:45 (the
                # lane's own terminal backup stub landed 15:29:50 — it triggers on
                # the kickoff_request ENDING, i.e. the abort itself, so on this
                # path it is ALWAYS too late). Author an honest DEFERRED section
                # instead: the milestone proceeds degraded on the cumulative
                # contract rather than killing a run with delivered releases.
                if not eps or not tbls:
                    if not _m2plus:
                        continue
                    content: Dict[str, Any] = {
                        "section": "backend",
                        "endpoints": list(eps),
                        "data_model": ({"tables": list(tbls)} if tbls else {}),
                        "deferred": True,
                        "source": "auto_backup_timeout_m2plus",
                        "note": ("kickoff timed out with no backend section and an "
                                 "unparseable slice at milestone 2+ — deferred; the "
                                 "cumulative contract carries the prior milestones "
                                 "(#96/#108 downgrade these shapes to warnings)"),
                    }
                else:
                    content = {
                        "section": "backend", "endpoints": list(eps),
                        "data_model": {"tables": list(tbls)},
                    }
            elif lane == "frontend":
                if not fe_source_eps and not fe_source_tbls:
                    continue  # GUARD: no endpoints or tables → only a login page; skip
                # #1202pf: the design's screens first; the endpoint list only when it has none.
                content = {"section": "frontend",
                           "ui_pages": run_kickoff.salvaged_frontend_pages_1202pf(
                               getattr(self._orch, "output_dir", None) or "",
                               fe_source_eps, fe_source_tbls)}
            else:
                continue  # verifier handled by the existing defer block below
            try:
                self._orch.hubs.workhub.add_meeting_decision(
                    kickoff_handle.get("meeting_id"),
                    decision={
                        "section": lane, "content": content,
                        "note": ("auto-derived at kickoff stall from the milestone "
                                 "slice — lane did not author it in time"),
                    },
                    agent=lane,  # load-bearing: _missing_attendees counts by agent
                    milestone_index=kickoff_handle.get("milestone_index"),
                )
                salvaged.append(lane)
            except Exception as exc:  # pragma: no cover - defensive
                self._orch._logger.warning(
                    "Kickoff derive of '%s' failed (%s): %s", lane, reason, exc)
        if salvaged:
            self._orch._logger.warning(
                "🔧 KICKOFF DERIVE (%s): authored %s from the milestone slice "
                "(%d endpoints, %d tables) → re-synthesizing instead of aborting.",
                reason, salvaged, len(eps), len(tbls))
        return salvaged

    def _attempt_reconciled_finalize(self, kickoff_handle, reason: str):
        """Last-resort deterministic kickoff convergence (charter §8).

        Before aborting a kickoff that won't reach consensus, re-synthesize with
        ``reconcile=True`` — which prunes frontend api_calls to UNDEFINED
        endpoints (a UI call into the void; e.g. an invented ``GET /api/stories``)
        — and, if that makes the synthesis ``ready``, finalize the contract
        instead of failing the whole run. Returns the finalize receipt on
        success, or ``None`` (caller proceeds to ``synthesize_fallback``) when
        reconciliation can't produce a ready synthesis (a non-reconcilable
        conflict — dead endpoint, data-model drift — still aborts honestly).
        """
        from .kickoff import run_kickoff
        try:
            synth = run_kickoff.try_synthesize(
                self._orch.hubs, kickoff_handle, reconcile=True,
            )
        except Exception as exc:  # pragma: no cover - defensive
            self._orch._logger.warning(
                "Kickoff reconcile attempt raised (%s): %s", reason, exc,
            )
            return None
        # ESSENTIAL-lane salvage (youtube 2026-06-21): a slow Gemini frontend/backend
        # lane that never authored its section in time leaves an essential attendee
        # "missing" → non-deferrable → the run aborts even though M1 already delivered.
        # The milestone slice deterministically lists the endpoints/tables, so DERIVE
        # the missing essential lane's section from it (attributed to that lane),
        # clearing quorum, then re-synthesize. Runs BEFORE the verifier defer so a
        # frontend+verifier gap collapses to just-verifier, which the defer handles.
        if synth.get("status") == "awaiting":
            _missing = [m for m in (synth.get("missing") or []) if isinstance(m, str)]
            _essential = [m for m in _missing if m not in _DEFERRABLE_KICKOFF_ATTENDEES]
            if _essential and self._derive_missing_essential_sections(
                    kickoff_handle, _essential, reason):
                try:
                    synth = run_kickoff.try_synthesize(
                        self._orch.hubs, kickoff_handle, reconcile=True)
                except Exception:
                    return None
        # PROPOSAL #32: if synthesis is only blocked because a DEFERRABLE attendee never
        # submitted (the verifier — its acceptance predicates are derived from the
        # frontend's user_flows + the roadmap floor, and its REAL work, verification
        # chains, is designed POST-impl), record a deferred decision ATTRIBUTED TO that
        # attendee (load-bearing: _missing_attendees counts by the decision's ``agent``
        # field, so it must be agent=<attendee>, not "orchestrator") and re-synthesize.
        # Run #31 died here: Gemini didn't author section='verifier' → awaiting → kickoff
        # FAILED. ESSENTIAL attendees (backend/frontend) missing are NOT deferred → the
        # re-synthesis still returns awaiting → honest fallback (deferral can't
        # manufacture a real contract). The verifier still registers real chains at
        # validation (the deferred kickoff stub sets no "done" flag).
        if synth.get("status") == "awaiting":
            missing = [m for m in (synth.get("missing") or []) if isinstance(m, str)]
            if missing and all(m in _DEFERRABLE_KICKOFF_ATTENDEES for m in missing):
                for attendee in missing:
                    try:
                        self._orch.hubs.workhub.add_meeting_decision(
                            kickoff_handle.get("meeting_id"),
                            decision={
                                "section": attendee,
                                "content": {"deferred": True},
                                "note": ("auto-deferred at kickoff stall — section is "
                                         "derived/post-impl; lane did not author it in time"),
                            },
                            agent=attendee,
                            milestone_index=kickoff_handle.get("milestone_index"),
                        )
                    except Exception as _def_err:  # pragma: no cover - defensive
                        self._orch._logger.warning(
                            "Kickoff defer of '%s' failed (%s): %s", attendee, reason, _def_err,
                        )
                self._orch._logger.warning(
                    "Kickoff (%s): deferred non-submitting attendee(s) %s (section "
                    "derived/post-impl) → re-synthesizing instead of failing the run.",
                    reason, missing,
                )
                try:
                    synth = run_kickoff.try_synthesize(
                        self._orch.hubs, kickoff_handle, reconcile=True,
                    )
                except Exception:
                    return None
        if synth.get("status") != "ready":
            # Diagnostic: surface what's still blocking after pruning dangling
            # UI calls + downgrading dead endpoints, so the run log pinpoints
            # any residual runtime-fatal drift (e.g. api↔data_model) instead of
            # an opaque "still conflict".
            findings = synth.get("findings") or []
            details = [
                # cross-check findings carry detail/offending_field; roadmap
                # validation findings carry section/id/message — log whichever.
                (f.get("message") or f.get("detail")
                 or f.get("offending_field")
                 or f.get("id") or f.get("section"))
                for f in findings if isinstance(f, dict)
            ][:8]
            self._orch._logger.warning(
                "Kickoff reconcile (%s) did not reach ready (status=%s); "
                "residual findings=%s — falling through to fallback.",
                reason, synth.get("status"), details,
            )
            return None
        added = synth.get("reconciled_added") or []
        normalized = synth.get("reconciled_normalized") or []
        self._orch._logger.warning(
            "🔧 KICKOFF RECONCILE (%s): auto-registered %d endpoint(s) for frontend "
            "call(s) the backend didn't declare %s (the skeleton generates them); "
            "normalized %d endpoint-shape issue(s) %s → synthesis ready; finalizing "
            "instead of aborting the run.",
            reason, len(added), added, len(normalized), normalized[:6],
        )
        receipt = run_kickoff.finalize_kickoff(
            hubs=self._orch.hubs,
            kickoff_handle=kickoff_handle,
            synthesis=synth,
            agent="orchestrator",
        )
        try:
            self._orch._author_kickoff_docs(synth)
        except Exception as _auth_err:  # pragma: no cover - doc bug, not kickoff
            self._orch._logger.warning(
                "kickoff authoring failed (non-fatal): %s", _auth_err,
            )
        return receipt

    def _kickoff_fallback_or_reconcile(
        self, kickoff_handle, last_synthesis, reason: str,
    ):
        """Try a deterministic reconcile-and-finalize before the hard abort.

        Wraps every kickoff abort site: if dangling-UI-call reconciliation can
        finalize the contract, return that receipt; otherwise fall through to
        the honest ``synthesize_fallback`` (kickoff_failed) path.
        """
        from .kickoff import run_kickoff
        receipt = self._orch._attempt_reconciled_finalize(kickoff_handle, reason)
        if receipt is not None:
            return receipt
        fallback = run_kickoff.synthesize_fallback(
            hubs=self._orch.hubs,
            kickoff_handle=kickoff_handle,
            last_synthesis=last_synthesis,
            agent="orchestrator",
        )
        # #1202ed: WHICH of the nine aborts produced this fallback, and how long it
        # really took. Every call site here passes a distinct `reason` — timeout,
        # escalate, max_rounds, driver_wedged, consensus_not_ready, initial_stall,
        # no_revisers, unknown_action, provider_terminal — and all nine collapse into
        # the single phase "timeout_fallback", which the orchestrator then reports as a
        # timeout. Only one of the nine is one. Stamped here because this is the one
        # place every abort passes through.
        try:
            fallback["abort_reason_1202ed"] = str(reason)
            _started_1202ed = kickoff_handle.get("started_at")
            if isinstance(_started_1202ed, (int, float)):
                fallback["abort_elapsed_1202ed"] = time.time() - float(_started_1202ed)
        except Exception as _stamp_err_1202ed:
            from .message_format import warn_once_1201
            warn_once_1201("kickoff_driver._kickoff_fallback_or_reconcile",
                           "a kickoff abort cannot say which reason produced it",
                           _stamp_err_1202ed)
        return fallback

    async def _dispatch_implementation_phase(self) -> List[str]:
        """§5-entry / D4.3 (reframed): deterministically hand the implementation
        phase to the lanes the moment kickoff finalizes.

        finalize_kickoff already created + assigned the task tree; this is the
        ``[P]`` dispatch step (pipeline_process_design.md §4 D4.3 / §5.1). Smoke
        #3 (2026-06-05) proved the old "lanes wake on kickoff_complete + a later
        nudge" path fails: kickoff_complete isn't a ``task_ready`` so it doesn't
        pass ``KickoffBootstrapGate`` (allowed_starters=['orchestrator']), and the
        lanes burn their idle budget on empty kickoff-reply finishes and get
        ``LaneIdleCircuitBreaker``-halted before they ever implement.

        So, right after finalize, we:
          1. RESET each lane's idle counters — the kickoff-reply phase must not
             pre-halt the implementation phase (fresh budget at the boundary).
          2. DISPATCH an orchestrator ``task_ready`` to each implementation lane
             with assigned work — which passes ``KickoffBootstrapGate`` and makes
             the lane claim + implement (one-pass), no subscription/nudge race.

        The verifier is intentionally NOT dispatched here — it self-triggers on
        impl-completion (the §6 / ⚠2 validation-ready hub signal)."""
        from tools.communication_tools import _create_message

        # 1. Reset idle counters at the kickoff→implement boundary.
        for lane_id, agent in self._orch._agents.items():
            if agent is None:
                continue
            agent._consecutive_idle_steps = 0
            agent._last_idle_tier = 0
            agent._lane_idle_tier3_failed = False
            # None forces the breaker to re-seed its "owned" baseline on the next
            # finish — so the first implementation step is never counted as idle.
            agent._lane_idle_prev_owned = None

        # 2. Which lanes have assigned implementation tasks?
        try:
            tasks = self._orch.hubs.workhub.list_tasks() or {}
            task_iter = tasks.values() if isinstance(tasks, dict) else tasks
        except Exception:
            task_iter = []
        # #1076: WAKE EVERY IMPL LANE, DELIBERATELY — and say so instead of
        # encoding it as a check that cannot fail. This read
        #
        #     if lane in impl_lanes and (lane in assignees or True)
        #
        # where `X or True` is always True, so `lane in assignees` never mattered
        # and the twelve lines above it — walk the task tree, read each task's
        # owner/assignee, lowercase, collect — existed only to be ignored. Nothing
        # else in this function read that set.
        #
        # The behaviour was right. This function exists BECAUSE lanes must be woken
        # at the kickoff->implementation boundary: otherwise they "burn their idle
        # budget on empty kickoff-reply finishes and get LaneIdleCircuitBreaker-
        # halted before they ever implement" (smoke #3, 2026-06-05). Filtering on
        # current assignment would risk waking nobody when the tree has not been
        # read yet, which is presumably why the `or True` went in.
        targets = _impl_dispatch_targets_1076(self._orch._agents)

        dispatched: List[str] = []
        for lane_id in targets:
            msg = _create_message(
                source_agent_id="orchestrator",
                target_agent_id=lane_id,
                content=(
                    "Kickoff finalized — the M1 contract (endpoints/tables/pages) "
                    "and your assigned task_tree entries are registered in "
                    "RegistryHub/WorkHub. Claim your tasks now "
                    f"(workhub_list_tasks assignee='{lane_id}', status='pending') "
                    "and implement them in one pass. Do NOT ack-and-wait."
                ),
                msg_type="task_ready",
                priority="urgent",
                persist=True,
                tags=["kickoff_dispatch", "implementation_start"],
            )
            try:
                if await self._orch.message_bus.send(msg):
                    dispatched.append(lane_id)
            except Exception as exc:
                self._orch._logger.warning("impl dispatch to %s failed: %s", lane_id, exc)
        self._orch._logger.info(
            "Dispatched implementation phase task_ready to: %s",
            ", ".join(dispatched) or "none",
        )
        return dispatched

    def _lane_activity_1202fg(self) -> str:
        """Say what the agent logs SHOW, instead of asserting which of two causes it is.

        #862's line read "This is the shape of a lane that never started rather than one
        that is slow; check .agent_logs for empty per-agent directories" -- it names the
        distinguishing evidence and then does not look at it. netflix-r41's third resume
        died on that sentence being wrong: the lanes had made 151 tool calls between them
        (verifier 74, orchestrator 62, backend 7, frontend 2) and the log still said they
        never started, so the run's own record points at the wrong repair.

        The two causes need different fixes -- a lane that never spawned is an orchestration
        failure, a lane that is working but has not recorded a SECTION is a meeting-protocol
        one -- which is exactly why #1114/#1023's rule applies here: report the evidence,
        never assert the verdict.
        """
        try:
            act = _lane_log_activity_1202fg(getattr(self._orch, "output_dir", ""))
            if not act:
                return ("No .agent_logs to read, so which of the two causes this is cannot "
                        "be told from here (#1202fg).")
            live = {k: v for k, v in act.items() if v > 0}
            if not live:
                return ("Every per-agent .agent_logs directory is EMPTY — the lanes never "
                        "started, which is an orchestration failure, not a slow meeting.")
            return ("But the lanes ARE running: %s. They started and have not recorded a "
                    "SECTION, which is a meeting-protocol failure and needs a different "
                    "repair than a lane that never spawned (#1202fg)."
                    % ", ".join("%s %.0fKB" % (k, v / 1024.0)
                                for k, v in sorted(live.items())))
        except Exception:
            return "Could not read .agent_logs to tell the two causes apart (#1202fg)."

    def _author_kickoff_docs(
        self, synthesis: Dict[str, Any],
    ) -> None:
        """Round 8f.2: after finalize_kickoff returns a clean receipt,
        materialize the human-readable milestone docs to disk.

        Writes (under ``self._orch.output_dir``):
          * ``docs/milestones/MILESTONE_M{n}.md`` (overwrite)
          * ``docs/ROADMAP.md`` (idempotent append/replace by M-section)
          * ``docs/briefings/BRIEFING_M{n}_{agent}.md`` per attendee

        Uses :mod:`runtime.kickoff.authoring` — pure-Python rendering,
        no LLM call. Determinism is enforced by passing the same
        synthesis_result the driver already used for finalize_kickoff.

        Errors are intentionally swallowed by the caller: the contract
        ALREADY shipped via finalize_kickoff before this runs; a
        markdown-write failure must not invalidate that. The caller
        logs at WARNING so a debug pass can pick up the failure.
        """
        from .kickoff.authoring import author_all
        # Read existing ROADMAP.md (if any) so we append/replace
        # idempotently rather than blowing away prior milestones.
        roadmap_path = self._orch.output_dir / "docs" / "ROADMAP.md"
        prior_roadmap_md: Optional[str] = None
        if roadmap_path.exists():
            try:
                prior_roadmap_md = roadmap_path.read_text(encoding="utf-8")
            except OSError as _e:
                self._orch._logger.warning(
                    "Could not read existing %s (%s); rewriting from scratch.",
                    roadmap_path, _e,
                )
        project_name = getattr(self._orch.context, "name", None) or "Project"
        outputs = author_all(
            synthesis,
            project_name=project_name,
            prior_roadmap_md=prior_roadmap_md,
        )
        # Write artifacts. Paths in `outputs["paths"]` are relative; we
        # anchor under output_dir so they land alongside the project
        # workspace (CI repo / live_monitor inspection / etc.).
        milestone_path = self._orch.output_dir / outputs["paths"]["milestone"]
        milestone_path.parent.mkdir(parents=True, exist_ok=True)
        milestone_path.write_text(outputs["milestone"], encoding="utf-8")

        roadmap_path.parent.mkdir(parents=True, exist_ok=True)
        roadmap_path.write_text(outputs["roadmap"], encoding="utf-8")

        for agent_id, briefing_md in (outputs.get("briefings") or {}).items():
            rel = outputs["paths"]["briefings"][agent_id]
            briefing_path = self._orch.output_dir / rel
            briefing_path.parent.mkdir(parents=True, exist_ok=True)
            briefing_path.write_text(briefing_md, encoding="utf-8")

        self._orch._logger.info(
            "Authored kickoff docs: %s + %s + %d briefings",
            milestone_path, roadmap_path,
            len(outputs.get("briefings") or {}),
        )

