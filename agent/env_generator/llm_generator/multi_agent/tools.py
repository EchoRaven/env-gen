"""
Tools Integration for Multi-Agent System

Provides a minimal baseline plus explicit profile bundles.
"""

from pathlib import Path
from typing import List, Optional

from utils.tool import BaseTool, ToolRegistry
from .tool_runtime import (
    ToolAssemblyContext,
    ToolPermissionContext,
    ToolPoolBuilder,
    normalize_category_filter,
    normalize_tool_name_filter,
)
from .tool_bundles import apply_tool_bundles

# Import from existing tools module
import sys
_llm_gen_dir = Path(__file__).parent.parent
if str(_llm_gen_dir) not in sys.path:
    sys.path.insert(0, str(_llm_gen_dir))

from tools.file_tools import UpdateJsonPathTool, UpdateYamlPathTool
from tools import (
    # Workspace
    Workspace,
    
    # File Tools
    ReadTool,
    WriteTool,
    EditTool as CanonicalEditTool,
    ApplyPatchTool,
    DeleteFileTool,
    GlobTool,
    GrepTool,
    ViewImageTool,
    # FileHistory is a singleton helper, not a tool
    
    # Code Tools
    LintTool,
    
    # Reasoning Tools
    GetTimeTool,
    WaitTool,
    PlanTool,
    VerifyPlanTool,

    # Analysis / project helpers used by full-pool compatibility mode
    create_analysis_tools,
    create_project_tools,
    create_database_tools,
    create_log_tools,

    # Runtime / infra used by full-pool compatibility mode
    ExecuteBashTool,
    FindFreePortTool,
    RunBackgroundTool,
    StopProcessTool,
    ListProcessesTool,
    GetProcessOutputTool,
    TestAPITool,
    create_docker_tools,
    BROWSER_TOOLS_AVAILABLE,
    create_browser_tools,
    create_vision_tools,
    
    # Progress Reporting Tools
    ReportProgressTool,
    ReportCompletionTool,
    ReportIssueTool,
    GetProgressTool,
    create_step_reminder_tools,
    
    FinishTool,
    ReadMemoryBankTool,
    UpdateMemoryBankTool,

    create_communication_tools,
)

# Knowledge Tools (from multi_agent.knowledge)
try:
    from tools.knowledge_tools import (
        create_knowledge_tools,
    )
    KNOWLEDGE_TOOLS_AVAILABLE = True
except ImportError as e:
    raise RuntimeError(f"Knowledge tools are required but failed to import: {e}") from e

# Hub tools are registered via tool bundles (codehub, workhub, registryhub, eventhub).

# Team Protocol Tools (managed agent-team lifecycle)
# Inspired by Claude Code Agent Teams: https://code.claude.com/docs/en/agent-teams
try:
    from tools.team_tools import (
        get_team_tools,
        inject_team_protocols,
    )
    TEAM_TOOLS_AVAILABLE = True
except ImportError as e:
    TEAM_TOOLS_AVAILABLE = False
    def get_team_tools():
        return []
    def inject_team_protocols(*args, **kwargs):
        pass


def create_tool_assembly_context(
    *,
    agent_type: str,
    workspace: Workspace,
    agent_id: Optional[str] = None,
    include_browser: bool = False,
    include_docker: bool = False,
    include_vision: bool = False,
    llm_client=None,
    allowed_tool_categories: Optional[List[str]] = None,
    allow_tools: Optional[List[str]] = None,
    deny_tools: Optional[List[str]] = None,
    assembly_mode: str = "agent",
    tool_profile_id: Optional[str] = None,
    tool_bundle_ids: Optional[List[str]] = None,
) -> ToolAssemblyContext:
    """Create a unified tool assembly context for runtime tool exposure."""
    permission_context = ToolPermissionContext(
        allowed_categories=normalize_category_filter(allowed_tool_categories),
        allow_tools=normalize_tool_name_filter(allow_tools),
        deny_tools=normalize_tool_name_filter(deny_tools),
        metadata={
            "agent_type": agent_type,
            "tool_profile_id": tool_profile_id,
            "assembly_mode": assembly_mode,
        },
    )
    return ToolAssemblyContext(
        agent_type=agent_type,
        workspace=workspace,
        agent_id=agent_id or agent_type,
        include_browser=include_browser,
        include_docker=include_docker,
        include_vision=include_vision,
        llm_client=llm_client,
        permission_context=permission_context,
        assembly_mode=assembly_mode,
        tool_profile_id=tool_profile_id,
        tool_bundle_ids=list(tool_bundle_ids or []),
    )


def _assemble_full_tool_pool(context: ToolAssemblyContext) -> List[BaseTool]:
    """Build a broad single-agent style tool pool from the unified runtime."""
    workspace = context.workspace
    builder = ToolPoolBuilder(context)

    builder.add([
        ReadTool(workspace=workspace),
        WriteTool(workspace=workspace),
        CanonicalEditTool(workspace=workspace),
        ApplyPatchTool(workspace=workspace),
        DeleteFileTool(workspace=workspace),
        GlobTool(workspace=workspace),
        GrepTool(workspace=workspace),
    ], "file")

    builder.add([
        PlanTool(agent_id=context.agent_type or "default"),
    ], "reasoning")
    builder.add(create_step_reminder_tools(), "reasoning")

    builder.add(create_analysis_tools(workspace=workspace), "reasoning", "workspace")
    builder.add([
        ExecuteBashTool(workspace=workspace),
        FindFreePortTool(),
        RunBackgroundTool(workspace=workspace),
        StopProcessTool(),
        ListProcessesTool(),
        GetProcessOutputTool(),
        TestAPITool(),
    ], "runtime", "api")

    if context.include_docker:
        builder.add(create_docker_tools(workspace=workspace), "docker")

    builder.add(create_project_tools(workspace=workspace), "workspace")
    builder.add(create_database_tools(workspace=workspace), "database")
    builder.add(create_log_tools(workspace=workspace), "workspace")

    if context.include_browser and BROWSER_TOOLS_AVAILABLE:
        builder.add(create_browser_tools(workspace.base_root), "browser")

    if context.include_vision and context.llm_client:
        builder.add(create_vision_tools(context.llm_client, workspace=workspace), "vision")

    return builder.build()


def _assemble_agent_tool_pool(context: ToolAssemblyContext) -> List[BaseTool]:
    """Build a per-agent tool pool from the unified runtime."""
    agent_type = context.agent_type
    workspace = context.workspace
    builder = ToolPoolBuilder(context)

    builder.add([
        ReadTool(workspace=workspace),
        WriteTool(workspace=workspace),
        CanonicalEditTool(workspace=workspace),
        ApplyPatchTool(workspace=workspace),
        DeleteFileTool(workspace=workspace),
        GlobTool(workspace=workspace),
        GrepTool(workspace=workspace),
        LintTool(workspace=workspace),
        ViewImageTool(workspace=workspace),
        # Structured edits — the shared agent prompt instructs agents to prefer these.
        UpdateJsonPathTool(workspace=workspace),
        UpdateYamlPathTool(workspace=workspace),
    ], "file")

    builder.add([
        GetTimeTool(),
        WaitTool(),
        PlanTool(agent_id=agent_type),
        VerifyPlanTool(agent_id=agent_type),
    ], "reasoning")

    builder.add([
        ReportProgressTool(agent_id=context.agent_id or agent_type),
        ReportCompletionTool(agent_id=context.agent_id or agent_type),
        ReportIssueTool(agent_id=context.agent_id or agent_type),
        GetProgressTool(agent_id=context.agent_id or agent_type),
    ], "progress")
    builder.add(create_step_reminder_tools(), "reasoning")

    builder.add([FinishTool(agent_id=agent_type)], always=True)
    # focus_hub is no longer offered: hub-focus gating is off by default (writes are
    # directly available; see step_pipeline/action.py), so the switching tool only
    # invited thrash — agents burned hundreds of LLM turns toggling focus.
    builder.add(
        [
            ReadMemoryBankTool(workspace=workspace, agent_id=context.agent_id or agent_type),
            UpdateMemoryBankTool(),
        ],
        always=True,
    )
    builder.add(create_communication_tools(include_advanced=False), "communication")
    apply_tool_bundles(builder, context, context.tool_bundle_ids)

    return builder.build()


def assemble_tool_pool(context: ToolAssemblyContext) -> List[BaseTool]:
    """Unified entrypoint for assembling tool pools."""
    if context.assembly_mode == "all":
        return _assemble_full_tool_pool(context)
    return _assemble_agent_tool_pool(context)


def get_all_tools(
    workspace: Workspace,
    include_browser: bool = True,
    include_docker: bool = True,
    include_vision: bool = False,
    llm_client = None,
) -> List[BaseTool]:
    """Compatibility wrapper for broad single-agent tool access."""
    context = create_tool_assembly_context(
        agent_type="default",
        workspace=workspace,
        include_browser=include_browser,
        include_docker=include_docker,
        include_vision=include_vision,
        llm_client=llm_client,
        assembly_mode="all",
    )
    return assemble_tool_pool(context)


def get_agent_tools(
    agent_type: str,
    workspace: Workspace,
    include_browser: bool = False,
    include_docker: bool = False,
    include_vision: bool = False,
    llm_client = None,
    allowed_tool_categories: Optional[List[str]] = None,
) -> List[BaseTool]:
    """Compatibility wrapper for role-filtered tool pools."""
    context = create_tool_assembly_context(
        agent_type=agent_type,
        workspace=workspace,
        include_browser=include_browser,
        include_docker=include_docker,
        include_vision=include_vision,
        llm_client=llm_client,
        allowed_tool_categories=allowed_tool_categories,
        assembly_mode="agent",
    )
    return assemble_tool_pool(context)


def inject_team_protocols_to_tools(
    tools: List[BaseTool],
    agent_id: str,
    agent_manager=None,
    persona_catalog=None,
    plan_decision=None,
    parallel_reasoning=None,
    practice_store=None,
) -> None:
    """
    Inject team protocols into tools.
    
    Call this after creating agent tools to enable team collaboration features:
    - spawn_worker: Create new task-scoped workers dynamically
    - create/define/launch/monitor/pause/resume/terminate agent team lifecycle
    - run_parallel_reasoning: Start multi-candidate analysis
    - accept_plan/request_plan_changes: Resolve agent plans
    - list_personas: See available agent personas
    - suggest_team: Get team suggestions based on past practices
    - record_practice: Record successful team patterns
    
    Args:
        tools: List of tools (from get_agent_tools)
        agent_id: ID of the agent using these tools
        agent_manager: DynamicAgentManager instance
        persona_catalog: PersonaCatalog instance
        plan_decision: PlanDecisionProtocol instance
        parallel_reasoning: ParallelReasoningProtocol instance
        practice_store: TeamPracticeStore instance
    """
    if not TEAM_TOOLS_AVAILABLE:
        return
    
    inject_team_protocols(
        tools=tools,
        agent_id=agent_id,
        agent_manager=agent_manager,
        persona_catalog=persona_catalog,
        plan_decision=plan_decision,
        parallel_reasoning=parallel_reasoning,
        practice_store=practice_store,
    )


# Re-export Workspace
__all__ = [
    "Workspace",
    "ToolAssemblyContext",
    "ToolPermissionContext",
    "create_tool_assembly_context",
    "assemble_tool_pool",
    "get_all_tools",
    "get_agent_tools",
    "inject_team_protocols_to_tools",
    "PlanTool",  # Exposed for plan status checking
    "TEAM_TOOLS_AVAILABLE",
]

