from __future__ import annotations

import os
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from utils.llm import Message

from ....hub_tool_surface import ALL_HUB_WRITES, hub_of_write_tool
from ..action_stage_policy import (
    resolve_enabled_action_stages as _enabled_action_stages,
    round_plan_fires_every_round as _round_plan_every_round)

# Hub-focus gating is OFF by default (2026-06-09): requiring focus_hub(<hub>) before
# each hub's WRITE tools made the agents thrash focus switches instead of working
# (instagram run: frontend 424 / backend 224 / verifier 152 focus_hub calls — each a
# wasted LLM turn just to unlock the next write). The full write surface is ~44
# tools, which the per-step ranker already bounds; offering writes directly costs
# less than the switching ceremony. Set ENVGEN_HUB_FOCUS=1 to re-enable gating.
_HUB_FOCUS_ENABLED = os.environ.get("ENVGEN_HUB_FOCUS", "0").strip().lower() in (
    "1", "true", "yes", "on",
)


def _apply_hub_focus(self, names: Set[str]) -> Set[str]:
    """Drop hub WRITE tools that don't belong to the agent's current focus hub."""
    if not _HUB_FOCUS_ENABLED or not getattr(self, "_hub_focus_enabled", True):
        return names
    focus = getattr(self, "_focus_hub", None)
    return {n for n in names if n not in ALL_HUB_WRITES or hub_of_write_tool(n) == focus}


class AgentActionStageMixin:
    def _build_endpoint_impl_directive(self) -> Optional[str]:
        """FIX #24 — framework-driven per-endpoint implementation focus.

        The backend LLM implements single endpoints fine but, asked to implement
        all ~25 of a large contract in one wakeup, games the completion gate or
        reads the scaffold and assumes it's done (Instagram runs #6/#8). This
        decomposes the work to ONE endpoint at a time WITHOUT relying on LLM
        memory: every step, deterministically compute which owned business
        endpoints still lack a route handler in source (reusing FIX #23's route
        detection) and inject a directive naming the NEXT one to write. The
        framework tracks progress; the model just executes the next unit.

        Returns a short directive string, or ``None`` when not applicable
        (kickoff/no endpoints/all endpoints already have route code) so it never
        fires outside active endpoint implementation.
        """
        try:
            from ..preconditions import (
                _agent_owning_lane,
                _collect_source_route_tokens,
                _endpoint_resource_token,
            )
        except Exception:
            return None
        hubs = getattr(self, "_hubs", None)
        registryhub = getattr(hubs, "registryhub", None) if hubs is not None else None
        if registryhub is None or not hasattr(registryhub, "get_endpoints"):
            return None
        lane = _agent_owning_lane(self)
        wt = getattr(self, "_worktree_dir", None)
        # FIX #24 diagnostic (one-shot per agent): the directive has never fired
        # live across 3 runs despite working in reproduction — log the gating
        # state ONCE so the next run pins which precondition is None.
        if not getattr(self, "_impl_dir_diag_logged", False):
            self._impl_dir_diag_logged = True
            try:
                _neps = len(registryhub.get_endpoints() or {})
            except Exception:
                _neps = -1
            try:
                self._logger.warning(
                    "FIX#24 diag: agent_id=%r lane=%r worktree=%r exists=%s endpoints=%s",
                    getattr(self, "agent_id", None), lane, str(wt),
                    (wt is not None and os.path.exists(str(wt))), _neps,
                )
            except Exception:
                pass
        if not lane:
            return None
        if not wt:
            return None
        from pathlib import Path as _P
        root = _P(wt)
        if not root.exists():
            return None
        endpoints = registryhub.get_endpoints() or {}
        owned = []
        for ep in endpoints.values():
            if not isinstance(ep, dict):
                continue
            provider = ep.get("provider")
            if provider and provider != lane:
                continue
            if (ep.get("kind") or "").lower() in (
                    "infra", "auth", "spine", "control", "system"):
                continue
            owned.append(ep)
        if not owned:
            return None
        route_tokens = _collect_source_route_tokens(root)
        missing = []
        for ep in owned:
            token = _endpoint_resource_token(ep.get("path") or "")
            if token and token not in route_tokens:
                missing.append(
                    f"{(ep.get('method') or '?').upper()} {ep.get('path')}")
        if not missing:
            return None
        missing.sort()
        done = len(owned) - len(missing)
        nxt = missing[:3]
        return (
            f"\n[IMPLEMENTATION PROGRESS — framework-tracked, do not ignore] "
            f"{done}/{len(owned)} of your business endpoints have a route "
            f"handler in your source code. {len(missing)} still have NO route "
            f"code — you CANNOT finish until they do (registering them "
            f"'implemented' without writing the handler is rejected). The "
            f"framework scaffold (main.py/models.py/database.py/auth) is ALREADY "
            f"provided — do NOT re-read it and assume done.\n"
            f"NEXT to implement: {nxt}\n"
            f"ACTION THIS STEP: take the FIRST one and WRITE its FastAPI route "
            f"handler with real DB logic via the write/edit tool (e.g. add a "
            f"router in app/backend/ with @router.<method>(\"<path>\") + the "
            f"query + include_router(...) in main.py), THEN "
            f"registryhub_register_endpoint(...status='implemented'). Implement ONE "
            f"endpoint now; the next will be shown on the following step."
        )

    def _in_endpoint_impl_mode(self) -> bool:
        """True when this lane owns at least one endpoint NOT yet at a terminal
        status (``implemented``/``deprecated``) — i.e. it should be concentrating
        on writing code. Drives FIX #22's per-round coordination-stage trimming.

        Cheap + side-effect free: reads ``registryhub.get_endpoints()`` and filters by
        ``provider == owning-lane`` (same predicate as the
        ``kickoff_endpoints_implemented`` finish-gate). Returns ``False`` on any
        error, when registryhub is empty (kickoff phase, before finalize), or when the
        lane owns no pending endpoints — so behavior is UNCHANGED outside active
        endpoint implementation. Computed once per step by the caller.
        """
        try:
            from ..preconditions import (
                _agent_owning_lane,
                _FINISH_TERMINAL_STATUSES,
            )
        except Exception:
            return False
        hubs = getattr(self, "_hubs", None)
        registryhub = getattr(hubs, "registryhub", None) if hubs is not None else None
        if registryhub is None or not hasattr(registryhub, "get_endpoints"):
            return False
        lane = _agent_owning_lane(self)
        if not lane:
            return False
        try:
            endpoints = registryhub.get_endpoints() or {}
        except Exception:
            return False
        for ep in endpoints.values():
            if not isinstance(ep, dict):
                continue
            provider = ep.get("provider")
            if provider and provider != lane:
                continue
            if ep.get("status") not in _FINISH_TERMINAL_STATUSES:
                return True
        return False

    async def _run_action_round_plan(
        self,
        *,
        tool_schema_map: Dict[str, Dict[str, Any]],
        messages: List[Message],
        files_created: List[str],
        files_modified: List[str],
        step: int,
        action_round: int,
        max_action_rounds: int,
        step_trace: Dict[str, Any],
        step_traces: List[Dict[str, Any]],
        loop_time: Callable[[], float],
    ) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
        round_plan_result: Dict[str, Any] = {
            "executed": False,
        }

        round_plan_start = loop_time()
        try:
            self._stamp_step_activity()  # #149: LLM progress = liveness
            round_plan_resp = await self._call_stage_llm(
                messages,
                "planning",
                (
                    f"Before action round {action_round + 1}/{max_action_rounds}, "
                    "plan the immediate next moves for this round. "
                    "State in plain text: objective, next actions, stop condition for this round, "
                    "and what would justify another action round."
                ),
                [],
            )
            if getattr(round_plan_resp, "content", None):
                messages.append(Message.assistant(round_plan_resp.content))
            round_plan_result = {
                "executed": True,
                "duration_ms": int((loop_time() - round_plan_start) * 1000),
                "tool_calls": len(getattr(round_plan_resp, "tool_calls", []) or []),
            }
        except Exception as e:
            round_plan_result = {
                "executed": False,
                "duration_ms": int((loop_time() - round_plan_start) * 1000),
                "skip_reason": f"error: {e}",
            }
            self._logger.warning(
                f"[{self.agent_id}] action round planning skipped ({action_round + 1}): {e}"
            )
        return None, round_plan_result

    async def _run_action_internal_stage(
        self,
        *,
        action_stage_name: str,
        action_round: int,
        max_action_rounds: int,
        all_names: Set[str],
        tool_schema_map: Dict[str, Dict[str, Any]],
        retrieved_action_names: Dict[str, Set[str]],
        knowledge_fetch_names: Set[str],
        knowledge_store_names: Set[str],
        hub_sync_tool_names: Set[str],
        initial_prompt: str,
        messages: List[Message],
        files_created: List[str],
        files_modified: List[str],
        step: int,
        step_trace: Dict[str, Any],
        step_traces: List[Dict[str, Any]],
        action_round_results: List[Dict[str, Any]],
        round_internal_stage_results: List[Dict[str, Any]],
        loop_time: Callable[[], float],
        mark_stage: Callable[..., None],
    ) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any], bool, bool]:
        stage_start = loop_time()
        if action_stage_name == "delegate_team":
            candidate_names = (set(self.TEAM_TOOL_NAMES) | set(self.TEAM_MODE_SUPPORT_TOOLS)) & all_names
        elif self._execution_mode == "team":
            candidate_names = (set(self.TEAM_TOOL_NAMES) | set(self.TEAM_MODE_SUPPORT_TOOLS)) & all_names
        else:
            candidate_names = all_names - set(self.TEAM_TOOL_NAMES)
        # Force-offered delivery-gate tools must survive the knowledge-fetch
        # subtraction. ``get_skill`` is BOTH a knowledge-fetch tool AND force-offered
        # in the deliver/action stages (deliver_project is gated on
        # release_readiness_consulted, which the agent can only clear by calling
        # get_skill(release-readiness)). Subtracting it here silently nullified the
        # force-offer — tool_surface filters always_include ∩ candidate_names, so a
        # tool removed from the pool can't be re-admitted — and the orchestrator
        # could never consult the skill → deliver_project DEADLOCK (smoke run #6:
        # reached delivery, then "I do not have the get_skill tool" ×N, get_skill
        # dispatched 0×). Exempt this stage's force-offer set from the knowledge
        # subtraction ONLY (store/hub-sync subtractions are untouched).
        _force_offer = set(self.ACTION_STAGE_ALWAYS_INCLUDE.get(action_stage_name, set()))
        if (action_stage_name in set(getattr(self, "ACTION_INTERNAL_STAGES", ()) or ())
                and action_stage_name != "action"):
            _force_offer |= set(self.ACTION_STAGE_ALWAYS_INCLUDE.get("action", set()))
        candidate_names -= (
            (knowledge_fetch_names - _force_offer)
            | knowledge_store_names | hub_sync_tool_names)
        candidate_names.discard("think")
        # Hub-focus: only the focus hub's write tools are eligible this stage.
        candidate_names = _apply_hub_focus(self, candidate_names)

        stage_limit = 8 if action_stage_name in {"communicate", "deliver"} else 10
        focus_hint = ""
        if _HUB_FOCUS_ENABLED and getattr(self, "_hub_focus_enabled", True):
            _focus = getattr(self, "_focus_hub", None)
            if _focus:
                focus_hint = (
                    f" You are focused on the {_focus} hub: its action tools are available now. "
                    "Call focus_hub(<hub>) to act on a different hub."
                )
            else:
                focus_hint = (
                    " You are not focused on any hub yet — hub READ tools are available, but to WRITE "
                    "to a hub (create a task, register an endpoint, open a PR, etc.) first call "
                    "focus_hub(<hub>)."
                )
        stage_prompt = (
            f"Action round {action_round + 1}/{max_action_rounds}, mode {action_stage_name} ({self._execution_mode}): "
            "use the smallest relevant tool subset for this step. "
            "If this step still needs another action move after this round, include `ACTION_STATUS: continue`. "
            "If you have completed the current plan move for this step, include `ACTION_STATUS: stop`. "
            "Call finish() if the task is complete."
            + focus_hint
        )
        selected_names = set(retrieved_action_names.get(action_stage_name) or set())
        if not selected_names:
            selected_names = self._stage_tool_names(
                tool_schema_map,
                action_stage_name,
                candidate_names,
                stage_prompt + "\n" + initial_prompt,
                limit=stage_limit,
            )
        # Re-apply hub-focus at the final chokepoint: the retrieve_context stage may
        # have pre-selected tools (retrieved_action_names) that bypass the candidate filter.
        selected_names = _apply_hub_focus(self, selected_names)
        action_tools = self._filtered_tool_schemas(tool_schema_map, selected_names)
        if not action_tools:
            return None, {"name": action_stage_name, "executed": False, "skip_reason": "no_stage_tools_available"}, False, False

        try:
            action_resp = await self._call_stage_llm(messages, action_stage_name, stage_prompt, action_tools)
            self._stamp_step_activity()  # #149: LLM progress = liveness
        except Exception as e:
            self._logger.error(f"LLM {action_stage_name} call failed: {e}")
            return None, {"name": action_stage_name, "executed": False, "skip_reason": f"llm_error: {e}"}, False, False

        if action_resp is None:
            return None, {"name": action_stage_name, "executed": False, "skip_reason": "llm_no_response"}, False, False

        action_content = (getattr(action_resp, "content", "") or "")
        action_tool_calls = getattr(action_resp, "tool_calls", []) or []
        action_status = self._parse_action_status(action_content)
        # Log the model's REASONING when the visible content is empty. On gemini
        # tool-call turns .content is "" and the text lives in .reasoning (the
        # [LLM thinking] stream) — logging only content made every such turn show up
        # in the monitor as `response -> {tokens: N}` with NO visible reasoning. Prefer
        # content, fall back to the thinking, so the action log shows WHAT the agent thought.
        _logged_text = action_content or (getattr(action_resp, "reasoning", "") or "")
        self.log_response(_logged_text, tokens=getattr(action_resp, "usage", {}).get("total_tokens", 0))

        if not action_tool_calls:
            if action_content:
                messages.append(Message.assistant(action_content))
            return None, {
                "name": action_stage_name,
                "executed": False,
                "skip_reason": "no_tool_calls",
                "visible_tools": sorted(selected_names),
                "action_status": action_status or "implicit_stop",
            }, False, action_status == "stop"

        done = await self._process_tool_calls(
            messages,
            files_created,
            files_modified,
            stage_name=action_stage_name,
            step_idx=step,
            tool_calls=action_tool_calls,
        )
        if done:
            mark_stage(
                "action",
                executed=True,
                duration_ms=int((loop_time() - stage_start) * 1000),
                metadata={
                    "rounds": action_round_results
                    + [{
                        "round": action_round + 1,
                        "internal_stages": round_internal_stage_results
                        + [{
                            "name": action_stage_name,
                            "executed": True,
                            "tool_calls": len(action_tool_calls),
                            "visible_tools": sorted(selected_names),
                            "action_status": action_status,
                        }],
                    }]
                },
            )
            step_trace["mode_after"] = self._execution_mode
            step_traces.append(step_trace)
            done["step_traces"] = step_traces
            return done, {}, True, True

        if action_content:
            messages.append(Message.assistant(action_content))
        return None, {
            "name": action_stage_name,
            "executed": True,
            "tool_calls": len(action_tool_calls),
            "visible_tools": sorted(selected_names),
            "duration_ms": int((loop_time() - stage_start) * 1000),
            "action_status": action_status or "continue",
        }, True, action_status == "stop"

    async def _run_action_stage(
        self,
        *,
        enabled: bool,
        tool_schema_map: Dict[str, Dict[str, Any]],
        retrieved_action_names: Dict[str, Set[str]],
        knowledge_fetch_names: Set[str],
        knowledge_store_names: Set[str],
        hub_sync_tool_names: Set[str],
        initial_prompt: str,
        max_action_rounds: int,
        background_mode: bool,
        no_action_tool_steps: int,
        messages: List[Message],
        files_created: List[str],
        files_modified: List[str],
        step: int,
        step_trace: Dict[str, Any],
        step_traces: List[Dict[str, Any]],
        loop_time: Callable[[], float],
        mark_stage: Callable[..., None],
    ) -> Tuple[Optional[Dict[str, Any]], int]:
        if not enabled:
            mark_stage("action", executed=False, skip_reason="disabled_by_config")
            return None, no_action_tool_steps

        all_names = set(tool_schema_map.keys())
        any_action_calls = False
        action_round_results: List[Dict[str, Any]] = []
        stop_action_step = False

        # FIX #22 (Instagram impl-throughput): computed ONCE per step. When the
        # lane is mid endpoint-implementation, later action rounds skip the
        # coordination internal stages (communicate, deliver) and concentrate on
        # edit_code — see _in_endpoint_impl_mode + the per-stage skip below.
        lean_impl = (
            getattr(self, "_lean_impl_action_rounds", True)
            and self._in_endpoint_impl_mode()
        )

        for action_round in range(max_action_rounds):
            # #149: round-top liveness stamp — a healthy step spends 600-800s
            # across its rounds; without per-round stamps the #147 watchdog
            # false-declared 4 such lanes WEDGED in run-72/73.
            self._stamp_step_activity()
            round_used_tools = False
            round_internal_stage_results: List[Dict[str, Any]] = []
            # Cost: the round-plan call passes tools=[] (it cannot act) and
            # appends its own text to `messages`, so every round after the
            # first re-derives a plan already in the model's context. Plan on
            # round 0; later rounds inherit. `action_round_plan: all` restores
            # the per-round plan for a profile that wants it.
            if action_round == 0 or _round_plan_every_round(self):
                done, round_plan_result = await self._run_action_round_plan(
                    tool_schema_map=tool_schema_map,
                    messages=messages,
                    files_created=files_created,
                    files_modified=files_modified,
                    step=step,
                    action_round=action_round,
                    max_action_rounds=max_action_rounds,
                    step_trace=step_trace,
                    step_traces=step_traces,
                    loop_time=loop_time,
                )
                if done:
                    return done, no_action_tool_steps
            else:
                round_plan_result = {
                    "executed": False,
                    "skip_reason": "round_plan_first_round_only",
                }

            # Orch-F1: a role that never acts in a stage must not pay an LLM
            # call to say so. `_enabled_action_stages` narrows the walk to the
            # profile's `execution_pipeline.action_stages` (all stages when
            # unset), so a disabled stage costs zero tokens rather than the
            # "no code to edit" filler that was 14.3% of the r93 orchestrator's
            # calls. Category re-homing is validated at construction, so a
            # skipped stage never strands a granted tool.
            for action_stage_name in _enabled_action_stages(self):
                if action_stage_name == "delegate_team" and self._execution_mode != "team":
                    continue
                if action_stage_name == "deliver" and "deliver_project" not in all_names and "finish" not in all_names:
                    continue
                # FIX #22: during endpoint implementation, on rounds AFTER the
                # first, skip the coordination stages so the round is spent in
                # edit_code (the only stage that writes code) rather than
                # re-checking the inbox or attempting a finish the
                # kickoff_endpoints_implemented gate blocks anyway. Round 0
                # always runs every stage (handles inbox / lets a finished lane
                # deliver); a skipped communicate is caught by the next step's
                # round 0, so message handling is at most one step delayed.
                if lean_impl and action_round > 0 and action_stage_name in ("communicate", "deliver"):
                    continue

                done, stage_result, stage_used_tools, should_stop = await self._run_action_internal_stage(
                    action_stage_name=action_stage_name,
                    action_round=action_round,
                    max_action_rounds=max_action_rounds,
                    all_names=all_names,
                    tool_schema_map=tool_schema_map,
                    retrieved_action_names=retrieved_action_names,
                    knowledge_fetch_names=knowledge_fetch_names,
                    knowledge_store_names=knowledge_store_names,
                    hub_sync_tool_names=hub_sync_tool_names,
                    initial_prompt=initial_prompt,
                    messages=messages,
                    files_created=files_created,
                    files_modified=files_modified,
                    step=step,
                    step_trace=step_trace,
                    step_traces=step_traces,
                    action_round_results=action_round_results,
                    round_internal_stage_results=round_internal_stage_results,
                    loop_time=loop_time,
                    mark_stage=mark_stage,
                )
                if done:
                    return done, no_action_tool_steps
                if stage_result:
                    round_internal_stage_results.append(stage_result)
                if stage_used_tools:
                    any_action_calls = True
                    round_used_tools = True
                if should_stop:
                    stop_action_step = True
                    break

            action_round_results.append(
                {
                    "round": action_round + 1,
                    "used_tools": round_used_tools,
                    "round_planning": round_plan_result,
                    "internal_stages": round_internal_stage_results,
                }
            )

            # Chat responsiveness: a real human typing in the chat panel goes
            # into our urgent priority queue (event_type="human_message",
            # priority="human_user"). The step boundary already drains it via
            # hub_pulse, but if the user sends while we're mid-step they would
            # have to wait for the *whole* step to finish. Drain between action
            # rounds so the worst-case reply latency is one round instead of
            # one full step. The handler is short (a single LLM call that
            # publishes an agent_reply); ordinary work resumes on the next
            # round. Cheap when nothing's urgent.
            try:
                while await self._check_and_handle_urgent(from_loop=True):
                    pass
            except Exception as _urgent_err:
                self._logger.debug(
                    f"[{self.agent_id}] urgent drain between action rounds failed: {_urgent_err}"
                )

            if stop_action_step or not round_used_tools:
                break

        if not any_action_calls:
            no_action_tool_steps += 1
            if not background_mode and no_action_tool_steps >= 12:
                step_trace["mode_after"] = self._execution_mode
                step_traces.append(step_trace)
                if getattr(self, "_is_resident_lane", False):
                    return {
                        "success": True,
                        "summary": "Resident lane idle; awaiting new messages, hub changes, or verification results.",
                        "files_created": files_created,
                        "files_modified": files_modified,
                        "step_traces": step_traces,
                        "resident_idle": True,
                    }, no_action_tool_steps
                return {
                    "success": False,
                    "error": "LLM did not use narrowed action tools; aborted to avoid stuck loop",
                    "files_created": files_created,
                    "files_modified": files_modified,
                    "step_traces": step_traces,
                }, no_action_tool_steps
        else:
            no_action_tool_steps = 0

        mark_stage(
            "action",
            executed=any_action_calls,
            metadata={"rounds": action_round_results, "max_action_rounds": max_action_rounds},
        )
        return None, no_action_tool_steps
