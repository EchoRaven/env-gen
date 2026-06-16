from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, List, Optional, Set

from utils.llm import Message

from .action import AgentActionStageMixin


class AgentStepStageMixin(AgentActionStageMixin):
    # How many steps to skip between auto-retrieves once knowledge has
    # been auto-fetched at least once. Lets the LLM-decision path still
    # fire in between — it'll usually say "no", saving the round-trip
    # without going completely blind. Reviewer's follow-up suggestion.
    _RETRIEVE_AUTO_THROTTLE_STEPS: int = 3

    def _agent_has_knowledge_to_fetch(self) -> bool:
        """Return True if there is any knowledge worth retrieving.

        Used by ``_run_retrieve_context_stage`` to skip the LLM
        "do I need retrieval?" round-trip. Sources checked:
          * Agent's in-memory ``GeneratorMemory._knowledge`` list.
          * Agent's persisted ``.memory/<id>.knowledge.jsonl`` file
            (covers the case where memory hasn't loaded into the list).
          * MemoryBank instance (canonical progress / context store).
        """
        # In-memory knowledge list
        try:
            mem = getattr(self, "memory", None)
            if mem is not None and getattr(mem, "_knowledge", None):
                if len(mem._knowledge) > 0:
                    return True
        except Exception:
            pass
        # MemoryBank — if the agent has a bank populated at all,
        # ``read_memory_bank(mode='digest')`` returns useful context.
        try:
            mb = getattr(self, "memory_bank", None)
            if mb is not None:
                # MemoryBank's emptiness is best probed via its files —
                # the bank renders any of project_brief / active_context /
                # progress / system_patterns / tech_context.
                from pathlib import Path
                bank_dir = getattr(mb, "memory_dir", None) or getattr(mb, "base_dir", None)
                if bank_dir and Path(bank_dir).exists():
                    for f in Path(bank_dir).glob("*.md"):
                        if f.stat().st_size > 0:
                            return True
        except Exception:
            pass
        # Persisted knowledge JSONL on disk
        try:
            mem = getattr(self, "memory", None)
            path = getattr(mem, "_persistence_path", None) if mem else None
            if path is not None:
                from pathlib import Path
                p = Path(path)
                if p.exists() and p.stat().st_size > 0:
                    return True
        except Exception:
            pass
        return False

    async def _decide_stage_boolean(
        self,
        *,
        messages: List[Message],
        stage_name: str,
        prompt: str,
        yes_marker: str,
    ) -> bool:
        try:
            decision = await self._call_stage_llm(
                messages,
                stage_name,
                prompt,
                [],
            )
            text = (getattr(decision, "content", "") or "").lower()
            if getattr(decision, "content", None):
                messages.append(Message.assistant(decision.content))
            return yes_marker.lower() in text
        except Exception:
            return False

    async def _run_stage_tool_call_phase(
        self,
        *,
        messages: List[Message],
        files_created: List[str],
        files_modified: List[str],
        stage_name: str,
        step: int,
        tool_schema_map: Dict[str, Dict[str, Any]],
        tool_names: Set[str],
        tool_prompt: str,
        max_calls: int,
        stage_start: float,
        step_trace: Dict[str, Any],
        step_traces: List[Dict[str, Any]],
        loop_time: Callable[[], float],
        mark_stage: Callable[..., None],
        metadata: Optional[Dict[str, Any]] = None,
        on_done: Optional[Callable[[], Awaitable[None]]] = None,
        error_log_message: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        try:
            resp = await self._call_stage_llm(
                messages,
                stage_name,
                tool_prompt,
                self._filtered_tool_schemas(tool_schema_map, tool_names),
            )
            done = await self._process_tool_calls(
                messages,
                files_created,
                files_modified,
                stage_name=stage_name,
                step_idx=step,
                tool_calls=getattr(resp, "tool_calls", []) or [],
                max_calls=max_calls,
            )
            stage_metadata = {"tool_calls": len(getattr(resp, "tool_calls", []) or [])}
            if metadata:
                stage_metadata.update(metadata)
            if done:
                if on_done is not None:
                    await on_done()
                mark_stage(
                    stage_name,
                    executed=True,
                    duration_ms=int((loop_time() - stage_start) * 1000),
                    metadata=stage_metadata,
                )
                step_trace["mode_after"] = self._execution_mode
                step_traces.append(step_trace)
                done["step_traces"] = step_traces
                return done
            if getattr(resp, "content", None):
                messages.append(Message.assistant(resp.content))
            mark_stage(
                stage_name,
                executed=True,
                duration_ms=int((loop_time() - stage_start) * 1000),
                metadata=stage_metadata,
            )
        except Exception as e:
            if error_log_message:
                self._logger.warning(f"[{self.agent_id}] {error_log_message}: {e}")
            mark_stage(
                stage_name,
                executed=False,
                duration_ms=int((loop_time() - stage_start) * 1000),
                skip_reason=f"error: {e}",
            )
        return None

    async def _run_planning_stage(
        self,
        *,
        enabled: bool,
        tool_schema_map: Dict[str, Dict[str, Any]],
        messages: List[Message],
        files_created: List[str],
        files_modified: List[str],
        step: int,
        max_calls_cfg: Dict[str, int],
        step_trace: Dict[str, Any],
        step_traces: List[Dict[str, Any]],
        loop_time: Callable[[], float],
        mark_stage: Callable[..., None],
    ) -> Optional[Dict[str, Any]]:
        if not enabled:
            mark_stage(
                "planning",
                executed=False,
                skip_reason="disabled_by_config",
            )
            return None

        stage_start = loop_time()
        try:
            plan_resp = await self._call_stage_llm(
                messages,
                "planning",
                "Stage planning: decide execution mode for this step (team or direct), "
                "state the immediate next moves, expected outputs, and main risk in plain text. "
                "Include one line in your reasoning text: MODE: team|direct|stay.",
                [],
            )
            plan_text = (getattr(plan_resp, "content", "") or "").lower()
            if "mode: team" in plan_text:
                self._enter_team_mode(reason="planning")
            elif "mode: direct" in plan_text:
                self._exit_team_mode(reason="planning")
            if getattr(plan_resp, "content", None):
                messages.append(Message.assistant(plan_resp.content))
            mark_stage(
                "planning",
                executed=True,
                duration_ms=int((loop_time() - stage_start) * 1000),
                metadata={
                    "tool_calls": len(getattr(plan_resp, "tool_calls", []) or []),
                    "mode_after": self._execution_mode,
                },
            )
        except Exception as e:
            self._logger.warning(f"[{self.agent_id}] planning stage skipped: {e}")
            mark_stage(
                "planning",
                executed=False,
                duration_ms=int((loop_time() - stage_start) * 1000),
                skip_reason=f"error: {e}",
            )
        return None

    async def _run_retrieve_context_stage(
        self,
        *,
        enabled: bool,
        tool_schema_map: Dict[str, Dict[str, Any]],
        knowledge_fetch_names: Set[str],
        knowledge_store_names: Set[str],
        hub_sync_tool_names: Set[str],
        initial_prompt: str,
        hub_pulse_prompt: Optional[str],
        runtime_team_status_prompt: Optional[str],
        retrieved_action_names: Dict[str, Set[str]],
        messages: List[Message],
        files_created: List[str],
        files_modified: List[str],
        step: int,
        max_calls_cfg: Dict[str, int],
        step_trace: Dict[str, Any],
        step_traces: List[Dict[str, Any]],
        loop_time: Callable[[], float],
        mark_stage: Callable[..., None],
    ) -> Optional[Dict[str, Any]]:
        if not enabled:
            mark_stage(
                "retrieve_context",
                executed=False,
                skip_reason="disabled_by_config",
            )
            return None

        stage_start = loop_time()
        retrieval_seed = "\n\n".join(
            part
            for part in [
                initial_prompt,
                hub_pulse_prompt,
                runtime_team_status_prompt,
            ]
            if part
        )
        all_names = set(tool_schema_map.keys())
        for internal_stage_name in self.ACTION_INTERNAL_STAGES:
            if internal_stage_name == "delegate_team":
                candidate_names = (set(self.TEAM_TOOL_NAMES) | set(self.TEAM_MODE_SUPPORT_TOOLS)) & all_names
            elif self._execution_mode == "team":
                candidate_names = (set(self.TEAM_TOOL_NAMES) | set(self.TEAM_MODE_SUPPORT_TOOLS)) & all_names
            else:
                candidate_names = all_names - set(self.TEAM_TOOL_NAMES)
            # Memory-mechanism redesign (2026-06-08): the forced per-step
            # retrieve_context / knowledge_sync stages are gone (the Memory Bank
            # auto-syncs). Keep ``read_memory_bank`` + ``update_memory_bank`` in
            # the ACTION surface so the agent can still read/update its Memory
            # Bank ON-DEMAND when it genuinely needs to — the rest of the
            # knowledge/hub-sync tools stay reserved for their dedicated stages.
            candidate_names -= (
                (knowledge_fetch_names | knowledge_store_names | hub_sync_tool_names)
                - {"read_memory_bank", "update_memory_bank"}
            )
            candidate_names.discard("think")
            retrieved_action_names[internal_stage_name] = self._stage_tool_names(
                tool_schema_map,
                internal_stage_name,
                candidate_names,
                retrieval_seed or initial_prompt,
                limit=10,
            )

        selected_action_tools_metadata = {
            "selected_action_tools": {
                key: sorted(value)[:10]
                for key, value in retrieved_action_names.items()
                if value
            }
        }
        # Reviewer's memory-redesign recommendation #3: "让 query_knowledge
        # 进入 retrieve_context 阶段被默认调用". Skip the LLM "do I need
        # retrieval?" round-trip whenever there's any knowledge to fetch —
        # the agent's own knowledge bank is cheap to query and the
        # Memory-Bank digest is the canonical source for "what was I doing
        # last step". The opt-out is when knowledge_fetch_names is empty
        # (no tools available, no point asking).
        #
        # Throttle (reviewer's follow-up minor note): auto-fetch on EVERY
        # step is acceptable for the first deploy (the LLM-decision path
        # was biased toward "no" too often), but a tight throttle keeps
        # baseline token/latency from creeping up if the knowledge bank
        # never meaningfully changes. After an auto-retrieve fires, skip
        # the next ``_RETRIEVE_AUTO_THROTTLE_STEPS`` steps unless the
        # LLM-decision path explicitly says yes.
        _last_auto = getattr(self, "_last_auto_retrieve_step", -10**9)
        _steps_since_auto = step - _last_auto
        if (
            knowledge_fetch_names
            and self._agent_has_knowledge_to_fetch()
            and _steps_since_auto >= self._RETRIEVE_AUTO_THROTTLE_STEPS
        ):
            need_retrieval = True
            self._last_auto_retrieve_step = step
            # Inject the seed so ``_run_stage_tool_call_phase`` has the
            # context that "retrieval was auto-selected, not LLM-decided".
            messages.append(Message.system(
                "Stage retrieve_context: auto-retrieving Memory Bank digest "
                "and recent knowledge for this step (your knowledge bank is "
                "non-empty). No need to decide — just call the retrieve "
                "tools you actually need."
            ))
        else:
            need_retrieval = await self._decide_stage_boolean(
                messages=messages,
                stage_name="retrieve_context",
                prompt=(
                    "Stage retrieve_context: decide whether you need to retrieve your Memory Bank digest, knowledge, or skills for this step. "
                    "Reply exactly NEED_RETRIEVAL: yes|no and one reason."
                ),
                yes_marker="NEED_RETRIEVAL: yes",
            )

        if need_retrieval and knowledge_fetch_names:
            done = await self._run_stage_tool_call_phase(
                messages=messages,
                files_created=files_created,
                files_modified=files_modified,
                stage_name="retrieve_context",
                step=step,
                tool_schema_map=tool_schema_map,
                tool_names=knowledge_fetch_names,
                tool_prompt=(
                    "Stage retrieve_context: retrieve only the minimum relevant context for this step. "
                    "Prefer read_memory_bank(mode='digest') when you need your own current focus, blockers, decisions, or progress; "
                    "use knowledge/skill tools only for reusable cross-run information."
                ),
                max_calls=max_calls_cfg.get("retrieve_context", 2),
                stage_start=stage_start,
                step_trace=step_trace,
                step_traces=step_traces,
                loop_time=loop_time,
                mark_stage=mark_stage,
                metadata=selected_action_tools_metadata,
                error_log_message="retrieve_context failed",
            )
            if done:
                return done
        else:
            mark_stage(
                "retrieve_context",
                executed=True,
                duration_ms=int((loop_time() - stage_start) * 1000),
                skip_reason="model_decision_no" if knowledge_fetch_names else "knowledge_tools_unavailable",
                metadata=selected_action_tools_metadata,
            )
        return None

    async def _run_hub_sync_stage(
        self,
        *,
        enabled: bool,
        hub_sync_tool_names: Set[str],
        tool_schema_map: Dict[str, Dict[str, Any]],
        messages: List[Message],
        files_created: List[str],
        files_modified: List[str],
        step: int,
        max_calls_cfg: Dict[str, int],
        step_trace: Dict[str, Any],
        step_traces: List[Dict[str, Any]],
        loop_time: Callable[[], float],
        mark_stage: Callable[..., None],
    ) -> Optional[Dict[str, Any]]:
        if not enabled or not hub_sync_tool_names:
            mark_stage(
                "hub_sync",
                executed=False,
                skip_reason="disabled_by_config" if not enabled else "tools_unavailable",
            )
            return None

        stage_start = loop_time()
        has_file_changes = bool(files_created or files_modified)
        if has_file_changes:
            do_hub_sync = True
        else:
            do_hub_sync = await self._decide_stage_boolean(
                messages=messages,
                stage_name="hub_sync",
                prompt=(
                    "Stage hub_sync: should semantic shared hub state be updated this step? "
                    "Reply exactly SHOULD_HUB_SYNC: yes|no and one reason."
                ),
                yes_marker="SHOULD_HUB_SYNC: yes",
            )

        if do_hub_sync:
            changed_files = list(dict.fromkeys([*files_created, *files_modified]))[-20:]
            done = await self._run_stage_tool_call_phase(
                messages=messages,
                files_created=files_created,
                files_modified=files_modified,
                stage_name="hub_sync",
                step=step,
                tool_schema_map=tool_schema_map,
                tool_names=hub_sync_tool_names,
                tool_prompt=(
                    "Stage hub_sync: synchronize shared hub state for cross-agent convergence. "
                    f"Changed files this step: {changed_files}. "
                    "Record only facts that are true now; do not invent future work. "
                    "If you created or changed API routes, update endpoint/contracts. "
                    "If you created or changed database schema/seed files, update table/database state. "
                    "If you created or changed frontend pages/routes/components, update page/UI state. "
                    "If you produced files, ensure artifact/file-region status reflects the current owner and result. "
                    "If you edited a claimed region, complete or update that file region. "
                    "If you inserted locally using anchors, keep anchor/operation records consistent. "
                    "If you ran tests or verification, record validation/build results. "
                    "Keep calls concise and prefer the smallest hub updates needed for other agents to observe your work."
                ),
                max_calls=max_calls_cfg.get("hub_sync", 2),
                stage_start=stage_start,
                step_trace=step_trace,
                step_traces=step_traces,
                loop_time=loop_time,
                mark_stage=mark_stage,
                error_log_message="hub_sync failed",
            )
            if done:
                return done
        else:
            mark_stage(
                "hub_sync",
                executed=False,
                duration_ms=int((loop_time() - stage_start) * 1000),
                skip_reason="model_decision_no_no_file_changes",
            )
        return None

    async def _run_knowledge_sync_stage(
        self,
        *,
        enabled: bool,
        knowledge_store_names: Set[str],
        tool_schema_map: Dict[str, Dict[str, Any]],
        observer_handler: Any,
        messages: List[Message],
        files_created: List[str],
        files_modified: List[str],
        step: int,
        max_calls_cfg: Dict[str, int],
        step_trace: Dict[str, Any],
        step_traces: List[Dict[str, Any]],
        loop_time: Callable[[], float],
        mark_stage: Callable[..., None],
    ) -> Optional[Dict[str, Any]]:
        if not enabled:
            mark_stage(
                "knowledge_sync",
                executed=False,
                skip_reason="disabled_by_config",
            )
            return None

        stage_start = loop_time()
        if observer_handler is not None:
            try:
                await observer_handler.on_tick(self)
            except Exception as e:
                self._logger.warning(f"[{self.agent_id}] observer knowledge_sync hook failed: {e}")

        do_store_knowledge = False
        if knowledge_store_names:
            do_store_knowledge = await self._decide_stage_boolean(
                messages=messages,
                stage_name="knowledge_sync",
                prompt=(
                    "Stage knowledge_sync: should project-local Memory Bank context or reusable knowledge be synced now? "
                    "Say yes after meaningful progress, blockers, decisions, tech notes, or reusable learnings. "
                    "Reply exactly SHOULD_STORE_KNOWLEDGE: yes|no and one reason."
                ),
                yes_marker="SHOULD_STORE_KNOWLEDGE: yes",
            )

        if do_store_knowledge and knowledge_store_names:
            done = await self._run_stage_tool_call_phase(
                messages=messages,
                files_created=files_created,
                files_modified=files_modified,
                stage_name="knowledge_sync",
                step=step,
                tool_schema_map=tool_schema_map,
                tool_names=knowledge_store_names,
                tool_prompt=(
                    "Stage knowledge_sync: sync durable learnings only. "
                    "Use update_memory_bank for this agent's project-local focus, completed work, blockers, decisions, and tech notes. "
                    "Use knowledge tools only for reusable cross-run patterns or skills."
                ),
                max_calls=max_calls_cfg.get("knowledge_sync", 1),
                stage_start=stage_start,
                step_trace=step_trace,
                step_traces=step_traces,
                loop_time=loop_time,
                mark_stage=mark_stage,
                on_done=lambda: self._process_pending_notifications(flush_bus=True, flush_knowledge=True),
                error_log_message="knowledge_sync failed",
            )
            if done:
                return done
        else:
            await self._process_pending_notifications(flush_bus=True, flush_knowledge=True)
            mark_stage(
                "knowledge_sync",
                executed=True,
                duration_ms=int((loop_time() - stage_start) * 1000),
                skip_reason="model_decision_no" if knowledge_store_names else "store_tools_unavailable",
            )
        return None
