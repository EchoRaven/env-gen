from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import Dict, List, Mapping, Optional, Tuple
from uuid import uuid4

from utils.llm import Message
from utils.message import BaseMessage, MessageHeader, MessagePriority, MessageType, TaskMessage

from .common import ProcessingState


class AgentMessaging:
    async def receive_message(self, message: BaseMessage) -> None:
        """
        Override BaseAgent.receive_message to use priority queue.

        Message priority (agent-controlled):
        - URGENT (4): Immediate attention required
        - HIGH (3): Process as soon as possible
        - NORMAL (2): Standard processing order
        - LOW (1): Process when idle

        Priority is set by the SENDER. Only system-critical messages are auto-elevated.
        Same priority messages are processed in FIFO order.
        """
        # Cross-loop guard: a hub event emitted from inside a `to_thread` tool
        # worker (e.g. registryhub_register_endpoint -> _emit -> publish_event ->
        # bridge.deliver) reaches receive_message on a DIFFERENT loop than the
        # one this agent's queues are bound to. The queue's asyncio.Lock/Event
        # then raise "bound to a different event loop" and the message is dropped
        # (flooded orchestrator delivery in the 2026-06-06 smokes). Redispatch
        # the whole call onto the agent's home loop, thread-safely, and return.
        home = getattr(self, "_home_loop", None)
        if home is not None:
            try:
                running = asyncio.get_running_loop()
            except RuntimeError:
                running = None
            if running is not home:
                home.call_soon_threadsafe(
                    lambda: home.create_task(self.receive_message(message))
                )
                return

        msg_type = message.metadata.get("msg_type", "").lower()

        if msg_type == "shutdown":
            message.header.priority = MessagePriority.URGENT

        self._logger.debug(f"[{self.agent_id}] Received {msg_type} (priority={message.header.priority.name})")

        if msg_type in ("ack", "status"):
            original_msg_id = message.metadata.get("original_message_id")
            if original_msg_id and self._message_tracker:
                ack_type = message.metadata.get("ack_type", "")
                if ack_type == "delivered":
                    self._message_tracker.mark_delivered(original_msg_id)
                elif ack_type == "read":
                    self._message_tracker.mark_read(original_msg_id)
                elif message.metadata.get("processing_status") == "in_progress":
                    self._message_tracker.mark_read(original_msg_id)
                if msg_type == "ack":
                    return

        inbox_msg = {
            "id": message.header.message_id,
            "from": message.header.source_agent_id,
            "type": msg_type or message.message_type.value,
            "content": message.payload if isinstance(message.payload, str) else str(message.payload),
            "tags": message.metadata.get("tags", []),
            "metadata": dict(message.metadata or {}),
            "priority": message.header.priority.name.lower(),
            "persist": message.metadata.get("persist", False),
            "read": False,
            "timestamp": datetime.now().isoformat(),
        }

        inbox = getattr(self, "_subscription_inbox", None)
        if inbox is None:
            self._subscription_inbox = []
            inbox = self._subscription_inbox
        inbox.append(inbox_msg)

        if msg_type in ("issue", "task_ready", "question"):
            await self._send_delivery_ack(message)

        if message.header.priority in (MessagePriority.URGENT, MessagePriority.HIGH):
            if msg_type in ("issue", "task_ready", "question"):
                self._interrupt_messages.append(inbox_msg)
                self._logger.info(f"[{self.agent_id}] Queued interrupt: {msg_type} from {inbox_msg['from']}")

        await self._priority_queue.put(message)
        await self._enqueue_for_dispatch(message)
        await self._maybe_schedule_resident_message_wakeup(message, inbox_msg)

    def get_inbox_messages(self, limit: int = 10, clear: bool = True) -> List[Dict]:
        """Get messages from inbox."""
        inbox = getattr(self, "_subscription_inbox", [])
        messages = inbox[:limit]
        if clear:
            self._subscription_inbox = [m for m in inbox if m.get("persist", False)]
        return messages

    async def _maybe_schedule_resident_message_wakeup(
        self,
        message: BaseMessage,
        inbox_msg: Dict,
    ) -> None:
        """Wake resident lanes for ordinary inbox messages, not only task_ready."""
        if not getattr(self, "_is_resident_lane", False):
            return
        if isinstance(message, TaskMessage):
            return

        msg_type = str(inbox_msg.get("type") or "").lower()
        # ``info`` is non-actionable per-step NARRATION ("Writing tailwind…",
        # "Continuing scaffolding…") — it must NOT wake a resident lane. v9: the
        # frontend sent 39 info messages to the orchestrator, each waking it →
        # the orchestrator churned 78 near-empty finish cycles. Real work uses
        # issue / question / task_ready / blocker, which still wake. (ack/status/
        # shutdown were already excluded; info joins them.)
        if msg_type in {"ack", "status", "shutdown", "info"}:
            return
        # F2b (2026-07-22): during coordinator-owned KICKOFF, an attendee's progress 'update' /
        # 'answer' must NOT wake the orchestrator — it can take no kickoff action then (the
        # pure-Python coordinator drives declaration→synthesis; chairing arrives as the separate
        # kickoff_facilitate_request / kickoff_detail_request msg_types, which still wake). Each such
        # wake is a wasted large-context LLM call (~88s) that also starves the attendees of GPT-5.6
        # throughput — r6: 44 idle orchestrator wakes during kickoff, kickoff crawled >21min. Mirrors
        # the 'info' exclusion above, but SCOPED to pre-finalize so post-kickoff update/answer
        # handling (the youtube#12 answer/question drain) is unchanged.
        if msg_type in {"update", "answer"}:
            try:
                from .preconditions import kickoff_finalized_signal
                _pre_finalize = not kickoff_finalized_signal(getattr(self, "_hubs", None), self)
            except Exception:
                _pre_finalize = False
            if _pre_finalize:
                self._logger.debug(
                    f"[{self.agent_id}] retained {msg_type} from {inbox_msg.get('from')} without "
                    "wakeup; coordinator-owned kickoff not finalized (F2b)")
                return
        # task_ready / issue / question / answer are DIRECT work-for-this-lane
        # signals. They used to be UNCONDITIONALLY excluded here and delegated
        # SOLELY to the priority-queue urgent-drain (run_loop). youtube run #12
        # (Defect C): once a resident lane finish()ed and went idle, that drain
        # stopped consuming — a task_ready (frontend) / question (orchestrator)
        # sat queued forever, the verifier dead-waited on the frontend, and the
        # whole run idle-spun to its wall-clock budget. We now let these flow
        # through the SAME policy-gated wakeup path as other inbox messages,
        # giving an idle resident lane a second, INDEPENDENT way to wake and
        # drain (via the _main_loop task path, which we know reaches idle
        # residents because dispatched tasks do). This is additive and
        # self-deduping: if the urgent-drain still works it pops the message
        # first and the woken step finds nothing; if it wedged, this wakes the
        # lane to drain. It is NOT a policy bypass — the allow_resident_wakeup
        # gate below (VerifierValidationTriggerPolicy / DependsOnPolicy) still
        # decides whether the lane should actually wake, so the gating those
        # policies enforce on task_ready is preserved. Unifies with Defect B:
        # all "new work for a resident lane" now reaches it through _main_loop.
        tags = {str(tag).strip().lower() for tag in (inbox_msg.get("tags") or [])}
        if (
            not getattr(self, "_kickoff_bootstrapped", True)
            and self._has_kickoff_bootstrap_gate()
            and "wake_resident" not in tags
            and "force_wakeup" not in tags
        ):
            self._logger.debug(
                f"[{self.agent_id}] retained {msg_type} from {inbox_msg.get('from')} without wakeup; "
                "kickoff bootstrap gate is still closed"
            )
            return
        # Exempt ``task_created`` events whose new task is assigned
        # to THIS lane from every policy gate. The lane's own task
        # queue gaining an entry is a definitionally legitimate
        # wakeup — DependsOnPolicy / VerifierValidationTriggerPolicy
        # etc. should still gate the lane from doing work it isn't
        # ready for, but they must not block awareness of its own
        # tasks. Smoke #44-#46 wedged here: kickoff synthesized
        # validate_* tasks for verifier, but the policy chain
        # suppressed every task_created event, so verifier never
        # claimed them.
        bypass_policies = False
        if msg_type == "task_created":
            payload = getattr(message, "payload", None)
            if isinstance(payload, str):
                import ast
                import json as _json
                parsed = None
                try:
                    parsed = _json.loads(payload)
                except Exception:
                    try:
                        parsed = ast.literal_eval(payload)
                    except Exception:
                        parsed = None
                payload = parsed
            if isinstance(payload, dict):
                assignee = (payload.get("assignee") or payload.get("owner") or "").strip()
                if assignee == self.agent_id:
                    bypass_policies = True
        # Kickoff PARTICIPATION events are MANDATORY work for every attendee (author
        # your section, post the phase_acks) — NOT "arbitrary inbox messages". The
        # VerifierValidationTriggerPolicy / DependsOnPolicy must NOT suppress them, or
        # the lane never wakes to participate and the kickoff hangs to its timeout
        # waiting on it — the exact instagram M1/M2 hang (verifier + frontend
        # suppressed their kickoff_reply_phase_request wakeup, 42×, → 1200s timeout).
        # The notifications (kickoff_complete/failed/fallback/transition) are NOT
        # participation and stay policy-gated.
        elif msg_type in (
            "kickoff_request", "kickoff_comment_phase_request",
            "kickoff_reply_phase_request", "kickoff_revision_request",
        ):
            bypass_policies = True

        # Re-audit (2026-05-29) HIGH #4: consult the dedicated
        # ``allow_resident_wakeup`` hook so the resident-wakeup path
        # respects DependsOnPolicy / VerifierValidationTriggerPolicy.
        # Policies that don't care return None and the wakeup
        # proceeds. Skipped when the event is task_created-for-self
        # (see comment above).
        if not bypass_policies:
            for policy in getattr(self, "_workflow_policies", []) or []:
                try:
                    decision = policy.allow_resident_wakeup(self, message, inbox_msg)
                except Exception as _pol_err:
                    # A buggy policy must never block legitimate wakeups —
                    # log and continue, matching the defensive posture of
                    # the rest of this path.
                    self._logger.warning(
                        f"[{self.agent_id}] resident-wakeup policy "
                        f"{type(policy).__name__} raised: {_pol_err}; "
                        "treating as no-opinion"
                    )
                    continue
                if decision is None:
                    continue
                allowed, reason = decision
                if not allowed:
                    self._logger.info(
                        f"[{self.agent_id}] suppressing resident wakeup "
                        f"({msg_type} from {inbox_msg.get('from')}): {reason}"
                    )
                    return
        if getattr(self, "_resident_wakeup_task_pending", False):
            return

        self._resident_wakeup_task_pending = True

        async def _enqueue_wakeup() -> None:
            await asyncio.sleep(0)
            try:
                header = MessageHeader(
                    message_id=str(uuid4()),
                    source_agent_id="runtime",
                    target_agent_id=self.agent_id,
                    priority=MessagePriority.LOW,
                )
                task_msg = TaskMessage(
                    header=header,
                    task_id=str(uuid4()),
                    task_name="resident_message_wakeup",
                    payload={
                        "name": "resident_message_wakeup",
                        "workflow": "resident_tick",
                        "trigger": "inbox_message",
                        "source_agent": inbox_msg.get("from"),
                        "message_type": msg_type,
                        "message_id": inbox_msg.get("id"),
                        "instruction": (
                            "You are a resident lane woken up by a new inbox message. "
                            "Check unread inbox messages, decide whether action is required, "
                            "route or perform the next step, then call finish()."
                        ),
                    },
                )
                await self._message_queue.put(task_msg)
                self._logger.info(
                    f"[{self.agent_id}] scheduled resident wakeup for {msg_type} from {inbox_msg.get('from')}"
                )
            except Exception as e:
                self._logger.warning(f"[{self.agent_id}] failed to schedule resident wakeup: {e}")
                self._resident_wakeup_task_pending = False

        asyncio.create_task(_enqueue_wakeup())

    def _has_kickoff_bootstrap_gate(self) -> bool:
        for policy in getattr(self, "_workflow_policies", []) or []:
            if policy.__class__.__name__ == "KickoffBootstrapGate":
                return True
        return False

    async def _send_delivery_ack(self, message: BaseMessage) -> None:
        """Send automatic delivery acknowledgement back to sender."""
        sender = message.header.source_agent_id
        if not sender or sender == self.agent_id:
            return

        bus = self._external_bus
        if not bus:
            return

        msg_type = message.metadata.get("msg_type", "")
        msg_id = message.header.message_id
        ack_header = MessageHeader(
            source_agent_id=self.agent_id,
            target_agent_id=sender,
            priority=MessagePriority.LOW,
            reply_to=msg_id,
        )
        ack_message = BaseMessage(
            header=ack_header,
            message_type=MessageType.STATUS,
            payload=f"DELIVERED: {msg_type} message received by {self.agent_id}",
            metadata={
                "msg_type": "ack",
                "original_message_id": msg_id,
                "ack_type": "delivered",
            },
        )

        try:
            await bus.publish(ack_message)
            self._logger.debug(f"[{self.agent_id}] Sent delivery ACK for {msg_id[:8]}... to {sender}")
        except Exception as e:
            self._logger.warning(f"[{self.agent_id}] Failed to send delivery ACK: {e}")


    async def _enqueue_for_dispatch(self, message) -> None:
        """FIX #150 (run-71/run-77 REAL-wedge root, USR2-proven live): never
        park the SENDER on the bounded dispatch queue. run-77 09:56: SEVEN
        tasks sat parked at `await self._message_queue.put(...)` — the target
        lane's _main_loop was itself stuck inside _dispatch_message, so its
        Queue(100) never drained; the backend's post-FINISH notification flush
        parked on it and the finishing loop never unwound (state stuck
        PROCESSING_TASK 12min until the #147/#149 watchdog rescue). By this
        point the message already reached _subscription_inbox, the priority
        queue, and the interrupt channel for urgent types — the bounded queue
        only feeds ordinary _main_loop dispatch, and a 100-deep backlog means
        that dispatch is already dead. Drop THAT copy loudly instead of
        cascading the stall into every sender."""
        _put_nowait = getattr(self._message_queue, "put_nowait", None)
        if _put_nowait is None:
            # duck-typed queue without a non-blocking put (test doubles) —
            # legacy path; the real asyncio.Queue always has put_nowait.
            await self._message_queue.put(message)
            return
        try:
            _put_nowait(message)
        except asyncio.QueueFull:
            self._logger.warning(
                f"[{self.agent_id}] dispatch queue FULL "
                f"({self._message_queue.maxsize} pending) — dropping the "
                "ordinary-dispatch copy (inbox + priority-queue copies kept) "
                "instead of parking the sender (FIX #150)")

    async def _pickup_undelivered_inbox_events(self) -> int:
        """Drain cross-process events from the on-disk inbox.

        The MessageBusBridge only sees publishes that happen inside *this*
        process; chat messages from the monitor server (a different process,
        also using HubRegistry) land on disk with ``delivered=False`` and never
        reach our priority queue. JsonStore re-reads from disk on every call,
        so we can scan the agent's on-disk inbox here, build BaseMessages for
        every undelivered item, push them through ``receive_message`` (which
        enqueues them into the same priority queue as in-process events), and
        mark them delivered via ``mark_delivered``. Idempotent — already-
        delivered items are skipped.
        """
        hubs = getattr(self, "_hubs", None)
        if not hubs or not getattr(hubs, "hubs", None):
            return 0
        eventhub = hubs.hubs.eventhub
        try:
            inbox = eventhub._inboxes.get(self.agent_id) or {}
        except Exception:
            return 0
        items = (inbox.get("items") or {}) if isinstance(inbox, dict) else {}
        if not items:
            return 0
        picked = 0
        # BaseMessage, MessageHeader, MessageType, MessagePriority already
        # imported at module top from utils.message.
        priority_map = {
            "low": MessagePriority.LOW, "normal": MessagePriority.NORMAL,
            "high": MessagePriority.HIGH, "critical": MessagePriority.URGENT,
            "human_user": MessagePriority.URGENT,
        }
        for event_id, item in list(items.items()):
            if not isinstance(item, dict) or item.get("delivered"):
                continue
            event = None
            try:
                event = eventhub._events.get(event_id)
            except Exception:
                pass
            if not isinstance(event, dict):
                # Cannot reconstruct without the event body; mark delivered so
                # we don't retry forever on a corrupted entry.
                # O14/Phase 4.1: self-mutation (agent marks own inbox).
                try: eventhub.mark_delivered(
                    self.agent_id, event_id, caller=self.agent_id,
                )
                except Exception: pass
                continue
            priority = priority_map.get(str(event.get("priority", "normal")), MessagePriority.NORMAL)
            header = MessageHeader(
                source_agent_id=event.get("source_hub", "eventhub"),
                target_agent_id=self.agent_id,
                priority=priority,
                correlation_id=event.get("thread_id"),
            )
            payload = event.get("payload") or {}
            metadata = {
                "source_hub": event.get("source_hub"),
                "event_id": event_id,
                "event_type": event.get("event_type"),
                "thread_id": event.get("thread_id"),
                "resource_type": payload.get("resource_type"),
                "resource_id": payload.get("resource_id"),
                "msg_type": event.get("event_type"),
                "tags": event.get("tags") or [],
            }
            msg = BaseMessage(header=header, message_type=MessageType.STATUS, payload=payload, metadata=metadata)
            try:
                result = self.receive_message(msg)
                if hasattr(result, "__await__"):
                    await result
                # O14/Phase 4.1: self-mutation (agent marks own inbox).
                eventhub.mark_delivered(
                    self.agent_id, event_id, caller=self.agent_id,
                )
                picked += 1
            except Exception as e:
                self._logger.debug(f"[{self.agent_id}] pickup undelivered {event_id} failed: {e}")
        if picked:
            self._logger.info(f"[{self.agent_id}] picked up {picked} undelivered cross-process event(s)")
        return picked

    async def _check_and_handle_urgent(self, from_loop: bool = False) -> bool:
        """Check for urgent messages and handle them.

        Drain the on-disk inbox first so cross-process events (e.g. chat
        messages published by the monitor server) make it into the priority
        queue before we pull from it.

        ``from_loop`` (#149): True when the caller IS the running agentic loop
        (step boundary / between action rounds). A drain the loop itself
        executes proves the loop is alive, so the #147 wedge branch must not
        fire there — all four run-72/73 WEDGED declarations were healthy
        mid-step lanes (the backend loop declared wedged at 00:32:29 completed
        its task normally at 00:43:16), and the force-reset spawned CONCURRENT
        loops in the same lane. The resident poller (base.run_loop) keeps the
        default False and retains the run-71 real-wedge rescue.
        """
        try:
            await self._pickup_undelivered_inbox_events()
        except Exception as e:
            self._logger.debug(f"[{self.agent_id}] pickup_undelivered_inbox_events errored: {e}")
        urgent_msg = await self._priority_queue.get_if_urgent()
        if not urgent_msg:
            return False

        msg_type = urgent_msg.metadata.get("msg_type", "").lower()

        # Shield the kickoff-response AUTHORING pass from interrupt starvation.
        # During kickoff the orchestrator's synthesis fires a flood of
        # task_created / endpoint_schema_changed / integrity_check events (38+
        # observed in M1), and the ``task_created``-for-self bypass (smoke
        # #44-46, added so the VERIFIER could claim its validation tasks) lets
        # every one of them WAKE the lane mid-kickoff. The lane then burns its
        # tight ~12-step kickoff budget processing the flood (inbox / memory_bank
        # churn) and NEVER calls ``workhub_add_meeting_decision`` to author its
        # contract section — leaving an empty auto_backup stub that the frontend
        # can't align to, which loops the meeting in unresolvable revision rounds
        # (the prime cause of the M1 kickoff stalls). While authoring (only while
        # ``_active_phase == "kickoff"``), DROP these non-kickoff interrupts: the
        # underlying tasks/events persist in their hubs, and the lane picks them
        # up right after kickoff via ``task_ready`` + ``workhub_list_tasks`` — so
        # the verifier's task-claiming and everything else is unaffected outside
        # the brief authoring window.
        if getattr(self, "_active_phase", None) == "kickoff" and msg_type in (
            "task_created", "endpoint_schema_changed", "integrity_check",
            "table_changed", "endpoint_implemented", "api_requirement",
        ):
            self._logger.info(
                f"[{self.agent_id}] deferring urgent {msg_type} during kickoff "
                "authoring (persists in-hub; re-picked-up post-kickoff)"
            )
            return True

        self._logger.info(f"[{self.agent_id}] Handling urgent {msg_type}")

        # Cutover 29: Human-user messages from EventHub → dedicated handler.
        event_type = (urgent_msg.metadata or {}).get("event_type", "")
        if event_type == "human_message":
            try:
                await self._handle_human_message(urgent_msg)
            except Exception as e:
                self._logger.error(f"[{self.agent_id}] Error handling human_message: {e}")
            return True

        if msg_type == "shutdown":
            self._shutdown_requested = True
            return True

        if msg_type == "question":
            prev_state = self._processing_state
            self._processing_state = ProcessingState.ANSWERING_QUESTION
            await self._handle_question(urgent_msg)
            self._processing_state = prev_state
            return True

        if msg_type == "answer":
            await self._handle_answer(urgent_msg)
            return True

        if msg_type == "issue":
            await self._handle_issue(urgent_msg)
            return True

        # Round-8c Fix #2 (per round-8b reviewer correction): the
        # kickoff_request urgent event was being received and logged
        # ("Handling urgent kickoff_request") but no msg_type branch
        # below dispatched into an LLM turn, so the 4 attendees just
        # sat idle — confirmed in the round-8b smoke (their
        # .agent_logs/ directories were empty for the first ~5 min).
        # Wire it to a dedicated handler that renders the
        # kickoff_response_prompt macro and runs ONE agentic loop —
        # the macro itself caps the response at "Run ONCE, then
        # finish(). Do NOT loop. Do NOT poll for synthesis."
        # Kickoff handlers run IMMEDIATELY when received (the V26 behavior).
        # HISTORY: a busy-guard that DEFERRED these (to avoid running a second
        # agentic loop concurrently with the resident main loop) was tried and
        # LIVELOCKED — the orchestrator's continuous resident wakeups out-raced the
        # drain, so a deferred kickoff_detail_request sat unhandled for minutes while
        # the lane idled "waiting for kickoff", the detail was never authored, and the
        # poll fell back to the slice (V27 01:48-01:52). The concrete double-AUTHOR
        # harm (two milestone_set_detail writes) is already prevented at the SOURCE:
        # milestone_registry.set_detail no-ops once detail_authored is marked, and the
        # author poll resolves on is_detail_authored (turn-complete). So dispatching
        # directly is correct + unblocks the kickoff; the full per-agent turn mutex is
        # the deferred structural fix for the (benign-in-practice) concurrent loop.
        if msg_type == "kickoff_request":
            await self._handle_kickoff_request(urgent_msg)
            return True

        # Round-8f.1: facilitator handler — only the orchestrator subscribes to
        # ``kickoff_facilitate_request``. The driver fires it after try_synthesize
        # returns ready/conflict, asking the orchestrator to CHAIR the meeting: read
        # all attendee decisions, author ONE facilitator_note (consensus /
        # request_revision / escalate). Mirror of _handle_kickoff_request.
        if msg_type == "kickoff_facilitate_request":
            await self._handle_kickoff_facilitate_request(urgent_msg)
            return True

        # Per-milestone KICKOFF-DETAIL turn: author THIS phase's detailed milestone
        # spec + (optionally) revise FUTURE milestones via the milestone_* tools,
        # BEFORE the lanes draft. Mirror of facilitate; macro kickoff_milestone_detail_prompt.
        if msg_type == "kickoff_detail_request":
            await self._handle_kickoff_detail_request(urgent_msg)
            return True

        # Round-8f.1: facilitator-driven single-pass revision. After
        # round 1 the orchestrator (as meeting facilitator) records a
        # facilitator_note flagging a subset of attendees as ``revisers``
        # plus a per-agent ``revision_focus``. ``request_revisions``
        # (runtime/kickoff/facilitate.py) broadcasts a
        # ``kickoff_revision_request`` urgent event to exactly those
        # revisers. Without a dedicated branch here, the urgent loop
        # would log "Handling urgent kickoff_revision_request" and drop
        # the event — identical to the round-8b regression class that
        # Fix #2 closed for kickoff_request. Wire it to a dedicated
        # handler that renders the ``kickoff_revision_prompt`` macro
        # and runs ONE agentic loop (single-pass per the macro itself).
        if msg_type == "kickoff_revision_request":
            await self._handle_kickoff_revision_request(urgent_msg)
            return True

        # Round-8g Fix: phase-aware meeting protocol — comment + reply
        # phases. Broadcast to all attendees by the driver after Round 1
        # initial drafts (comment) and again after comment phase
        # completes (reply). Each attendee MUST end with a phase_ack
        # decision so the driver knows the phase is done.
        if msg_type == "kickoff_comment_phase_request":
            await self._handle_kickoff_comment_phase_request(urgent_msg)
            return True
        if msg_type == "kickoff_reply_phase_request":
            await self._handle_kickoff_reply_phase_request(urgent_msg)
            return True

        if msg_type == "task_ready":
            from_agent = urgent_msg.header.source_agent_id
            self._upstream_ready_agents.add(from_agent)
            allowed, reason = self._should_start_from_task_ready(urgent_msg)
            if not allowed:
                self._logger.info(
                    f"[{self.agent_id}] Ignoring task_ready from {from_agent}: {reason}"
                )
                return True

            # V30 RE-ENTRANCY GUARD: only start a task_ready handler (which runs a FULL
            # nested run_agentic_loop) when we are NOT already inside an agentic loop. The
            # shared _processing_state can read IDLE mid-outer-loop (a prior nested handler's
            # finally reset it) — that window let the urgent drain start a SECOND in-stack
            # run_agentic_loop, which deadlocked in setup and hung the frontend lane silently
            # for 13min (V30). The depth counter (step_runner) is reset-proof. When already in
            # a loop, fall through to the busy branch below -> defer to
            # _deferred_task_ready_messages (drained, exactly as today, when the lane next
            # goes IDLE). Lower-priority urgent work correctly waits for the in-flight task.
            if (self._processing_state == ProcessingState.IDLE
                    and getattr(self, "_agentic_loop_depth", 0) == 0):
                await self._handle_task_ready(urgent_msg)
                return True

            # FIX #147 (run-71 M2 STUCK, live): the verifier claimed BUSY for
            # 13min with ZERO step activity (its last finish was 19:53:01, the
            # in-flight loop never returned) — every gate-check remediation
            # task_ready was deferred "for later" and the deferred queue never
            # drained (drain only runs in a handler's finally) → 7-cycle
            # no-convergence abort with all 3 milestones' work done. When the
            # lane claims busy but its agentic loop has produced NO step for
            # ENVGEN_LANE_WEDGE_S (default 600s; 0 disables), the loop is
            # WEDGED, not busy: force-reset to IDLE (the wedged loop's finally,
            # if it ever runs, is harmless — depth uses max(0, n-1)) and handle
            # this task_ready NOW in the urgent-drain context (which
            # demonstrably still runs while the loop is wedged).
            # #149 guards on the branch below: (a) never fire from an IN-LOOP
            # drain — the loop executing this code is by definition not wedged
            # (all 4 run-72/73 declarations were healthy mid-step lanes, and
            # the reset spawned concurrent double-authoring loops); (b) a real
            # reset bumps _loop_generation so the undead loop's finally cannot
            # stomp the replacement loop's state/depth (step_runner unwind
            # checks its entry generation).
            import os as _os
            _last = getattr(self, "_last_step_activity", None)
            try:
                _wedge_s = float(_os.environ.get("ENVGEN_LANE_WEDGE_S", "600") or 600)
            except Exception:
                _wedge_s = 600.0
            if (not from_loop and _last is not None and _wedge_s > 0
                    and (time.time() - _last) >= _wedge_s):
                self._logger.warning(
                    f"[{self.agent_id}] lane claims busy (state={self._processing_state}, "
                    f"depth={getattr(self, '_agentic_loop_depth', 0)}) but NO step activity "
                    f"for {int(time.time() - _last)}s — declaring the in-flight loop WEDGED "
                    "(FIX #147), force-resetting to IDLE and handling this task_ready now")
                self._loop_generation = getattr(self, "_loop_generation", 0) + 1
                self._processing_state = ProcessingState.IDLE
                self._agentic_loop_depth = 0
                await self._handle_task_ready(urgent_msg)
                return True

            queued = list(getattr(self, "_deferred_task_ready_messages", []) or [])
            queued_ids = {
                getattr(item.header, "message_id", None)
                for item in queued
                if getattr(item, "header", None) is not None
            }
            if urgent_msg.header.message_id in queued_ids:
                self._logger.info(f"[{self.agent_id}] duplicate task_ready ignored while busy")
                return True
            queued.append(urgent_msg)
            self._deferred_task_ready_messages = queued
            self._logger.info(f"[{self.agent_id}] task_ready received but busy, queued for later")

        return False

    def _should_start_from_task_ready(self, message: BaseMessage) -> Tuple[bool, str]:
        """Runtime gate for task_ready auto-start behavior."""
        for policy in getattr(self, "_workflow_policies", []) or []:
            decision = policy.allow_task_ready(self, message)
            if decision is None:
                continue
            allowed, reason = decision
            if not allowed:
                return allowed, reason
        return True, "ok"

    async def _handle_question(self, message: BaseMessage) -> None:
        """Handle a question from another agent."""
        from_agent = message.header.source_agent_id
        question = message.payload if isinstance(message.payload, str) else str(message.payload)
        context = message.metadata.get("context", {})
        question_id = context.get("question_id", message.header.message_id)

        self._logger.info(f"[{self.agent_id}] Answering question from {from_agent}")
        answer = await self._generate_answer(question, from_agent)
        await self._send_answer(from_agent, answer, question_id)

    async def _generate_answer(self, question: str, from_agent: str) -> str:
        """Generate an answer to a question using LLM."""
        system_prompt = self._compose_system_prompt()
        prompt = f"""Another agent ({from_agent}) is asking you a question while you're working.

Question: {question}

Based on your expertise and current work, provide a helpful and concise answer.
Answer directly without using tools."""

        messages = [Message.system(system_prompt), Message.user(prompt)]
        try:
            from ...runtime.reasoning_effort import resolve_effort
            _effort = resolve_effort(
                getattr(self.workspace, "base_dir", "."),
                self.agent_id,
                getattr(self, "reasoning_effort", None),
            )
            response = await self.call_with_retry(
                self.llm.chat_messages, messages, reasoning_effort=_effort
            )
            if isinstance(response, str):
                return response or "I don't have enough context to answer."
            return response.content or "I don't have enough context to answer."
        except Exception as e:
            self._logger.error(f"Failed to generate answer: {e}")
            return f"Sorry, I couldn't process your question: {e}"

    async def _send_answer(self, to_agent: str, answer: str, question_id: str):
        """Send answer back to the asking agent."""
        if self._external_bus:
            from uuid import uuid4

            header = MessageHeader(
                message_id=str(uuid4()),
                source_agent_id=self._agent_id,
                target_agent_id=to_agent,
                priority=MessagePriority.HIGH,
            )
            message = BaseMessage(
                header=header,
                message_type=MessageType.RESULT,
                payload=answer,
                metadata={"msg_type": "answer", "context": {"question_id": question_id}},
            )
            await self._external_bus.send(message)

    async def _handle_answer(self, message: BaseMessage) -> None:
        """Handle an answer to a question we asked."""
        context = message.metadata.get("context", {})
        question_id = context.get("question_id")
        answer = message.payload if isinstance(message.payload, str) else str(message.payload)

        if question_id and question_id in self._pending_questions:
            self._pending_questions[question_id].set_result(answer)
            self._logger.info(f"[{self.agent_id}] Received answer for question {question_id[:8]}")

    async def _handle_issue(self, message: BaseMessage) -> None:
        """Handle an issue reported by another agent."""
        from_agent = message.header.source_agent_id
        issue_content = message.payload if isinstance(message.payload, str) else str(message.payload)
        context = message.metadata.get("context", {})
        severity = context.get("severity", "error")

        self._logger.info(f"[{self.agent_id}] Received issue from {from_agent}: {issue_content[:100]}...")
        await self._send_runtime_status_update(
            to_agent=from_agent,
            status="in_progress",
            content=f"{self.agent_id} is handling the reported issue now.",
            metadata={
                "source_message_type": "issue",
                "severity": severity,
            },
        )

        fix_prompt = f"""## Issue Reported by {from_agent}

**Severity**: {severity}
**Issue**: {issue_content}

## Your Task

Fix this issue in your code. Steps:
1. Analyze the issue and identify the root cause
2. Use `read()` only for files that already exist or where you need real context
3. If the fix is to create a missing file, do not waste a read just to confirm the file is absent
4. Use `edit()`, `write()`, or `apply_patch()` to fix the code
5. Use `lint()` to verify no new errors were introduced
6. When fixed, use `send_message(to_agent="{from_agent}", content="Fixed: <brief description>", msg_type="info")` to report back

Start by thinking about what might cause this issue.
"""

        prev_state = self._processing_state
        self._processing_state = ProcessingState.PROCESSING_TASK
        # An issue/bug reported to this lane is the TEST-FIX phase of the lifecycle
        # (close the reported defect; do not start new features). Pin _active_phase so the
        # profile's ``test_fix:*`` stage_tool_allowlist applies (falls through to the full
        # toolset for profiles without one — safe). Restored in finally.
        prev_phase = getattr(self, "_active_phase", None)
        self._active_phase = "test_fix"

        try:
            system_prompt = self._compose_system_prompt()
            await self.run_agentic_loop(
                system_prompt=system_prompt,
                initial_prompt=fix_prompt,
                max_steps=30,
            )
        except Exception as e:
            self._logger.error(f"[{self.agent_id}] Failed to fix issue: {e}")
            if self._external_bus:
                from uuid import uuid4

                header = MessageHeader(
                    message_id=str(uuid4()),
                    source_agent_id=self.agent_id,
                    target_agent_id=from_agent,
                    priority=MessagePriority.NORMAL,
                )
                error_msg = BaseMessage(
                    header=header,
                    message_type=MessageType.STATUS,
                    payload=f"Failed to fix issue: {str(e)[:200]}",
                    metadata={"msg_type": "error"},
                )
                await self._external_bus.send(error_msg)
        finally:
            self._processing_state = prev_state
            self._active_phase = prev_phase
            await self._drain_deferred_task_ready_messages()

    async def _handle_task_ready(self, message: BaseMessage) -> None:
        """Handle task_ready message from upstream agent."""
        from_agent = message.header.source_agent_id
        content = message.payload if isinstance(message.payload, str) else str(message.payload)

        self._logger.info(f"[{self.agent_id}] Starting work - triggered by {from_agent}: {content[:100]}...")
        await self._send_runtime_status_update(
            to_agent=from_agent,
            status="in_progress",
            content=f"{self.agent_id} accepted task_ready and is starting work.",
            metadata={"source_message_type": "task_ready"},
        )

        # Render the lane's task_macro (the lane-specific recipe).
        # Pass an empty task dict to bypass the description short-
        # circuit in _build_task_prompt and hit the default task_macro
        # path. Fall back to a minimal generic prompt for lanes
        # without a configured macro.
        lane_recipe: Optional[str] = None
        if hasattr(self, "_build_task_prompt"):
            try:
                lane_recipe = self._build_task_prompt({})
            except Exception as exc:
                self._logger.debug(
                    f"[{self.agent_id}] task_macro render failed: {exc}"
                )
                lane_recipe = None

        if lane_recipe and lane_recipe.strip():
            task_prompt = (
                f"## Task from {from_agent}\n\n{content}\n\n---\n\n{lane_recipe}"
            )
        else:
            task_prompt = (
                f"## Task from {from_agent}\n\n{content}\n\n"
                f"1. `workhub_list_tasks(assignee=\"{self.agent_id}\", status=\"pending\")`; for each: "
                f"`focus_hub(hub=\"workhub\")` then `workhub_task(action=\"claim\", task_id=...)`.\n"
                f"2. `plan()` then implement.\n"
                f"3. `finish(notify=[...])`.\n"
            )

        self._processing_state = ProcessingState.PROCESSING_TASK
        try:
            system_prompt = self._compose_system_prompt()
            # Per-agent ceiling. Default 2000 preserves prior behavior for
            # worker lanes that need many steps to implement. Wake-driven
            # agents (e.g. knowledge) can set this much lower (5) via the
            # `max_steps_per_task_ready` YAML flag so a system-prompt-ignoring
            # LLM is still hard-bounded.
            max_steps = getattr(self, "_max_steps_per_task_ready", 2000)
            # PRE-LAUNCH AUDIT R1: pin _active_phase="implementation" around the loop so
            # the lane's `implementation:action` stage allowlist BINDS on this urgent
            # task_ready path too. process_task pins it (base.py), but this interrupt
            # path called run_agentic_loop directly with _active_phase=None → the
            # verifier's validation allowlist silently missed and it fell back to the
            # ~10-slot ranker (the crowd-out #28's allowlist was meant to prevent).
            # Save/restore so resident-loop state is untouched.
            _prev_active_phase = getattr(self, "_active_phase", None)
            self._active_phase = "implementation"
            try:
                await self.run_agentic_loop(
                    system_prompt=system_prompt,
                    initial_prompt=task_prompt,
                    max_steps=max_steps,
                )
            finally:
                self._active_phase = _prev_active_phase
        except Exception as e:
            self._logger.error(f"[{self.agent_id}] Task failed: {e}")
        finally:
            self._processing_state = ProcessingState.IDLE
            await self._drain_deferred_task_ready_messages()

    async def _drain_deferred_task_ready_messages(self) -> None:
        """Start the next deferred kickoff/task_ready once the agent becomes idle.

        Every kickoff_* handler and _handle_task_ready calls this in its
        ``finally`` block right after restoring ``_processing_state = IDLE``, so
        this is the single re-entry point for ALL deferred urgent work. Drain
        DEFERRED KICKOFF events FIRST (DUAL-LOOP DOUBLE-AUTHOR FIX): a kickoff
        turn that was declined while the lane was busy is time-critical (the
        kickoff driver is polling for its decision/section), whereas a deferred
        task_ready is implementation-phase work that can wait until kickoff is
        done.
        """
        if getattr(self, "_shutdown_requested", False):
            self._deferred_task_ready_messages = []
            self._deferred_kickoff_messages = []
            return
        if self._processing_state != ProcessingState.IDLE:
            return
        kickoff_queued = list(getattr(self, "_deferred_kickoff_messages", []) or [])
        if kickoff_queued:
            next_kickoff, next_msg_type = kickoff_queued.pop(0)
            self._deferred_kickoff_messages = kickoff_queued
            self._logger.info(
                f"[{self.agent_id}] draining deferred kickoff {next_msg_type} "
                "now that the lane is idle"
            )
            await self._defer_or_handle_kickoff(next_kickoff, next_msg_type)
            return
        queued = list(getattr(self, "_deferred_task_ready_messages", []) or [])
        if not queued:
            return
        next_message = queued.pop(0)
        self._deferred_task_ready_messages = queued
        await self._handle_task_ready(next_message)

    async def _defer_or_handle_kickoff(
        self, message: BaseMessage, msg_type: str
    ) -> bool:
        """Busy-guarded dispatch for the kickoff_* urgent handlers.

        DUAL-LOOP DOUBLE-AUTHOR FIX: each kickoff_* handler runs a full
        ``run_agentic_loop``. They MUST NOT run concurrently with the resident
        main loop (or with one another) — two loops authoring the same meeting
        section / milestone detail at once is the double-author race. Mirror the
        ``task_ready`` busy-guard at ``_check_and_handle_urgent`` :544 EXACTLY:

          * IDLE  → run the matching handler now (it sets
            ``_processing_state = PROCESSING_TASK`` for its duration and restores
            IDLE + drains in its own ``finally``).
          * BUSY  → queue the (message, msg_type) into
            ``_deferred_kickoff_messages`` (deduped by message_id) and return —
            ``_drain_deferred_task_ready_messages`` replays it the instant the
            current turn finishes.

        This declines to START a concurrent loop; it never holds a cross-lane
        lock, so it cannot deadlock. Always returns True (the urgent event was
        consumed — either handled or queued — so the urgent drain does not retry
        it as unhandled).
        """
        handlers = {
            "kickoff_request": self._handle_kickoff_request,
            "kickoff_facilitate_request": self._handle_kickoff_facilitate_request,
            "kickoff_detail_request": self._handle_kickoff_detail_request,
        }
        handler = handlers.get(msg_type)
        if handler is None:
            self._logger.warning(
                f"[{self.agent_id}] _defer_or_handle_kickoff called with "
                f"unknown msg_type={msg_type!r}; ignoring."
            )
            return True

        if self._processing_state == ProcessingState.IDLE:
            await handler(message)
            return True

        queued = list(getattr(self, "_deferred_kickoff_messages", []) or [])
        queued_ids = {
            getattr(item.header, "message_id", None)
            for (item, _mt) in queued
            if getattr(item, "header", None) is not None
        }
        if message.header.message_id in queued_ids:
            self._logger.info(
                f"[{self.agent_id}] duplicate {msg_type} ignored while busy"
            )
            return True
        queued.append((message, msg_type))
        self._deferred_kickoff_messages = queued
        self._logger.info(
            f"[{self.agent_id}] {msg_type} received but busy "
            f"(state={self._processing_state.name}); deferred to avoid a "
            "concurrent kickoff agentic loop (double-author guard)"
        )
        return True

    async def _handle_kickoff_request(self, message: BaseMessage) -> None:
        """Round-8c Fix #2: drive ONE LLM turn rendering kickoff_response_prompt.

        Background: round-8b smoke confirmed `agent_subscriptions.py`
        wires every resident attendee (design/backend/frontend/verifier)
        to ``("orchestrator", "kickoff_request", "high")`` so the urgent
        event arrives — but the urgent-event handler had no branch for
        ``msg_type == "kickoff_request"``, so it logged "Handling urgent
        kickoff_request" and returned False, never spawning an LLM turn.
        The 4 attendees sat idle until the orchestrator's legacy
        ``send_message(task_ready)`` arrived, and design then booted
        with the WRONG prompt (`task_ready` triggers a full implementation
        pass, not a kickoff-response).

        This handler bridges that gap: render the agent's
        ``kickoff_response_prompt`` macro with the kickoff payload and
        run ONE agentic loop. The macro itself caps the response at
        "Run ONCE, then finish(). Do NOT loop. Do NOT poll for
        synthesis." — so the iteration cap below is a safety net, not
        the primary stop condition.
        """
        payload = message.payload if isinstance(message.payload, Mapping) else {}
        meeting_id = payload.get("meeting_id") if isinstance(payload, Mapping) else None
        milestone_index = (
            payload.get("milestone_index") if isinstance(payload, Mapping) else None
        )
        # The payload's "requirements" is a list[str] per
        # start_kickoff; flatten to a single block for the macro.
        requirements_raw = (
            payload.get("requirements") if isinstance(payload, Mapping) else None
        )
        if isinstance(requirements_raw, (list, tuple)):
            requirements = "\n\n".join(
                str(r).strip() for r in requirements_raw if str(r).strip()
            )
        else:
            requirements = str(requirements_raw or "").strip()

        if not meeting_id:
            self._logger.warning(
                f"[{self.agent_id}] kickoff_request without meeting_id "
                f"(payload={payload!r}); ignoring."
            )
            return

        # Section identity is the agent_id itself — only the 4 attendees
        # subscribe to kickoff_request (see agent_subscriptions.py).
        expected_section = self.agent_id

        # The kickoff_response_prompt macro lives in the agent's own v3
        # template (design_agent.j2, backend_agent.j2, frontend_agent.j2,
        # verifier_agent.j2 each define one). Render via the agent's own
        # Jinja env so we pick up the macro the agent's system prompt
        # already advertises. If the agent profile isn't a configurable
        # agent (no template / render_macro), fall back to a minimal
        # text prompt — the agent's system prompt should still have the
        # kickoff_response instructions baked in.
        prompt_cfg = getattr(self, "_prompt_cfg", None) or {}
        template = prompt_cfg.get("template") if isinstance(prompt_cfg, Mapping) else None
        rendered: Optional[str] = None
        if template and hasattr(self, "render_macro"):
            try:
                rendered = self.render_macro(
                    template,
                    "kickoff_response_prompt",
                    meeting_id=meeting_id,
                    milestone_index=milestone_index,
                    requirements=requirements,
                    expected_section=expected_section,
                )
            except Exception as exc:
                self._logger.warning(
                    f"[{self.agent_id}] kickoff_response_prompt render failed "
                    f"({exc}); falling back to plain-text prompt."
                )
                rendered = None
        if not rendered:
            rendered = (
                f"## Kickoff request — meeting `{meeting_id}` (M{milestone_index})\n\n"
                f"Your section: **{expected_section}**.\n\n"
                "Per your system prompt's kickoff_response_prompt instructions, "
                "author ONE `workhub_add_meeting_decision(meeting_id=..., "
                f"section='{expected_section}', content={{...}}, kind='draft_section')` "
                "with the section-appropriate content shape, then `finish()`. "
                "Do NOT loop, do NOT poll for synthesis, do NOT start "
                "implementation work — kickoff is the contract-authoring phase.\n\n"
                f"Requirements:\n\n{requirements}\n"
            )

        self._logger.info(
            f"[{self.agent_id}] kickoff_request received "
            f"(meeting_id={meeting_id}, M{milestone_index}); "
            "rendering kickoff_response_prompt and running one agentic loop."
        )

        self._processing_state = ProcessingState.PROCESSING_TASK
        # Round-8d Fix #5-bis: pre-set hub focus to WorkHub for the
        # duration of the kickoff response. The per-step tool ranker
        # (tool_surface.rank_tool_names line 203) filters always_include
        # AGAINST candidate_names — so a tool dropped by _apply_hub_focus
        # earlier cannot be recovered by ACTION_STAGE_ALWAYS_INCLUDE
        # later. With _focus_hub=None at handler entry, _apply_hub_focus
        # drops every WorkHub write (including workhub_add_meeting_decision,
        # the ONE tool the kickoff_response_prompt macro instructs the
        # LLM to call) — observed in the round-8d-bis 20:35 smoke as
        # "Required tools such as workhub_add_meeting_decision /
        # focus_hub / codehub_commit are unavailable" + immediate
        # finish('blocked'). Pre-setting focus = workhub lets the
        # workhub writes pass _apply_hub_focus, and then the
        # always_include set forces workhub_add_meeting_decision into
        # the per-step LLM tool surface. Restore on exit so the legacy
        # task_ready flow (which sets focus dynamically) isn't broken.
        prev_focus_hub = getattr(self, "_focus_hub", None)
        self._focus_hub = "workhub"
        # PR3.1.2 / Loop B ⑧: pin phase so the PR3.1/PR3.2 levers can
        # gate kickoff differently from implementation even though both
        # share the same stage names (action/etc.). yaml entries keyed
        # on ``"kickoff:<stage>"`` take precedence over the bare-stage
        # key while this is set.
        prev_active_phase = getattr(self, "_active_phase", None)
        self._active_phase = "kickoff"
        try:
            system_prompt = self._compose_system_prompt()
            # The macro instructs "Run ONCE, then finish()"; this cap
            # is a tight safety net. Round-8c reviewer feedback: a
            # confused LLM at max_steps=50 would burn 50× token cost
            # before surfacing; ~12 lets read_refs → draft →
            # add_meeting_decision → finish() complete normally
            # (~4-8 steps in practice) while failing fast on loop.
            max_steps = getattr(self, "_max_steps_per_kickoff_response", 12)
            await self.run_agentic_loop(
                system_prompt=system_prompt,
                initial_prompt=rendered,
                max_steps=max_steps,
            )
            # CORRECTIVE TURNS (2026-06-10): when the turn ends without a
            # SUBSTANTIVE section (gemini drops/empties the decision when the
            # inline JSON argument is too long), do NOT author for the agent —
            # tell it WHY it failed and HOW to author in parts (file-first,
            # multiple small writes), and give it another bounded turn. The
            # section stays the agent's own work.
            _author_started = time.time()
            for _attempt in range(2):
                if self._has_substantive_section(meeting_id, expected_section):
                    break
                # AUTHORING DEADLINE (2026-06-11, round 16 post-mortem): the
                # reject/retry dance must end WELL before the kickoff driver's
                # 1200s timeout — the terminal stub landed 1s late and the
                # whole run aborted. Half the kickoff budget is the ceiling.
                try:
                    from ...runtime.kickoff.run_kickoff import KICKOFF_TIMEOUT_SEC as _KTS
                except Exception:
                    _KTS = 1200.0
                if time.time() - _author_started > _KTS * 0.5:
                    self._logger.warning(
                        f"[{self.agent_id}] authoring deadline reached "
                        f"({_KTS * 0.5:.0f}s) — skipping remaining corrective "
                        "turns; terminal stub will let the meeting advance.")
                    break
                # KICKOFF STALL FIX (Task C): the attendee called finish() during
                # kickoff-initial while its substantive section is still MISSING.
                # Do NOT accept that finish silently — log LOUD (ERROR) and feed
                # the agent back a finish-REJECTION prompt that NAMES the missing
                # section, so it declares its endpoint/table/page decisions instead
                # of looping finish() and stalling the meeting to the 1200s timeout.
                self._logger.error(
                    f"[{self.agent_id}] finish() during kickoff-initial REJECTED: "
                    f"section='{expected_section}' has no substantive "
                    f"{_kickoff_missing_section_kind(expected_section)} recorded "
                    f"on meeting {meeting_id} — corrective turn {_attempt + 1}/2 "
                    "(re-prompting the attendee to declare it before finishing)."
                )
                await self.run_agentic_loop(
                    system_prompt=system_prompt,
                    initial_prompt=_kickoff_correction_prompt(
                        expected_section, meeting_id, milestone_index),
                    max_steps=10,
                )
        except Exception as e:
            self._logger.error(
                f"[{self.agent_id}] kickoff_response agentic loop failed: {e}"
            )
        finally:
            self._processing_state = ProcessingState.IDLE
            self._focus_hub = prev_focus_hub
            self._active_phase = prev_active_phase
            # Drain any task_ready that arrived while we were busy
            # responding to kickoff. This is the same path
            # _handle_task_ready uses on its way out.
            await self._drain_deferred_task_ready_messages()
            self._ensure_initial_section_decision(
                meeting_id=meeting_id,
                milestone_index=milestone_index,
                expected_section=expected_section,
            )

    def _has_substantive_section(self, meeting_id, section: str) -> bool:
        """True iff THIS agent already recorded a substantive section decision
        on the meeting (used to decide whether a corrective turn is needed)."""
        try:
            workhub = getattr(self._hubs, "workhub", None)
            pages_store = getattr(workhub, "stores", None)
            pages = getattr(pages_store, "documents", None) if pages_store else None
            page = pages.value().get(meeting_id) if (pages and hasattr(pages, "value")) else None
            if not isinstance(page, Mapping):
                return False
            for d in (page.get("metadata") or {}).get("decisions") or []:
                if not isinstance(d, Mapping):
                    continue
                if (d.get("section") or (d.get("content") or {}).get("section")) != section:
                    continue
                if (d.get("recorded_by") or d.get("agent")) != self.agent_id:
                    continue
                if _decision_has_substance(d, section):
                    return True
        except Exception:
            return False
        return False

    def _ensure_initial_section_decision(
        self,
        *,
        meeting_id: Optional[str],
        milestone_index: Optional[int],
        expected_section: str,
    ) -> None:
        """Closed-by-construction (round 8g Fix #C): guarantee a
        ``section=<agent_id>`` decision exists for this attendee once
        ``_handle_kickoff_request`` exits.

        Smoke #9-ter (2026-06-02 23:45) caught verifier calling
        ``finish('awaiting RegistryHub focus to read prior endpoint/table
        artifacts')`` instead of writing its initial section. The driver
        then waited on verifier indefinitely because ``current_phase``
        only transitions initial→comment once every attendee has a
        section decision.

        Mirrors the ``_ensure_phase_ack`` shape: if the LLM produced
        the section, no-op; otherwise write a placeholder marked with
        ``source='auto_backup'`` so the meeting can advance and other
        attendees can flag the gap in the comment phase.
        """
        if not meeting_id or not expected_section:
            return
        try:
            workhub = getattr(self._hubs, "workhub", None)
            if workhub is None or not hasattr(workhub, "add_meeting_decision"):
                return
            # Walk the meeting page directly — no facilitate helper here
            # because the initial-section check needs section-name (not
            # round_n + phase) keying.
            pages_store = getattr(workhub, "stores", None)
            pages = getattr(pages_store, "documents", None) if pages_store else None
            page = None
            if pages and hasattr(pages, "value"):
                page = pages.value().get(meeting_id)
            if not isinstance(page, Mapping):
                return
            decisions = (page.get("metadata") or {}).get("decisions") or []
            # SUBSTANCE check (2026-06-10): a decision EXISTING is not enough —
            # gemini sometimes lands an all-empty shell ({"ui_pages": [],
            # "auth": null, ...}) after its full-payload call malforms, which
            # used to satisfy this check and starve the synthesis. An empty
            # section is treated as un-authored; the spec-derived backup is
            # appended and wins via _collect_drafts' last-write-wins.
            already_authored = any(
                isinstance(d, Mapping)
                and (d.get("section") or (d.get("content") or {}).get("section"))
                    == expected_section
                and (d.get("recorded_by") or d.get("agent")) == self.agent_id
                and _decision_has_substance(d, expected_section)
                for d in decisions
            )
            if already_authored:
                return
            # Terminal guarantee only: the agent had its main turn + 2
            # corrective turns (file-first, author-in-parts guidance). A
            # deferred stub here keeps the meeting advancing; the
            # deterministic reconcile fills gaps from the contract. The
            # framework does NOT author the section for the agent.
            content = {
                "section": expected_section,
                "deferred": True,
                "source": "auto_backup",
                "note": (
                    f"{self.agent_id} ended its kickoff_request handler "
                    "without writing a substantive section decision after "
                    "corrective turns; stub inserted so the meeting can "
                    "advance to synthesis, where the deterministic "
                    "reconcile fills this section's gaps from the "
                    "contract and the other sections."
                ),
            }
            decision = {
                "section": expected_section,
                "kind": "draft_section",
                "content": content,
            }
            kwargs = {"meeting_id": meeting_id, "decision": decision,
                      "agent": self.agent_id}
            if milestone_index is not None:
                kwargs["milestone_index"] = milestone_index
            workhub.add_meeting_decision(**kwargs)
            _kind = ("section derived from the compiled reference spec"
                     if content.get("source") == "auto_backup_spec"
                     else "deferred stub")
            self._logger.warning(
                f"[{self.agent_id}] initial kickoff_request ended without a "
                f"SUBSTANTIVE section='{expected_section}' decision "
                f"(meeting={meeting_id}); auto-wrote backup ({_kind}) so the "
                "meeting can advance."
            )
        except Exception as e:
            self._logger.error(
                f"[{self.agent_id}] _ensure_initial_section_decision failed "
                f"for meeting={meeting_id} section={expected_section}: {e}"
            )

    async def _handle_kickoff_revision_request(self, message: BaseMessage) -> None:
        """Round-8f.1: attendee single-pass revision in response to a
        facilitator-driven ``kickoff_revision_request``.

        ``runtime/kickoff/facilitate.py:request_revisions`` broadcasts
        this urgent event after the orchestrator (chairing the meeting)
        records a ``facilitator_note`` decision with action
        ``request_revision``. The payload carries the per-agent
        ``revision_focus``, the facilitator's ``rationale``, the
        ``acks_consensus_on`` (do-not-touch) list, and any
        ``open_questions``. ``recipients=revisers`` is set on the
        publish, but the broadcaster may also fan-out to subscribers —
        so each attendee guards on ``self.agent_id in revisers`` and
        no-ops if it was not flagged.

        Structural mirror of ``_handle_kickoff_request``: render the
        agent's ``kickoff_revision_prompt`` macro, pre-set
        ``self._focus_hub = 'workhub'`` (Fix #5-bis class) so the
        always-include ranker can surface
        ``workhub_add_meeting_decision``, run ONE agentic loop with
        ``max_steps=12`` (the macro itself caps at "single pass, then
        finish()"), then restore prior focus.
        """
        payload = message.payload if isinstance(message.payload, Mapping) else {}
        meeting_id = payload.get("meeting_id") if isinstance(payload, Mapping) else None
        milestone_index = (
            payload.get("milestone_index") if isinstance(payload, Mapping) else None
        )
        current_round = (
            payload.get("current_round") if isinstance(payload, Mapping) else None
        )
        revisers = (
            payload.get("revisers") if isinstance(payload, Mapping) else None
        ) or []
        revision_focus = (
            payload.get("revision_focus") if isinstance(payload, Mapping) else None
        ) or {}
        facilitator_rationale = (
            payload.get("facilitator_rationale") if isinstance(payload, Mapping) else None
        ) or ""
        acks_consensus_on = (
            payload.get("acks_consensus_on") if isinstance(payload, Mapping) else None
        ) or []
        open_questions = (
            payload.get("open_questions") if isinstance(payload, Mapping) else None
        ) or []

        if not meeting_id:
            self._logger.warning(
                f"[{self.agent_id}] kickoff_revision_request without meeting_id "
                f"(payload={payload!r}); ignoring."
            )
            return

        # Broadcaster may fan-out to all subscribers; each attendee
        # acts only if it is in the revisers list. Non-revisers stay
        # quiet — no churn, no spurious LLM turn.
        if self.agent_id not in revisers:
            self._logger.info(
                f"[{self.agent_id}] kickoff_revision_request received but "
                f"not in revisers={revisers!r}; skipping."
            )
            return

        prompt_cfg = getattr(self, "_prompt_cfg", None) or {}
        template = prompt_cfg.get("template") if isinstance(prompt_cfg, Mapping) else None
        rendered: Optional[str] = None
        if template and hasattr(self, "render_macro"):
            try:
                rendered = self.render_macro(
                    template,
                    "kickoff_revision_prompt",
                    meeting_id=meeting_id,
                    milestone_index=milestone_index,
                    current_round=current_round,
                    revision_focus=revision_focus,
                    facilitator_rationale=facilitator_rationale,
                    acks_consensus_on=acks_consensus_on,
                    open_questions=open_questions,
                )
            except Exception as exc:
                self._logger.warning(
                    f"[{self.agent_id}] kickoff_revision_prompt render failed "
                    f"({exc}); falling back to plain-text prompt."
                )
                rendered = None
        if not rendered:
            per_agent_focus = (
                revision_focus.get(self.agent_id)
                if isinstance(revision_focus, Mapping)
                else None
            ) or "(no per-agent revision_focus entry was provided)"
            rendered = (
                f"## Kickoff revision request — meeting `{meeting_id}` "
                f"(M{milestone_index}), revision round {current_round}\n\n"
                f"Your section: **{self.agent_id}**.\n\n"
                "The facilitator flagged your section as needing changes "
                "before the meeting can reach consensus. SINGLE PASS — "
                "author the revised section, record ONE "
                "`workhub_add_meeting_decision(meeting_id=..., "
                f"section='{self.agent_id}', content={{...}}, "
                "kind='draft_section', round=...)` with the revised "
                "content, then `finish()`. Do NOT poll synthesis.\n\n"
                f"**Revision focus**: {per_agent_focus}\n\n"
                f"**Facilitator rationale**: {facilitator_rationale}\n\n"
                f"**Do NOT change (acked consensus)**: {acks_consensus_on!r}\n\n"
                f"**Open questions**: {open_questions!r}\n"
            )

        self._logger.info(
            f"[{self.agent_id}] kickoff_revision_request received "
            f"(meeting_id={meeting_id}, M{milestone_index}, "
            f"round={current_round}); rendering kickoff_revision_prompt "
            "and running one agentic loop."
        )

        self._processing_state = ProcessingState.PROCESSING_TASK
        # Fix #5-bis (same rationale as _handle_kickoff_request):
        # pre-set hub focus = workhub so _apply_hub_focus does not
        # drop the workhub writes the kickoff_revision_prompt macro
        # instructs the LLM to call (workhub_get_document +
        # workhub_add_meeting_decision). Restore on exit.
        prev_focus_hub = getattr(self, "_focus_hub", None)
        self._focus_hub = "workhub"
        # PR3.1.2 / Loop B ⑧: pin phase so the PR3.1/PR3.2 levers can
        # gate kickoff differently from implementation even though both
        # share the same stage names (action/etc.). yaml entries keyed
        # on ``"kickoff:<stage>"`` take precedence over the bare-stage
        # key while this is set.
        prev_active_phase = getattr(self, "_active_phase", None)
        self._active_phase = "kickoff"
        try:
            system_prompt = self._compose_system_prompt()
            max_steps = getattr(self, "_max_steps_per_kickoff_revision", 12)
            await self.run_agentic_loop(
                system_prompt=system_prompt,
                initial_prompt=rendered,
                max_steps=max_steps,
            )
        except Exception as e:
            self._logger.error(
                f"[{self.agent_id}] kickoff_revision agentic loop failed: {e}"
            )
        finally:
            self._processing_state = ProcessingState.IDLE
            self._focus_hub = prev_focus_hub
            self._active_phase = prev_active_phase
            await self._drain_deferred_task_ready_messages()
            self._ensure_revision_section_decision(
                meeting_id=meeting_id,
                milestone_index=milestone_index,
                round_n=current_round,
            )

    def _ensure_revision_section_decision(
        self,
        *,
        meeting_id: Optional[str],
        milestone_index: Optional[int],
        round_n: Optional[int],
    ) -> None:
        """Closed-by-construction (round 8h Fix #F): guarantee a
        ``section=<agent_id>`` decision exists for THIS reviser in
        ``round_n`` once ``_handle_kickoff_revision_request`` exits.

        Mirror of :meth:`_ensure_initial_section_decision` for revision
        rounds. Smoke #9-sextus (2026-06-03 00:48) caught the structural
        gap: revisers were dispatched correctly but if a reviser ended
        its revision agentic loop without writing a new round-N section
        decision, ``current_phase`` would stay at ``initial`` forever
        waiting on a section that would never arrive. Combined with
        the round-aware ``expected_attendees_for_round`` (Fix #G) this
        closes the revision-round flow end-to-end.

        Stub carries the same audit shape as Fix #C
        (``content.source="auto_backup"``, ``content.deferred=True``,
        a self-describing ``content.note``), plus the explicit
        ``round`` field so ``current_phase`` attributes it to the
        right revision round.
        """
        if not meeting_id or round_n is None:
            return
        try:
            workhub = getattr(self._hubs, "workhub", None)
            if workhub is None or not hasattr(workhub, "add_meeting_decision"):
                return
            pages_store = getattr(workhub, "stores", None)
            pages = getattr(pages_store, "documents", None) if pages_store else None
            page = None
            if pages and hasattr(pages, "value"):
                page = pages.value().get(meeting_id)
            if not isinstance(page, Mapping):
                return
            decisions = (page.get("metadata") or {}).get("decisions") or []
            already_authored = any(
                isinstance(d, Mapping)
                and (d.get("section") or (d.get("content") or {}).get("section"))
                    == self.agent_id
                and (d.get("recorded_by") or d.get("agent")) == self.agent_id
                and d.get("round") == round_n
                for d in decisions
            )
            if already_authored:
                return
            decision = {
                "section": self.agent_id,
                "round": round_n,
                "kind": "draft_section",
                "content": {
                    "section": self.agent_id,
                    "deferred": True,
                    "source": "auto_backup",
                    "note": (
                        f"{self.agent_id} ended its kickoff_revision_request "
                        f"handler for round {round_n} without writing a "
                        "revised section decision; an auto-backup stub was "
                        "inserted so the meeting can advance to the comment "
                        "phase of the revision round, where the missing "
                        "revision is visible to other revisers and the "
                        "facilitator."
                    ),
                },
            }
            kwargs = {"meeting_id": meeting_id, "decision": decision,
                      "agent": self.agent_id}
            if milestone_index is not None:
                kwargs["milestone_index"] = milestone_index
            workhub.add_meeting_decision(**kwargs)
            self._logger.warning(
                f"[{self.agent_id}] revision round {round_n} ended without "
                f"an explicit section='{self.agent_id}' decision "
                f"(meeting={meeting_id}); auto-wrote backup stub so the "
                "meeting can advance."
            )
        except Exception as e:
            self._logger.error(
                f"[{self.agent_id}] _ensure_revision_section_decision failed "
                f"for meeting={meeting_id} round={round_n}: {e}"
            )

    async def _handle_kickoff_facilitate_request(self, message: BaseMessage) -> None:
        """Round-8f.1: orchestrator chairs the kickoff meeting.

        Fires from ``runtime/kickoff/facilitate.py:request_facilitation``
        after ``try_synthesize`` returns ``ready`` or ``conflict``. Only
        the orchestrator subscribes to ``kickoff_facilitate_request``
        (see ``agent_subscriptions.py``). The macro
        ``kickoff_facilitation_prompt`` (in ``orchestrator_agent.j2``)
        instructs the LLM to read the meeting state, inspect
        pre-computed cross-check signals, and record ONE structured
        ``facilitator_note`` decision with action
        ``consensus`` / ``request_revision`` / ``escalate`` — then
        ``finish()``. The driver acts on the decision; this handler
        does not finalize or dispatch revisions itself.

        Structural mirror of ``_handle_kickoff_request`` — different
        event_type + different macro name. Same Fix #5-bis pre-set
        of ``self._focus_hub = 'workhub'`` so the always_include
        ranker can surface ``workhub_add_meeting_decision`` /
        ``workhub_get_document`` to the per-step LLM tool surface.
        """
        payload = message.payload if isinstance(message.payload, Mapping) else {}
        meeting_id = payload.get("meeting_id") if isinstance(payload, Mapping) else None
        milestone_index = (
            payload.get("milestone_index") if isinstance(payload, Mapping) else None
        )
        current_round = (
            payload.get("current_round") if isinstance(payload, Mapping) else None
        )
        max_rounds = (
            payload.get("max_rounds") if isinstance(payload, Mapping) else None
        )
        cross_check_findings = (
            payload.get("cross_check_findings") if isinstance(payload, Mapping) else None
        ) or []
        cross_check_revisers = (
            payload.get("cross_check_revisers") if isinstance(payload, Mapping) else None
        ) or {}
        last_synthesis_status = (
            payload.get("last_synthesis_status") if isinstance(payload, Mapping) else None
        ) or "unknown"

        if not meeting_id:
            self._logger.warning(
                f"[{self.agent_id}] kickoff_facilitate_request without meeting_id "
                f"(payload={payload!r}); ignoring."
            )
            return

        prompt_cfg = getattr(self, "_prompt_cfg", None) or {}
        template = prompt_cfg.get("template") if isinstance(prompt_cfg, Mapping) else None
        rendered: Optional[str] = None
        if template and hasattr(self, "render_macro"):
            try:
                rendered = self.render_macro(
                    template,
                    "kickoff_facilitation_prompt",
                    meeting_id=meeting_id,
                    milestone_index=milestone_index,
                    current_round=current_round,
                    max_rounds=max_rounds,
                    last_synthesis_status=last_synthesis_status,
                    cross_check_findings=cross_check_findings,
                    cross_check_revisers=cross_check_revisers,
                )
            except Exception as exc:
                self._logger.warning(
                    f"[{self.agent_id}] kickoff_facilitation_prompt render failed "
                    f"({exc}); falling back to plain-text prompt."
                )
                rendered = None
        if not rendered:
            rendered = (
                f"## Kickoff facilitation — meeting `{meeting_id}` "
                f"(M{milestone_index}), round {current_round}/{max_rounds}\n\n"
                f"Last synthesis status: **{last_synthesis_status}**.\n\n"
                "You are CHAIRING this kickoff meeting. Per your system "
                "prompt's kickoff_facilitation_prompt instructions, read "
                "all attendee decisions for the current round, inspect "
                "the pre-computed cross_check findings/revisers in this "
                "payload, then record ONE "
                "`workhub_add_meeting_decision(meeting_id=..., "
                "decision={'section': 'facilitator_note', 'round': ..., "
                "'content': {'action': 'consensus'|'request_revision'|"
                "'escalate', ...}}, ...)` and `finish()`. "
                "Do NOT call finalize_kickoff and do NOT dispatch "
                "revision events — the driver handles both based on "
                "your decision.\n\n"
                f"cross_check_findings: {cross_check_findings!r}\n\n"
                f"cross_check_revisers: {cross_check_revisers!r}\n"
            )

        self._logger.info(
            f"[{self.agent_id}] kickoff_facilitate_request received "
            f"(meeting_id={meeting_id}, M{milestone_index}, "
            f"round={current_round}/{max_rounds}, "
            f"last_synthesis_status={last_synthesis_status}); "
            "rendering kickoff_facilitation_prompt and running one agentic loop."
        )

        self._processing_state = ProcessingState.PROCESSING_TASK
        # Fix #5-bis (same rationale as _handle_kickoff_request):
        # pre-set hub focus = workhub so _apply_hub_focus does not
        # drop the workhub writes the kickoff_facilitation_prompt
        # macro instructs the LLM to call (workhub_get_document +
        # workhub_add_meeting_decision). Restore on exit.
        prev_focus_hub = getattr(self, "_focus_hub", None)
        self._focus_hub = "workhub"
        # PR3.1.2 / Loop B ⑧: pin phase so the PR3.1/PR3.2 levers can
        # gate kickoff differently from implementation even though both
        # share the same stage names (action/etc.). yaml entries keyed
        # on ``"kickoff:<stage>"`` take precedence over the bare-stage
        # key while this is set.
        prev_active_phase = getattr(self, "_active_phase", None)
        self._active_phase = "kickoff"
        try:
            system_prompt = self._compose_system_prompt()
            await self.run_agentic_loop(
                system_prompt=system_prompt,
                initial_prompt=rendered,
                max_steps=20,
            )
        except Exception as e:
            self._logger.error(
                f"[{self.agent_id}] kickoff_facilitation agentic loop failed: {e}"
            )
        finally:
            self._processing_state = ProcessingState.IDLE
            self._focus_hub = prev_focus_hub
            self._active_phase = prev_active_phase
            await self._drain_deferred_task_ready_messages()
            self._ensure_facilitator_note(
                meeting_id=meeting_id,
                milestone_index=milestone_index,
                round_n=current_round,
                last_synthesis_status=last_synthesis_status,
            )

    async def _handle_kickoff_detail_request(self, message: BaseMessage) -> None:
        """Per-milestone KICKOFF-DETAIL turn (2026-06-24). Fired by
        ``run_kickoff.author_milestone_detail`` at milestone ENTRY, BEFORE the lanes
        draft. The orchestrator (full system prompt + hub context + the ``milestone_*``
        tools) reviews the roadmap, MAY revise FUTURE phases (milestone_add/update/
        remove — delivered+active frozen), and MUST set THIS phase's detailed detail
        (milestone_set_detail). Renders ``kickoff_milestone_detail_prompt``; structural
        mirror of ``_handle_kickoff_facilitate_request``.

        Turn-completion contract: the FINALLY block ALWAYS marks the phase
        ``detail_authored`` (via ms.mark_detail_authored) so the main-loop poll
        (author_milestone_detail) resolves on turn COMPLETION rather than on the first
        store write. The framework does NOT silently substitute a slice here — if the
        turn authored NO detail, that is logged LOUD (ERROR) for investigation and the
        empty detail propagates so the caller's own loud fallback fires."""
        payload = message.payload if isinstance(message.payload, Mapping) else {}
        milestone_index = payload.get("milestone_index") if isinstance(payload, Mapping) else None
        milestone_id = payload.get("milestone_id") if isinstance(payload, Mapping) else None
        raw_requirements = (payload.get("raw_requirements") if isinstance(payload, Mapping) else "") or ""

        ms = getattr(self, "_hubs", None)
        ms = getattr(ms, "milestones", None)
        roadmap, current = [], None
        if ms is not None:
            try:
                roadmap = ms.list_milestones()
                current = ((ms.get(milestone_id) if milestone_id else None)
                           or ms.get_by_index(milestone_index) or ms.get_current())
            except Exception:
                roadmap, current = [], None
        if current is None:
            self._logger.warning(
                f"[{self.agent_id}] kickoff_detail_request without a resolvable milestone "
                f"(payload={payload!r}); ignoring.")
            return
        milestone_id = current.get("id")

        prompt_cfg = getattr(self, "_prompt_cfg", None) or {}
        template = prompt_cfg.get("template") if isinstance(prompt_cfg, Mapping) else None
        rendered: Optional[str] = None
        if template and hasattr(self, "render_macro"):
            try:
                rendered = self.render_macro(
                    template, "kickoff_milestone_detail_prompt",
                    milestone_index=milestone_index, milestone_id=milestone_id,
                    current=current, roadmap=roadmap, raw_requirements=raw_requirements)
            except Exception as exc:
                self._logger.warning(
                    f"[{self.agent_id}] kickoff_milestone_detail_prompt render failed "
                    f"({exc}); falling back to plain-text prompt.")
                rendered = None
        if not rendered:
            _rm = "\n".join(
                f"  M{m.get('index')} [{m.get('name')}@{m.get('version')}] {m.get('status')}: "
                f"{str(m.get('description_slice',''))}" for m in roadmap)
            rendered = (
                f"## Milestone {milestone_index} kickoff — author the phase detail\n\n"
                f"You are entering milestone {milestone_index} of {len(roadmap)}. FIRST call "
                f"`milestone_list`. Review the roadmap below against what's DELIVERED. You MAY "
                f"revise the FUTURE (not-yet-started) phases via `milestone_add` / "
                f"`milestone_update` / `milestone_remove` (delivered + active are frozen) — a "
                f"no-op is fine. Then you MUST call "
                f"`milestone_set_detail(milestone='{milestone_index}', detail=...)` with a "
                f"concrete, bounded detail for THIS phase: exactly which endpoints / pages / "
                f"components / data this phase ADDS, the acceptance, and what's already shipped "
                f"(do NOT rebuild). Then `finish()`.\n\n"
                f"OVERALL GOAL (context only — do NOT build it all this phase):\n"
                f"{str(raw_requirements)}\n\nROADMAP:\n{_rm}\n")

        self._logger.info(
            f"[{self.agent_id}] kickoff_detail_request (M{milestone_index}, id={milestone_id}); "
            "rendering kickoff_milestone_detail_prompt and running one agentic loop.")
        self._processing_state = ProcessingState.PROCESSING_TASK
        prev_active_phase = getattr(self, "_active_phase", None)
        self._active_phase = "kickoff"
        try:
            system_prompt = self._compose_system_prompt()
            await self.run_agentic_loop(
                system_prompt=system_prompt, initial_prompt=rendered, max_steps=16)
        except Exception as e:
            self._logger.error(f"[{self.agent_id}] kickoff_detail agentic loop failed: {e}")
        finally:
            self._processing_state = ProcessingState.IDLE
            self._active_phase = prev_active_phase
            # Turn-completion contract: ALWAYS mark the phase detail_authored so the
            # main-loop poll (author_milestone_detail) resolves on turn COMPLETION,
            # NOT on the first store write (that race broadcast a half-finished detail
            # + let the main resident loop re-author). The framework does NOT silently
            # substitute the slice here — if the turn authored NO detail, log LOUD so a
            # reviewer can investigate; the empty detail propagates and the caller's own
            # loud fallback handles last-resort scope.
            try:
                if ms is not None:
                    cur = ms.get(milestone_id)
                    if cur is not None and not str(cur.get("detail") or "").strip():
                        self._logger.error(
                            f"[{self.agent_id}] milestone-detail turn authored NO detail "
                            f"for M{milestone_index} — investigate.")
                    ms.mark_detail_authored(milestone_id, agent="orchestrator")
            except Exception:
                pass
            # DUAL-LOOP DOUBLE-AUTHOR FIX: drain any kickoff_* / task_ready that
            # was deferred while this milestone-detail turn ran, now that the
            # lane is IDLE again (mirrors the other kickoff handlers' finally).
            await self._drain_deferred_task_ready_messages()

    def _ensure_facilitator_note(
        self,
        *,
        meeting_id: Optional[str],
        milestone_index: Optional[int],
        round_n: Optional[int],
        last_synthesis_status: str,
    ) -> None:
        """Closed-by-construction (round 8g Fix #D): guarantee a
        ``section=facilitator_note`` decision exists for this round
        once ``_handle_kickoff_facilitate_request`` exits.

        Smoke #9-quater (2026-06-02 23:52) caught the orchestrator's
        facilitation turn finishing with the prose summary
        ``"Handled the urgent kickoff facilitation blocker by re-driving
        the frontend..."`` but never writing the structured
        ``facilitator_note`` decision the driver polls via
        ``facilitate.read_facilitator_decision``. The driver then
        re-polled ``current_phase`` which kept returning ``facilitator``
        forever — the meeting hung until the 1200s synthesize_fallback
        timeout.

        Default action when the LLM didn't write a clean decision:
        ``escalate`` → the driver falls through to ``synthesize_fallback``
        which assembles a contract from whatever sections exist and
        ships. This is safer than ``request_revision`` (which loops back
        through more LLM cost without rationale) and safer than
        ``consensus`` (which would dispatch task_tree from a possibly
        unaligned set of drafts).
        """
        if not meeting_id or round_n is None:
            return
        try:
            from ...runtime.kickoff import facilitate as _facilitate
            # Round 8h Fix #D-bis: smoke #9-quindecimus (2026-06-03 05:24)
            # showed Fix #D firing spuriously even when 2 LLM-written
            # facilitator_notes already existed on disk. The original
            # check used read_facilitator_decision which only returns
            # the LATEST note — fragile against race conditions in the
            # writer and against intentional multiple-writes (the LLM
            # sometimes amends its first note mid-turn). Replace with a
            # full scan of decisions[]: if ANY existing facilitator_note
            # for round_n has any action token, do NOT write the backup.
            workhub_check = getattr(self._hubs, "workhub", None)
            pages_store = getattr(workhub_check, "stores", None)
            pages = getattr(pages_store, "documents", None) if pages_store else None
            existing_action: Optional[str] = None
            if pages and hasattr(pages, "value"):
                page = pages.value().get(meeting_id)
                if isinstance(page, Mapping):
                    decisions = (page.get("metadata") or {}).get("decisions") or []
                    for d in decisions:
                        if not isinstance(d, Mapping):
                            continue
                        if d.get("section") != "facilitator_note":
                            continue
                        if (d.get("agent") or d.get("recorded_by")) != "orchestrator":
                            continue
                        if d.get("round") != round_n:
                            continue
                        # Skip prior auto_backup entries — if those are
                        # the only "notes", we still want to surface a
                        # fresh backup (defensive: the prior backup may
                        # have been written by a different code path).
                        ds_content = d.get("content") or {}
                        if isinstance(ds_content, Mapping) and ds_content.get("source") == "auto_backup":
                            continue
                        action = (ds_content.get("action") if isinstance(ds_content, Mapping) else None) or None
                        if action:
                            existing_action = action
                            break
            if existing_action:
                self._logger.info(
                    f"[{self.agent_id}] _ensure_facilitator_note: "
                    f"found LLM-written facilitator_note for round={round_n} "
                    f"(action={existing_action!r}); skipping backup write."
                )
                return
            workhub = getattr(self._hubs, "workhub", None)
            if workhub is None or not hasattr(workhub, "add_meeting_decision"):
                return
            decision = {
                "section": "facilitator_note",
                "round": round_n,
                "kind": "facilitator_decision",
                "content": {
                    "action": "escalate",
                    "rationale": (
                        f"Orchestrator's kickoff_facilitate handler ended "
                        f"without writing a structured facilitator_note "
                        f"(last_synthesis_status={last_synthesis_status}); "
                        "auto-wrote backup escalate so the driver can "
                        "fall through to synthesize_fallback rather than "
                        "hanging the meeting."
                    ),
                    "source": "auto_backup",
                },
            }
            kwargs = {"meeting_id": meeting_id, "decision": decision,
                      "agent": self.agent_id}
            if milestone_index is not None:
                kwargs["milestone_index"] = milestone_index
            workhub.add_meeting_decision(**kwargs)
            self._logger.warning(
                f"[{self.agent_id}] kickoff_facilitate ended without "
                f"explicit facilitator_note (meeting={meeting_id}, "
                f"round={round_n}); auto-wrote backup escalate so the "
                "meeting falls through to synthesize_fallback."
            )
        except Exception as e:
            self._logger.error(
                f"[{self.agent_id}] _ensure_facilitator_note failed "
                f"for meeting={meeting_id} round={round_n}: {e}"
            )

    async def _handle_kickoff_comment_phase_request(self, message: BaseMessage) -> None:
        """Round-8g: phase-aware kickoff meeting — comment phase.

        Wakes the attendee to read all initial-round drafts via
        workhub_get_document, post 0+ section="comment" decisions targeting
        OTHER attendees' drafts, then end with a section="phase_ack"
        decision marking the comment phase done for this round.
        Mirrors the structural pattern of _handle_kickoff_request.
        """
        payload = message.payload if isinstance(message.payload, Mapping) else {}
        meeting_id = payload.get("meeting_id")
        milestone_index = payload.get("milestone_index")
        current_round = payload.get("current_round")
        attendees = payload.get("attendees") or []

        if not meeting_id:
            self._logger.warning(
                f"[{self.agent_id}] kickoff_comment_phase_request without "
                f"meeting_id; ignoring."
            )
            return

        prompt_cfg = getattr(self, "_prompt_cfg", None) or {}
        template = prompt_cfg.get("template") if isinstance(prompt_cfg, Mapping) else None
        rendered: Optional[str] = None
        if template and hasattr(self, "render_macro"):
            try:
                rendered = self.render_macro(
                    template,
                    "kickoff_comment_phase_prompt",
                    meeting_id=meeting_id,
                    milestone_index=milestone_index,
                    current_round=current_round,
                    attendees=attendees,
                )
            except Exception as exc:
                self._logger.warning(
                    f"[{self.agent_id}] kickoff_comment_phase_prompt render "
                    f"failed ({exc}); falling back to plain-text prompt."
                )
                rendered = None
        if not rendered:
            rendered = (
                f"## Kickoff comment phase — meeting `{meeting_id}` "
                f"(M{milestone_index}, round {current_round})\n\n"
                "Read all initial drafts via workhub_get_document, post 0+ "
                "section='comment' decisions targeting other attendees' "
                "sections (kind=question/disagree/suggest/ack with "
                "target_decision_id + target_section + body), then end "
                "with section='phase_ack' kind='comment_phase_done' "
                f"round={current_round} content={{'ack': true, 'phase': "
                "'comment'}}. finish() once done.\n"
            )

        self._logger.info(
            f"[{self.agent_id}] kickoff_comment_phase_request received "
            f"(meeting_id={meeting_id}, round={current_round}); running "
            "agentic loop on kickoff_comment_phase_prompt."
        )

        self._processing_state = ProcessingState.PROCESSING_TASK
        prev_focus_hub = getattr(self, "_focus_hub", None)
        self._focus_hub = "workhub"
        # PR3.1.2 / Loop B ⑧: pin phase so the PR3.1/PR3.2 levers can
        # gate kickoff differently from implementation even though both
        # share the same stage names (action/etc.). yaml entries keyed
        # on ``"kickoff:<stage>"`` take precedence over the bare-stage
        # key while this is set.
        prev_active_phase = getattr(self, "_active_phase", None)
        self._active_phase = "kickoff"
        try:
            system_prompt = self._compose_system_prompt()
            # Comment phase is heavier than initial response: read all
            # drafts + post N comments + phase_ack. Cap at 20 steps to
            # allow read + 5-7 comments + ack + finish.
            max_steps = getattr(self, "_max_steps_per_kickoff_phase", 20)
            await self.run_agentic_loop(
                system_prompt=system_prompt,
                initial_prompt=rendered,
                max_steps=max_steps,
            )
        except Exception as e:
            self._logger.error(
                f"[{self.agent_id}] kickoff_comment_phase agentic loop failed: {e}"
            )
        finally:
            self._processing_state = ProcessingState.IDLE
            self._focus_hub = prev_focus_hub
            self._active_phase = prev_active_phase
            await self._drain_deferred_task_ready_messages()
            self._ensure_phase_ack(
                meeting_id=meeting_id,
                milestone_index=milestone_index,
                round_n=current_round,
                phase="comment",
            )

    async def _handle_kickoff_reply_phase_request(self, message: BaseMessage) -> None:
        """Round-8g: phase-aware kickoff meeting — reply phase.

        Wakes the attendee to read comments targeting its OWN section,
        decide for each: reply (more comment with parent_id), revise
        (new section decision with kind=proposal_v{N}_revised), or ack.
        Ends with a section="phase_ack" decision marking the reply
        phase done.
        """
        payload = message.payload if isinstance(message.payload, Mapping) else {}
        meeting_id = payload.get("meeting_id")
        milestone_index = payload.get("milestone_index")
        current_round = payload.get("current_round")

        if not meeting_id:
            self._logger.warning(
                f"[{self.agent_id}] kickoff_reply_phase_request without "
                f"meeting_id; ignoring."
            )
            return

        prompt_cfg = getattr(self, "_prompt_cfg", None) or {}
        template = prompt_cfg.get("template") if isinstance(prompt_cfg, Mapping) else None
        rendered: Optional[str] = None
        if template and hasattr(self, "render_macro"):
            try:
                rendered = self.render_macro(
                    template,
                    "kickoff_reply_phase_prompt",
                    meeting_id=meeting_id,
                    milestone_index=milestone_index,
                    current_round=current_round,
                )
            except Exception as exc:
                self._logger.warning(
                    f"[{self.agent_id}] kickoff_reply_phase_prompt render "
                    f"failed ({exc}); falling back to plain-text prompt."
                )
                rendered = None
        if not rendered:
            rendered = (
                f"## Kickoff reply phase — meeting `{meeting_id}` "
                f"(M{milestone_index}, round {current_round})\n\n"
                "Read all section='comment' decisions targeting your "
                f"section ('{self.agent_id}') via workhub_get_document. For "
                "each comment, either reply (post another comment with "
                "parent_id), revise your initial draft (new "
                f"section='{self.agent_id}' decision with "
                f"kind='proposal_v{current_round}_revised'), or ack. "
                "End with section='phase_ack' "
                f"kind='reply_phase_done' round={current_round} "
                "content={'ack': true, 'phase': 'reply'}. finish().\n"
            )

        self._logger.info(
            f"[{self.agent_id}] kickoff_reply_phase_request received "
            f"(meeting_id={meeting_id}, round={current_round}); running "
            "agentic loop on kickoff_reply_phase_prompt."
        )

        self._processing_state = ProcessingState.PROCESSING_TASK
        prev_focus_hub = getattr(self, "_focus_hub", None)
        self._focus_hub = "workhub"
        # PR3.1.2 / Loop B ⑧: pin phase so the PR3.1/PR3.2 levers can
        # gate kickoff differently from implementation even though both
        # share the same stage names (action/etc.). yaml entries keyed
        # on ``"kickoff:<stage>"`` take precedence over the bare-stage
        # key while this is set.
        prev_active_phase = getattr(self, "_active_phase", None)
        self._active_phase = "kickoff"
        try:
            system_prompt = self._compose_system_prompt()
            # Reply phase: read comments + possibly revise + ack. Same
            # cap as comment phase — generous enough for revisions but
            # bounded.
            max_steps = getattr(self, "_max_steps_per_kickoff_phase", 20)
            await self.run_agentic_loop(
                system_prompt=system_prompt,
                initial_prompt=rendered,
                max_steps=max_steps,
            )
        except Exception as e:
            self._logger.error(
                f"[{self.agent_id}] kickoff_reply_phase agentic loop failed: {e}"
            )
        finally:
            self._processing_state = ProcessingState.IDLE
            self._focus_hub = prev_focus_hub
            self._active_phase = prev_active_phase
            await self._drain_deferred_task_ready_messages()
            self._ensure_phase_ack(
                meeting_id=meeting_id,
                milestone_index=milestone_index,
                round_n=current_round,
                phase="reply",
            )

    def _ensure_phase_ack(
        self,
        *,
        meeting_id: Optional[str],
        milestone_index: Optional[int],
        round_n: Optional[int],
        phase: str,
    ) -> None:
        """Closed-by-construction: guarantee a phase_ack exists for
        (this agent, round_n, phase) once a kickoff phase handler exits.

        The phase macro instructs the LLM to write the ack, but if it
        finishes early or hits max_steps, the meeting would hang forever
        waiting on this attendee. Auto-writing a backup ack ensures the
        driver can always advance — the LLM-written ack is preserved
        when present (we only write when missing).
        """
        if not meeting_id or round_n is None:
            return
        try:
            from ...runtime.kickoff import facilitate as _facilitate
            already = _facilitate.phase_acked_by(
                self._hubs, meeting_id, round_n, phase,
            )
            if self.agent_id in already:
                return
            workhub = getattr(self._hubs, "workhub", None)
            if workhub is None or not hasattr(workhub, "add_meeting_decision"):
                return
            decision = {
                "section": "phase_ack",
                "round": round_n,
                "kind": f"{phase}_phase_done",
                "content": {
                    "ack": True,
                    "phase": phase,
                    "source": "auto_backup",
                },
            }
            kwargs = {"meeting_id": meeting_id, "decision": decision,
                      "agent": self.agent_id}
            if milestone_index is not None:
                kwargs["milestone_index"] = milestone_index
            workhub.add_meeting_decision(**kwargs)
            self._logger.warning(
                f"[{self.agent_id}] {phase}_phase ended without explicit "
                f"phase_ack (meeting={meeting_id}, round={round_n}); "
                "auto-wrote backup ack so the meeting can advance."
            )
        except Exception as e:
            self._logger.error(
                f"[{self.agent_id}] _ensure_phase_ack failed for "
                f"meeting={meeting_id} round={round_n} phase={phase}: {e}"
            )

    async def _send_runtime_status_update(
        self,
        *,
        to_agent: Optional[str],
        status: str,
        content: str,
        metadata: Optional[Dict[str, str]] = None,
    ) -> None:
        """Emit a lightweight status/update message to upstream coordination."""
        if not to_agent or not self._external_bus:
            return

        from uuid import uuid4

        header = MessageHeader(
            message_id=str(uuid4()),
            source_agent_id=self.agent_id,
            target_agent_id=to_agent,
            priority=MessagePriority.NORMAL,
        )
        message = BaseMessage(
            header=header,
            message_type=MessageType.STATUS,
            payload=content,
            metadata={
                "msg_type": "status",
                "processing_status": status,
                **(metadata or {}),
            },
        )
        try:
            await self._external_bus.send(message)
        except Exception as e:
            self._logger.warning(f"[{self.agent_id}] Failed to send runtime status update: {e}")


def _kickoff_missing_section_kind(section: str) -> str:
    """Name the substantive decisions the given kickoff section MUST contain, so
    the finish-rejection error below can tell the attendee EXACTLY what is missing
    (no generic "your section" — a named, actionable gap)."""
    s = (section or "").strip().lower()
    if s == "backend":
        return "endpoint + data-model/table decisions (api_endpoints + data_model.tables)"
    if s == "frontend":
        return "page/UI decisions (ui_pages + user_flows)"
    if s == "verifier":
        return "acceptance-predicate decisions (predicates)"
    return "endpoint/table/page decisions"


def _kickoff_correction_prompt(section: str, meeting_id, milestone_index) -> str:
    """KICKOFF STALL FIX — LOUD rejected-finish prompt.

    Task C root cause: an attendee whose ``kickoff_declare_*`` / decision was
    mangled by MALFORMED records NO substantive section, the kickoff driver
    measures it as MISSING, the attendee gets NO feedback, concludes it is done,
    and loops ``finish()`` — so the meeting stalls in phase=initial to the 1200s
    timeout. Instead of silently accepting that finish, we REJECT it loudly: this
    prompt is framed as a finish/tool ERROR that NAMES the missing section so the
    attendee knows it is NOT done and exactly what to declare before finishing.
    We still teach author-in-parts (the practical recovery) and never author the
    section FOR the agent — the section stays the agent's own work."""
    kind = _kickoff_missing_section_kind(section)
    return (
        f"## finish() REJECTED — your initial proposal has NO recorded "
        f"{kind}\n\n"
        f"You called finish(), but your initial kickoff proposal for "
        f"section='{section}' on meeting `{meeting_id}` has NO substantive "
        f"decision recorded (it is missing or all-empty — usually because the "
        f"inline `decision={{...}}` JSON was TOO LONG for one tool call and got "
        f"mangled/dropped). The meeting CANNOT advance and you are NOT done: the "
        f"kickoff driver counts you as MISSING. You MUST declare your "
        f"{kind} via `workhub_add_meeting_decision` BEFORE finishing.\n\n"
        "Author it now IN PARTS — the meeting MERGES multiple decisions for your "
        "section, so submit SMALL pieces:\n"
        f"1. `workhub_add_meeting_decision(meeting_id='{meeting_id}', milestone_index={milestone_index}, "
        "decision={{'section': '" + section + "', 'content': {{<ONE field piece, e.g. 2 ui_pages "
        "or 2 endpoints or 2 predicates>}}}})`\n"
        "2. Repeat with the next small piece until your whole section is submitted "
        "(each call well under 60 lines of JSON).\n"
        "3. ONLY THEN `finish()`.\n\n"
        "Do NOT try to emit one giant payload — long arguments get mangled. "
        "Do NOT re-state your analysis. Just submit the pieces."
    )


# Shared substance checks — single source in kickoff/section_substance.py.
from ...runtime.kickoff.section_substance import (  # noqa: E402
    decision_has_substance as _decision_has_substance,
    real_items as _real_items,
    section_has_substance as _section_has_substance,
)
