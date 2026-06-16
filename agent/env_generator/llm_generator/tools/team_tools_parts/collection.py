"""Collection helpers for split team tool modules."""

from typing import List

from utils.tool import BaseTool

from .runtime_management import (
    SpawnWorkerTool, TerminateRuntimeAgentTool, ListRuntimeAgentsTool, TeamHealthSummaryTool,
)
from .managed_team import (
    CreateAgentTeamTool, DefineTeamAgentTool, LaunchAgentTeamTool, MonitorAgentTeamTool,
    PauseAgentTeamTool, ResumeAgentTeamTool, TerminateAgentTeamTool,
)
from .reasoning import RunParallelReasoningTool
from .approval import (
    SubmitPlanTool, AcceptPlanTool, RequestPlanChangesTool, ListPendingPlanDecisionsTool,
)
from .parallel import ParallelExecuteTool

def get_team_tools() -> List[BaseTool]:
    """Get team protocol tools."""
    return [
        # Low-level Dynamic Agent Operations
        SpawnWorkerTool(),
        TerminateRuntimeAgentTool(),
        ListRuntimeAgentsTool(),

        # Managed Team Operations
        TeamHealthSummaryTool(),
        CreateAgentTeamTool(),
        DefineTeamAgentTool(),
        LaunchAgentTeamTool(),
        MonitorAgentTeamTool(),
        PauseAgentTeamTool(),
        ResumeAgentTeamTool(),
        TerminateAgentTeamTool(),
        
        # Parallel Reasoning
        RunParallelReasoningTool(),

        # Plan Decision
        SubmitPlanTool(),
        AcceptPlanTool(),
        RequestPlanChangesTool(),
        ListPendingPlanDecisionsTool(),

        # Parallel Execution
        ParallelExecuteTool(),
    ]


def inject_team_protocols(
    tools: List[BaseTool],
    agent_id: str,
    agent_manager=None,
    persona_catalog=None,
    plan_decision=None,
    parallel_reasoning=None,
    practice_store=None,
) -> None:
    """Inject team protocols into tools."""
    for tool in tools:
        if hasattr(tool, "_agent_id"):
            tool._agent_id = agent_id
        if hasattr(tool, "_agent_manager"):
            tool._agent_manager = agent_manager
        if hasattr(tool, "_persona_catalog"):
            tool._persona_catalog = persona_catalog
        if hasattr(tool, "_plan_decision"):
            tool._plan_decision = plan_decision
        if hasattr(tool, "_parallel_reasoning"):
            tool._parallel_reasoning = parallel_reasoning
        if hasattr(tool, "_practice_store"):
            tool._practice_store = practice_store


__all__ = [
    "get_team_tools",
    "inject_team_protocols",
    "SpawnWorkerTool",
    "TerminateRuntimeAgentTool",
    "ListRuntimeAgentsTool",
    "TeamHealthSummaryTool",
    "CreateAgentTeamTool",
    "DefineTeamAgentTool",
    "LaunchAgentTeamTool",
    "MonitorAgentTeamTool",
    "PauseAgentTeamTool",
    "ResumeAgentTeamTool",
    "TerminateAgentTeamTool",
    "RunParallelReasoningTool",
    "SubmitPlanTool",
    "AcceptPlanTool",
    "RequestPlanChangesTool",
    "ListPendingPlanDecisionsTool",
    # Parallel Execution
    "ParallelExecuteTool",
]
