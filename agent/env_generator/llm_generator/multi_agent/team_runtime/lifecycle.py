"""Managed team lifecycle support for dynamic agent management."""

import asyncio
import json
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set

from .models import AgentLifecycle, AgentTeam, TeamAgentSpec


class TeamLifecycleSupport:
    # #681: THE HOST-CLASS CONTRACT, DECLARED. This is a MIXIN — the names below are
    # supplied by the class it is mixed into, so a checker reading this file alone reports
    # every use as a missing attribute. That was 990 of 2218 diagnostics (45%), the single
    # largest class, and it buried real ones: the same sweep found #658 and a dangling
    # WorkHub annotation under it. Annotation-only, under TYPE_CHECKING — no runtime effect.
    if TYPE_CHECKING:
        STATIC_CORE_AGENT_TYPES: Any
        _agent_ledger: Any
        _agent_teams: Any
        def _extract_string_list(self, *a: Any, **k: Any) -> Any: ...
        def _is_active_team_member_agent(self, *a: Any, **k: Any) -> Any: ...
        _logger: Any
        def _normalize_tool_names(self, *a: Any, **k: Any) -> Any: ...
        def _notify_parent_team_completion(self, *a: Any, **k: Any) -> Any: ...
        def _report_team_conflict_to_hub(self, *a: Any, **k: Any) -> Any: ...
        def _slug(self, *a: Any, **k: Any) -> Any: ...
        _spawned_agents: Any
        _team_launch_tasks: Any
        def _validate_file_contract_context_shape(self, *a: Any, **k: Any) -> Any: ...
        def _validate_team_member_file_ownership(self, *a: Any, **k: Any) -> Any: ...
        def spawn_worker(self, *a: Any, **k: Any) -> Any: ...
        def terminate_runtime_agent(self, *a: Any, **k: Any) -> Any: ...

    def _apply_disabled_tools(self, agent: Any, disabled_tools: Optional[List[str]]) -> List[str]:
        disabled = self._normalize_tool_names(disabled_tools)
        if not disabled:
            return []
        removed: List[str] = []
        for tool_name in disabled:
            removed_from_instances = False
            try:
                if hasattr(agent, "_tool_instances") and tool_name in getattr(agent, "_tool_instances", {}):
                    del agent._tool_instances[tool_name]
                    removed_from_instances = True
            except Exception:
                removed_from_instances = False

            removed_from_registry = False
            try:
                if hasattr(agent, "_tools") and agent._tools is not None and hasattr(agent._tools, "unregister"):
                    removed_from_registry = bool(agent._tools.unregister(tool_name))
            except Exception:
                removed_from_registry = False

            if removed_from_instances or removed_from_registry:
                removed.append(tool_name)
        return removed

    def _build_team_member_task_prompt(
        self,
        *,
        team: AgentTeam,
        spec: TeamAgentSpec,
        member_id: str,
        parent_id: Optional[str],
    ) -> str:
        dependency_text = ", ".join(spec.depends_on) if spec.depends_on else "none"
        disabled_text = ", ".join(spec.disabled_tools) if spec.disabled_tools else "none"
        capability_text = ", ".join(spec.capabilities) if spec.capabilities else "none"
        skill_text = ", ".join(spec.skills) if spec.skills else "inherit/default"
        write_scope_text = ", ".join(spec.write_scopes) if spec.write_scopes else "inherit from parent/profile"
        file_contract = spec.context.get("file_contract", {}) if isinstance(spec.context, dict) else {}
        owned_files = self._extract_string_list((spec.context or {}).get("owned_files")) + self._extract_string_list(
            file_contract.get("owned_files")
        )
        forbidden_files = self._extract_string_list((spec.context or {}).get("forbidden_files")) + self._extract_string_list(
            file_contract.get("forbidden_files")
        )
        owned_text = ", ".join(sorted(set(owned_files))) if owned_files else "none"
        forbidden_text = ", ".join(sorted(set(forbidden_files))) if forbidden_files else "none"
        context_lines = "\n".join(f"- {k}: {v}" for k, v in (spec.context or {}).items()) or "- none"
        base_task = spec.task or f"Deliver your part for team '{team.team_id}'."
        return (
            f"{base_task}\n\n"
            f"Team context:\n"
            f"- team_id: {team.team_id}\n"
            f"- team_description: {team.description}\n"
            f"- collaboration: {team.collaboration or 'none provided'}\n"
            f"- your_member_id: {member_id}\n"
            f"- your_description: {spec.description}\n"
            f"- parent_agent: {parent_id or team.parent_id or 'unknown'}\n"
            f"- runtime_agent_type: {spec.agent_type}\n"
            f"- config_profile: {spec.config_profile or 'infer from agent_type/parent'}\n"
            f"- role: {spec.role or 'none'}\n"
            f"- model: {spec.model or 'default runtime model'}\n"
            f"- capabilities: {capability_text}\n"
            f"- skills: {skill_text}\n"
            f"- inherit_parent_skills: {spec.inherit_parent_skills}\n"
            f"- include_vision: {spec.include_vision if spec.include_vision is not None else 'inherit'}\n"
            f"- write_scopes: {write_scope_text}\n"
            f"- depends_on: {dependency_text}\n"
            f"- owned_files: {owned_text}\n"
            f"- forbidden_files: {forbidden_text}\n"
            f"- disabled_tools (enforced): {disabled_text}\n\n"
            f"Task-specific context:\n{context_lines}\n"
        )

    def _topological_levels(self, members: Dict[str, TeamAgentSpec]) -> List[List[str]]:
        unresolved: Dict[str, Set[str]] = {
            member_id: set(spec.depends_on or [])
            for member_id, spec in members.items()
        }
        for member_id, deps in unresolved.items():
            unknown = [d for d in deps if d not in members]
            if unknown:
                raise ValueError(f"Team member '{member_id}' depends on unknown members: {unknown}")

        levels: List[List[str]] = []
        ready = sorted([mid for mid, deps in unresolved.items() if not deps])
        visited: Set[str] = set()
        while ready:
            levels.append(ready)
            next_ready: List[str] = []
            for member_id in ready:
                visited.add(member_id)
                for candidate_id, deps in unresolved.items():
                    if member_id in deps:
                        deps.remove(member_id)
                        if not deps and candidate_id not in visited and candidate_id not in next_ready:
                            next_ready.append(candidate_id)
            ready = sorted(next_ready)
        if len(visited) != len(members):
            remaining = sorted(set(members.keys()) - visited)
            raise ValueError(f"Team dependency cycle detected among: {remaining}")
        return levels

    def create_agent_team(
        self,
        *,
        team_id: str,
        parent_id: Optional[str],
        description: str,
        collaboration: str = "",
        agents: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        if not isinstance(team_id, str) or not team_id.strip():
            raise ValueError("team_id is required")
        normalized_team_id = self._slug(team_id, max_len=48)
        if not normalized_team_id:
            raise ValueError("team_id is required")
        if normalized_team_id in self._agent_teams:
            raise ValueError(f"Team '{normalized_team_id}' already exists")
        if not description or not str(description).strip():
            raise ValueError("description is required for team creation")
        if self._is_active_team_member_agent(parent_id):
            raise ValueError(
                "Nested team creation is not allowed: team members cannot create new agent teams."
            )

        team = AgentTeam(
            team_id=normalized_team_id,
            parent_id=parent_id,
            description=str(description).strip(),
            collaboration=str(collaboration or "").strip(),
        )
        self._agent_teams[normalized_team_id] = team

        for member in agents or []:
            self.define_team_agent(
                team_id=normalized_team_id,
                agent_id=member.get("agent_id") or member.get("id"),
                description=member.get("description", ""),
                agent_type=member.get("agent_type", "worker"),
                role=member.get("role"),
                task=member.get("task"),
                config_profile=member.get("config_profile"),
                skills=member.get("skills") or [],
                inherit_parent_skills=member.get("inherit_parent_skills", True),
                capabilities=member.get("capabilities") or [],
                model=member.get("model"),
                write_scopes=member.get("write_scopes") or [],
                include_vision=member.get("include_vision"),
                context=member.get("context") or {},
                depends_on=member.get("depends_on") or [],
                disabled_tools=member.get("disabled_tools") or [],
            )

        return team.to_dict()

    def define_team_agent(
        self,
        *,
        team_id: str,
        agent_id: str,
        description: str,
        agent_type: str = "worker",
        role: Optional[str] = None,
        task: Optional[str] = None,
        config_profile: Optional[str] = None,
        skills: Optional[List[str]] = None,
        inherit_parent_skills: bool = True,
        capabilities: Optional[List[str]] = None,
        model: Optional[str] = None,
        write_scopes: Optional[List[str]] = None,
        include_vision: Optional[bool] = None,
        context: Optional[Dict[str, Any]] = None,
        depends_on: Optional[List[str]] = None,
        disabled_tools: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        team = self._agent_teams.get(team_id)
        if not team:
            raise ValueError(f"Team '{team_id}' not found")
        if team.status not in {"created"}:
            raise ValueError(f"Team '{team_id}' is already launched; cannot redefine members")

        if not isinstance(agent_id, str) or not agent_id.strip():
            raise ValueError("agent_id is required")
        member_id = self._slug(agent_id, max_len=48)
        if not member_id:
            raise ValueError("agent_id is required")
        if not description or not str(description).strip():
            raise ValueError("description is required")
        normalized_agent_type = (agent_type or "worker").strip().lower() or "worker"
        normalized_config_profile = (
            str(config_profile).strip().lower()
            if isinstance(config_profile, str) and config_profile.strip()
            else None
        )
        if team.parent_id == "orchestrator" and normalized_agent_type in self.STATIC_CORE_AGENT_TYPES:
            raise ValueError(
                f"orchestrator-led dynamic teams cannot define core static role '{normalized_agent_type}'. "
                f"Use send_message(msg_type='task_ready') to the existing static agent instead."
            )
        if (
            normalized_config_profile
            and normalized_agent_type in self.STATIC_CORE_AGENT_TYPES
            and normalized_config_profile in self.STATIC_CORE_AGENT_TYPES
            and normalized_agent_type != normalized_config_profile
        ):
            raise ValueError(
                "Dynamic team member cannot mix different static core roles. "
                f"agent_type='{normalized_agent_type}', config_profile='{normalized_config_profile}'. "
                "Use a neutral agent_type such as 'analysis_worker' or 'review_worker' for cross-domain inspection."
            )
        context_payload = context or {}
        context_shape_error = self._validate_file_contract_context_shape(context_payload)
        if context_shape_error:
            raise ValueError(f"E_CHILD_TASK_CONTRACT: {context_shape_error}")

        depends = [self._slug(dep, max_len=48) for dep in (depends_on or []) if isinstance(dep, str) and dep.strip()]
        spec = TeamAgentSpec(
            agent_id=member_id,
            description=str(description).strip(),
            agent_type=normalized_agent_type,
            role=role,
            task=task,
            config_profile=normalized_config_profile,
            skills=self._normalize_tool_names(skills),
            inherit_parent_skills=bool(inherit_parent_skills),
            capabilities=self._normalize_tool_names(capabilities),
            model=(str(model).strip() if isinstance(model, str) and model.strip() else None),
            write_scopes=self._normalize_tool_names(write_scopes),
            include_vision=include_vision if isinstance(include_vision, bool) else None,
            context=context_payload,
            depends_on=depends,
            disabled_tools=self._normalize_tool_names(disabled_tools),
        )
        team.members[member_id] = spec
        team.member_states[member_id] = "pending"
        return spec.to_dict()

    async def _run_team_launch(
        self,
        *,
        team_id: str,
        parent_id: Optional[str],
        timeout_per_member: float,
    ) -> Dict[str, Any]:
        team = self._agent_teams[team_id]
        team.status = "running"
        launch_parent = parent_id or team.parent_id
        levels = self._topological_levels(team.members)

        for level in levels:
            launched_batch: List[tuple[str, str]] = []
            for member_id in level:
                if team.member_states.get(member_id) == "completed":
                    continue
                spec = team.members[member_id]
                task_prompt = self._build_team_member_task_prompt(
                    team=team,
                    spec=spec,
                    member_id=member_id,
                    parent_id=launch_parent,
                )
                runtime_id = await self.spawn_worker(
                    worker_type=spec.agent_type,
                    task=task_prompt,
                    parent_id=launch_parent,
                    role=spec.role,
                    model=spec.model,
                    custom_name=member_id,
                    disabled_tools=spec.disabled_tools,
                    config_key=spec.config_profile,
                    skills=spec.skills,
                    inherit_parent_skills=spec.inherit_parent_skills,
                    write_scopes=spec.write_scopes,
                    include_vision=spec.include_vision,
                    team_id=team.team_id,
                    team_member_id=member_id,
                )
                team.runtime_agent_ids[member_id] = runtime_id
                if member_id not in team.launch_order:
                    team.launch_order.append(member_id)
                team.member_states[member_id] = "running"
                launched_batch.append((member_id, runtime_id))

            async def _wait_for_member(member_id: str, runtime_id: str) -> None:
                spawned = self._spawned_agents.get(runtime_id)
                if spawned and spawned.task_done_event:
                    try:
                        await asyncio.wait_for(spawned.task_done_event.wait(), timeout=timeout_per_member)
                        team.member_states[member_id] = "completed"
                    except asyncio.TimeoutError as e:
                        team.member_states[member_id] = "failed"
                        raise TimeoutError(f"Team member '{member_id}' timed out") from e
                else:
                    team.member_states[member_id] = "failed"
                    raise RuntimeError(f"Team member '{member_id}' missing completion event")

            if launched_batch:
                wait_results = await asyncio.gather(
                    *[_wait_for_member(member_id, runtime_id) for member_id, runtime_id in launched_batch],
                    return_exceptions=True,
                )
                failures = [
                    (member_id, result)
                    for (member_id, _), result in zip(launched_batch, wait_results)
                    if isinstance(result, Exception)
                ]
                if failures:
                    member_id, error = failures[0]
                    raise RuntimeError(f"Team member '{member_id}' failed: {error}") from error

        team.status = "completed"
        return self.get_agent_team_status(team_id=team_id)

    async def launch_agent_team(
        self,
        *,
        team_id: str,
        parent_id: Optional[str] = None,
        timeout_per_member: float = 300.0,
        wait_for_completion: bool = True,
    ) -> Dict[str, Any]:
        team = self._agent_teams.get(team_id)
        if not team:
            raise ValueError(f"Team '{team_id}' not found")
        if self._is_active_team_member_agent(parent_id):
            raise ValueError(
                "Nested team launch is not allowed: team members cannot launch agent teams."
            )
        if not team.members:
            raise ValueError(f"Team '{team_id}' has no members defined")
        if team.status not in {"created", "paused", "failed"}:
            raise ValueError(f"Team '{team_id}' cannot be launched from status '{team.status}'")
        ownership_validation = self._validate_team_member_file_ownership(team)
        duplicate_owners = ownership_validation.get("duplicate_owners") or []
        self_conflicts = ownership_validation.get("self_conflicts") or []
        if duplicate_owners or self_conflicts:
            details = {
                "team_id": team_id,
                "duplicate_owners": duplicate_owners,
                "self_conflicts": self_conflicts,
            }
            self._report_team_conflict_to_hub(
                conflict_type="launch_contract_conflict",
                team_id=team_id,
                parent_id=parent_id or team.parent_id,
                details=details,
                severity="error",
            )
            raise ValueError(
                "E_FILE_CLAIM_CONFLICT: team member file ownership contract is invalid before launch. "
                f"details={json.dumps(details, ensure_ascii=False)}"
            )

        existing_task = self._team_launch_tasks.get(team_id)
        if existing_task and not existing_task.done():
            raise ValueError(f"Team '{team_id}' is already launching/running")

        team.status = "launching"
        team.launched_at = datetime.now()
        team.last_error = None
        launch_parent = parent_id or team.parent_id

        if wait_for_completion:
            try:
                return await self._run_team_launch(
                    team_id=team_id,
                    parent_id=launch_parent,
                    timeout_per_member=timeout_per_member,
                )
            except Exception as e:
                team.status = "failed"
                team.last_error = str(e)
                raise

        task = asyncio.create_task(
            self._run_team_launch(
                team_id=team_id,
                parent_id=launch_parent,
                timeout_per_member=timeout_per_member,
            )
        )
        self._team_launch_tasks[team_id] = task

        def _done_callback(done_task: asyncio.Task) -> None:
            final_status = team.status
            final_error: Optional[str] = None
            try:
                done_task.result()
                final_status = team.status
            except asyncio.CancelledError:
                if team.status not in {"paused", "terminated"}:
                    team.status = "paused"
                final_status = team.status
            except Exception as e:
                if team.status not in {"paused", "terminated"}:
                    team.status = "failed"
                    team.last_error = str(e)
                final_status = team.status
                final_error = str(e)
            finally:
                if self._team_launch_tasks.get(team_id) is done_task:
                    self._team_launch_tasks.pop(team_id, None)
                if launch_parent and final_status in {"completed", "failed"}:
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(
                            self._notify_parent_team_completion(
                                parent_id=launch_parent,
                                team_id=team_id,
                                status=final_status,
                                error_message=final_error or team.last_error,
                            )
                        )
                    except Exception as notify_error:
                        self._logger.debug(
                            "Failed to schedule team completion notification for %s: %s",
                            team_id,
                            notify_error,
                        )

        task.add_done_callback(_done_callback)
        return self.get_agent_team_status(team_id=team_id)

    async def pause_agent_team(self, *, team_id: str, wait: bool = True) -> Dict[str, Any]:
        team = self._agent_teams.get(team_id)
        if not team:
            raise ValueError(f"Team '{team_id}' not found")
        if team.status not in {"launching", "running"}:
            raise ValueError(f"Team '{team_id}' is not running (status={team.status})")

        launch_task = self._team_launch_tasks.get(team_id)
        if launch_task and not launch_task.done():
            launch_task.cancel()
            self._team_launch_tasks.pop(team_id, None)

        terminated_members: List[str] = []
        for member_id, runtime_id in list(team.runtime_agent_ids.items()):
            spawned = self._spawned_agents.get(runtime_id)
            if not spawned:
                continue
            if spawned.lifecycle in (AgentLifecycle.TERMINATED, AgentLifecycle.SHUTTING_DOWN):
                continue
            if await self.terminate_runtime_agent(runtime_id, wait=wait):
                terminated_members.append(member_id)
                if team.member_states.get(member_id) != "completed":
                    team.member_states[member_id] = "paused"

        team.status = "paused"
        return {
            "team_id": team_id,
            "status": team.status,
            "paused_members": terminated_members,
            "paused_count": len(terminated_members),
        }

    async def resume_agent_team(
        self,
        *,
        team_id: str,
        parent_id: Optional[str] = None,
        timeout_per_member: float = 300.0,
        wait_for_completion: bool = False,
    ) -> Dict[str, Any]:
        team = self._agent_teams.get(team_id)
        if not team:
            raise ValueError(f"Team '{team_id}' not found")
        if team.status not in {"paused", "failed"}:
            raise ValueError(f"Team '{team_id}' cannot be resumed from status '{team.status}'")

        for member_id, state in list(team.member_states.items()):
            if state in {"paused", "failed"}:
                old_runtime_id = team.runtime_agent_ids.pop(member_id, None)
                if old_runtime_id:
                    ledger = self._agent_ledger.get(old_runtime_id)
                    if ledger:
                        ledger["status"] = "superseded"
                        ledger["superseded_at"] = datetime.now().isoformat()
                        ledger["superseded_by_resume_team_id"] = team_id
                        ledger["updated_at"] = datetime.now().isoformat()
                team.member_states[member_id] = "pending"

        return await self.launch_agent_team(
            team_id=team_id,
            parent_id=parent_id,
            timeout_per_member=timeout_per_member,
            wait_for_completion=wait_for_completion,
        )

    def get_agent_team_status(self, *, team_id: str) -> Dict[str, Any]:
        team = self._agent_teams.get(team_id)
        if not team:
            raise ValueError(f"Team '{team_id}' not found")

        member_runtime: Dict[str, Any] = {}
        for member_id, runtime_id in team.runtime_agent_ids.items():
            spawned = self._spawned_agents.get(runtime_id)
            ledger = self._agent_ledger.get(runtime_id, {})
            member_runtime[member_id] = {
                "runtime_agent_id": runtime_id,
                "lifecycle": spawned.lifecycle.value if spawned else "unknown",
                "requested_type": ledger.get("requested_type"),
                "config_profile": ledger.get("config_profile"),
                "status": ledger.get("status"),
            }

        return {
            **team.to_dict(),
            "launch_task_active": bool(self._team_launch_tasks.get(team_id) and not self._team_launch_tasks[team_id].done()),
            "member_runtime": member_runtime,
            "active_members": len(
                [
                    v for v in member_runtime.values()
                    if v.get("lifecycle") not in {"terminated", "shutting_down", "unknown"}
                ]
            ),
        }

    async def terminate_agent_team(self, *, team_id: str, wait: bool = True) -> Dict[str, Any]:
        team = self._agent_teams.get(team_id)
        if not team:
            raise ValueError(f"Team '{team_id}' not found")
        launch_task = self._team_launch_tasks.get(team_id)
        if launch_task and not launch_task.done():
            launch_task.cancel()
            self._team_launch_tasks.pop(team_id, None)
        terminated: List[str] = []
        for member_id, runtime_id in list(team.runtime_agent_ids.items()):
            if await self.terminate_runtime_agent(runtime_id, wait=wait):
                terminated.append(runtime_id)
                if team.member_states.get(member_id) != "completed":
                    team.member_states[member_id] = "terminated"
        team.status = "terminated"
        return {
            "team_id": team_id,
            "terminated_agents": terminated,
            "terminated_count": len(terminated),
            "total_agents": len(team.runtime_agent_ids),
        }

    def list_agent_teams(self) -> List[Dict[str, Any]]:
        return [team.to_dict() for team in self._agent_teams.values()]
