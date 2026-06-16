"""Shared imports/helpers for split team tool modules."""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.tool import BaseTool, ToolResult, create_tool_param, ToolCategory

from .shared import _merge_team_member_context
from .managed_team_shared import _managed_team_member_schema_properties


class CreateAgentTeamTool(BaseTool):
    """Create a managed agent team definition."""

    NAME = "create_agent_team"
    DESCRIPTION = """Create a managed agent team.

This defines:
- team_id
- team-level work description
- team collaboration relationship
- optional initial member list

Managed team members can now include richer runtime fields such as:
- `agent_type` + optional `config_profile`
- `skills` and `inherit_parent_skills`
- `capabilities`
- `model`
- `write_scopes`
- `include_vision`

Use this before defining members and launching the team.
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
                    "team_id": {"type": "string", "description": "Unique team ID"},
                    "description": {"type": "string", "description": "Overall team objective and constraints"},
                    "collaboration": {"type": "string", "description": "Collaboration/coordination policy"},
                    "agents": {
                        "type": "array",
                        "description": "Optional initial team members",
                        "items": {
                            "type": "object",
                            "properties": _managed_team_member_schema_properties(),
                            "required": ["agent_id", "description"],
                        },
                    },
                },
                "required": ["team_id", "description"],
            },
        )

    def execute(
        self,
        team_id: str,
        description: str,
        collaboration: str = "",
        agents: Optional[List[Dict[str, Any]]] = None,
        **kwargs,
    ) -> ToolResult:
        if not self._agent_manager:
            return ToolResult(success=False, error_message="Agent manager not configured")
        try:
            normalized_agents: List[Dict[str, Any]] = []
            for member in agents or []:
                member_copy = dict(member or {})
                member_copy["context"] = _merge_team_member_context(
                    context=member_copy.get("context"),
                    writing_style=member_copy.get("writing_style"),
                    supervision=member_copy.get("supervision"),
                )
                normalized_agents.append(member_copy)

            team = self._agent_manager.create_agent_team(
                team_id=team_id,
                parent_id=self._agent_id,
                description=description,
                collaboration=collaboration,
                agents=normalized_agents,
            )
            return ToolResult(success=True, data={"team": team})
        except Exception as e:
            return ToolResult(success=False, error_message=str(e))
class DefineTeamAgentTool(BaseTool):
    """Define or update a member in a managed team."""

    NAME = "define_team_agent"
    DESCRIPTION = """Define one agent inside an existing team.

Parent agent controls:
- member id and description
- optional dependency graph (depends_on)
- optional disabled_tools list
- optional agent_type/role/task/context
- optional `config_profile`, `skills`, `inherit_parent_skills`
- optional `capabilities`, `model`, `write_scopes`, `include_vision`
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
                    "team_id": {"type": "string"},
                    "agent_id": {"type": "string"},
                    "description": {"type": "string"},
                    **_managed_team_member_schema_properties(),
                },
                "required": ["team_id", "agent_id", "description"],
            },
        )

    def execute(
        self,
        team_id: str,
        agent_id: str,
        description: str,
        agent_type: str = "worker",
        config_profile: Optional[str] = None,
        role: Optional[str] = None,
        task: Optional[str] = None,
        writing_style: Optional[str] = None,
        supervision: Optional[str] = None,
        skills: Optional[List[str]] = None,
        inherit_parent_skills: bool = True,
        capabilities: Optional[List[str]] = None,
        model: Optional[str] = None,
        write_scopes: Optional[List[str]] = None,
        include_vision: Optional[bool] = None,
        depends_on: Optional[List[str]] = None,
        disabled_tools: Optional[List[str]] = None,
        context: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> ToolResult:
        if not self._agent_manager:
            return ToolResult(success=False, error_message="Agent manager not configured")
        try:
            member = self._agent_manager.define_team_agent(
                team_id=team_id,
                agent_id=agent_id,
                description=description,
                agent_type=agent_type,
                config_profile=config_profile,
                role=role,
                task=task,
                skills=skills or [],
                inherit_parent_skills=inherit_parent_skills,
                capabilities=capabilities or [],
                model=model,
                write_scopes=write_scopes or [],
                include_vision=include_vision,
                context=_merge_team_member_context(
                    context=context,
                    writing_style=writing_style,
                    supervision=supervision,
                ),
                depends_on=depends_on or [],
                disabled_tools=disabled_tools or [],
            )
            return ToolResult(success=True, data={"member": member})
        except Exception as e:
            return ToolResult(success=False, error_message=str(e))
class LaunchAgentTeamTool(BaseTool):
    """Launch a managed agent team."""

    NAME = "launch_agent_team"
    DESCRIPTION = """Launch a previously created team by team_id.

Launch semantics:
- members are started in dependency order
- each member receives team description + collaboration + member description
- richer member runtime fields (profile, skills, model, write scopes, vision override) are passed through to spawn
- disabled tools are enforced before execution
- supports non-blocking mode for parent-side monitoring
- in non-blocking mode, the parent receives an automatic team completion/failure message when the launch run ends
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
                    "team_id": {"type": "string"},
                    "timeout_per_member": {
                        "type": "number",
                        "description": "Wait timeout per dependency level member",
                        "default": 300.0,
                    },
                    "wait_for_completion": {
                        "type": "boolean",
                        "description": "If false, return immediately after launch starts",
                        "default": False,
                    },
                },
                "required": ["team_id"],
            },
        )

    async def execute(
        self,
        team_id: str,
        timeout_per_member: float = 300.0,
        wait_for_completion: bool = False,
        **kwargs,
    ) -> ToolResult:
        if not self._agent_manager:
            return ToolResult(success=False, error_message="Agent manager not configured")
        try:
            team_status = await self._agent_manager.launch_agent_team(
                team_id=team_id,
                parent_id=self._agent_id,
                timeout_per_member=timeout_per_member,
                wait_for_completion=wait_for_completion,
            )
            return ToolResult(success=True, data={"team": team_status})
        except Exception as e:
            return ToolResult(success=False, error_message=str(e))
class MonitorAgentTeamTool(BaseTool):
    """Monitor one team or list all teams."""

    NAME = "monitor_agent_team"
    DESCRIPTION = """Monitor managed team status.

If team_id is provided, returns detailed status for that team.
If team_id is omitted, returns all teams and current agent registry snapshot.
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
                    "team_id": {"type": "string", "description": "Optional team ID"},
                },
            },
        )

    def execute(self, team_id: Optional[str] = None, **kwargs) -> ToolResult:
        if not self._agent_manager:
            return ToolResult(success=False, error_message="Agent manager not configured")
        try:
            if team_id:
                return ToolResult(
                    success=True,
                    data={"team": self._agent_manager.get_agent_team_status(team_id=team_id)},
                )
            return ToolResult(
                success=True,
                data={
                    "teams": self._agent_manager.list_agent_teams(),
                    "agent_registry": self._agent_manager.get_agent_registry_snapshot(),
                },
            )
        except Exception as e:
            return ToolResult(success=False, error_message=str(e))
class PauseAgentTeamTool(BaseTool):
    """Pause a running managed team."""

    NAME = "pause_agent_team"
    DESCRIPTION = """Pause a running/launching managed team by team_id.

This stops in-flight launch orchestration and terminates active team members,
so the parent can inspect state and later resume.
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
                    "team_id": {"type": "string"},
                    "wait": {"type": "boolean", "default": True},
                },
                "required": ["team_id"],
            },
        )

    async def execute(self, team_id: str, wait: bool = True, **kwargs) -> ToolResult:
        if not self._agent_manager:
            return ToolResult(success=False, error_message="Agent manager not configured")
        try:
            result = await self._agent_manager.pause_agent_team(team_id=team_id, wait=wait)
            return ToolResult(success=True, data=result)
        except Exception as e:
            return ToolResult(success=False, error_message=str(e))
class ResumeAgentTeamTool(BaseTool):
    """Resume a paused/failed managed team."""

    NAME = "resume_agent_team"
    DESCRIPTION = """Resume a paused (or failed) managed team.

By default this is non-blocking and should be paired with monitor_agent_team.
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
                    "team_id": {"type": "string"},
                    "timeout_per_member": {
                        "type": "number",
                        "default": 300.0,
                    },
                    "wait_for_completion": {
                        "type": "boolean",
                        "default": False,
                    },
                },
                "required": ["team_id"],
            },
        )

    async def execute(
        self,
        team_id: str,
        timeout_per_member: float = 300.0,
        wait_for_completion: bool = False,
        **kwargs,
    ) -> ToolResult:
        if not self._agent_manager:
            return ToolResult(success=False, error_message="Agent manager not configured")
        try:
            result = await self._agent_manager.resume_agent_team(
                team_id=team_id,
                parent_id=self._agent_id,
                timeout_per_member=timeout_per_member,
                wait_for_completion=wait_for_completion,
            )
            return ToolResult(success=True, data={"team": result})
        except Exception as e:
            return ToolResult(success=False, error_message=str(e))
class TerminateAgentTeamTool(BaseTool):
    """Terminate an entire managed team."""

    NAME = "terminate_agent_team"
    DESCRIPTION = """Terminate all launched agents in a managed team by team_id."""

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
                    "team_id": {"type": "string"},
                    "wait": {"type": "boolean", "default": True},
                },
                "required": ["team_id"],
            },
        )

    async def execute(self, team_id: str, wait: bool = True, **kwargs) -> ToolResult:
        if not self._agent_manager:
            return ToolResult(success=False, error_message="Agent manager not configured")
        try:
            result = await self._agent_manager.terminate_agent_team(team_id=team_id, wait=wait)
            return ToolResult(success=True, data=result)
        except Exception as e:
            return ToolResult(success=False, error_message=str(e))


# ============================================================
# 2. PARALLEL REASONING TOOLS
# ============================================================
