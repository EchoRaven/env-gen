"""Profiled parallel execution flow."""

import asyncio
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional
from uuid import uuid4


class ProfiledParallelExecutionSupport:
    # #681: THE HOST-CLASS CONTRACT, DECLARED. This is a MIXIN — the names below are
    # supplied by the class it is mixed into, so a checker reading this file alone reports
    # every use as a missing attribute. That was 990 of 2218 diagnostics (45%), the single
    # largest class, and it buried real ones: the same sweep found #658 and a dangling
    # WorkHub annotation under it. Annotation-only, under TYPE_CHECKING — no runtime effect.
    if TYPE_CHECKING:
        def _acquire_file_claims(self, *a: Any, **k: Any) -> Any: ...
        def _available_spawn_budget(self, *a: Any, **k: Any) -> Any: ...
        _completed_subtask_fingerprints: Any
        def _error_payload(self, *a: Any, **k: Any) -> Any: ...
        def _extract_declared_files(self, *a: Any, **k: Any) -> Any: ...
        def _extract_error_code(self, *a: Any, **k: Any) -> Any: ...
        def _is_success_findings(self, *a: Any, **k: Any) -> Any: ...
        _logger: Any
        def _preplan_subtask_file_claims(self, *a: Any, **k: Any) -> Any: ...
        def _recent_failure_rate(self, *a: Any, **k: Any) -> Any: ...
        def _recommended_action_from_error_code(self, *a: Any, **k: Any) -> Any: ...
        def _recommended_actions_summary(self, *a: Any, **k: Any) -> Any: ...
        def _record_completed_subtask(self, *a: Any, **k: Any) -> Any: ...
        def _record_parallel_observability(self, *a: Any, **k: Any) -> Any: ...
        def _record_subtask_outcome(self, *a: Any, **k: Any) -> Any: ...
        def _release_file_claims(self, *a: Any, **k: Any) -> Any: ...
        def _report_team_conflict_to_hub(self, *a: Any, **k: Any) -> Any: ...
        def _resolve_adaptive_concurrency(self, *a: Any, **k: Any) -> Any: ...
        _spawn_window_seconds: Any
        _spawned_agents: Any
        def _subtask_fingerprint(self, *a: Any, **k: Any) -> Any: ...
        def _validate_subtask_contract(self, *a: Any, **k: Any) -> Any: ...
        def spawn_worker(self, *a: Any, **k: Any) -> Any: ...
        def terminate_runtime_agent(self, *a: Any, **k: Any) -> Any: ...

    async def parallel_execute_profiled(
        self,
        subtasks: List[Dict[str, Any]],
        parent_id: str,
        team_name: str = "CustomTeam",
        max_concurrent: int = 5,
        timeout: float = 300.0,
    ) -> Dict[str, Any]:
        start_time = datetime.now()
        results: Dict[int, Any] = {}
        failed: List[int] = []
        spawned_ids: List[str] = []
        executable_subtasks: List[Dict[str, Any]] = []
        batch_seen_fingerprints: Dict[str, int] = {}

        for index, subtask in enumerate(subtasks):
            contract_error = self._validate_subtask_contract(subtask, custom_mode=True)
            if contract_error:
                agent_def = subtask.get("agent_definition", {}) if isinstance(subtask, dict) else {}
                msg = f"E_CHILD_TASK_CONTRACT: {contract_error}"
                results[index] = {
                    "success": False,
                    "agent_name": agent_def.get("name", f"Agent_{index}") if isinstance(agent_def, dict) else f"Agent_{index}",
                    "task": subtask.get("task", f"Task {index}") if isinstance(subtask, dict) else f"Task {index}",
                    "error_code": "E_CHILD_TASK_CONTRACT",
                    "error_message": msg,
                    "error": msg,
                    "recommended_action": self._recommended_action_from_error_code("E_CHILD_TASK_CONTRACT"),
                    "agent_id": None,
                }
                failed.append(index)
                continue

            agent_def = subtask.get("agent_definition", {}) if isinstance(subtask, dict) else {}
            resolved_agent_type = self._infer_agent_type_from_definition(
                agent_def=agent_def if isinstance(agent_def, dict) else {},
                parent_id=parent_id,
            )
            fingerprint = self._subtask_fingerprint(
                subtask,
                parent_id=parent_id,
                agent_type=resolved_agent_type,
                custom_mode=True,
            )
            if fingerprint in batch_seen_fingerprints:
                original_index = batch_seen_fingerprints[fingerprint]
                results[index] = {
                    "success": True,
                    "agent_name": agent_def.get("name", f"Agent_{index}"),
                    "task": subtask.get("task", f"Task {index}"),
                    "status": "skipped_duplicate_in_batch",
                    "duplicate_of": original_index,
                    "fingerprint": fingerprint,
                    "agent_id": None,
                }
                continue
            if fingerprint in self._completed_subtask_fingerprints:
                results[index] = {
                    "success": True,
                    "agent_name": agent_def.get("name", f"Agent_{index}"),
                    "task": subtask.get("task", f"Task {index}"),
                    "status": "skipped_duplicate_recent",
                    "fingerprint": fingerprint,
                    "agent_id": None,
                }
                continue

            batch_seen_fingerprints[fingerprint] = index
            executable_subtasks.append({
                "index": index,
                "subtask": subtask,
                "fingerprint": fingerprint,
                "resolved_agent_type": resolved_agent_type,
            })

        executable_subtasks, preclaim_blocked = self._preplan_subtask_file_claims(executable_subtasks)
        for blocked_index, blocked_meta in preclaim_blocked.items():
            if blocked_index in results:
                continue
            subtask_raw = subtasks[blocked_index] if blocked_index < len(subtasks) else {}
            agent_def = subtask_raw.get("agent_definition", {}) if isinstance(subtask_raw, dict) else {}
            task_text = (
                subtask_raw.get("task", f"Task {blocked_index}")
                if isinstance(subtask_raw, dict)
                else f"Task {blocked_index}"
            )
            msg = "File ownership conflict inside current profiled batch."
            results[blocked_index] = {
                "success": False,
                "agent_name": agent_def.get("name", f"Agent_{blocked_index}") if isinstance(agent_def, dict) else f"Agent_{blocked_index}",
                "task": task_text,
                "error_code": "E_FILE_CLAIM_CONFLICT",
                "error_message": msg,
                "error": msg,
                "error_details": blocked_meta,
                "recommended_action": self._recommended_action_from_error_code("E_FILE_CLAIM_CONFLICT"),
                "agent_id": None,
            }
            failed.append(blocked_index)
        if preclaim_blocked:
            self._report_team_conflict_to_hub(
                conflict_type="profiled_preclaim_conflict",
                team_id=team_name,
                parent_id=parent_id,
                details={
                    "blocked_count": len(preclaim_blocked),
                    "blocked_indices": sorted(preclaim_blocked.keys()),
                    "blocked": preclaim_blocked,
                },
                severity="warning",
            )

        available_budget = self._available_spawn_budget()
        if len(executable_subtasks) > available_budget:
            budget_message = (
                f"Spawn budget insufficient for team '{team_name}': requested={len(executable_subtasks)}, "
                f"available={available_budget}, window={int(self._spawn_window_seconds)}s."
            )
            result = {
                "success": False,
                "team_name": team_name,
                "results": [results.get(i, self._error_payload(code="E_NOT_EXECUTED", message="Not executed")) for i in range(len(subtasks))],
                "failed": sorted(set(failed + [item["index"] for item in executable_subtasks])),
                "duration": 0.0,
                "agents_spawned": 0,
                "effective_max_concurrent": 0,
                "error_code": "E_SPAWN_BUDGET_EXCEEDED",
                "error_message": budget_message,
                "error": budget_message,
                "recommended_action": self._recommended_action_from_error_code("E_SPAWN_BUDGET_EXCEEDED"),
            }
            self._record_parallel_observability(
                total_subtasks=len(subtasks),
                deduped_count=len([r for r in results.values() if r.get("status", "").startswith("skipped_duplicate")]),
                contract_rejected_count=len([r for r in results.values() if r.get("error_code") == "E_CHILD_TASK_CONTRACT"]),
                duration_seconds=0.0,
                recommended_actions_summary=self._recommended_actions_summary(result["results"]),
            )
            return result
        effective_max = self._resolve_adaptive_concurrency(
            subtasks=[item["subtask"] for item in executable_subtasks],
            requested_max=max_concurrent,
            workload_type=(
                executable_subtasks[0]["resolved_agent_type"]
                if executable_subtasks and len({item["resolved_agent_type"] for item in executable_subtasks}) == 1
                else "worker"
            ),
        )

        self._logger.info(
            f"Starting profiled team '{team_name}': {len(executable_subtasks)}/{len(subtasks)} executable agents, "
            f"max_concurrent={max_concurrent} -> effective={effective_max}"
        )

        semaphore = asyncio.Semaphore(effective_max)

        async def execute_custom_agent(index: int, subtask: Dict[str, Any], fingerprint: str, resolved_agent_type: str) -> None:
            async with semaphore:
                task_desc = subtask.get("task", f"Task {index}")
                context = subtask.get("context", {})
                agent_def = subtask.get("agent_definition", {})
                claimed_files = self._extract_declared_files(subtask)
                claim_owner = f"{parent_id}:profiled:{index}:{uuid4().hex[:8]}"

                agent_name = agent_def.get("name", f"Agent_{index}")
                agent_role = agent_def.get("role", "general assistant")

                full_task = (
                    f"{task_desc}\n\n"
                    f"Team context:\n"
                    f"- team_name: {team_name}\n"
                    f"- agent_name: {agent_name}\n"
                    f"- agent_role: {agent_role}\n"
                    f"- resolved_agent_type: {resolved_agent_type}\n"
                    f"- coordination: {context.get('_coordination', '') or 'none'}"
                )
                visible_context = {k: v for k, v in context.items() if not k.startswith("_")}
                if visible_context:
                    ctx_str = "\n".join(f"- {k}: {v}" for k, v in visible_context.items())
                    full_task = f"{full_task}\n\nTask context:\n{ctx_str}"

                agent_id = None
                try:
                    if claimed_files:
                        claim_ok, conflicts = await self._acquire_file_claims(
                            claim_owner=claim_owner,
                            files=claimed_files,
                        )
                        if not claim_ok:
                            msg = (
                                "File ownership conflict detected for declared files. "
                                "Split ownership and rerun."
                            )
                            self._report_team_conflict_to_hub(
                                conflict_type="profiled_runtime_claim_conflict",
                                team_id=team_name,
                                parent_id=parent_id,
                                details={
                                    "subtask_index": index,
                                    "task": task_desc,
                                    "agent_name": agent_name,
                                    "conflicts": conflicts,
                                },
                                severity="warning",
                            )
                            results[index] = {
                                "success": False,
                                "agent_name": agent_name,
                                "agent_type": resolved_agent_type,
                                "task": task_desc,
                                "error_code": "E_FILE_CLAIM_CONFLICT",
                                "error_message": msg,
                                "error": msg,
                                "error_details": {"conflicts": conflicts},
                                "recommended_action": self._recommended_action_from_error_code("E_FILE_CLAIM_CONFLICT"),
                                "agent_id": None,
                                "fingerprint": fingerprint,
                            }
                            self._record_subtask_outcome(success=False)
                            failed.append(index)
                            return

                    disabled_tools = list(agent_def.get("disabled_tools") or [])
                    write_scopes = agent_def.get("write_scopes")
                    include_vision = agent_def.get("include_vision")
                    if not claimed_files:
                        # Inspector/reviewer subtasks are read-only by default. A subtask
                        # must declare `files` or explicit write_scopes to receive write tools.
                        disabled_tools = list(dict.fromkeys([
                            *disabled_tools,
                            "write",
                            "edit",
                            "apply_patch",
                            "delete_file",
                        ]))
                        if write_scopes is None:
                            write_scopes = []

                    agent_id = await self.spawn_worker(
                        worker_type=resolved_agent_type,
                        task=full_task,
                        parent_id=parent_id,
                        role=agent_role,
                        custom_name=agent_name,
                        config_key=agent_def.get("config_profile"),
                        disabled_tools=disabled_tools,
                        write_scopes=write_scopes,
                        include_vision=include_vision,
                        skills=agent_def.get("skills"),
                        inherit_parent_skills=bool(agent_def.get("inherit_parent_skills", True)),
                    )
                    spawned_ids.append(agent_id)

                    spawned = self._spawned_agents.get(agent_id)
                    if spawned and spawned.task_done_event:
                        await asyncio.wait_for(spawned.task_done_event.wait(), timeout=timeout)
                        if spawned.result_done_event:
                            try:
                                await asyncio.wait_for(
                                    spawned.result_done_event.wait(),
                                    timeout=min(5.0, timeout),
                                )
                            except asyncio.TimeoutError:
                                self._logger.warning(
                                    f"Result message not received after task completion for {agent_id}"
                                )
                        findings = spawned.findings or {"status": "completed"}
                        success = self._is_success_findings(findings)
                        results[index] = {
                            "success": success,
                            "agent_name": agent_name,
                            "agent_type": resolved_agent_type,
                            "task": task_desc,
                            "findings": findings,
                            "agent_id": agent_id,
                            "fingerprint": fingerprint,
                        }
                        if not success:
                            results[index]["recommended_action"] = (
                                findings.get("recommended_action")
                                or self._recommended_action_from_error_code(findings.get("error_code"))
                            )
                        self._record_subtask_outcome(success=success)
                        if success:
                            self._record_completed_subtask(fingerprint)
                        if not success:
                            failed.append(index)
                    else:
                        await asyncio.sleep(min(timeout, 1.0))
                        results[index] = {
                            "success": False,
                            "agent_name": agent_name,
                            "agent_type": resolved_agent_type,
                            "task": task_desc,
                            "error_code": "E_AGENT_NO_COMPLETION_EVENT",
                            "error_message": "No completion event available",
                            "error": "No completion event available",
                            "recommended_action": self._recommended_action_from_error_code("E_AGENT_NO_COMPLETION_EVENT"),
                            "agent_id": agent_id,
                            "fingerprint": fingerprint,
                        }
                        self._record_subtask_outcome(success=False)
                        failed.append(index)

                    if index not in results:
                        results[index] = {
                            "success": False,
                            "agent_name": agent_name,
                            "agent_type": resolved_agent_type,
                            "task": task_desc,
                            "error_code": "E_AGENT_TIMEOUT",
                            "error_message": "Timeout",
                            "error": "Timeout",
                            "recommended_action": self._recommended_action_from_error_code("E_AGENT_TIMEOUT"),
                            "agent_id": agent_id,
                            "fingerprint": fingerprint,
                        }
                        self._record_subtask_outcome(success=False)
                        failed.append(index)
                except asyncio.TimeoutError:
                    results[index] = {
                        "success": False,
                        "agent_name": agent_name,
                        "agent_type": resolved_agent_type,
                        "task": task_desc,
                        "error_code": "E_AGENT_TIMEOUT",
                        "error_message": "Timeout",
                        "error": "Timeout",
                        "recommended_action": self._recommended_action_from_error_code("E_AGENT_TIMEOUT"),
                        "agent_id": agent_id,
                        "fingerprint": fingerprint,
                    }
                    self._record_subtask_outcome(success=False)
                    failed.append(index)
                except Exception as e:
                    self._logger.error(f"Agent {agent_name} failed: {e}")
                    error_code = self._extract_error_code(str(e), fallback="E_AGENT_EXECUTION")
                    results[index] = {
                        "success": False,
                        "agent_name": agent_name,
                        "agent_type": resolved_agent_type,
                        "task": task_desc,
                        "error_code": error_code,
                        "error_message": str(e),
                        "error": str(e),
                        "recommended_action": self._recommended_action_from_error_code(error_code),
                        "agent_id": agent_id,
                        "fingerprint": fingerprint,
                    }
                    self._record_subtask_outcome(success=False)
                    failed.append(index)
                finally:
                    if agent_id:
                        await self.terminate_runtime_agent(agent_id, wait=False)
                    if claimed_files:
                        await self._release_file_claims(
                            claim_owner=claim_owner,
                            files=claimed_files,
                        )

        await asyncio.gather(*[
            execute_custom_agent(
                item["index"],
                item["subtask"],
                item["fingerprint"],
                item["resolved_agent_type"],
            )
            for item in executable_subtasks
        ])

        duration = (datetime.now() - start_time).total_seconds()
        sorted_results = [
            results.get(i, self._error_payload(code="E_NOT_EXECUTED", message="Not executed"))
            for i in range(len(subtasks))
        ]

        self._logger.info(
            f"Team '{team_name}' complete: {len(subtasks) - len(failed)}/{len(subtasks)} succeeded "
            f"in {duration:.1f}s"
        )

        result = {
            "success": len(failed) == 0,
            "team_name": team_name,
            "results": sorted_results,
            "failed": failed,
            "duration": duration,
            "agents_spawned": len(spawned_ids),
            "effective_max_concurrent": effective_max,
            "failure_rate_recent": round(self._recent_failure_rate(), 3),
            "spawn_budget_remaining": self._available_spawn_budget(),
            "deduped_count": len([r for r in results.values() if r.get("status", "").startswith("skipped_duplicate")]),
            "contract_rejected_count": len([r for r in results.values() if r.get("error_code") == "E_CHILD_TASK_CONTRACT"]),
            "recommended_actions_summary": self._recommended_actions_summary(sorted_results),
        }
        self._record_parallel_observability(
            total_subtasks=len(subtasks),
            deduped_count=result["deduped_count"],
            contract_rejected_count=result["contract_rejected_count"],
            duration_seconds=duration,
            recommended_actions_summary=result["recommended_actions_summary"],
        )
        return result

    def _infer_agent_type_from_definition(
        self,
        *,
        agent_def: Dict[str, Any],
        parent_id: Optional[str],
    ) -> str:
        explicit = str(agent_def.get("agent_type", "")).strip()
        if explicit:
            return explicit

        text_parts = [
            str(agent_def.get("name", "")),
            str(agent_def.get("role", "")),
            " ".join(str(c) for c in (agent_def.get("capabilities", []) or [])),
        ]
        text = " ".join(text_parts).lower()

        keyword_candidates = [
            ("frontend", "frontend"),
            ("ui", "frontend"),
            ("react", "frontend"),
            ("backend", "backend"),
            ("api", "backend"),
            ("express", "backend"),
            ("database", "database"),
            ("postgres", "database"),
            ("sql", "database"),
            ("design", "design"),
            ("architect", "design"),
            ("test", "verifier"),
            ("task", "verifier"),
            ("knowledge", "knowledge"),
            ("mcp", "backend"),
            ("review", "review_worker"),
            ("audit", "review_worker"),
            ("investig", "analysis_worker"),
            ("research", "analysis_worker"),
            ("analysis", "analysis_worker"),
        ]

        try:
            from ..agents.configurable_agent import list_available_agents

            available = set(list_available_agents())
        except Exception:
            available = set()

        candidates: List[str] = []
        for key, candidate in keyword_candidates:
            if key in text:
                candidates.append(candidate)

        for candidate in candidates:
            if not candidate:
                continue
            if not available or candidate in available:
                return candidate
        raise ValueError(
            "Unable to infer a valid execution profile from team definition. "
            "Provide 'agent_type' or 'config_profile' explicitly."
        )
