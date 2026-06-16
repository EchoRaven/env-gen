"""Shared imports/helpers for split team tool modules."""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.tool import BaseTool, ToolResult, create_tool_param, ToolCategory


class SpawnWorkerTool(BaseTool):
    """Spawn a new task-scoped worker using neutral worker terminology."""

    NAME = "spawn_worker"
    DESCRIPTION = """Spawn a task-scoped worker runtime.

Use this when you need:
- an analysis worker
- a review worker
- a parallel implementation worker
- a temporary bug-fix or research worker

Strict runtime rule:
- `worker_type` may be a real execution profile such as `analysis_worker`
- if `worker_type` is only a custom runtime label, you must also provide
  `config_profile`
- do not mix static core roles: `worker_type="backend"` with
  `config_profile="frontend"` is invalid. For cross-domain inspection, use
  `worker_type="analysis_worker"` or `review_worker` and choose one backing
  `config_profile`.
- workers inherit parent skills by default unless `inherit_parent_skills=false`
- set `wait_for_completion=true` if the parent should block until the worker finishes
- otherwise the worker runs in background and its result is sent back to the parent via message bus

Examples:
    spawn_worker(worker_type="analysis_worker", task="Investigate database query bug", role="root_cause_analyst")
    spawn_worker(worker_type="security_auditor", task="Review backend auth flow for security issues", config_profile="review_worker")
"""

    def __init__(self):
        super().__init__(name=self.NAME, category=ToolCategory.CUSTOM)
        self._agent_manager = None
        self._agent_id = None

    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME,
            description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "worker_type": {
                        "type": "string",
                        "description": "Runtime worker label (free-form). Examples: analysis_worker, security_auditor, implementation_worker, parallel_worker, bugfix_worker",
                    },
                    "task": {
                        "type": "string",
                        "description": "Task for this worker runtime",
                    },
                    "role": {
                        "type": "string",
                        "description": "Optional role specialization for the worker",
                    },
                    "config_profile": {
                        "type": "string",
                        "description": "Explicit backing profile/config id. Required when worker_type is a custom runtime label. Examples: backend, frontend, review_worker, analysis_worker, worker",
                    },
                    "custom_name": {
                        "type": "string",
                        "description": "Optional display name for this worker runtime",
                    },
                    "model": {
                        "type": "string",
                        "description": "Optional model override for this worker runtime",
                    },
                    "disabled_tools": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional tools to remove from the worker surface",
                    },
                    "write_scopes": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional workspace path prefixes this worker may write",
                    },
                    "include_vision": {
                        "type": "boolean",
                        "description": "Optional override for enabling vision tools",
                    },
                    "skills": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional explicit skill allowlist override for this worker",
                    },
                    "inherit_parent_skills": {
                        "type": "boolean",
                        "description": "Whether to union parent skills into the worker skill set (default: true)",
                    },
                    "wait_for_completion": {
                        "type": "boolean",
                        "description": "If true, wait until the spawned worker finishes before continuing",
                        "default": False,
                    },
                    "timeout_seconds": {
                        "type": "number",
                        "description": "When wait_for_completion=true, max seconds to wait for worker completion",
                        "default": 300.0,
                    },
                },
                "required": ["worker_type", "task"],
            }
        )

    async def execute(
        self,
        worker_type: str,
        task: str,
        role: Optional[str] = None,
        model: Optional[str] = None,
        config_profile: Optional[str] = None,
        custom_name: Optional[str] = None,
        disabled_tools: Optional[List[str]] = None,
        write_scopes: Optional[List[str]] = None,
        include_vision: Optional[bool] = None,
        skills: Optional[List[str]] = None,
        inherit_parent_skills: bool = True,
        wait_for_completion: bool = False,
        timeout_seconds: float = 300.0,
        **kwargs
    ) -> ToolResult:
        if not self._agent_manager:
            return ToolResult(success=False, error_message="Agent manager not configured")

        try:
            runtime_id = await self._agent_manager.spawn_worker(
                worker_type=worker_type,
                task=task,
                parent_id=self._agent_id,
                role=role,
                model=model,
                config_key=config_profile,
                custom_name=custom_name,
                disabled_tools=disabled_tools,
                write_scopes=write_scopes,
                include_vision=include_vision,
                skills=skills,
                inherit_parent_skills=inherit_parent_skills,
            )
            completion = None
            if wait_for_completion:
                completion = await self._agent_manager.wait_for_runtime_agent(
                    agent_id=runtime_id,
                    timeout=timeout_seconds,
                )
            return ToolResult(
                success=True,
                data={
                    "agent_id": runtime_id,
                    "worker_type": worker_type,
                    "role": role,
                    "task": task[:100] + "..." if len(task) > 100 else task,
                    "model": model,
                    "config_profile": config_profile,
                    "disabled_tools": disabled_tools or [],
                    "write_scopes": write_scopes or [],
                    "include_vision": include_vision,
                    "skills": skills or [],
                    "inherit_parent_skills": inherit_parent_skills,
                    "wait_for_completion": wait_for_completion,
                    "timeout_seconds": timeout_seconds if wait_for_completion else None,
                    "completion": completion,
                },
            )
        except Exception as e:
            return ToolResult(success=False, error_message=str(e))
class TerminateRuntimeAgentTool(BaseTool):
    """Terminate any runtime agent instance using neutral naming."""

    NAME = "terminate_runtime_agent"
    DESCRIPTION = """Terminate a runtime agent instance.

Use this when:
- a task-scoped worker has finished
- a resident or ephemeral runtime is stuck
- you want runtime-centric lifecycle control terminology

Example:
    terminate_runtime_agent(agent_id="review_worker_backend_ab12cd34")
"""

    def __init__(self):
        super().__init__(name=self.NAME, category=ToolCategory.CUSTOM)
        self._agent_manager = None

    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME,
            description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "Runtime agent instance ID to terminate",
                    },
                },
                "required": ["agent_id"],
            }
        )

    async def execute(self, agent_id: str, **kwargs) -> ToolResult:
        if not self._agent_manager:
            return ToolResult(success=False, error_message="Agent manager not configured")

        try:
            success = await self._agent_manager.terminate_runtime_agent(agent_id)
            if success:
                return ToolResult(success=True, data={"terminated": agent_id})
            return ToolResult(success=False, error_message=f"Failed to terminate runtime agent {agent_id}")
        except Exception as e:
            return ToolResult(success=False, error_message=str(e))
class ListRuntimeAgentsTool(BaseTool):
    """List all registered runtime agents across resident and ephemeral lifecycles."""

    NAME = "list_runtime_agents"
    DESCRIPTION = """List all registered runtime agents.

Shows:
- resident lanes supervised by orchestrator
- ephemeral workers spawned at runtime
- profile id, lifecycle, parent linkage, and write scopes

Example:
    list_runtime_agents()
"""

    def __init__(self):
        super().__init__(name=self.NAME, category=ToolCategory.CUSTOM)
        self._agent_manager = None

    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME,
            description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {},
            }
        )

    def execute(self, **kwargs) -> ToolResult:
        if not self._agent_manager:
            return ToolResult(success=False, error_message="Agent manager not configured")

        snapshot = self._agent_manager.get_runtime_registry_snapshot()
        return ToolResult(success=True, data=snapshot)
class TeamHealthSummaryTool(BaseTool):
    """Get dynamic team operational health summary."""

    NAME = "team_health_summary"
    DESCRIPTION = """Return a lightweight operational snapshot for dynamic collaboration.

Includes:
- recent success/failure rate
- spawn budget and circuit-breaker status
- dedup/contract validation rates
- recent parallel run duration stats
- recommended action distribution from recent failures

Example:
    team_health_summary()
"""

    def __init__(self):
        super().__init__(name=self.NAME, category=ToolCategory.CUSTOM)
        self._agent_manager = None

    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME,
            description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {},
            }
        )

    def execute(self, **kwargs) -> ToolResult:
        if not self._agent_manager:
            return ToolResult(success=False, error_message="Agent manager not configured")
        try:
            return ToolResult(
                success=True,
                data=self._agent_manager.get_team_health_summary(),
            )
        except Exception as e:
            return ToolResult(success=False, error_message=str(e))


# ------------------------------------------------------------
# Managed Team Lifecycle Tools (create -> define -> launch -> monitor -> terminate)
# ------------------------------------------------------------
