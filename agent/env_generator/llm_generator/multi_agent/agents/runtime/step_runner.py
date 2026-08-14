from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set

from utils.llm import Message

from .common import ProcessingState
from .step_pipeline import AgentStepHelperMixin, AgentStepStageMixin, AgentStepToolingMixin


class AgentStepRunner(AgentStepHelperMixin, AgentStepStageMixin, AgentStepToolingMixin):
    # #681: THE HOST-CLASS CONTRACT, DECLARED.
    # This is a MIXIN: `agent_id`, `_logger`, `_hubs` and the sibling methods below are
    # supplied by the class it is mixed into (multi_agent/agents/base.py), so a checker
    # reading this file alone reports every use as a missing attribute. That was 990 of
    # the 2218 diagnostics — 45%, the single largest class — and it buried the real ones:
    # the same sweep found #658 (two constructors called with arguments the classes do not
    # have) and a dangling `WorkHub` annotation, both genuine, under that noise.
    # Annotation-only, under TYPE_CHECKING: no runtime effect, no import at runtime.
    if TYPE_CHECKING:
        agent_id: str
        _logger: Any
        _hubs: Any
        _execution_mode: Any
        _shutdown_requested: Any
        _interrupt_messages: Any
        def check_if_stuck(self, *a: Any, **k: Any) -> Any: ...
        def get_loop_breaker_prompt(self, *a: Any, **k: Any) -> Any: ...
        def clear_stuck_history(self, *a: Any, **k: Any) -> Any: ...
        def _check_and_handle_urgent(self, *a: Any, **k: Any) -> Any: ...


    def _stamp_step_activity(self) -> None:
        """#147/#149 liveness stamp. Called from loop-OWNED paths only (loop
        enter, step top, action-round top, after each stage-LLM return) — a
        healthy long step keeps its stamp fresh so the wedge watchdog cannot
        false-positive on it; a loop parked on a dead await stops stamping and
        the resident poller still declares it wedged. Never call this from the
        poller context (that would mask real wedges)."""
        self._last_step_activity = time.time()

    def _unwind_agentic_loop(self, entry_generation: int) -> None:
        """#149 generation-guarded unwind. A #147 force-reset bumps
        _loop_generation; a loop that entered under an OLDER generation was
        declared dead and replaced — its finally must not stomp the
        replacement loop's PROCESSING_TASK back to IDLE / zero its depth
        (run-73: the stomp blinded the V30 re-entrancy guard and let a third
        concurrent loop start)."""
        if getattr(self, "_loop_generation", 0) != entry_generation:
            self._logger.warning(
                f"[{self.agent_id}] stale agentic loop unwound after a watchdog "
                "reset (generation moved) — leaving state/depth to the "
                "replacement loop")
            return
        self._processing_state = ProcessingState.IDLE
        self._agentic_loop_depth = max(0, getattr(self, "_agentic_loop_depth", 1) - 1)

    async def run_one_step(
        self,
        *,
        system_prompt: str,
        initial_prompt: str,
        observer_handler: Any = None,
    ) -> Dict[str, Any]:
        """Run one bounded pipeline step using the shared staged runtime."""
        return await self.run_agentic_loop(
            system_prompt=system_prompt,
            initial_prompt=initial_prompt,
            max_steps=1,
            background_mode=True,
            observer_handler=observer_handler,
        )

    async def run_agentic_loop(
        self,
        system_prompt: str,
        initial_prompt: str,
        max_steps: int = 2000,
        background_mode: bool = False,
        observer_handler: Any = None,
    ) -> Dict:
        """
        Run LLM agentic loop until finish() is called.

        Features:
        - ReAct pattern: Thought → Action → Observation
        - Checks for urgent messages between steps
        - Stuck detection and loop breaking
        - Output truncation/compression
        """
        self._processing_state = ProcessingState.PROCESSING_TASK
        # V30 RE-ENTRANCY GUARD: track agentic-loop nesting depth so the urgent drain
        # (messaging._check_and_handle_urgent) can refuse to start a NESTED run_agentic_loop.
        # The shared _processing_state flag is reset to IDLE by a nested handler's finally,
        # leaving a window where the urgent drain (step_runner step boundary) read IDLE and
        # started a SECOND in-stack run_agentic_loop that deadlocked in setup (before step 1)
        # and hung the frontend lane silently for 13min (V30). This monotonic depth counter
        # is reset-proof; decremented in the finally below.
        self._agentic_loop_depth = getattr(self, "_agentic_loop_depth", 0) + 1
        # #149: capture the wedge-reset generation at entry — the finally only
        # unwinds state/depth if no watchdog reset superseded this loop.
        _entry_generation = getattr(self, "_loop_generation", 0)
        self._stamp_step_activity()  # #147: loop-enter counts as activity
        # V30 liveness: log loop ENTER so a stall BEFORE the first step (the silent pre-step
        # hang the frontend hit) is observable, and depth>1 surfaces unexpected nesting.
        self._logger.info(
            f"[{self.agent_id}] run_agentic_loop ENTER (depth={self._agentic_loop_depth}, "
            f"max_steps={max_steps})")
        messages = [Message.system(system_prompt), Message.user(initial_prompt)]

        # Memory refinement (2026-06-09, user-asked): inject the Memory-Bank digest
        # DIRECTLY at task start, deterministically (no LLM round-trip). This replaces
        # the old retrieve_context step-0 stage, which spent 1-2 LLM calls to DECIDE to
        # read and then read this same digest — now it is always present and reliable.
        # Skipped during kickoff (the bank is empty then). Best-effort, never fatal; the
        # read_memory_bank / knowledge tools stay available on-demand in the action stage.
        if getattr(self, "_active_phase", None) != "kickoff":
            try:
                _mb_tool = getattr(self, "_tool_instances", {}).get("read_memory_bank")
                if _mb_tool is not None:
                    _res = _mb_tool.execute(mode="digest")
                    _digest = ""
                    if getattr(_res, "success", False):
                        _digest = ((getattr(_res, "data", None) or {}).get("content") or "").strip()
                    if _digest and "not initialized" not in _digest.lower():
                        messages.append(Message.system(
                            "Your Memory Bank digest (current focus, recent changes, next "
                            "steps, blockers — auto-maintained; injected at task start so you "
                            "need not read it again unless you want full detail):\n\n" + _digest
                        ))
            except Exception:
                pass

        files_created: List[str] = []
        files_modified: List[str] = []
        no_action_tool_steps = 0

        tool_schema_map = self._build_tool_schema_map()
        self._log_registered_tools(tool_schema_map)

        # Dedicated hub-sync tools were removed when the CRDT observer was dropped
        # (Cutover 5); hub state is now surfaced via the hub_pulse stage. Kept as an
        # explicit empty set so the action stages don't subtract anything here.
        hub_sync_tool_names: set = set()
        knowledge_fetch_names = set(self.KNOWLEDGE_FETCH_TOOL_NAMES) & set(tool_schema_map.keys())
        knowledge_store_names = set(self.KNOWLEDGE_STORE_TOOL_NAMES) & set(tool_schema_map.keys())
        pipeline_cfg = getattr(self, "_execution_pipeline_config", {}) or {}
        configured_stages = pipeline_cfg.get("stages")
        default_stage_order = [
            "hub_pulse",
            "runtime_team_status",
            "planning",
            "retrieve_context",
            "action",
            "hub_commit_gate",
            "knowledge_sync",
        ]
        stage_order = [
            str(s).strip().lower().replace("-", "_")
            for s in (configured_stages or default_stage_order)
            if str(s).strip()
        ]
        enabled_stages = set(stage_order)
        # Engine-forced stages: hub_pulse always first, hub_commit_gate always last.
        # Cannot be disabled via yaml — code-forced for invariants.
        if "hub_pulse" not in enabled_stages:
            enabled_stages.add("hub_pulse")
            stage_order = ["hub_pulse"] + [s for s in stage_order if s != "hub_pulse"]
        if "hub_commit_gate" not in enabled_stages:
            enabled_stages.add("hub_commit_gate")
            stage_order = [s for s in stage_order if s != "hub_commit_gate"] + ["hub_commit_gate"]
        max_calls_cfg = {
            "hub_pulse": 0,
            "planning": 1,
            "retrieve_context": 2,
            "hub_commit_gate": 0,
            "knowledge_sync": 1,
        }
        max_action_rounds = 15
        raw_max_calls = pipeline_cfg.get("max_tool_calls_per_stage", {}) or {}
        for stage_name, raw_value in raw_max_calls.items():
            try:
                normalized = str(stage_name).strip().lower().replace("-", "_")
                max_calls_cfg[normalized] = int(raw_value)
            except Exception:
                continue
        try:
            max_action_rounds = max(1, int(pipeline_cfg.get("max_action_rounds_per_step", 15)))
        except Exception:
            max_action_rounds = 15
        step_traces: List[Dict[str, Any]] = []

        def _stage_enabled(stage_name: str) -> bool:
            # Memory-mechanism redesign (2026-06-08, user-approved). The Memory
            # Bank ALREADY auto-updates via MemoryBankSync (no LLM, batched
            # 30s/5-item) from the agent's tool activity — so the per-step
            # retrieve_context + knowledge_sync stages, each an LLM round-trip
            # EVERY step just to DECIDE whether to read/write the same bank, are
            # redundant churn (112 read + 76 write observed in one short kickoff).
            # Lean on the auto-sync instead; the read_memory_bank / update_memory_
            # bank tools stay available ON-DEMAND in the action stage:
            #   * knowledge_sync: never forced per-step. The auto-sync captures
            #     routine progress + run_agentic_loop force-syncs at task end.
            #   * retrieve_context: runs ONCE at task start (step 0) to load the
            #     Memory-Bank digest, then is skipped (and skipped entirely during
            #     kickoff, where the bank is empty). The agent re-reads on demand.
            if stage_name == "knowledge_sync":
                return False
            if stage_name == "retrieve_context":
                # The Memory-Bank digest is now injected deterministically at task start
                # (above) — reliable, no LLM. retrieve_context is kept at step 0 ONLY
                # (skipped during kickoff) so the lane still gets its cross-run knowledge
                # fetch + action-tool pre-selection. Fully RETIRING it (run #10) coincided
                # with a drop in lane code quality (new handler↔model + raw-psycopg bugs
                # that run #8's step-0 retrieve_context did not produce), so step-0 is
                # restored as the conservative choice; the per-step churn the user flagged
                # stays gone (this runs once per task, not every step).
                if getattr(self, "_active_phase", None) == "kickoff":
                    return False
                return step == 0
            return stage_name in enabled_stages

        # Per-wake reset: the hub_pulse is re-injected ONLY when it CHANGES since the
        # last step (see the hub_pulse stage). Reset the tracker each wake so the FIRST
        # pulse of a fresh wake always renders (orientation), then dedups within the wake.
        self._last_hub_pulse_prompt = None
        try:
            for step in range(max_steps):
                # FIX #147: step-activity stamp — the busy-wedge watchdog
                # (messaging.py) treats a lane with no stamp movement for
                # ENVGEN_LANE_WEDGE_S as wedged, not busy.
                self._stamp_step_activity()
                if self._shutdown_requested:
                    return {"success": False, "error": "Shutdown requested", "files_created": files_created}

                # Condense at EVERY step boundary (was step % 10 — too rare, let
                # context bloat to ~770 → saturation). A step boundary is BETWEEN
                # endpoints (the prior endpoint is written + registered), so
                # summarizing the completed work here never disrupts an in-progress
                # implementation. (The previous mid-action chokepoint in
                # step_pipeline/tooling._call_stage_llm did disrupt it — summarizing
                # the backend's working state mid-endpoint → it lost track and looped
                # on memory reads instead of finishing the code. That guard is removed;
                # this every-step boundary condensation is the sole bound, and it
                # keeps context ~28-100, far under the ~770 saturation.)
                _model = getattr(getattr(self, "config", None), "model_name", None)
                if step > 0:
                    messages = _mask_old_observations(messages, model=_model)
                if step > 0 and hasattr(self, "memory"):
                    if self.memory.should_condense_messages(messages):
                        # F3/F4 (2026-07-21): should_condense_messages triggers on raw message
                        # COUNT (>50), re-firing every 2-4 steps — each an LLM summarization call —
                        # even on large-context models nowhere near their real budget, and each
                        # condense injects a "RESUME NOW: write code" directive that is wrong for a
                        # coordinating lane mid-kickoff. Gate the (expensive) condense on:
                        #   F4: NOT in the kickoff phase (coordinating lanes must not be told to code);
                        #   F3: the model's actual char budget being pressured AFTER masking; and
                        #   F3: a min-steps cooldown since the last condense (kills the thrash loop).
                        _phase_ok = getattr(self, "_active_phase", None) != "kickoff"
                        _cooldown_ok = (step - getattr(self, "_last_condense_step", -999)) >= 6
                        _pressured = True  # fail-safe: condense if we cannot size the budget
                        try:
                            from utils.model_limits import resolve_ctx_working_chars
                            _budget = resolve_ctx_working_chars(_model)
                            if _budget:
                                # Count only STRING content, accessed via getattr — messages are
                                # Message OBJECTS here (mirrors _mask_old_observations so both layers
                                # agree on the gate). Skipping non-str content also avoids inflating
                                # the estimate with base64 image blocks in list content.
                                _chars = 0
                                for _m in messages:
                                    _c = getattr(_m, "content", None)
                                    if isinstance(_c, str):
                                        _chars += len(_c)
                                _pressured = _chars > _budget * 0.9
                        except Exception:
                            _pressured = True
                        if _phase_ok and _cooldown_ok and _pressured:
                            self._logger.info(f"[{self.agent_id}] Condensing messages (len={len(messages)})")
                            messages = await self.memory.condense_messages(messages)
                            self._last_condense_step = step
                            self._logger.info(f"[{self.agent_id}] After condensation: len={len(messages)}")

                hub_pulse_prompt = None
                runtime_team_status_prompt = None
                step_reminder_count = len(getattr(self, "_step_reminders", []) or [])
                step_reminder_prompt = self._build_step_reminder_prompt()
                retrieved_action_names: Dict[str, Set[str]] = {}

                if step_reminder_prompt:
                    messages.append(Message.user(step_reminder_prompt))
                    if hasattr(self, "advance_step_reminders"):
                        self.advance_step_reminders()

                # FIX #24: framework-driven per-endpoint implementation focus.
                # During endpoint implementation, inject a deterministic
                # directive naming the next endpoint that still lacks route code
                # so the lane implements one-at-a-time instead of gaming/drifting
                # on "implement all 25". Returns None outside impl, so this is a
                # no-op for kickoff/other phases + non-endpoint lanes.
                if hasattr(self, "_build_endpoint_impl_directive"):
                    try:
                        _impl_directive = self._build_endpoint_impl_directive()
                    except Exception:
                        _impl_directive = None
                    if _impl_directive:
                        messages.append(Message.user(_impl_directive))

                if self.check_if_stuck():
                    breaker_prompt = self.get_loop_breaker_prompt()
                    if breaker_prompt:
                        messages.append(Message.user(breaker_prompt))
                        self.clear_stuck_history()

                loop_time = asyncio.get_running_loop().time
                step_trace: Dict[str, Any] = {
                    "step": step + 1,
                    "mode_before": self._execution_mode,
                    "mode_after": self._execution_mode,
                    "stages": {},
                }

                def _mark_stage(
                    stage_name: str,
                    *,
                    executed: bool,
                    duration_ms: int = 0,
                    skip_reason: Optional[str] = None,
                    metadata: Optional[Dict[str, Any]] = None,
                ) -> None:
                    payload: Dict[str, Any] = {
                        "executed": executed,
                        "duration_ms": duration_ms,
                    }
                    if skip_reason:
                        payload["skip_reason"] = skip_reason
                    if metadata:
                        payload["metadata"] = metadata
                    step_trace["stages"][stage_name] = payload

                await _idle_backoff_639(self)
                self._logger.info(f"[{self.agent_id}] Step {step + 1}/{max_steps} (mode={self._execution_mode})")
                _mark_stage(
                    "step_reminders",
                    executed=bool(step_reminder_prompt),
                    metadata={"count": step_reminder_count},
                    skip_reason=None if step_reminder_prompt else "no_step_reminders",
                )
                _mark_stage(
                    "hub_auto_sync_start",
                    executed=True,
                    metadata=self._auto_sync_hub_state(
                        step=step,
                        files_created=files_created,
                        files_modified=files_modified,
                        step_trace=step_trace,
                        status="working",
                    ),
                )

                if _stage_enabled("hub_pulse"):
                    stage_start = loop_time()
                    self._active_stage = "hub_pulse"
                    try:
                        # Phase 0b: pull other agents' merged work from the
                        # shared ``integration`` branch into this agent's
                        # worktree BEFORE anything else this step. Without
                        # this, verifier never sees backend's commits,
                        # frontend never sees design's app/shared/ etc.
                        try:
                            wt = getattr(self, "_worktree_dir", None)
                            if wt is not None:
                                from .auto_commit import pull_main_into_worktree
                                _superseded: list = []  # PROPOSAL #26 N2
                                pulled_ok, pulled_info = pull_main_into_worktree(
                                    worktree_dir=wt, main_branch="integration",
                                    superseded_out=_superseded,
                                )
                                if pulled_ok and "_no_conflict" in (pulled_info or ""):
                                    # #623: the pull was skipped, not conflicted — so no
                                    # merge_conflict event and no P0 task. It must still be
                                    # visible: trading a false alarm for silence would hide
                                    # the 187 measured stash failures completely.
                                    self._logger.warning(
                                        f"[{self.agent_id}] step-start pull did not run: "
                                        f"{pulled_info}"
                                    )
                                if pulled_ok and _superseded:
                                    # PROPOSAL #26 N2: the framework superseded the
                                    # lane's edit(s) to framework-owned file(s) while
                                    # resolving the pull conflict. Tell THIS lane (emit
                                    # to self, inbox_only → surfaced at next pulse, NO
                                    # wakeup) so it stops re-editing them → re-conflict.
                                    try:
                                        from ...runtime.framework_notice import emit_framework_decision
                                        emit_framework_decision(
                                            getattr(self._hubs, "eventhub", None),
                                            lane=self.agent_id, kind="conflict_resolved",
                                            paths=_superseded)  # caller defaults to registryhub (==source_hub, gate-admitted)
                                    except Exception:
                                        pass
                                if pulled_ok:
                                    # CLOSURE BY CONSTRUCTION (round 32): a
                                    # successful pull IS the resolution of any
                                    # open step-start merge-conflict task for
                                    # this agent — complete it here instead of
                                    # leaving the lane to cancel it ("lack
                                    # file editing tools" during kickoff).
                                    try:
                                        workhub = getattr(self._hubs, "workhub", None)
                                        if workhub is not None:
                                            for _t in (workhub.stores.tasks.value() or {}).values():
                                                if (isinstance(_t, dict)
                                                        and _t.get("status") in ("pending", "in_progress")
                                                        and (_t.get("metadata") or {}).get("source") == "step_runner_merge_conflict"
                                                        and _t.get("assignee") == self.agent_id):
                                                    if _t.get("status") == "pending":
                                                        workhub.claim_task(_t["id"], self.agent_id)
                                                    workhub.complete_task(
                                                        _t["id"], self.agent_id,
                                                        evidence={"source": "step_runner",
                                                                  "reason": "step-start pull succeeded — conflict gone"})
                                    except Exception:
                                        pass
                                if not pulled_ok:
                                    # Conflict pulling integration → emit issue
                                    # event so orchestrator can route. The
                                    # agent continues; its worktree is back
                                    # at HEAD because the helper aborts the
                                    # merge on conflict.
                                    self._logger.warning(
                                        f"[{self.agent_id}] step-start pull conflict: {pulled_info}"
                                    )
                                    # #667: DEDUPE THE EVENT THE WAY THE TASK BELOW IS ALREADY
                                    # DEDUPED. The remediation task is created once per
                                    # unresolved conflict (`_dup` below); the urgent event was
                                    # republished on EVERY step, carrying identical content the
                                    # orchestrator can do nothing new with.
                                    #
                                    # Measured over the 249 run logs: 4320 conflicts across 31
                                    # runs, median 50 per run, 796 in r124 alone — and the
                                    # orchestrator's bounded dispatch queue is saturated in
                                    # lockstep. Runs WITH pull conflicts show a median of 396
                                    # "dispatch queue FULL" warnings against 202 for runs
                                    # without, r = 0.78 over 128 runs, and the three worst
                                    # conflict runs (796/612/454) are the three worst saturation
                                    # runs (2498/2814/2176). #150 drops the ordinary-dispatch
                                    # copy when that queue fills, so this repeat is buying
                                    # nothing and crowding the channel that carries everything
                                    # else.
                                    #
                                    # The first event still fires, and fires again after each
                                    # resolution (the task auto-completes, so the next conflict
                                    # sees no open task). The task remains the durable record —
                                    # exactly the split the code below already chose.
                                    _open_conflict_task = False
                                    try:
                                        _wh = getattr(self._hubs, "workhub", None)
                                        if _wh is not None and hasattr(_wh, "stores"):
                                            _open_conflict_task = any(
                                                isinstance(_t, dict)
                                                and _t.get("status") in ("pending", "in_progress")
                                                and (_t.get("metadata") or {}).get("source")
                                                == "step_runner_merge_conflict"
                                                and _t.get("assignee") == self.agent_id
                                                for _t in (_wh.stores.tasks.value() or {}).values())
                                    except Exception:
                                        _open_conflict_task = False
                                    try:
                                        if (not _open_conflict_task
                                                and self._hubs is not None
                                                and hasattr(self._hubs, "eventhub")):
                                            self._hubs.eventhub.publish_event(
                                                source_hub=self.agent_id,
                                                event_type="merge_conflict",
                                                payload={
                                                    "agent": self.agent_id,
                                                    "phase": "step_start_pull",
                                                    "source_branch": "integration",
                                                    "target_branch": f"agent/{self.agent_id}",
                                                    "detail": pulled_info,
                                                },
                                                recipients=["orchestrator"],
                                                priority="urgent",
                                            )
                                    except Exception:
                                        pass
                                    # May 29 audit fix (workflow w241o5bwn):
                                    # the previous code only emitted the event
                                    # to recipients=['orchestrator'], but the
                                    # orchestrator had NO handler — events
                                    # went to dead air, lanes re-hit the
                                    # conflict on every step. Mirror the
                                    # codehub._handle_merge_conflict pattern:
                                    # auto-create a WorkHub remediation task
                                    # at the SAME callsite so the conflict
                                    # appears in the work queue, the worktree
                                    # owner can be woken via task_ready, and
                                    # the stall loop is broken.
                                    try:
                                        workhub = getattr(self._hubs, "workhub", None)
                                        if workhub is not None and hasattr(workhub, "create_task"):
                                            _dup = any(
                                                isinstance(_t, dict)
                                                and _t.get("status") in ("pending", "in_progress")
                                                and (_t.get("metadata") or {}).get("source") == "step_runner_merge_conflict"
                                                and _t.get("assignee") == self.agent_id
                                                for _t in (workhub.stores.tasks.value() or {}).values())
                                            if not _dup:
                                                workhub.create_task(
                                                    title=f"Resolve step-start merge conflict ({self.agent_id})",
                                                    description=(
                                                        f"Agent '{self.agent_id}' hit a step-start integration "
                                                        f"pull conflict during step_runner. "
                                                        f"Source: integration → agent/{self.agent_id}. "
                                                        f"Detail: {pulled_info}. "
                                                        f"The agent's worktree was returned to HEAD after the "
                                                        f"merge --abort; the pull retries EVERY step and this "
                                                        f"task AUTO-COMPLETES when one succeeds. If you cannot "
                                                        f"edit files right now (e.g. mid-kickoff), do NOT cancel "
                                                        f"— finish your current work; only act on this if the "
                                                        f"conflict persists across steps (then resolve the "
                                                        f"conflicting files in your worktree)."
                                                    ),
                                                    assignee=self.agent_id,
                                                    agent=self.agent_id,
                                                    source="step_runner_merge_conflict",
                                                    priority="P0",
                                                )
                                    except Exception:
                                        # Workhub failure is non-fatal — the
                                        # event was already emitted, the
                                        # auto_commit.pull_main_into_worktree
                                        # closed-by-construction fix already
                                        # handles the recurring-stash case.
                                        pass
                        except Exception as _pull_err:
                            self._logger.debug(
                                f"[{self.agent_id}] step-start pull skipped: {_pull_err}"
                            )

                        # Drain urgent interrupts and emit any pending interrupt prompt
                        # so the agent still sees them at step start (formerly inbox_status job).
                        while await self._check_and_handle_urgent(from_loop=True):
                            pass
                        if self._interrupt_messages:
                            interrupt_prompt = self._build_interrupt_prompt()
                            if interrupt_prompt:
                                messages.append(Message.user(interrupt_prompt))
                                self._logger.info(
                                    f"[{self.agent_id}] Injected {len(self._interrupt_messages)} interrupt message(s)"
                                )
                            self._interrupt_messages.clear()

                        if not getattr(self, "_first_step_catchup_done", False):
                            self._first_step_catchup_done = True
                            catchup_events = await self._collect_eventhub_catchup_summary()
                            catchup_prompt = self._build_eventhub_catchup_prompt(catchup_events)
                            if catchup_prompt:
                                messages.append(Message.user(catchup_prompt))

                        # Roll forward any pending integrity prompt from the previous
                        # step's hub_commit_gate (single-consumption).
                        pending_integrity = getattr(self, "_pending_integrity_prompt", None)
                        if pending_integrity:
                            messages.append(Message.user(pending_integrity))
                            self._pending_integrity_prompt = None

                        from .hub_pulse import collect_hub_pulse, build_hub_pulse_prompt
                        hubs = getattr(self, "_hubs", None)
                        if hubs is not None:
                            pulse = collect_hub_pulse(hubs, self.agent_id, step_num=step, agent=self)
                            hub_pulse_prompt = build_hub_pulse_prompt(pulse)
                            # Inject ONLY when the pulse CHANGED since the last step. The
                            # pulse is re-collected every step but is identical while a lane
                            # is heads-down building; re-appending the same block each step
                            # bloated context (prior pulse is still in the conversation) and
                            # read as 'forced task enumeration every step' (v10). A changed
                            # pulse (task done, new bug, phase shift) always re-renders.
                            if hub_pulse_prompt and hub_pulse_prompt != getattr(self, "_last_hub_pulse_prompt", None):
                                messages.append(Message.user(hub_pulse_prompt))
                                self._last_hub_pulse_prompt = hub_pulse_prompt
                        _mark_stage(
                            "hub_pulse",
                            executed=True,
                            duration_ms=int((loop_time() - stage_start) * 1000),
                        )
                    except Exception as e:
                        self._logger.warning(f"[{self.agent_id}] hub_pulse stage skipped: {e}")
                        _mark_stage(
                            "hub_pulse",
                            executed=False,
                            duration_ms=int((loop_time() - stage_start) * 1000),
                            skip_reason="exception",
                            metadata={"error": str(e)},
                        )
                else:
                    _mark_stage("hub_pulse", executed=False, skip_reason="disabled_by_config")

                if _stage_enabled("runtime_team_status"):
                    stage_start = loop_time()
                    try:
                        runtime_team_snapshot = self._build_runtime_team_status_snapshot()
                        runtime_team_status_prompt = self._build_runtime_team_status_prompt(runtime_team_snapshot)
                        if runtime_team_status_prompt:
                            messages.append(Message.user(runtime_team_status_prompt))
                        _mark_stage(
                            "runtime_team_status",
                            executed=bool(runtime_team_snapshot),
                            duration_ms=int((loop_time() - stage_start) * 1000),
                            metadata=runtime_team_snapshot or {},
                            skip_reason=None if runtime_team_snapshot else "no_owned_runtimes_or_teams",
                        )
                    except Exception as e:
                        self._logger.warning(f"[{self.agent_id}] runtime_team_status stage skipped: {e}")
                        _mark_stage(
                            "runtime_team_status",
                            executed=False,
                            duration_ms=int((loop_time() - stage_start) * 1000),
                            skip_reason=f"error: {e}",
                        )
                else:
                    _mark_stage("runtime_team_status", executed=False, skip_reason="disabled_by_config")

                done = await self._run_retrieve_context_stage(
                    enabled=_stage_enabled("retrieve_context"),
                    tool_schema_map=tool_schema_map,
                    knowledge_fetch_names=knowledge_fetch_names,
                    knowledge_store_names=knowledge_store_names,
                    hub_sync_tool_names=hub_sync_tool_names,
                    initial_prompt=initial_prompt,
                    hub_pulse_prompt=hub_pulse_prompt,
                    runtime_team_status_prompt=runtime_team_status_prompt,
                    retrieved_action_names=retrieved_action_names,
                    messages=messages,
                    files_created=files_created,
                    files_modified=files_modified,
                    step=step,
                    max_calls_cfg=max_calls_cfg,
                    step_trace=step_trace,
                    step_traces=step_traces,
                    loop_time=loop_time,
                    mark_stage=_mark_stage,
                )
                if done:
                    return done

                done, no_action_tool_steps = await self._run_action_stage(
                    enabled=_stage_enabled("action"),
                    tool_schema_map=tool_schema_map,
                    retrieved_action_names=retrieved_action_names,
                    knowledge_fetch_names=knowledge_fetch_names,
                    knowledge_store_names=knowledge_store_names,
                    hub_sync_tool_names=hub_sync_tool_names,
                    initial_prompt=initial_prompt,
                    max_action_rounds=max_action_rounds,
                    background_mode=background_mode,
                    no_action_tool_steps=no_action_tool_steps,
                    messages=messages,
                    files_created=files_created,
                    files_modified=files_modified,
                    step=step,
                    step_trace=step_trace,
                    step_traces=step_traces,
                    loop_time=loop_time,
                    mark_stage=_mark_stage,
                )
                if done:
                    self._auto_sync_hub_state(
                        step=step,
                        files_created=files_created,
                        files_modified=files_modified,
                        step_trace=step_trace,
                        status="completed",
                    )
                    return done

                _mark_stage(
                    "hub_auto_sync",
                    executed=True,
                    metadata=self._auto_sync_hub_state(
                        step=step,
                        files_created=files_created,
                        files_modified=files_modified,
                        step_trace=step_trace,
                        status="working",
                    ),
                )

                if _stage_enabled("hub_commit_gate"):
                    stage_start = loop_time()
                    self._active_stage = "hub_commit_gate"
                    try:
                        from .commit_gate import (
                            collect_loose_ends,
                            collect_loose_ends_details,
                            build_commit_gate_prompt,
                            DEFAULT_THRESHOLDS,
                        )
                        hubs = getattr(self, "_hubs", None)
                        loose: Dict[str, Any] = {}
                        details: Dict[str, Any] = {}
                        gate_prompt: Optional[str] = None
                        if hubs is not None:
                            thresholds = DEFAULT_THRESHOLDS
                            details = collect_loose_ends_details(
                                hubs, self.agent_id, step, thresholds
                            )
                            loose = collect_loose_ends(
                                hubs, self.agent_id, step, thresholds
                            )
                            # KICKOFF: the dirty_worktree nag advises
                            # ``codehub_commit(...)``, but the kickoff-phase toolset
                            # withholds file/commit tools (see the mid-kickoff editing
                            # guard below) — the agent has no such tool. memory-bank/ +
                            # .agent_home churn during kickoff is committed by the
                            # framework at kickoff finalize and flushed by the heal
                            # pipeline at merge, never by the authoring agent. Surfacing
                            # it sent verifier/frontend chasing a tool they don't have,
                            # yielding turn after turn without recording their kickoff
                            # section → the meeting stalled in phase=initial until the
                            # ~240s stall-escape reconciled it, every run. Drop the
                            # unactionable flag so the gate only surfaces loose ends a
                            # kickoff agent can actually clear. Phase-scoped: byte-
                            # identical for every non-kickoff step.
                            if (getattr(self, "_active_phase", None) == "kickoff"
                                    and loose.get("dirty_worktree")):
                                loose["dirty_worktree"] = False
                                details["dirty_files"] = []
                            gate_prompt = build_commit_gate_prompt(loose, details)
                            if gate_prompt:
                                # Roll forward to next step's hub_pulse rendering —
                                # this is the loose-ends REMINDER (always delivered).
                                self._pending_integrity_prompt = gate_prompt
                                # FIX #30: only PUBLISH the high-priority
                                # integrity_check EVENT when the loose-ends set
                                # actually CHANGES. ``unpushed_commits`` is True on
                                # essentially every impl step (commits land before
                                # the async merge), so the old unconditional publish
                                # fired a high-priority self-message EVERY step —
                                # instagram-core: 272 integrity_check events that
                                # the lane had to "handle," keeping it perpetually
                                # busy so the task_ready that STARTS implementation
                                # was queued 28x and never drained (Starting work=0,
                                # 0 routes). The event has no consumer beyond the
                                # self-interrupt; the prompt above carries the
                                # reminder. Dedup kills the flood, keeps real-change
                                # signalling.
                                _sig = repr(sorted((loose or {}).items())) if isinstance(loose, dict) else repr(loose)
                                if _sig != getattr(self, "_last_integrity_sig", None):
                                    self._last_integrity_sig = _sig
                                    try:
                                        eventhub = getattr(hubs, "eventhub", None)
                                        if eventhub is not None and hasattr(eventhub, "publish_event"):
                                            eventhub.publish_event(
                                                source_hub="system",
                                                event_type="integrity_check",
                                                payload={"loose": loose, "details": details},
                                                recipients=[self.agent_id],
                                                priority="high",
                                            )
                                    except Exception:
                                        pass
                        _mark_stage(
                            "hub_commit_gate",
                            executed=True,
                            duration_ms=int((loop_time() - stage_start) * 1000),
                            metadata={
                                "loose": loose,
                                "has_pending_integrity_prompt": bool(gate_prompt),
                            },
                        )
                    except Exception as e:
                        self._logger.warning(
                            f"[{self.agent_id}] hub_commit_gate stage skipped: {e}"
                        )
                        _mark_stage(
                            "hub_commit_gate",
                            executed=False,
                            duration_ms=int((loop_time() - stage_start) * 1000),
                            skip_reason="exception",
                            metadata={"error": str(e)},
                        )
                else:
                    _mark_stage(
                        "hub_commit_gate",
                        executed=False,
                        skip_reason="disabled_by_config",
                    )
                done = False

                done = await self._run_knowledge_sync_stage(
                    enabled=_stage_enabled("knowledge_sync"),
                    knowledge_store_names=knowledge_store_names,
                    tool_schema_map=tool_schema_map,
                    observer_handler=observer_handler,
                    messages=messages,
                    files_created=files_created,
                    files_modified=files_modified,
                    step=step,
                    max_calls_cfg=max_calls_cfg,
                    step_trace=step_trace,
                    step_traces=step_traces,
                    loop_time=loop_time,
                    mark_stage=_mark_stage,
                )
                if done:
                    self._auto_sync_hub_state(
                        step=step,
                        files_created=files_created,
                        files_modified=files_modified,
                        step_trace=step_trace,
                        status="completed",
                    )
                    return done

                step_trace["mode_after"] = self._execution_mode
                step_traces.append(step_trace)

            if background_mode:
                return {
                    "success": True,
                    "summary": "Shared step complete",
                    "files_created": files_created,
                    "files_modified": files_modified,
                    "step_traces": step_traces,
                    "background_step": True,
                }
            return {
                "success": False,
                "error": f"Max steps ({max_steps})",
                "files_created": files_created,
                "step_traces": step_traces,
            }
        finally:
            self._active_stage = "action"
            self._unwind_agentic_loop(_entry_generation)  # #149 generation guard
            try:
                self._auto_sync_hub_state(
                    step=max(0, len(step_traces) - 1),
                    files_created=files_created,
                    files_modified=files_modified,
                    step_trace=step_traces[-1] if step_traces else {},
                    status="idle",
                )
            except Exception:
                pass
            # Memory-mechanism redesign (2026-06-08): flush any pending MemoryBank
            # auto-sync updates at task end. The periodic 30s/5-item auto-sync may
            # not have fired for a short task (e.g. a kickoff pass), and the forced
            # per-step knowledge_sync stage that used to flush is now removed.
            try:
                mem = getattr(self, "memory", None)
                if mem is not None and hasattr(mem, "sync_to_memory_bank"):
                    mem.sync_to_memory_bank()
            except Exception:
                pass


_IDLE_BACKOFF_AFTER_639 = 6      # streak length at which P(next step does work) collapses to 8%
_IDLE_BACKOFF_MAX_S_639 = 60.0   # ceiling; the measured median step gap is 10.3s


async def _idle_backoff_639(agent: Any) -> float:
    """#639 — pace an agent that has finished N steps in a row with nothing to do.

    #637 measured the cost: **952M of the orchestrator's 2.76B tokens (35%)** go to steps that
    conclude "Idle.", a median of 63 such steps per run. It added the counter only, because the
    cost of pacing "is not measurable from any artifact on disk". That was wrong — the artifacts
    carry timestamps, and the counterfactual is small and one-sided:

        P(next step does real work)     after 1 idle 53% · after 2 40% · after 6+ **8%**
        tokens in the k>=6 idle bucket  **199M**
        transitions a backoff postpones 110 total = **1.8 per run**
        median step gap (one tick)      10.3s      median run 68 min
        => added latency                0.3 min/run = **0.5% of wall clock**

    So: 0.5% of the clock against 199M tokens, and nothing is ever dropped — work that arrives
    during the wait is picked up by the very next step, at most one backoff later.

    Engages only from the 6th consecutive idle finish, doubles per additional idle step, and is
    capped. Any step that does real work resets the streak (see `note_finish_637`), so a busy
    agent never waits. Returns the seconds slept, for the caller's trace; never raises.
    """
    try:
        streak = int(getattr(agent, "_idle_streak_637", 0) or 0)
        if streak < _IDLE_BACKOFF_AFTER_639:
            return 0.0
        delay = min(_IDLE_BACKOFF_MAX_S_639,
                    10.0 * (2 ** min(streak - _IDLE_BACKOFF_AFTER_639, 4)))
        log = getattr(agent, "_logger", None)
        if log is not None:
            log.info("[%s] idle backoff: %d consecutive no-op steps — waiting %.0fs before the "
                     "next model call (#639)", getattr(agent, "agent_id", "?"), streak, delay)
        await asyncio.sleep(delay)
        return delay
    except Exception:
        return 0.0


def _mask_old_observations(messages, model: Optional[str] = None,
                           keep_last: int = 8, head_chars: int = 300):
    """OBSERVATION MASKING (harness-engineering): keep the call record but
    truncate the BODIES of old tool outputs — only the most recent
    ``keep_last`` tool results stay full. Old observations dominate context
    (a single read/grep result can be tens of KB) while the model rarely
    needs more than "what did I call and roughly what came back"; it can
    re-run the tool when it does. Deterministic and idempotent; disabled via
    ENVGEN_OBS_MASK=0.

    MODEL-AWARE (user 2026-06-24): gate behind the SAME working-char budget the
    llm.py layer uses (``resolve_ctx_working_chars(model)``). If the FULL message
    history fits the model's recommended working window, do NOT mask at all — a
    1M-context model keeps its complete tool outputs (no info loss). Trimming
    kicks in only when history would actually overflow. Without a model we cannot
    size the budget, so we fall through to the legacy unconditional masking."""
    import os
    if os.environ.get("ENVGEN_OBS_MASK", "1").lower() in ("0", "false", "no", "off"):
        return messages
    # If the whole history fits the model's working budget, skip masking entirely
    # (mirrors utils.llm._mask_old_observations so both layers agree on the gate).
    if model:
        try:
            from utils.model_limits import resolve_ctx_working_chars
            budget = resolve_ctx_working_chars(model)
        except Exception:
            budget = 0
        if budget:
            total = 0
            for m in messages:
                c = getattr(m, "content", None)
                if isinstance(c, str):
                    total += len(c)
            if total <= budget:
                return messages
    tool_idxs = [i for i, m in enumerate(messages)
                 if getattr(m, "role", None) == "tool"]
    if len(tool_idxs) <= keep_last:
        return messages
    for i in tool_idxs[:-keep_last]:
        m = messages[i]
        content = getattr(m, "content", None)
        if not isinstance(content, str) or len(content) <= head_chars + 120:
            continue
        if content.endswith("[masked]"):
            continue
        m.content = (content[:head_chars]
                     + f"\n…[masked {len(content) - head_chars} chars of old tool"
                     " output — re-run the tool if you need it][masked]")
    return messages
