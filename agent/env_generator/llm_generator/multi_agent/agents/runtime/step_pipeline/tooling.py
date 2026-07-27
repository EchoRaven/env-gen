from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Set

from utils.llm import Message

from ....tool_surface import rank_tool_names


def _auto_stage(agent, file_path: str, *, action: str) -> None:
    """Best-effort auto-stage of an agent write in its worktree.

    Failures are logged at WARNING — staging is bookkeeping, not
    load-bearing. The next ``codehub_commit`` call will pick the file
    up via ``git add -A`` if explicit staging fails.

    ``action="add"`` for write/edit/apply_patch (file exists post-op);
    ``action="delete"`` for delete_file (file may no longer exist).
    """
    wt = getattr(agent, "_worktree_dir", None)
    if wt is None:
        return
    workspace = getattr(agent, "workspace", None)
    try:
        resolved = workspace.resolve(file_path) if workspace else None
    except Exception:
        resolved = None
    if resolved is None:
        return
    from ..auto_commit import stage_file, stage_deletion
    fn = stage_deletion if action == "delete" else stage_file
    ok, info = fn(wt, resolved)
    if not ok:
        try:
            agent._logger.warning(
                f"[{agent.agent_id}] auto-stage ({action}) skipped for "
                f"{file_path}: {info}"
            )
        except Exception:
            pass


class AgentStepToolingMixin:
    def _scrub_workspace_paths(self, text: Any) -> Any:
        """Relativize absolute env/worktree roots in agent-facing tool output
        (PATH FIREWALL — see helpers.scrub_workspace_paths). Gathers this lane's
        known absolute roots (its worktree, the env base_dir, the workspace
        root) so the model only ever sees workspace-relative paths."""
        from .helpers import scrub_workspace_paths
        roots = []
        for attr in ("_worktree_dir",):
            v = getattr(self, attr, None)
            if v:
                roots.append(str(v))
        hubs = getattr(self, "_hubs", None)
        base = getattr(hubs, "base_dir", None) if hubs is not None else None
        if base:
            roots.append(str(base))
        ws = getattr(self, "workspace", None)
        ws_root = getattr(ws, "root", None) if ws is not None else None
        if ws_root:
            roots.append(str(ws_root))
        if not roots:
            return text
        return scrub_workspace_paths(text, roots)

    def _build_tool_schema_map(self) -> Dict[str, Dict[str, Any]]:
        tool_schemas_all = self.get_tools_for_llm()
        tool_schema_map: Dict[str, Dict[str, Any]] = {}
        try:
            for schema in tool_schemas_all:
                fn = schema.get("function", {})
                name = fn.get("name")
                if name:
                    tool_schema_map[name] = schema
        except Exception as e:
            self._logger.warning(f"[{self.agent_id}] Tool schema build failed: {e}")
            return {}
        return tool_schema_map

    def _log_registered_tools(self, tool_schema_map: Dict[str, Dict[str, Any]]) -> None:
        if not tool_schema_map:
            self._logger.warning(
                f"[{self.agent_id}] No tools registered for LLM. "
                f"allowed_tool_categories={getattr(self, 'allowed_tool_categories', [])}"
            )
            return
        preview = list(tool_schema_map.keys())[:15]
        self._logger.info(
            f"[{self.agent_id}] Tools registered for LLM: {len(tool_schema_map)} -> {', '.join(preview)}"
        )

    @staticmethod
    def _filtered_tool_schemas(
        tool_schema_map: Dict[str, Dict[str, Any]],
        allowed_names: Set[str],
    ) -> List[Dict[str, Any]]:
        if not allowed_names:
            return []
        return [tool_schema_map[name] for name in tool_schema_map.keys() if name in allowed_names]

    def _stage_tool_names(
        self,
        tool_schema_map: Dict[str, Dict[str, Any]],
        stage_name: str,
        candidate_names: Set[str],
        prompt_text: str,
        *,
        limit: int,
    ) -> Set[str]:
        if not candidate_names:
            return set()
        preferred_categories = set(self.ACTION_STAGE_CATEGORY_HINTS.get(stage_name, set()))
        if stage_name == "delegate_team":
            candidate_names = candidate_names & (set(self.TEAM_TOOL_NAMES) | set(self.TEAM_MODE_SUPPORT_TOOLS))
        # Per-stage allowlist from agent config (PR3.1). Restricts the
        # candidate pool to a per-stage subset — replaces "DO NOT call X
        # during stage Y" prompt rules with engine-side filtering.
        # Stages without an entry fall back to the default ranker.
        # Loop B iter-2 ⑨: when an allowlist is set, ``always_include``
        # must be intersected with it too — else the ranker re-unions
        # ALWAYS_INCLUDE tools AFTER the filter, defeating the gate
        # ("soft allowlist"). With the intersection, the allowlist is
        # authoritative: a profile that omits ``finish`` from its
        # allowlist truly hides ``finish``, and the LLM cannot bypass
        # the gate via the engine floor.
        # Loop B iter-2 ⑧ + PR3.1.2: kickoff and implementation share
        # the same stage names (action/etc.), so a composite
        # ``"phase:stage"`` key (e.g. ``"kickoff:action"``) takes
        # precedence over the bare stage when ``_active_phase`` is set.
        # Lookup falls back to the bare stage key when no phase-keyed
        # entry exists, so existing yaml stays valid.
        allowlist = getattr(self, "_stage_tool_allowlist", {}) or {}
        phase = getattr(self, "_active_phase", None)
        action_inner = set(getattr(self, "ACTION_INTERNAL_STAGES", ()) or ())
        # Lookup chain (PR3.1.2 + Smoke #30 fallback):
        #   1. ``"<phase>:<stage>"`` — composite phase-keyed
        #   2. ``"<stage>"``          — bare stage name
        #   3. ``"<phase>:action"`` / ``"action"`` when the current
        #      stage is an action internal sub-stage (communicate /
        #      edit_code / run_checks / delegate_team / deliver). Mirrors
        #      ``_enforce_stage_preconditions`` in runtime/tooling.py so
        #      yaml authors can key once on the outer ``action`` and
        #      cover all five sub-stages.
        # Empty list at any level means "no restriction at this level"
        # → falls through (consistent with
        # ``empty_allowlist_for_stage_falls_through``).
        stage_allow = None
        if phase:
            stage_allow = allowlist.get(f"{phase}:{stage_name}") or None
        if not stage_allow:
            stage_allow = allowlist.get(stage_name) or None
        if not stage_allow and stage_name in action_inner:
            if phase:
                stage_allow = allowlist.get(f"{phase}:action") or None
            if not stage_allow:
                stage_allow = allowlist.get("action") or None
        if stage_allow:
            stage_allow_set = set(stage_allow)
            candidate_names = candidate_names & stage_allow_set
            if not candidate_names:
                return set()
        always_include = set(self.ACTION_STAGE_ALWAYS_INCLUDE.get(stage_name, set()))
        # The orchestrator runs the action-internal sub-stages (communicate/edit_code/
        # run_checks/delegate_team/deliver) as SEPARATE LLM calls, and this lookup keys
        # on the BARE sub-stage name. The deliver-gate tools force-offered under the
        # "action" key (get_skill / submit_retro / deliver_project / deliverability_check)
        # therefore never reached the run_checks/communicate/edit_code menus → the model
        # emitted deliver_project from run_checks, hit the release-readiness/retro gate,
        # then could not call get_skill/submit_retro ("not available in my current scope")
        # → delivery DEADLOCK (run bsb900gpt: get_skill dispatched 0×, run killed). Mirror
        # the stage_allow action-inner → "action" fallback above: union the "action"
        # force-offer into every action-inner sub-stage. The _KICKOFF_DEFER_TOOLS gate
        # below still strips delivery tools until the run is validation-ready.
        if stage_name in action_inner and stage_name != "action":
            always_include |= set(self.ACTION_STAGE_ALWAYS_INCLUDE.get("action", set()))
        if stage_allow:
            always_include = always_include & stage_allow_set
        # PROPOSAL #28 F2 + PRE-LAUNCH AUDIT F1: do NOT force-offer the validation/
        # delivery tools until the run is VALIDATION-ready. Originally gated on the
        # kickoff signal (defer only during kickoff), but the orchestrator then polled
        # run_validation/deliverability_check all through IMPLEMENTATION too (nothing
        # built → empty/partial; run #28/#31). Gate on the STICKY validation-ready signal
        # so these stay deferred through kickoff AND implementation and only surface once
        # every business endpoint is implemented — when there's actually something to
        # validate/deliver (matches the delivery_phase_reached precondition). This only
        # removes the force-PRIORITY; an allowlisted tool can still be ranked if a lane
        # genuinely needs it. Sticky → no re-defer if a late endpoint regresses (F5).
        defer = getattr(self, "_KICKOFF_DEFER_TOOLS", None)
        if defer and always_include:
            try:
                from ..preconditions import (
                    kickoff_finalized_signal, validation_ready_signal)
                hubs = getattr(self, "_hubs", None)
                # The ORCHESTRATOR polls delivery/validation tools all through
                # IMPLEMENTATION (run #28/#31), so defer them until VALIDATION-ready for
                # it. EVERY OTHER lane keeps the kickoff-only defer — critically the
                # VERIFIER, whose JOB at validation IS run_validation /
                # register_verification_chain (in _VALIDATION_FLOW): a validation-ready
                # defer there would STRIP those tools if it triggers before
                # all_business_endpoints_implemented (e.g. a non-backend-owned business
                # endpoint), breaking validation. So validation-ready scope = orchestrator
                # only; kickoff scope = everyone else (a no-op post-kickoff, preserving
                # the verifier's force-offer). The orchestrator's hard block stays the
                # delivery_phase_reached precondition.
                if getattr(self, "agent_id", None) == "orchestrator":
                    ready = validation_ready_signal(hubs, self)
                else:
                    ready = kickoff_finalized_signal(hubs, self)
                if not ready:
                    always_include = set(always_include) - defer
            except Exception:
                pass
        # FIX #29: when a per-stage allowlist is configured, it already IS the
        # curated set of tools this workflow stage needs — so OFFER ALL OF THEM
        # rather than ranking down to the global top-k (~10). The 10-cap was
        # designed when candidates = the full ~154-tool pool; once the allowlist
        # narrows to ~37 (e.g. backend implementation:action), capping to 10 hid
        # ~27 tools the lane legitimately needs that step, so lanes mis-reported
        # "I only have generic tools / tool unavailable" and interrogated the
        # orchestrator (instagram-core frontend/debugger ping-pong → freeze).
        # The reactive _FLOW / ALWAYS_INCLUDE force-sets existed precisely to
        # patch this crowd-out one tool at a time; offering the whole allowlist
        # makes them largely redundant. Bounded at 48 so context stays sane;
        # non-allowlisted stages keep the global top-k (their candidate pool is
        # the unfiltered surface, where trimming IS appropriate).
        effective_limit = limit
        if stage_allow:
            effective_limit = max(limit, min(len(candidate_names), 48))
        ranked = rank_tool_names(
            tool_instances=getattr(self, "_tool_instances", {}),
            candidate_names=candidate_names,
            query_text=prompt_text,
            preferred_categories=preferred_categories,
            limit=effective_limit,
            always_include=always_include,
        )
        return set(ranked)

    @staticmethod
    def _normalize_tool_call(tool_call: Any, step_idx: int) -> tuple[Optional[str], Dict[str, Any], str]:
        try:
            fn = getattr(tool_call, "function", None)
            if fn is None and isinstance(tool_call, dict):
                fn = tool_call.get("function", {})
            tool_name = getattr(fn, "name", None) or (fn.get("name") if isinstance(fn, dict) else None)
            args_raw = getattr(fn, "arguments", None) or (fn.get("arguments", "{}") if isinstance(fn, dict) else "{}")
            tool_call_id = getattr(tool_call, "id", None) or (
                tool_call.get("id") if isinstance(tool_call, dict) else None
            ) or f"call_{step_idx}"
        except Exception:
            return None, {}, f"call_{step_idx}"

        try:
            tool_args = json.loads(args_raw) if isinstance(args_raw, str) else (args_raw or {})
            if not isinstance(tool_args, dict):
                tool_args = {}
        except Exception:
            tool_args = {}
        return tool_name, tool_args, tool_call_id

    async def _call_stage_llm(
        self,
        messages: List[Message],
        stage_name: str,
        prompt: str,
        stage_tools: List[Dict[str, Any]],
    ) -> Any:
        self._active_stage = stage_name
        messages.append(Message.user(prompt))
        # NOTE: the previous in-place condense guard was REMOVED here. It fired on
        # EVERY staged call — i.e. MID-ACTION, while a step was part-way through
        # writing an endpoint (read file → plan → write across <=15 rounds). The
        # condenser summarized the backend's working state out from under it, so it
        # lost track and looped on memory reads instead of finishing the code (the
        # ~2-endpoint stall). Context is now bounded by the step loop's
        # every-step-boundary condensation (between endpoints, where it's safe),
        # which keeps the list ~28-100 — well under the ~770 saturation — without
        # ever interrupting an in-progress implementation.
        return await self.call_with_retry(self.llm.chat_messages, messages, tools=stage_tools)

    async def _maybe_condense_messages_in_place(self, messages: List[Message]) -> None:
        """Condense ``messages`` in-place if it exceeds the condenser cap.

        Bounds every LLM-call path regardless of which loop produced the
        growth. Mutates the passed list (rather than returning a new one) so
        callers holding the same reference — the step runner's per-step
        ``messages`` and every nested action round — all observe the
        condensed history. Safe-cutoff logic in the condenser keeps
        assistant(tool_calls)+tool pairs intact. No-op (and never raises)
        when memory/condenser is absent (minimal test objects).
        """
        memory = getattr(self, "memory", None)
        if memory is None:
            return
        try:
            if not memory.should_condense_messages(messages):
                return
            before = len(messages)
            condensed = await memory.condense_messages(messages)
            if condensed is not None and condensed is not messages:
                # Replace contents in place to preserve the shared reference.
                messages[:] = condensed
            if len(messages) < before:
                self._logger.info(
                    f"[{self.agent_id}] [{self._active_stage}] condensed messages "
                    f"in-place: {before} -> {len(messages)}"
                )
        except Exception as exc:
            # Condensation is best-effort; never block the LLM call on it.
            try:
                self._logger.debug(
                    f"[{self.agent_id}] in-place condensation skipped: {exc}"
                )
            except Exception:
                pass

    async def _process_tool_calls(
        self,
        messages: List[Message],
        files_created: List[str],
        files_modified: List[str],
        *,
        stage_name: str,
        step_idx: int,
        tool_calls: List[Any],
        max_calls: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        if not tool_calls:
            return None

        self._active_stage = stage_name
        calls = tool_calls[: max_calls or len(tool_calls)]

        summary: List[str] = []
        for tc in calls:
            tool_name, tool_args, _ = self._normalize_tool_call(tc, step_idx)
            if not tool_name:
                summary.append("tool_call_parse_error")
            else:
                summary.append(f"{tool_name}({','.join(list(tool_args.keys())[:4])})")
        self._logger.info(f"[{self.agent_id}] [{stage_name}] Tool calls: {', '.join(summary)}")

        for tool_call in calls:
            tool_name, tool_args, tool_call_id = self._normalize_tool_call(tool_call, step_idx)
            if not tool_name:
                continue

            self._log_tool_details(tool_name, tool_args)
            self.record_action(f"{tool_name}({list(tool_args.keys())})")

            if tool_name == "finish":
                finish_policy_outcome = await self._apply_finish_policies(
                    tool_name=tool_name,
                    tool_args=tool_args,
                    tool_call=tool_call,
                    tool_call_id=tool_call_id,
                    messages=messages,
                    files_created=files_created,
                    files_modified=files_modified,
                )
                if finish_policy_outcome:
                    if finish_policy_outcome.get("action") == "continue":
                        continue
                    if finish_policy_outcome.get("action") == "finish":
                        return finish_policy_outcome.get("result")

                result = await self._execute_tool(tool_name, tool_args)
                if not result.success:
                    messages.append(Message.assistant(tool_calls=[tool_call]))
                    messages.append(Message.tool(f"Error: {result.error_message}", tool_call_id))
                    continue
                if hasattr(self, "clear_finish_step_reminders"):
                    self.clear_finish_step_reminders()
                await self._process_pending_notifications(flush_bus=True, flush_knowledge=True)
                return {
                    "success": True,
                    "summary": tool_args.get("message", "Done"),
                    "files_created": files_created,
                    "files_modified": files_modified,
                    "finish": tool_args,
                }

            if tool_name in ("deliver_project", "report_completion"):
                # PR 2.5-fix (reviewer 2026-05-28): the lifecycle-
                # policy hook (``_apply_finish_policies``) was
                # previously only consulted on ``tool_name=="finish"``.
                # That made ``RetroBeforeDeliverPolicy`` dead code in
                # production: its ``handle_finish`` early-exits when
                # the tool isn't ``deliver_project``/``report_completion``,
                # so a finish call falls through it; and a
                # deliver_project call never reached the hook at all
                # because the dispatch site above only fires on
                # "finish". Route deliver/report through the same
                # hook so retro / delivery policies actually run.
                lifecycle_outcome = await self._apply_finish_policies(
                    tool_name=tool_name,
                    tool_args=tool_args,
                    tool_call=tool_call,
                    tool_call_id=tool_call_id,
                    messages=messages,
                    files_created=files_created,
                    files_modified=files_modified,
                )
                if lifecycle_outcome:
                    if lifecycle_outcome.get("action") == "continue":
                        continue
                    if lifecycle_outcome.get("action") == "finish":
                        return lifecycle_outcome.get("result")

                result = await self._execute_tool(tool_name, tool_args)
                if result.success:
                    if hasattr(self, "clear_finish_step_reminders"):
                        self.clear_finish_step_reminders()
                    await self._process_pending_notifications(flush_bus=True, flush_knowledge=True)
                    # PR 2.5-fix-2 (2026-05-29, reviewer follow-up):
                    # ``report_completion`` is a per-milestone signal,
                    # not a delivery. The previous return always
                    # carried ``delivered=True`` regardless of which
                    # tool ran, mislabeling milestone steps as
                    # deliveries in the step trace. Branch the
                    # return so the trace reflects intent. No
                    # downstream consumer reads the ``delivered``
                    # key for shutdown (the orchestrator's
                    # termination signal is
                    # ``_project_delivered_event`` set inside
                    # ``DeliverProjectTool.execute``), so the change
                    # is cosmetic/log-only.
                    if tool_name == "deliver_project":
                        return {
                            "success": True,
                            "summary": tool_args.get("delivery_summary", "Project delivered"),
                            "files_created": files_created,
                            "files_modified": files_modified,
                            "delivered": True,
                        }
                    return {
                        "success": True,
                        "summary": tool_args.get(
                            "delivery_summary", "Milestone reported"
                        ),
                        "files_created": files_created,
                        "files_modified": files_modified,
                        "milestone_reported": True,
                    }
                messages.append(Message.assistant(tool_calls=[tool_call]))
                messages.append(Message.tool(f"Error: {result.error_message}", tool_call_id))
                continue

            import time as _time

            _tool_start = _time.time()
            result = await self._execute_tool(tool_name, tool_args)
            _tool_duration_ms = int((_time.time() - _tool_start) * 1000)
            self._log_tool_result(tool_name, result, _tool_duration_ms)

            path = None
            if tool_name == "write":
                path = tool_args.get("path") or tool_args.get("file_path")
                if path:
                    files_created.append(path)
                    if hasattr(self, "memory"):
                        self.memory.record_file_created(path)
                    _auto_stage(self, path, action="add")
            elif tool_name == "edit":
                path = tool_args.get("file_path") or tool_args.get("path")
                if path:
                    files_modified.append(path)
                    if hasattr(self, "memory"):
                        self.memory.record_file_modified(path)
                    _auto_stage(self, path, action="add")
            elif tool_name == "apply_patch":
                patch_text = tool_args.get("patch", "")
                patch_paths: List[str] = []
                patch_created: List[str] = []
                if isinstance(patch_text, str):
                    for line in patch_text.splitlines():
                        if line.startswith("*** Add File: "):
                            patch_path = line.split(": ", 1)[1].strip()
                            if patch_path:
                                patch_created.append(patch_path)
                        elif line.startswith("*** Update File: "):
                            patch_path = line.split(": ", 1)[1].strip()
                            if patch_path:
                                patch_paths.append(patch_path)
                for patch_path in patch_created:
                    files_created.append(patch_path)
                    if hasattr(self, "memory"):
                        self.memory.record_file_created(patch_path)
                    _auto_stage(self, patch_path, action="add")
                for patch_path in patch_paths:
                    files_modified.append(patch_path)
                    if hasattr(self, "memory"):
                        self.memory.record_file_modified(patch_path)
                    _auto_stage(self, patch_path, action="add")
            elif tool_name == "delete_file":
                path = tool_args.get("file_path") or tool_args.get("path")
                if path:
                    _auto_stage(self, path, action="delete")
            elif tool_name == "lint":
                path = tool_args.get("path")
                if path and hasattr(self, "memory"):
                    self.memory.record_lint(path, result.success)

            # Mechanism #40: image payloads must reach the model as IMAGE
            # PARTS, not as json text. Extract them before the result dict is
            # recorded/stringified (a dumped base64 would nuke the context and
            # the model still couldn't see it).
            _mm_image = None
            if result.success and isinstance(result.data, dict):
                _cand = result.data.pop("multimodal_content", None)
                result.data.pop("image_base64", None)
                if isinstance(_cand, dict) and _cand.get("type") == "image_url":
                    _mm_image = _cand

            if hasattr(self, "memory"):
                loop_info = self.memory.record_tool_call(
                    tool_name=tool_name,
                    tool_args=tool_args,
                    result=result.data if result.success else result.error_message,
                    success=result.success,
                    duration_ms=_tool_duration_ms,
                )
                if loop_info.get("is_potential_loop") and loop_info.get("consecutive_count", 0) % 20 == 0:
                    self._logger.debug(
                        f"[{self.agent_id}] Batch operation: {loop_info['consecutive_count']} "
                        f"consecutive {tool_name} calls"
                    )

            if result.success:
                self.record_observation(
                    self._scrub_workspace_paths(str(result.data)[:200]) if result.data else "OK")
            else:
                self.record_error(self._scrub_workspace_paths(result.error_message or ""))
                if hasattr(self, "memory"):
                    self.memory.record_error(result.error_message or "", context=f"tool={tool_name}")

            messages.append(Message.assistant(tool_calls=[tool_call]))
            result_str = result.data if result.success else f"Error: {result.error_message}"
            if isinstance(result_str, dict):
                result_str = json.dumps(result_str, indent=2)
            result_str = str(result_str)

            if not result_str.strip() or result_str.strip() == "{}":
                result_str = "Your command ran successfully and did not produce any output."
            elif result_str.strip() == "None":
                result_str = f"Tool {tool_name} completed successfully (no output)."

            # NO compression / NO cap (user decision 2026-06-24): the FULL tool result
            # reaches the agent — truncated tool output is a correctness hazard (the
            # agent acts on a partial view). This was the DOMINANT truncation: the live
            # step pipeline used to run a ToolResultCompressor (~1000 chars/tool,
            # head/summary) on any result >1000 chars, THEN cap at 16000, so large file
            # reads / hub dumps / chain results were silently shrunk to a digest before
            # the model ever saw them. Both were removed here in 2026-06-24, and the
            # now-orphaned compressor module itself was deleted 2026-07-27. Live context
            # reduction is tool-level (compact list + get-by-id) + _mask_old_observations.
            # PATH FIREWALL: relativize absolute env/worktree roots before the
            # result reaches the model, so it perceives its workspace as root and
            # never learns the host path to script against (run #13 leak).
            result_str = self._scrub_workspace_paths(result_str)
            messages.append(Message.tool(result_str, tool_call_id))
            if _mm_image is not None:
                _img_label = ""
                if isinstance(result.data, dict):
                    _img_label = str(result.data.get("path") or "")
                messages.append(Message.user_multimodal([
                    {"type": "text", "text": (
                        f"[view_image] {_img_label} — the image content follows. "
                        "Analyze it directly; this is the authoritative reference.")},
                    _mm_image,
                ]))

        return None
