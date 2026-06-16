"""
Configurable tool bundle registry.

Profiles can compose named bundles in YAML instead of forcing every capability
decision to live inline in the tool assembly function.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, List

from .tool_runtime import ToolAssemblyContext, ToolPoolBuilder
from tools.agent_interaction_tools import DeliverProjectTool, ReadMemoryBankTool, UpdateMemoryBankTool
from tools.analysis_tools import create_analysis_tools
from tools.browser import create_browser_tools
from tools.data_engine_tools import create_data_engine_tools
from tools.database_tools import create_database_tools
from tools.dependency_tools import create_dependency_tools
from tools.docker_tools import DockerRestartTool, create_docker_tools
from tools.reasoning_tools import PlanTool, VerifyPlanTool
from tools.file_tools import CopyReferenceImageTool, ListReferenceImagesTool
from tools.image_search_tools import create_image_search_tools
from tools.knowledge_tools import create_knowledge_tools
from tools.structured_knowledge_tools import create_structured_knowledge_tools
from tools.retro_tools import create_retro_tools
from tools.observability_tools import create_observability_tools
from tools.coverage_tools import create_coverage_tools
from tools.visual_review_tools import create_visual_review_tools
from tools.seed_tools import create_seed_tools
from tools.deliverability_tools import create_deliverability_tools
from tools.mcp_registry_tools import create_mcp_registry_tools
import time as _time
from tools.bug_tools import create_bug_tools
from tools.design_tools import create_design_tools
from tools.run_tools import create_run_tools
from tools.hub_tools import create_hub_tools
from tools.log_tools import create_log_tools
from tools.communication_tools import create_communication_tools
from tools.project_tools import create_project_tools
from tools.runtime_tools import (
    CleanupPortsTool,
    ExecuteBashTool,
    ExecuteIPythonTool,
    FindFreePortTool,
    GetProcessOutputTool,
    InterruptProcessTool,
    ListProcessesTool,
    RunBackgroundTool,
    StopProcessTool,
    TestAPITool,
    WaitForProcessTool,
)
from tools.task_definition_tools import create_task_definition_tools
from tools.task_suite_executor import ExecuteTaskSuiteTool
from tools.verification_tools import (
    GenerateAPISpecTool,
    VerifyAPIContractTool,
    WaitForAPISpecTool,
    create_verification_tools,
)
from tools.vision_tools import create_vision_tools
from tools.web_tools import create_web_tools

try:
    # The browser package exports PLAYWRIGHT_AVAILABLE (it has never exported a
    # BROWSER_TOOLS_AVAILABLE name) — importing the wrong name here ImportError'd
    # in EVERY environment, so this guard silently pinned the flag False and
    # _bundle_browser_tools never assembled: the verifier's whole browser
    # toolset (ui_flow testing) was physically absent while its prompt and
    # stage allowlist kept teaching it (found by the 2026-06-12 allowlist
    # cross-validator audit).
    from tools.browser import PLAYWRIGHT_AVAILABLE as BROWSER_TOOLS_AVAILABLE
except ImportError:
    BROWSER_TOOLS_AVAILABLE = False


BundleApplier = Callable[[ToolPoolBuilder, ToolAssemblyContext], None]


def _bundle_runtime_full(builder: ToolPoolBuilder, context: ToolAssemblyContext) -> None:
    workspace = context.workspace
    builder.add([
        ExecuteBashTool(workspace=workspace),
        ExecuteIPythonTool(workspace=workspace),
        FindFreePortTool(),
        CleanupPortsTool(),
        RunBackgroundTool(workspace=workspace),
        StopProcessTool(),
        InterruptProcessTool(),
        ListProcessesTool(),
        GetProcessOutputTool(),
        WaitForProcessTool(),
    ], "runtime", "api")


def _bundle_runtime_bash_only(builder: ToolPoolBuilder, context: ToolAssemblyContext) -> None:
    builder.add([ExecuteBashTool(workspace=context.workspace)], "runtime")


def _bundle_api_test(builder: ToolPoolBuilder, context: ToolAssemblyContext) -> None:
    builder.add([TestAPITool()], "api")


def _bundle_docker_core(builder: ToolPoolBuilder, context: ToolAssemblyContext) -> None:
    if context.include_docker:
        builder.add(create_docker_tools(workspace=context.workspace), "docker")


def _bundle_docker_restart(builder: ToolPoolBuilder, context: ToolAssemblyContext) -> None:
    if context.include_docker:
        builder.add([DockerRestartTool(workspace=context.workspace)], "docker")


def _bundle_database_tools(builder: ToolPoolBuilder, context: ToolAssemblyContext) -> None:
    builder.add(create_database_tools(workspace=context.workspace), "database")


def _bundle_dependency_tools(builder: ToolPoolBuilder, context: ToolAssemblyContext) -> None:
    builder.add(create_dependency_tools(workspace=context.workspace), "dependency")


def _bundle_log_tools(builder: ToolPoolBuilder, context: ToolAssemblyContext) -> None:
    builder.add(create_log_tools(workspace=context.workspace), "logs")


def _bundle_reference_images(builder: ToolPoolBuilder, context: ToolAssemblyContext) -> None:
    builder.add([
        ListReferenceImagesTool(workspace=context.workspace),
        CopyReferenceImageTool(workspace=context.workspace),
    ], "reference")


def _bundle_image_search(builder: ToolPoolBuilder, context: ToolAssemblyContext) -> None:
    builder.add(create_image_search_tools(workspace=context.workspace), "image_search")


def _bundle_browser_tools(builder: ToolPoolBuilder, context: ToolAssemblyContext) -> None:
    if context.include_browser and BROWSER_TOOLS_AVAILABLE:
        builder.add(create_browser_tools(context.workspace.base_root), "browser")


def _bundle_vision_tools(builder: ToolPoolBuilder, context: ToolAssemblyContext) -> None:
    if context.include_vision and context.llm_client:
        builder.add(create_vision_tools(context.llm_client, workspace=context.workspace), "vision")


def _bundle_verification_tools(builder: ToolPoolBuilder, context: ToolAssemblyContext) -> None:
    builder.add(create_verification_tools(workspace=context.workspace), "verification")


def _bundle_data_engine_tools(builder: ToolPoolBuilder, context: ToolAssemblyContext) -> None:
    builder.add(create_data_engine_tools(workspace=context.workspace), "data_engine")


def _bundle_backend_api_contract(builder: ToolPoolBuilder, context: ToolAssemblyContext) -> None:
    builder.add([
        GenerateAPISpecTool(workspace=context.workspace),
        VerifyAPIContractTool(workspace=context.workspace),
    ], "api_contract")


def _bundle_frontend_api_contract(builder: ToolPoolBuilder, context: ToolAssemblyContext) -> None:
    builder.add([
        WaitForAPISpecTool(workspace=context.workspace),
        VerifyAPIContractTool(workspace=context.workspace),
    ], "api_contract")


def _bundle_mcp_client(builder: ToolPoolBuilder, context: ToolAssemblyContext) -> None:
    from tools.mcp_client_tools import create_mcp_client_tools

    builder.add(create_mcp_client_tools(), "api")


def _bundle_mcp_server(builder: ToolPoolBuilder, context: ToolAssemblyContext) -> None:
    from tools.mcp_tools import create_mcp_tools

    builder.add(create_mcp_tools(
        workspace_path=context.workspace.base_root if context.workspace else None,
        hubs=context.hub_workspace,
    ), "api")


def _bundle_task_definition(builder: ToolPoolBuilder, context: ToolAssemblyContext) -> None:
    builder.add(create_task_definition_tools(
        output_dir=context.workspace.base_root if context.workspace else None
    ), "task_definition")


def _bundle_execute_task_suite(builder: ToolPoolBuilder, context: ToolAssemblyContext) -> None:
    builder.add([
        ExecuteTaskSuiteTool(
            workspace=context.workspace,
            agent_id=context.agent_type,
            include_browser=bool(context.include_browser and BROWSER_TOOLS_AVAILABLE),
        ),
    ], "verification")


def _bundle_knowledge_read(builder: ToolPoolBuilder, context: ToolAssemblyContext) -> None:
    tools = [
        tool for tool in create_knowledge_tools(workspace=context.workspace)
        if getattr(tool, "NAME", "") in {"query_knowledge", "get_relevant_knowledge"}
    ]
    builder.add(tools, "knowledge_read")


def _bundle_knowledge_write(builder: ToolPoolBuilder, context: ToolAssemblyContext) -> None:
    tools = [
        tool for tool in create_knowledge_tools(workspace=context.workspace)
        if getattr(tool, "NAME", "") in {"store_knowledge", "submit_learning"}
    ]
    builder.add(tools, "knowledge_write")


def _bundle_knowledge_skill(builder: ToolPoolBuilder, context: ToolAssemblyContext) -> None:
    tools = [
        tool for tool in create_knowledge_tools(workspace=context.workspace)
        if getattr(tool, "NAME", "") in {"list_skills", "get_skill", "upsert_skill"}
    ]
    builder.add(tools, "knowledge_skill")


def _bundle_structured_knowledge_tools(builder: ToolPoolBuilder, context: ToolAssemblyContext) -> None:
    builder.add(create_structured_knowledge_tools(), "knowledge")


def _bundle_retro_tools(builder: ToolPoolBuilder, context: ToolAssemblyContext) -> None:
    # generation_id defaults to context start time; production orchestrator
    # supplies its own session start.
    gen_id = getattr(context, "generation_id", None) or _time.time()
    builder.add(
        create_retro_tools(hub_registry=context.hub_workspace, generation_id=gen_id),
        "memory",
    )


def _bundle_observability_tools(builder: ToolPoolBuilder, context: ToolAssemblyContext) -> None:
    builder.add(create_observability_tools(), "observability")


def _bundle_coverage_tools(builder: ToolPoolBuilder, context: ToolAssemblyContext) -> None:
    app_root = getattr(context, "app_root", None)
    if app_root is None and getattr(context, "workspace", None) is not None:
        app_root = getattr(context.workspace, "root", None)
    builder.add(
        create_coverage_tools(
            hub_registry=context.hub_workspace,
            app_root=str(app_root) if app_root else None),
        "coverage",
    )


def _bundle_visual_review_tools(builder: ToolPoolBuilder, context: ToolAssemblyContext) -> None:
    builder.add(
        create_visual_review_tools(hub_registry=context.hub_workspace),
        "visual_review",
    )


def _bundle_seed_tools(builder: ToolPoolBuilder, context: ToolAssemblyContext) -> None:
    builder.add(
        create_seed_tools(hub_registry=context.hub_workspace),
        "seed",
    )


def _bundle_deliverability_tools(builder: ToolPoolBuilder, context: ToolAssemblyContext) -> None:
    app_root = getattr(context, "app_root", None)
    if app_root is None and getattr(context, "workspace", None) is not None:
        app_root = getattr(context.workspace, "root", None)
    if app_root is None:
        app_root = getattr(context, "workspace_path", None)
    session_start_ts = getattr(context, "session_start_ts", None) or 0.0
    builder.add(
        create_deliverability_tools(
            hub_registry=context.hub_workspace,
            app_root=str(app_root) if app_root else None,
            session_start_ts=session_start_ts),
        "delivery",
    )


def _bundle_mcp_registry_tools(builder: ToolPoolBuilder, context: ToolAssemblyContext) -> None:
    builder.add(
        create_mcp_registry_tools(hub_registry=context.hub_workspace),
        "mcp_registry",
    )


def _bundle_schemahub_tools(builder: ToolPoolBuilder, context: ToolAssemblyContext) -> None:
    """PR 5 (hub-responsibility-split plan, rank 5) moved the
    database-table surface from RegistryHub to SchemaHub. The tool
    wrappers kept their historical ``registryhub_*`` NAMEs (LLM-facing
    contracts; prompts and trained behaviour still reference them)
    but route through ``GateRegistry``/``SchemaHub`` internally.

    Historically these table wrappers lived ONLY in
    ``_bundle_registryhub_tools`` — which carries an additional gate
    on the ``registryhub`` tool category. The database profile owns
    the table surface (it physically writes ``.sql``/migration
    files) but has never subscribed to the ``registryhub`` category
    because it doesn't need the endpoint-management tools. Net
    effect: database's ``hub_consistency_gate`` demanded
    ``registryhub_register_table`` calls the agent literally couldn't
    make → soft-wedge with no retry cap until the run budget.

    This bundle exposes the table tools as a focused, narrower
    surface so the database profile can subscribe without
    pulling in endpoint tools it doesn't use. The same
    underlying ``hub_tools.py`` classes are instantiated —
    ``include_names`` selects only the table-related subset."""
    tools = create_hub_tools(
        agent_id=context.agent_id or context.agent_type,
        hub_workspace=context.hub_workspace,
        include_names={
            "registryhub_register_table",
            "registryhub_list_tables",
            "registryhub_register_table_consumer",
            "registryhub_get_table_breaking_changes",
            "registryhub_update_table_schema",
        },
    )
    builder.add(tools, "registryhub", "hub")


def _bundle_project_tools(builder: ToolPoolBuilder, context: ToolAssemblyContext) -> None:
    builder.add(create_project_tools(workspace=context.workspace), "project")


def _bundle_analysis_tools(builder: ToolPoolBuilder, context: ToolAssemblyContext) -> None:
    builder.add(create_analysis_tools(workspace=context.workspace), "analysis")


def _bundle_web_tools(builder: ToolPoolBuilder, context: ToolAssemblyContext) -> None:
    builder.add(create_web_tools(), "web")


def _bundle_codehub_tools(builder: ToolPoolBuilder, context: ToolAssemblyContext) -> None:
    tools = create_hub_tools(
        agent_id=context.agent_id or context.agent_type,
        hub_workspace=context.hub_workspace,
        include_names={
            "codehub_commit",
            "codehub_register_repo",
            "codehub_record_commit",
            "codehub_open_pr",
            # Round 8h smoke #18 follow-up: backend/verifier need to
            # write build:* + validation:* checks to satisfy the
            # orchestrator delivery gate (build checklist + validation
            # matrix at orchestrator.py:1414-1473). Pre-fix the only
            # caller path was Python-internal (step_pipeline +
            # hub_registry) so the LLM had no way to produce the
            # required evidence — agents reached "ready_for_delivery"
            # artifact state but no agent could record the check.
            "codehub_record_check",
            "codehub_list_inline_comments",
            "codehub_get_diff",
            "codehub_get_blob",
            "codehub_get_file_content",
            "codehub_list_prs",
            "codehub_list_checks",
            "codehub_resolve_conflict",
            "codehub_resolve_merge_conflict",
            "codehub_revert_commit",
            "codehub_suggest_reviewers",
            "hub_snapshot",
        },
    )
    builder.add(tools, "codehub", "hub")


def _bundle_codehub_admin_tools(builder: ToolPoolBuilder, context: ToolAssemblyContext) -> None:
    # Privileged integration ops — main-branch merges and releases. Restricted to
    # the orchestrator (the integrator); release also gates on a passing run.
    tools = create_hub_tools(
        agent_id=context.agent_id or context.agent_type,
        hub_workspace=context.hub_workspace,
        include_names={"codehub_force_merge", "codehub_create_release"},
    )
    builder.add(tools, "codehub", "hub")


def _bundle_workhub_tools(builder: ToolPoolBuilder, context: ToolAssemblyContext) -> None:
    tools = create_hub_tools(
        agent_id=context.agent_id or context.agent_type,
        hub_workspace=context.hub_workspace,
        include_names={
            "workhub_create_page",
            # Re-audit (2026-05-29, HIGH #3): HubConsistencyPolicy's
            # workhub_pages gate explicitly tells the agent to call
            # ``workhub_update_page(name=..., path=...,
            # status='implemented')`` to clear the
            # "WorkHub has 0 pages registered" block — but the tool
            # was missing from this bundle, so the gate was telling
            # the agent to call a tool it didn't have, soft-locking
            # frontend/design at finish. ``_count_owned_pages`` only
            # counts ``kind=="ui_page"`` entries, and
            # ``workhub_update_page`` is the only call that writes
            # that kind; ``workhub_create_page`` writes generic
            # pages and cannot satisfy the gate.
            "workhub_update_page",
            "workhub_task",
            "workhub_fail_task",
            "workhub_cancel_task",
            "workhub_get_task",
            "workhub_list_tasks",
            "workhub_available_tasks",
            "workhub_get_page",
            "workhub_list_pages",
            "workhub_list_ui_pages",
            "workhub_list_ui_components",
            "workhub_link_task_to_pr",
            "workhub_link_task_to_apis",
            "workhub_update_block",
            "workhub_archive_page",
            "workhub_record_decision",
            "workhub_comments_for",
            "workhub_invite_attendee",
            "workhub_remove_attendee",
            "workhub_comment",
            "workhub_reply",
            "workhub_share_implementation",
            "workhub_set_priority",
            "workhub_list_ready",
            "workhub_list_blocked",
            "hub_snapshot",
        },
    )
    builder.add(tools, "workhub", "hub")


def _bundle_meeting_tools(builder: ToolPoolBuilder, context: ToolAssemblyContext) -> None:
    """Kickoff/meeting write surface — the 3 ``workhub.create_meeting`` /
    ``add_meeting_decision`` / ``close_meeting`` wrappers. Lives in its own
    narrow bundle (rather than being folded into ``workhub_tools``) so
    profiles that need meeting authoring (e.g. orchestrator running the
    kickoff sub-protocol) can subscribe without re-granting the broad
    WorkHub write surface, and so the bundle's caller-set is auditable
    in agents_config.yaml."""
    tools = create_hub_tools(
        agent_id=context.agent_id or context.agent_type,
        hub_workspace=context.hub_workspace,
        include_names={
            "workhub_create_meeting",
            "workhub_add_meeting_decision",
            "workhub_close_meeting",
            "kickoff_declare_ui_page",
            "kickoff_declare_ui_component",
            "kickoff_declare_user_flow",
            "kickoff_declare_predicate",
            "kickoff_declare_endpoint",
            "kickoff_declare_table",
        },
    )
    builder.add(tools, "workhub", "hub")


def _bundle_registryhub_tools(builder: ToolPoolBuilder, context: ToolAssemblyContext) -> None:
    # `registryhub_record_contract_test` was extracted to a dedicated
    # `verifier_contract_tools` bundle as part of the Phase 4.4
    # pre-flight wiring trim (`docs/phase_4_4_record_api_test_audit_notes.md`
    # Path A): the underlying `hub.record_api_test` writes contract
    # evidence consumed by the delivery gate, and the Phase 4.4
    # authorship lock will eventually restrict it to
    # `{verifier, contract_test_runtime}`. Keeping it in the broad
    # registryhub_tools bundle (granted to 8 profiles) would make 7 of
    # those grants broken-by-construction the moment the gate fires.
    tools = create_hub_tools(
        agent_id=context.agent_id or context.agent_type,
        hub_workspace=context.hub_workspace,
        include_names={
            "registryhub_register_endpoint",
            "registryhub_update_schema",
            "registryhub_list_endpoints",
            "registryhub_get_endpoint",
            "registryhub_register_consumer",
            "registryhub_check_endpoint_drift",
            "registryhub_get_dependencies_for_file",
            "registryhub_get_breaking_changes",
            "registryhub_deprecate_endpoint",
            "registryhub_register_table",
            "registryhub_list_tables",
            "registryhub_register_table_consumer",
            "registryhub_get_table_breaking_changes",
            "registryhub_update_table_schema",
            "hub_snapshot",
        },
    )
    builder.add(tools, "registryhub", "hub")


def _bundle_verifier_contract_tools(builder: ToolPoolBuilder, context: ToolAssemblyContext) -> None:
    """Verifier-only contract-test write surface.

    Per `docs/phase_4_4_record_api_test_audit_notes.md` Path A, the
    `registryhub_record_contract_test` tool lives here rather than in the
    broad `registryhub_tools` bundle. agents_config.yaml grants this
    bundle ONLY to the `verifier` profile (and `contract_test_runtime`
    if/when that profile exists). This closes the Phase 4.4
    authorship lock by construction at the bundle layer — agents
    outside the allowed set don't have access to the tool at all,
    so the eventual runtime gate at `registryhub.record_api_test` becomes
    defense-in-depth rather than the primary enforcement point.
    """
    tools = create_hub_tools(
        agent_id=context.agent_id or context.agent_type,
        hub_workspace=context.hub_workspace,
        include_names={"registryhub_record_contract_test",
                       "registryhub_register_verification_chain"},
    )
    builder.add(tools, "verifier_contract", "hub")


def _bundle_bug_tools(builder: ToolPoolBuilder, context: ToolAssemblyContext) -> None:
    tools = create_bug_tools(
        agent_id=context.agent_id or context.agent_type,
        hub_workspace=context.hub_workspace,
    )
    builder.add(tools, "bug", "hub")


def _bundle_run_tools(builder: ToolPoolBuilder, context: ToolAssemblyContext) -> None:
    tools = create_run_tools(
        agent_id=context.agent_id or context.agent_type,
        hub_workspace=context.hub_workspace,
    )
    builder.add(tools, "run", "hub")


def _bundle_design_tools(builder: ToolPoolBuilder, context: ToolAssemblyContext) -> None:
    tools = create_design_tools(
        agent_id=context.agent_id or context.agent_type,
        hub_workspace=context.hub_workspace,
    )
    builder.add(tools, "design", "hub")


def _bundle_eventhub_tools(builder: ToolPoolBuilder, context: ToolAssemblyContext) -> None:
    tools = create_hub_tools(
        agent_id=context.agent_id or context.agent_type,
        hub_workspace=context.hub_workspace,
        include_names={
            "eventhub_inbox",
            "eventhub_subscribe",
            "eventhub_unsubscribe",
            "eventhub_list_subscriptions",
            "eventhub_get_thread",
            "eventhub_reply_in_thread",
            "eventhub_mark_all_read",
            "eventhub_get_agent_status",
            "hub_snapshot",
        },
    )
    builder.add(tools, "eventhub", "hub")


def _team_tools_by_names(names: List[str]) -> List[Any]:
    from tools.team_tools import get_team_tools

    allowed = set(names)
    return [tool for tool in get_team_tools() if getattr(tool, "NAME", "") in allowed]


def _bundle_team_spawn(builder: ToolPoolBuilder, context: ToolAssemblyContext) -> None:
    builder.add(_team_tools_by_names([
        "spawn_worker",
        "terminate_runtime_agent",
        "list_runtime_agents",
        "parallel_execute",
    ]), "team_spawn")


def _bundle_team_lifecycle(builder: ToolPoolBuilder, context: ToolAssemblyContext) -> None:
    builder.add(_team_tools_by_names([
        "team_health_summary",
        "create_agent_team",
        "define_team_agent",
        "launch_agent_team",
        "monitor_agent_team",
        "pause_agent_team",
        "resume_agent_team",
        "terminate_agent_team",
    ]), "team_lifecycle")


def _bundle_team_reasoning(builder: ToolPoolBuilder, context: ToolAssemblyContext) -> None:
    builder.add(_team_tools_by_names(["run_parallel_reasoning"]), "team_reasoning")


def _bundle_reasoning_tools(builder: ToolPoolBuilder, context: ToolAssemblyContext) -> None:
    """The base reasoning tools every agent needs: ``plan``, ``think``, ``verify_plan``.

    Plans are NOT orchestrator-only — every agent should be able to author their
    own plan (which auto-syncs to WorkHub via the step pipeline). PlanTool is a
    per-agent singleton, so we use ``get_instance(agent_id)`` to match the same
    instance the runtime's auto-sync helper already addresses; otherwise the
    bundle's instance and the singleton's instance would diverge and the sync
    would publish empty snapshots even after the agent called ``plan(...)``.
    """
    aid = context.agent_id or "default"
    tools = [PlanTool.get_instance(aid), VerifyPlanTool()]
    builder.add(tools, "reasoning")


def _bundle_team_planning(builder: ToolPoolBuilder, context: ToolAssemblyContext) -> None:
    builder.add(_team_tools_by_names([
        "submit_plan",
        "accept_plan",
        "request_plan_changes",
        "list_pending_plan_decisions",
    ]), "team_planning")


def _bundle_orchestrator_delivery(builder: ToolPoolBuilder, context: ToolAssemblyContext) -> None:
    builder.add([DeliverProjectTool()], always=True)


TOOL_BUNDLE_REGISTRY: Dict[str, BundleApplier] = {
    "runtime_full": _bundle_runtime_full,
    "runtime_bash_only": _bundle_runtime_bash_only,
    "api_test": _bundle_api_test,
    "docker_core": _bundle_docker_core,
    "docker_restart": _bundle_docker_restart,
    "database_tools": _bundle_database_tools,
    "dependency_tools": _bundle_dependency_tools,
    "log_tools": _bundle_log_tools,
    "reference_images": _bundle_reference_images,
    "image_search_tools": _bundle_image_search,
    "browser_tools": _bundle_browser_tools,
    "vision_tools": _bundle_vision_tools,
    "verification_tools": _bundle_verification_tools,
    "data_engine_tools": _bundle_data_engine_tools,
    "backend_api_contract_tools": _bundle_backend_api_contract,
    "frontend_api_contract_tools": _bundle_frontend_api_contract,
    "mcp_client_tools": _bundle_mcp_client,
    "mcp_server_tools": _bundle_mcp_server,
    "task_definition_tools": _bundle_task_definition,
    "execute_task_suite": _bundle_execute_task_suite,
    "orchestrator_delivery": _bundle_orchestrator_delivery,
    "knowledge_read_tools": _bundle_knowledge_read,
    "knowledge_write_tools": _bundle_knowledge_write,
    "knowledge_skill_tools": _bundle_knowledge_skill,
    "structured_knowledge_tools": _bundle_structured_knowledge_tools,
    "retro_tools": _bundle_retro_tools,
    "observability_tools": _bundle_observability_tools,
    "coverage_tools": _bundle_coverage_tools,
    "visual_review_tools": _bundle_visual_review_tools,
    "seed_tools": _bundle_seed_tools,
    "deliverability_tools": _bundle_deliverability_tools,
    "mcp_registry_tools": _bundle_mcp_registry_tools,
    "schemahub_tools": _bundle_schemahub_tools,
    "project_tools": _bundle_project_tools,
    "analysis_tools": _bundle_analysis_tools,
    "web_tools": _bundle_web_tools,
    "codehub_tools": _bundle_codehub_tools,
    "codehub_admin_tools": _bundle_codehub_admin_tools,
    "workhub_tools": _bundle_workhub_tools,
    "meeting_tools": _bundle_meeting_tools,
    "registryhub_tools": _bundle_registryhub_tools,
    "verifier_contract_tools": _bundle_verifier_contract_tools,
    "eventhub_tools": _bundle_eventhub_tools,
    "bug_tools": _bundle_bug_tools,
    "run_tools": _bundle_run_tools,
    "design_tools": _bundle_design_tools,
    "team_spawn_tools": _bundle_team_spawn,
    "team_lifecycle_tools": _bundle_team_lifecycle,
    "team_reasoning_tools": _bundle_team_reasoning,
    "team_planning_tools": _bundle_team_planning,
    "reasoning_tools": _bundle_reasoning_tools,
}


TOOL_BUNDLE_REQUIREMENTS: Dict[str, set[str]] = {
    "runtime_full": {"runtime"},
    "runtime_bash_only": {"runtime"},
    "api_test": {"api"},
    "docker_core": {"docker"},
    "docker_restart": {"docker"},
    "database_tools": {"database"},
    "dependency_tools": {"dependency"},
    "log_tools": {"logs"},
    "reference_images": {"reference"},
    "image_search_tools": {"image_search"},
    "browser_tools": {"browser"},
    "vision_tools": {"vision"},
    "verification_tools": {"verification"},
    "data_engine_tools": {"data_engine"},
    "backend_api_contract_tools": {"api_contract"},
    "frontend_api_contract_tools": {"api_contract"},
    "mcp_client_tools": {"api"},
    "mcp_server_tools": {"api"},
    "task_definition_tools": {"task_definition"},
    "execute_task_suite": {"verification"},
    "orchestrator_delivery": set(),
    "knowledge_read_tools": {"knowledge_read"},
    "knowledge_write_tools": {"knowledge_write"},
    "knowledge_skill_tools": {"knowledge_skill"},
    "structured_knowledge_tools": {"knowledge"},
    "retro_tools": {"memory"},
    "observability_tools": {"observability"},
    "coverage_tools": {"coverage"},
    "visual_review_tools": {"visual_review"},
    "seed_tools": {"seed"},
    "deliverability_tools": {"delivery"},
    "mcp_registry_tools": {"mcp_registry"},
    # ``schemahub_tools`` deliberately gates on the ``registryhub`` category
    # so a profile already authorized for registryhub doesn't need a new
    # category just for tables. database/backend that subscribe to
    # this bundle must include ``registryhub`` in tool_categories so the
    # underlying ``registryhub_*``-named wrappers pass the category check.
    "schemahub_tools": {"registryhub"},
    "project_tools": {"project"},
    "analysis_tools": {"analysis"},
    "web_tools": {"web"},
    "codehub_tools": {"codehub"},
    "codehub_admin_tools": {"codehub"},
    "workhub_tools": {"workhub"},
    "meeting_tools": {"workhub"},
    "registryhub_tools": {"registryhub"},
    # `verifier_contract_tools` (Phase 4.4 Path A bundle-trim 7272a2fc)
    # was registered in TOOL_BUNDLES + granted in agents_config.yaml but
    # never declared here — startup config validation rejected the
    # verifier profile with "unknown tool bundle". It's a subset of
    # registryhub_tools (just `registryhub_record_contract_test`), so it requires
    # the same `{"registryhub"}` category. Discovered when the v3 re-pilot
    # launch (launch_facebook_v3_repilot.sh) failed at
    # orchestrator._spawn_core_agents.
    "verifier_contract_tools": {"registryhub"},
    "eventhub_tools": {"eventhub"},
    "bug_tools": {"bug"},
    "run_tools": {"run"},
    # `design_tools` registers under the "design" tool_category
    # (see _bundle_design_tools above). Post-2026-06-02 kickoff-refactor
    # the design profile is gone and the bundle is granted to `frontend`,
    # which keeps "design" in its tool_categories. Requirement was
    # `{"frontend"}` historically — that pre-dated this consolidation and
    # would now reject the frontend grant outright.
    "design_tools": {"design"},
    "team_spawn_tools": {"team_spawn"},
    "team_lifecycle_tools": {"team_lifecycle"},
    "team_reasoning_tools": {"team_reasoning"},
    "team_planning_tools": {"team_planning"},
    "reasoning_tools": {"reasoning"},
}


def apply_tool_bundles(
    builder: ToolPoolBuilder,
    context: ToolAssemblyContext,
    bundle_ids: Iterable[str],
) -> None:
    for raw_bundle_id in bundle_ids or []:
        bundle_id = str(raw_bundle_id or "").strip()
        if not bundle_id:
            continue
        applier = TOOL_BUNDLE_REGISTRY.get(bundle_id)
        if applier is None:
            raise ValueError(f"Unknown tool bundle: {bundle_id}")
        applier(builder, context)
