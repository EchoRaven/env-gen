"""
Unified agent spawn runtime for resident and ephemeral agents.

Phase 1 goal:
- keep the existing agent loop/runtime intact
- centralize low-level spawn/terminate logic in one place
- let both orchestrator-started core agents and dynamically spawned agents
  use the same creation path
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .agents.configurable_agent import create_agent, list_available_agents


logger = logging.getLogger(__name__)


STATIC_CORE_AGENT_TYPES = {
    "database", "backend", "frontend",
    "verifier", "knowledge", "orchestrator",
}


@dataclass
class AgentSpawnRequest:
    """Low-level spawn request shared by resident and ephemeral agents."""

    agent_id: str
    agent_type: str
    task: Optional[str] = None
    parent_id: Optional[str] = None
    role: Optional[str] = None
    model: Optional[str] = None
    custom_name: Optional[str] = None
    disabled_tools: Optional[List[str]] = None
    write_scopes: Optional[List[str]] = None
    config_key: Optional[str] = None
    skills: Optional[List[str]] = None
    inherit_parent_skills: bool = True
    include_vision: Optional[bool] = None
    resident: bool = False
    wait_ready_timeout: float = 30.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    inherit_worktree: bool = False


@dataclass
class AgentSpawnResult:
    """Result of a successful spawn operation."""

    agent_id: str
    requested_type: str
    config_profile: str
    resident: bool
    agent: Any
    write_scopes: List[str] = field(default_factory=list)
    task_done_event: Optional[asyncio.Event] = None
    removed_tools: List[str] = field(default_factory=list)


class AgentSpawnService:
    """
    Shared spawn runtime for all agent instances.

    This service intentionally stays low-level:
    - it creates, wires, starts, and optionally seeds a task for an agent
    - higher-level collaboration semantics remain in DynamicAgentManager
    - orchestrator can use the same spawn path for resident core agents
    """

    def __init__(self, orchestrator: Any):
        self._orchestrator = orchestrator
        self._logger = logging.getLogger("AgentSpawnService")

    def _normalize_tool_names(self, tool_names: Optional[List[str]]) -> List[str]:
        normalized: List[str] = []
        seen = set()
        for name in tool_names or []:
            if not isinstance(name, str):
                continue
            cleaned = name.strip()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            normalized.append(cleaned)
        return normalized

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

    def _derive_parent_overrides(self, parent_id: Optional[str]) -> Dict[str, Any]:
        parent_agent = self._orchestrator._agents.get(parent_id) if parent_id else None
        permission_parent_id = parent_id
        inherited_tool_categories = None
        tool_profile_agent_type = None
        include_vision_override = None
        inherited_skills = None

        if parent_agent is not None:
            inherited = getattr(parent_agent, "_permission_parent_id", None)
            if inherited:
                permission_parent_id = inherited

            parent_categories = getattr(parent_agent, "allowed_tool_categories", None)
            if parent_categories:
                inherited_tool_categories = list(parent_categories)

            tool_profile_agent_type = getattr(
                parent_agent,
                "_tool_profile_agent_type",
                getattr(parent_agent, "_config_key", parent_id),
            )
            include_vision_override = bool(getattr(parent_agent, "_include_vision", False))
            parent_skills = getattr(parent_agent, "_skills", None)
            if parent_skills:
                inherited_skills = [skill.name for skill in parent_skills if getattr(skill, "name", None)]

        return {
            "parent_agent": parent_agent,
            "permission_parent_id": permission_parent_id,
            "inherited_tool_categories": inherited_tool_categories,
            "tool_profile_agent_type": tool_profile_agent_type,
            "include_vision_override": include_vision_override,
            "inherited_skills": inherited_skills,
        }

    def _resolve_write_scopes(
        self,
        request: AgentSpawnRequest,
        *,
        resolved_config_key: str,
    ) -> List[str]:
        """Return the requested write-scope list for the spawn result.

        Step 4 FOLD: write-scope enforcement moved into ``ROUTING_TABLE``
        (path_routed_workspace.py) keyed by ``agent_id``. The spawn
        service no longer needs to register per-instance scopes with
        the workspace — the routing table is consulted at every
        write-attempt against the agent's id directly. This helper
        kept its return shape for display + spawn-result observability.
        """
        if request.write_scopes:
            return list(request.write_scopes)
        # Inheritance (parent_id / config profile) is now informational
        # only — the gate consults agent_id against the routing table.
        return []

    def _resolve_config_profile(self, request: AgentSpawnRequest, parent_agent: Any, tool_profile_agent_type: Optional[str]) -> str:
        available_agent_configs = set(list_available_agents())
        requested_agent_type = (request.agent_type or "").strip() or "worker"

        resolved_config_key = request.config_key or requested_agent_type
        if request.config_key and resolved_config_key not in available_agent_configs:
            raise ValueError(f"Spawn config/profile '{request.config_key}' not found in config")
        if resolved_config_key not in available_agent_configs:
            raise ValueError(
                "Spawned runtime requires an explicit valid execution profile. "
                f"requested_type='{requested_agent_type}', config_key='{request.config_key}'. "
                f"Available profiles: {sorted(available_agent_configs)}"
            )
        if (
            requested_agent_type in STATIC_CORE_AGENT_TYPES
            and resolved_config_key in STATIC_CORE_AGENT_TYPES
            and requested_agent_type != resolved_config_key
        ):
            raise ValueError(
                "Spawned runtime cannot mix static core agent type and a different static execution profile. "
                f"requested_type='{requested_agent_type}', config_profile='{resolved_config_key}'. "
                "Use a neutral worker_type such as 'analysis_worker' with config_profile set to the desired profile, "
                "or make requested_type match config_profile."
            )
        return resolved_config_key

    async def spawn(self, request: AgentSpawnRequest) -> AgentSpawnResult:
        """
        Create and start one agent instance.

        All agent instances, including orchestrator-owned resident agents, should
        use this path to keep runtime behavior consistent.
        """
        requested_agent_type = (request.agent_type or "").strip() or "worker"
        agent = None
        task_ref = None
        try:
            overrides = self._derive_parent_overrides(request.parent_id)
            parent_agent = overrides["parent_agent"]
            resolved_config_key = self._resolve_config_profile(
                request=request,
                parent_agent=parent_agent,
                tool_profile_agent_type=overrides["tool_profile_agent_type"],
            )

            # A spawn that names its OWN explicit profile (config_key) distinct from the parent must
            # use THAT profile's tool surface — categories, tool bundles, and include_vision — NOT
            # inherit the parent's. Otherwise a specialized agent silently loses its own tool
            # categories: e.g. the one-shot `design_analyst` spawned by the orchestrator inherited
            # the orchestrator's categories (which lack reference/vision), so ALL its measurement
            # tools (sample_color/crop_reference/measure_layout/decompose_reference) were filtered
            # out and it fell back to eyeballing — the whole measure-per-component feature broke,
            # invisibly. Inheritance still applies to same-type helper spawns that share the
            # parent's scope (config_key omitted, or == the parent's profile).
            _parent_key = getattr(parent_agent, "_config_key", None) or request.parent_id
            if request.config_key and resolved_config_key != _parent_key:
                overrides = dict(overrides)
                overrides["inherited_tool_categories"] = None       # → use the profile's tool_categories
                overrides["tool_profile_agent_type"] = resolved_config_key  # assemble the OWN profile's bundles
                overrides["include_vision_override"] = None          # → use the profile's include_vision

            custom_name = request.custom_name
            if custom_name is None and requested_agent_type != resolved_config_key:
                custom_name = requested_agent_type

            # Per-component MODEL config (user feature, 2026-07-09): each profile may
            # run its own model (profiles.<key>.llm in agents_config.yaml, or
            # ENVGEN_MODEL_<KEY> env). No override → the orchestrator's global LLM.
            try:
                from .runtime.llm_overrides import get_component_llm
                _agent_llm = get_component_llm(self._orchestrator, resolved_config_key)
            except Exception:
                _agent_llm = self._orchestrator.llm
            agent = create_agent(
                agent_id=request.agent_id,
                llm=_agent_llm or self._orchestrator.llm,
                workspace_manager=self._orchestrator.workspace,
                config_override={
                    "_config_key": resolved_config_key,
                    "_role": request.role,
                    "_permission_parent_id": overrides["permission_parent_id"],
                    "_inherited_tool_categories": overrides["inherited_tool_categories"],
                    "_tool_profile_agent_type": overrides["tool_profile_agent_type"],
                    "_include_vision": (
                        request.include_vision
                        if request.include_vision is not None
                        else overrides["include_vision_override"]
                    ),
                    "_custom_name": custom_name,
                    "_write_scopes": request.write_scopes,
                    "_requested_agent_type": requested_agent_type,
                    "_skills": request.skills,
                    "_inherit_parent_skills": request.inherit_parent_skills,
                    "_inherited_skills": overrides["inherited_skills"],
                },
            )

            effective_write_scopes = self._resolve_write_scopes(
                request,
                resolved_config_key=resolved_config_key,
            )
            setattr(agent, "_write_scopes", list(effective_write_scopes))
            setattr(agent, "_is_resident_lane", bool(request.resident))

            removed_tools = self._apply_disabled_tools(agent, request.disabled_tools)
            if removed_tools:
                self._logger.info(
                    "Disabled tools for spawned agent %s: %s",
                    request.agent_id,
                    ", ".join(removed_tools),
                )

            agent.set_gen_context(self._orchestrator.context)
            agent.set_message_bus(self._orchestrator.message_bus)

            if hasattr(self._orchestrator, "hubs"):
                agent.set_hubs(self._orchestrator.hubs)

            agent.set_team_protocols(
                agent_manager=self._orchestrator.agent_manager,
                persona_catalog=getattr(self._orchestrator, "persona_catalog", None),
                plan_decision=getattr(self._orchestrator, "plan_decision", None),
                parallel_reasoning=getattr(self._orchestrator, "parallel_reasoning", None),
                practice_store=getattr(self._orchestrator, "team_practice_store", None),
            )

            self._orchestrator._agents[request.agent_id] = agent
            task_ref = asyncio.create_task(agent.run_loop())
            self._orchestrator._agent_tasks[request.agent_id] = task_ref

            if not await agent.wait_ready(timeout=request.wait_ready_timeout):
                raise RuntimeError(f"Spawned agent {request.agent_id} failed to start")

            task_done_event = None
            if request.task:
                task_done_event = await agent.send_task({
                    "task": request.task,
                    "role": request.role,
                    "parent_id": request.parent_id,
                    "resident": request.resident,
                    **(request.metadata or {}),
                })

            runtime_kind = "resident" if request.resident else "ephemeral"
            lifecycle = "working" if request.task else "ready"
            agent_manager = getattr(self._orchestrator, "agent_manager", None)
            if agent_manager is not None and hasattr(agent_manager, "register_runtime_agent"):
                agent_manager.register_runtime_agent(
                    agent_id=request.agent_id,
                    requested_type=requested_agent_type,
                    config_profile=resolved_config_key,
                    parent_id=request.parent_id,
                    role=request.role,
                    write_scopes=effective_write_scopes,
                    runtime_kind=runtime_kind,
                    lifecycle=lifecycle,
                    metadata=request.metadata,
                    team_id=(request.metadata or {}).get("team_id"),
                    team_member_id=(request.metadata or {}).get("team_member_id"),
                )

            self._logger.info(
                "Spawned agent runtime: id=%s requested_type=%s config_profile=%s resident=%s",
                request.agent_id,
                requested_agent_type,
                resolved_config_key,
                request.resident,
            )

            try:
                if not getattr(request, "inherit_worktree", False):
                    self._orchestrator.hubs.codehub.register_agent_worktree(request.agent_id)
            except Exception as exc:
                self._logger.warning(f"[{request.agent_id}] worktree registration failed: {exc}")

            return AgentSpawnResult(
                agent_id=request.agent_id,
                requested_type=requested_agent_type,
                config_profile=resolved_config_key,
                resident=request.resident,
                agent=agent,
                write_scopes=effective_write_scopes,
                task_done_event=task_done_event,
                removed_tools=removed_tools,
            )
        except Exception:
            if task_ref is not None:
                task_ref.cancel()
            if agent is not None:
                try:
                    agent.request_shutdown()
                except Exception:
                    pass
            # Step 4 FOLD: no more per-agent write-scope registration —
            # the routing table is stateless w.r.t. agent lifecycle.
            self._orchestrator._agents.pop(request.agent_id, None)
            self._orchestrator._agent_tasks.pop(request.agent_id, None)
            raise

    async def terminate(self, agent_id: str, wait: bool = True) -> bool:
        """Stop one agent instance created through the shared runtime."""
        agent = self._orchestrator._agents.get(agent_id)
        if not agent:
            agent_manager = getattr(self._orchestrator, "agent_manager", None)
            if agent_manager is not None and hasattr(agent_manager, "set_runtime_agent_lifecycle"):
                agent_manager.set_runtime_agent_lifecycle(agent_id, "terminated")
            return False

        try:
            agent.request_shutdown()
            task = self._orchestrator._agent_tasks.get(agent_id)
            if wait and task:
                try:
                    await asyncio.wait_for(task, timeout=10.0)
                except asyncio.TimeoutError:
                    task.cancel()

            self._orchestrator._agents.pop(agent_id, None)
            self._orchestrator._agent_tasks.pop(agent_id, None)
            agent_manager = getattr(self._orchestrator, "agent_manager", None)
            if agent_manager is not None and hasattr(agent_manager, "set_runtime_agent_lifecycle"):
                agent_manager.set_runtime_agent_lifecycle(agent_id, "terminated")

            # Bug-9: short-lived workers (``worker_*``) accumulate
            # worktrees + branches across the project's lifetime. Reap
            # them here. Core long-lived agents (orchestrator / design /
            # backend / …) keep their worktrees so subsequent runs can
            # pull integration into them.
            if isinstance(agent_id, str) and agent_id.startswith("worker_"):
                hubs = getattr(self._orchestrator, "hubs", None)
                try:
                    if hubs is not None and hasattr(hubs, "codehub"):
                        hubs.codehub.cleanup_worktree(agent_id)
                except Exception as cleanup_err:
                    self._logger.warning(
                        f"worker worktree cleanup skipped for {agent_id}: {cleanup_err}"
                    )
                # Also reap the worker's EventHub subscriptions so the
                # store doesn't accumulate dead rows across many runs.
                try:
                    if hubs is not None and hasattr(hubs, "eventhub") \
                       and hasattr(hubs.eventhub, "unsubscribe_all"):
                        # O14/Phase 4.1: service-initiated reap; use the
                        # "agent_spawn_service" sentinel (privileged via
                        # PHASE_4_1_SERVICE_CALLERS) so the cross-agent
                        # mutation is allowed AND attributable in meta.
                        hubs.eventhub.unsubscribe_all(
                            agent_id, caller="agent_spawn_service",
                        )
                except Exception as sub_err:
                    self._logger.warning(
                        f"worker subscription cleanup skipped for {agent_id}: {sub_err}"
                    )

            self._logger.info("Terminated agent runtime: %s", agent_id)
            return True
        except Exception as e:
            self._logger.error(f"Error terminating agent {agent_id}: {e}")
            return False
