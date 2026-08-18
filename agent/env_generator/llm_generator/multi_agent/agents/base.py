"""
EnvGenAgent - Base Agent for Multi-Agent Environment Generation

Inherits from utils.base_agent.BaseAgent and adds:
- Jinja2 prompt templates
- LLM agentic loop (chat + tool calling)
- Environment generation specific tools
- Priority message queue with urgent message handling
- Question preemption during task processing

Subclasses only need to define:
- agent_id, agent_name
- allowed_tool_categories  
- _get_system_prompt() - use j2 templates
- _build_task_prompt() - use j2 templates
"""

import asyncio
import json
import logging
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, TYPE_CHECKING

from jinja2 import Environment, FileSystemLoader, select_autoescape

# Import base classes from utils
from utils.base_agent import BaseAgent, AgentRole
from utils.config import AgentConfig
from utils.message import (
    TaskMessage,
    ResultMessage,
    MessagePriority,
    MessageHeader,
    MessageTracker,
    create_result_message,
)
from utils.tool import BaseTool
from utils.communication import MessageBus

# LLM
from utils.llm import LLM


# ==================== PRIORITY QUEUE ====================

from .priority_queue import PriorityMessageQueue

# Memory
import sys
_memory_dir = Path(__file__).parent.parent.parent
if str(_memory_dir) not in sys.path:
    sys.path.insert(0, str(_memory_dir))
from memory import GeneratorMemory, MemoryBank

from .runtime import (
    AgentMessaging,
    AgentStepRunner,
    AgentSync,
    AgentTooling,
    ProcessingState,
    safe_json_dumps,
)

if TYPE_CHECKING:
    from ..workspace_manager import WorkspaceManager


# Prompt templates directory
PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def _auto_stage_in_mini_loop(agent, file_path: str, *, action: str) -> None:
    """Mini-loop counterpart of step_pipeline._auto_stage.

    Duplicated rather than imported because step_pipeline lives under
    ``runtime/step_pipeline/`` and the mini-loop is a bounded fallback
    path with slightly different error-handling expectations (debug
    instead of warning by default). Both wrap the same pure
    ``stage_file``/``stage_deletion`` helpers from
    ``multi_agent.agents.runtime.auto_commit``.
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
    from multi_agent.agents.runtime.auto_commit import stage_file, stage_deletion
    fn = stage_deletion if action == "delete" else stage_file
    ok, info = fn(wt, resolved)
    if not ok:
        try:
            agent._logger.debug(
                f"[{agent.agent_id}] mini-loop auto-stage ({action}) skipped: {info}"
            )
        except Exception:
            pass


class EnvGenAgent(
    AgentMessaging,
    AgentSync,
    AgentTooling,
    AgentStepRunner,
    BaseAgent,
):
    """
    Environment Generation Agent Base Class.
    
    Extends BaseAgent with:
    - Jinja2 prompt templates
    - LLM agentic loop (tool calling)
    - Environment generation tools
    
    Subclasses override:
    - _get_system_prompt()
    - _build_task_prompt(task)
    """
    
    # Override in subclass
    agent_id: str = "base"
    agent_name: str = "BaseAgent"
    allowed_tool_categories: List[str] = ["file", "reasoning"]
    TEAM_TOOL_NAMES: Set[str] = {
        "spawn_worker", "terminate_runtime_agent", "list_runtime_agents",
        "team_health_summary",
        "create_agent_team", "define_team_agent", "launch_agent_team", "monitor_agent_team",
        "pause_agent_team", "resume_agent_team", "terminate_agent_team",
        "run_parallel_reasoning",
        "submit_plan", "accept_plan", "request_plan_changes", "list_pending_plan_decisions",
        "parallel_execute",
    }
    TEAM_MODE_SUPPORT_TOOLS: Set[str] = {
        # #346: "think" is not a registered tool anywhere in tools/, and the
        # action stages additionally discard it — an unresolvable pin.
        "wait", "check_inbox",
        "send_message", "ask_agent", "broadcast",
        "report_progress", "get_progress", "report_issue", "report_completion",
        "finish",
    }
    KNOWLEDGE_FETCH_TOOL_NAMES: Set[str] = {
        "query_knowledge", "get_relevant_knowledge", "list_skills", "get_skill",
        "read_memory_bank",
    }
    KNOWLEDGE_STORE_TOOL_NAMES: Set[str] = {
        "store_knowledge", "submit_learning", "upsert_skill", "update_memory_bank",
    }
    ACTION_INTERNAL_STAGES: Tuple[str, ...] = (
        "communicate",
        "edit_code",
        "run_checks",
        "delegate_team",
        "deliver",
    )
    ACTION_STAGE_CATEGORY_HINTS: Dict[str, Set[str]] = {
        "communicate": {"communication", "progress", "knowledge_write", "milestone"},
        "edit_code": {"file", "project", "analysis", "memory", "reference", "image_search"},
        "run_checks": {
            "runtime",
            "api",
            "api_contract",
            "verification",
            "dependency",
            "logs",
            "database",
            "data_engine",
            "browser",
            "docker",
            "task_definition",
            "vision",
        },
        "delegate_team": {
            "team_spawn",
            "team_lifecycle",
            "team_reasoning",
            "team_planning",
        },
        "deliver": {"progress"},
    }
    # Lifecycle / governance tools that must NEVER be hidden behind the
    # ranker. ``rank_tool_names`` intersects always_include with the
    # agent's candidate pool, so listing role-specific tools here is
    # safe — agents whose bundle doesn't expose the tool see it filtered
    # out before reaching the schema map.
    #
    # Why this matters: a long-context / large-spec run can push the
    # LLM-planning text far away from a transition tool's name (e.g.
    # backend finishes implementing an endpoint then thinks "double-check
    # design status before broadcast" — token overlap with
    # ``design_get_status`` is low and the ranker drops it from the
    # top-N, leaving the agent without the status check at hand).
    # Pinned to always-include only the read-side design tool that
    # downstream agents (backend/frontend/database) use to gate their
    # own work on the design page status.
    # (registryhub_request_review / registryhub_submit_review were removed from the
    # tool surface entirely — the per-endpoint review ceremony never ran in
    # practice and once sent the design agent into a doom loop.)
    _DESIGN_GOVERNANCE = {
        "design_get_status",
    }
    # Hub-state registration tools the HubConsistencyPolicy hard-blocks
    # finish() on. Pinning them to always-include means
    # ``registryhub_register_endpoint`` (and siblings) is always in the
    # agent's action schema — the LLM ranker can't drop it.
    # Only agents whose bundle includes the tool see it (intersect with
    # candidate_names), so e.g. frontend won't accidentally get register
    # for tables.
    _HUB_REGISTRATION = {
        "registryhub_register_endpoint",
        "registryhub_register_table",
        "registryhub_register_consumer",
        "registryhub_register_ui_page",
        "workhub_create_document",
        "workhub_share_implementation",
        "workhub_task",       # create/claim/complete — only way to mark task done
        "workhub_fail_task",  # creator/orchestrator-only since 2026-06-10; lanes get a guidance error
        "codehub_commit",
        # Round-8d Fix #5: kickoff meeting primitives. Same regression
        # class as the original _HUB_REGISTRATION rationale — the LLM
        # ranker (action.py:_apply_hub_focus → tooling.py:_stage_tool_names
        # → rank_tool_names, limit=10) was dropping these as semantically
        # similar to registryhub_register_ui_page / workhub_task, so attendees
        # following the kickoff_response_prompt macro's "call
        # workhub_add_meeting_decision" instruction could not find the
        # tool in their per-step surface and finished blocked. Live
        # smoke run 2026-06-02 20:11 (post-Fix-2bis): all 4 attendees
        # entered LLM turns, all 4 called focus_hub("workhub"), but
        # none could find workhub_add_meeting_decision because the
        # ranker chose register_ui_page/task instead. Pinning these to
        # always-include means the kickoff response macro's primary
        # tool is always reachable, the same way registryhub_register_*
        # tools are always reachable for design's section authoring.
        "workhub_create_meeting",
        "workhub_add_meeting_decision",
        "workhub_close_meeting",
        # Round-8g Fix #B: kickoff phase-aware meeting requires READING
        # the meeting page (other attendees' drafts, comments targeting
        # your section) during comment + reply phases. Smoke #9-bis
        # 2026-06-02 23:40 caught backend finishing reply phase early
        # with "Blocked: workhub_get_document tool is not available in
        # current toolset" — same ranker-drops-it pattern as Fix #5.
        # Pin so multi-round meeting always has read access to the
        # meeting state.
        "workhub_get_document",
    }
    # Claim-flow primitives that must always reach the LLM's per-step
    # surface: focus_hub (meta — needed to unlock hub WRITE tools),
    # workhub_list_tasks (read — enumerate assigned queue),
    # workhub_cancel_task (dep-blocked path of the claim flow). The
    # ranker would otherwise drop them when the query text doesn't
    # match their tokens, leaving the agent unable to honor
    # ClaimAssignedTasksPolicy.
    _CLAIM_FLOW = {
        "workhub_list_tasks",
        "workhub_cancel_task",
        # ``workhub_task`` (claim/update/complete) was only in _HUB_REGISTRATION,
        # which run_checks does NOT include — so the verifier could LIST but not
        # CLAIM its validate.api_smoke tasks while validating (smoke #5: backend
        # implemented 12 endpoints, but "verifier remains stalled by missing
        # WorkHub claim capability" → orchestrator spun 60min, no delivery). Claim
        # belongs wherever list does.
        "workhub_task",
    }
    # Conflict-resolution primitives the orchestrator needs when a
    # merge_conflict event arrives. Smoke #40 observed 508 orchestrator
    # tool calls — ZERO of them codehub_resolve_conflict — even though
    # the orchestrator's reasoning explicitly said "I'm handling the
    # merge conflict". The ranker dropped the tool from the per-step
    # surface (the focus_hub return text listed it, but the JSON tool
    # schema sent to the LLM didn't include it).
    _CONFLICT_FLOW = {
        # #35: codehub_resolve_conflict (pr_id-based) dropped — not surfaced (commit-only).
        "codehub_resolve_merge_conflict",
        "codehub_force_merge",
    }
    # Validation primitives the verifier needs to actually run + check
    # the generated app. Smoke #41 observed verifier complaining "the
    # required validation tools are unavailable" even though
    # ``run_start`` / ``browser_navigate`` / ``execute_task_suite``
    # exist in its bundle — the ranker filters them out per-step
    # when the query text doesn't match. Same pattern as _CLAIM_FLOW
    # and _CONFLICT_FLOW. Bundle-intersection guarantees other lanes
    # (e.g. backend) don't accidentally see browser_* tools they have
    # no business calling.
    _VALIDATION_FLOW = {
        # App lifecycle
        "run_start",
        "docker_up",
        "docker_status",
        # API smoke
        "run_validation",  # §6 deterministic one-call api_smoke — MUST be force-offered
        "test_api",
        "registryhub_record_contract_test",
        # run_validation BLOCKS until chains are registered, so the register tool MUST
        # be force-offered too — without it the verifier sees run_validation (which
        # errors "no chains registered") but the ranker never surfaces the register
        # tool, so it reports it "missing" and the run never validates → never delivers.
        "registryhub_register_verification_chain",
        # UI smoke + flow
        "browser_navigate",
        "browser_screenshot",
        "browser_click",
        "capture_webpage",
        # Suite + visual review
        "execute_task_suite",
        "register_visual_review_task",
        # Delivery + remediation
        "deliverability_check",
        "bug_create",
    }
    # Contract source-of-truth READ primitives. The backend/frontend lanes are
    # instructed to consult the RegistryHub contract (registered at finalize_kickoff)
    # before implementing an endpoint/table — "read the source of truth, then
    # write". But ``edit_code``'s category hints ({file, project, analysis,
    # memory, reference, image_search}) don't include registryhub, and
    # ``_HUB_REGISTRATION`` carries only the registryhub *register* (write) tools — so
    # the registryhub READ tools never reached the edit_code per-step surface.
    # Instagram run #4 (2026-06-06): the backend wrote the auth scaffold then
    # produced ZERO business endpoints across the entire impl phase — it claimed
    # each endpoint task then FAILED it with "required source-of-truth RegistryHub
    # table read was not executed in this step; no deliverable completed",
    # because it literally could not call registryhub_get_table / registryhub_get_endpoint
    # while in edit_code (40 fail_task, 0 code writes). Notes (5 endpoints) slid
    # by; Instagram (30) deadlocked. Force-offer the reads so the lane can
    # read-then-write in the SAME step (FIX #21 — same crowd-out class as
    # _CLAIM_FLOW / _VALIDATION_FLOW; intersected with each agent's pool so only
    # lanes that already bundle registryhub_get_* see them).
    _CONTRACT_READ = {
        "registryhub_get_endpoint",
        "registryhub_list_endpoints",
        # #346: `registryhub_get_table` was pinned here and matches NO registered
        # tool, so the force-offer (always_include & candidate_names) dropped it
        # silently — the framework believed it pinned a table read and pinned
        # nothing. `registryhub_list_tables` below already provides that read, so
        # this is dead weight, not a capability.
        "registryhub_list_tables",
    }
    # PROPOSAL #39 (#2): the DEBUGGER's canonical triage tools. The debugger's whole job is
    # to triage validation bugs (bug_list_open → root-cause → bug_triage(assignee=...)), and
    # its prompt instructs exactly that — but with a 6-slot action budget and NO
    # stage_tool_allowlist, the ranker crowded bug_triage/bug_list_open OUT of its per-step
    # surface (run #36: the debugger asked the orchestrator "I don't have the bug_triage
    # tool" and flailed). Same crowd-out class as _VALIDATION_FLOW / _CLAIM_FLOW. Force-offer
    # them; bundle-intersection means only lanes that bundle bug_tools see them — i.e. the
    # debugger. The VERIFIER also bundles bug_tools but its implementation:action allowlist
    # (which never lists bug_triage) is intersected FIRST (tooling.py:166), so it does NOT
    # leak there — triage stays debugger-only by role.
    _BUG_FLOW = {
        "bug_triage",
        "bug_list_open",
        "bug_list_assigned_to",
    }
    # The FRONTEND lane's reference-screenshot read tools. frontend_agent.j2
    # mandates "inspect them via view_image() and produce a visual_reference_analysis
    # section ... list_reference_images ONCE in Phase A, then view_image() for every
    # path — never guess the UI from memory" — i.e. the lane is supposed to LOOK at
    # the references while authoring src/pages/*.jsx. But view_image / list_reference_images
    # live in the "file" tool category (tools.py: _assemble_agent_tool_pool) and were
    # NOT in edit_code's always-include, so the per-step ranker (top-N over ~150 tools)
    # crowded them out: youtube run #20 AND outlook run #1 both show the frontend lane
    # calling view_image ZERO times across the whole run (and pleading "I am missing
    # ... view_image" to the orchestrator) — it never once saw the references it was
    # told to match, so every projected page is a generic fallback. Same crowd-out
    # class as _CONTRACT_READ / _CLAIM_FLOW / _BUG_FLOW. Force-offer in edit_code (the
    # build stage); bundle-intersection means only lanes that bundle these (frontend)
    # ever see them — backend/verifier are unaffected.
    _REFERENCE_VIEW = {
        "view_image",
        "list_reference_images",
    }
    # The ORCHESTRATOR's milestone-roadmap tools (milestone_tools bundle, category
    # "milestone"). They were added to the orchestrator's tool_categories + bundle but
    # NOT to any action stage's category hints or always-include — so they registered
    # into the 223-tool map yet were NEVER offered to the LLM in any action stage. The
    # per-milestone KICKOFF-DETAIL turn then ordered the orchestrator to call
    # milestone_list / milestone_set_detail; the model emitted a call for a tool absent
    # from the offered set and gemini returned MALFORMED_FUNCTION_CALL every time → the
    # detail was never authored and the whole kickoff wedged (V25, lanes never woken).
    # Same crowd-out / never-offered class as _CONTRACT_READ / _REFERENCE_VIEW. Force-
    # offer in the communicate stage (roadmap coordination + the broadcast it leads to)
    # and the generic action stage; bundle-intersected, so ONLY the orchestrator (which
    # bundles milestone_tools) ever sees them.
    _MILESTONE_FLOW = {
        "milestone_list",
        "milestone_add",
        "milestone_update",
        "milestone_remove",
        "milestone_set_detail",
    }
    # The ORCHESTRATOR's audit / monitoring / delivery-gate tools. They are GRANTED
    # (tool_categories delivery/memory/coverage/seed/run + bundles deliverability_tools /
    # retro_tools / coverage_tools / seed_tools / run_tools) AND the orchestrator prompt
    # MANDATES them: coverage_audit_check + seed_audit_check are the hard pre-flight gates
    # DeliverProjectTool runs before delivery, get_retro_stats feeds the mandatory
    # submit_retro, deliverability_summary is the "quick check" counterpart to
    # deliverability_check, and run_list/run_get are the prompt's named way to monitor
    # validation runs probe-by-probe. But their categories (delivery, memory, coverage,
    # seed, run) appear in NO ACTION_STAGE_CATEGORY_HINTS stage and their names were in NO
    # _FLOW / ACTION_STAGE_ALWAYS_INCLUDE set — so they registered into the tool map yet were
    # NEVER offered to the LLM in any action stage. EXACT same never-offered class as the
    # _MILESTONE_FLOW bug (V25: the model emitted a call for a tool absent from the offered
    # set → MALFORMED_FUNCTION_CALL, kickoff wedged). Force-offer in the deliver stage (the
    # pre-delivery gates + retro stats) AND the generic action stage (run_list/run_get
    # monitoring + deliverability_summary throughout the resident loop); bundle-intersected,
    # so ONLY the orchestrator (which bundles all five families) ever sees them.
    _ORCH_AUDIT_FLOW = {
        "deliverability_summary",
        "get_retro_stats",
        "coverage_audit_check",
        "seed_audit_check",
        "run_list",
        "run_get",
    }
    # The KNOWLEDGE lane's structured-document tools (structured_knowledge_tools bundle,
    # category "knowledge"). They are GRANTED — the bundle registers submit_adr /
    # submit_runbook / submit_postmortem under category "knowledge" — and the knowledge
    # agent prompt MANDATES them (knowledge_agent.j2: "submit_adr / submit_runbook /
    # submit_postmortem when the triggering artifact exactly matches the document shape").
    # But "knowledge" appears in NO ACTION_STAGE_CATEGORY_HINTS stage (the communicate
    # stage hints knowledge_write, not knowledge) and their names were in NO _FLOW /
    # ACTION_STAGE_ALWAYS_INCLUDE set — so they registered into the tool map yet were
    # ONLY reachable via the low-priority ranker, i.e. never offered. EXACT same orphan /
    # never-offered class as _MILESTONE_FLOW (V25) and _ORCH_AUDIT_FLOW. Force-offer in the
    # communicate stage (where the knowledge lane writes its artifacts); bundle-intersected,
    # so ONLY the knowledge agent (which bundles structured_knowledge_tools) ever sees them.
    _KNOWLEDGE_DOC_FLOW = {
        "submit_adr",
        "submit_runbook",
        "submit_postmortem",
    }
    # FIX #110 (runs 24+26 autopsy, 2026-07-08): the visual-gate remediation tasks carry
    # perfect measured diffs + an EXECUTABLE zoom_compare mandate (#53), yet zoom_compare
    # and capture_webpage were called ZERO times across entire runs — the ~10-slot ranker
    # crowded the visual verify tools out of every step's offered subset (the documented
    # never-offered class: V25 / _ORCH_AUDIT_FLOW / _KNOWLEDGE_DOC_FLOW). The frontend
    # lane was structurally BLIND to its own render: it edited CSS from prose, never saw
    # a capture, and self-certified visual tasks complete. Force-offer the verify chain
    # where the fixing happens (edit_code) and where verification happens (run_checks);
    # bundle-intersected, so only lanes granting these tools (frontend/design) see them.
    _VISUAL_VERIFY_FLOW = {
        "capture_webpage",
        "zoom_compare",
        "sample_color",
        "crop_reference",
        "compare_with_screenshot",
        "extract_palette",
    }
    ACTION_STAGE_ALWAYS_INCLUDE: Dict[str, Set[str]] = {
        "communicate": {"check_inbox", "send_message", "ask_agent", "broadcast", "report_progress", "finish"}
                        | _DESIGN_GOVERNANCE | _HUB_REGISTRATION | _CLAIM_FLOW | _CONFLICT_FLOW | _MILESTONE_FLOW | _KNOWLEDGE_DOC_FLOW,
        "edit_code": {"read", "edit", "apply_patch", "write", "finish"} | _HUB_REGISTRATION | _CLAIM_FLOW | _CONFLICT_FLOW | _CONTRACT_READ | _REFERENCE_VIEW | _VISUAL_VERIFY_FLOW,
        "run_checks": {"lint", "test_api", "finish"} | _CLAIM_FLOW | _VALIDATION_FLOW | _CONTRACT_READ | _VISUAL_VERIFY_FLOW,
        "delegate_team": {"finish"},
        # ``submit_retro`` + ``deliverability_check`` are the pre-delivery gate
        # tools — without them force-offered the ranker crowds them out and the
        # orchestrator reports "submit_retro gate tool is unavailable" then spins
        # forever even though the app is validated (smoke #9: RunHub run completed
        # fail_count=0, blocked only on the retro gate). Intersected with the
        # agent's pool, so only the orchestrator (which bundles retro_tools) gets
        # them. See FIX #1 (_VALIDATION_FLOW / run_validation) — same crowd-out.
        # PROPOSAL #30 S2: ``get_skill`` is force-offered here because deliver_project /
        # report_completion are gated on release_readiness_consulted (the gate requires
        # get_skill(release-readiness) first). get_skill is granted but, with the
        # orchestrator running a single un-allowlisted ``action`` stage, the ~10-slot
        # ranker crowded it out of ~150 tools → the orchestrator could never consult the
        # skill → deliver_project blocked (run #28: 33× wedge). Bundle-intersected, so
        # only the orchestrator (which bundles knowledge_skill_tools) ever sees it.
        "deliver": {"finish", "deliver_project", "report_completion", "submit_retro", "deliverability_check", "get_skill"} | _DESIGN_GOVERNANCE | _HUB_REGISTRATION | _CLAIM_FLOW | _CONFLICT_FLOW | _VALIDATION_FLOW | _ORCH_AUDIT_FLOW,
        "action": {"finish", "submit_retro", "deliverability_check", "get_skill"} | _DESIGN_GOVERNANCE | _HUB_REGISTRATION | _CLAIM_FLOW | _CONFLICT_FLOW | _VALIDATION_FLOW | _BUG_FLOW | _MILESTONE_FLOW | _ORCH_AUDIT_FLOW,
    }

    # PROPOSAL #28 F2 — validation/delivery tools that are MEANINGLESS during KICKOFF
    # (the kickoff_finalized precondition blocks them anyway, so force-offering them
    # only wastes a round: the orchestrator attempts run_validation/deliverability_check
    # then gets blocked). step_pipeline.tooling subtracts these from the action-stage
    # always-include while ``not kickoff_finalized_signal`` — a STRICT no-op post-kickoff
    # (the signal is monotonic), so the smoke #9/#41 delivery-gate crowd-out fix stays
    # intact once the contract exists.
    _KICKOFF_DEFER_TOOLS = _VALIDATION_FLOW | {
        "deliver_project", "report_completion", "submit_retro",
    }

    def __init__(
        self,
        config: AgentConfig,
        llm: LLM,
        workspace_manager: "WorkspaceManager",
        include_vision: bool = False,
    ):
        # Initialize parent with debug logging (stuck detection disabled - repeated write/edit calls are normal)
        super().__init__(
            config=config,
            role=AgentRole.WORKER,
            enable_stuck_detection=False,
            enable_debug_logging=True,
        )
        
        # Override agent_id from class attribute
        self._agent_id = self.agent_id
        self._name = self.agent_name
        
        # LLM
        self.llm = llm
        self._include_vision = include_vision
        
        # Workspace
        self.workspace = workspace_manager

        # Per-agent git worktree path (Phase 0). Set later by ``set_hubs``
        # once a HubRegistry with CodeHub is available — until then tools
        # are built against the shared base. ``set_hubs`` re-registers
        # the tool pool with a worktree-aware ``PathRoutedWorkspace``
        # so ``app/*`` writes route into the agent's own worktree
        # while cross-agent shared paths (``design/*``, ``shared/*``,
        # ``.memory/*``) stay anchored at the project base.
        self._worktree_dir: Optional[Path] = None

        # Relocate the debug jsonl log into this project's workspace so the
        # Action History UI shows tool calls for THIS run only. BaseAgent's
        # default landed at a CWD-relative ``.agent_logs/`` which (a)
        # depended on launch directory and (b) accumulated across unrelated
        # projects. Each workspace now owns its own action-history dir.
        if workspace_manager and hasattr(workspace_manager, "base_dir"):
            try:
                self._relocate_debug_log_to(Path(workspace_manager.base_dir) / ".agent_logs")
            except Exception as _log_err:
                # Don't fail agent boot if relocation fails.
                self._logger.debug(
                    f"[{self.agent_id}] debug-log relocation skipped: {_log_err}"
                )
        
        # External MessageBus reference (for inter-agent communication)
        self._external_bus: Optional[MessageBus] = None
        
        # Context
        self._requirements: Dict[str, Any] = {}
        self._design_docs: Dict[str, str] = {}
        self.gen_context = None
        
        # Memory (generator-specific)
        # Default lifecycle:
        # - working agents keep project-scoped jsonl memory under the generated workspace
        # - the knowledge resident lane writes durable cross-run memory under ~/.env-gen
        memory_path = None
        knowledge_ttl_seconds = 14 * 24 * 3600
        if workspace_manager and hasattr(workspace_manager, "base_dir"):
            if self.agent_id == "knowledge":
                memory_path = str(
                    Path.home()
                    / ".env-gen"
                    / "knowledge"
                    / "agent-memory"
                    / f"{self.agent_id}.knowledge.jsonl"
                )
                # Was None (never expire) — the file became a cross-project leak,
                # accumulating run-specific observations ("design reported specs
                # for the flight search project") that misled future runs in
                # unrelated projects. Cap at 14 days so even un-pruned entries
                # age out; the durable cross-project knowledge belongs in the
                # SQLite knowledge.db (which the audit prompt now keeps clean).
                knowledge_ttl_seconds = 14 * 24 * 3600
            else:
                memory_path = str(Path(workspace_manager.base_dir) / ".memory" / f"{self.agent_id}.knowledge.jsonl")
        self.memory = GeneratorMemory(
            llm=llm,
            short_term_size=50,
            # 30 was too tight once condensation actually fired (paired with
            # keep_recent=28 it left ~no headroom → the lane lost the working
            # context to keep coding). 50 gives the action phase room to hold the
            # task + contract + recent code, while still capping far below the
            # ~770-message saturation that caused the original bloat.
            # Env-configurable so the proven "small + unbounded" regime can be
            # reproduced per milestone: condensation in ANY form breaks the coding
            # lane's implementation momentum (it reverts to memory-bookkeeping), so
            # with small enough slices we set this very high to effectively disable
            # condensation (never fires under the ~770 saturation a small slice
            # stays below). Default 50 preserves prior behavior for other callers.
            condenser_max_size=int(os.environ.get("ENVGEN_CONDENSER_MAX_SIZE", "50")),
            persistence_mode="jsonl",
            persistence_path=memory_path,
            knowledge_ttl_seconds=knowledge_ttl_seconds,
        )
        self.memory_bank: Optional[MemoryBank] = None
        
        # (Context-Snowball manager removed 2026-07-27 — it was instantiated but
        # never fed or read; the step pipeline sends the raw messages[] list to the
        # LLM. Live context reduction is tool-level compaction (#302/#303/#305) plus
        # _mask_old_observations in step_runner.py.)

        # Skills consulted via get_skill this run (read by SkillConsultGate;
        # populated at the tool chokepoint — skill_consult.py).
        self._consulted_skills: Set[str] = set()
        # §5: reference images this agent actually loaded via view_image this run. The
        # frontend kickoff substance gate can require every reference_image_manifest path to
        # be in this set (so a manifest can't be authored from memory). Populated by ViewImageTool.
        self._viewed_reference_paths: Set[str] = set()
        # Tool instances for LLM tool calling
        self._tool_instances: Dict[str, BaseTool] = {}
        self._register_env_gen_tools()
        
        # Jinja2 environment
        self._jinja_env = Environment(
            loader=FileSystemLoader(str(PROMPTS_DIR)),
            autoescape=select_autoescape(['html', 'xml']),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        
        # Task completion event for external coordination
        self._task_complete_event = asyncio.Event()
        
        # Project delivery event (used by the coordinating lane for final delivery)
        self._project_delivered_event = asyncio.Event()
        self._project_delivered = False
        
        # Ready event - set when agent is initialized and running
        self._ready_event = asyncio.Event()
        
        # Shutdown flag
        self._shutdown_requested = False
        
        # Priority message queue (replaces BaseAgent's simple queue for urgent handling)
        self._priority_queue = PriorityMessageQueue(maxsize=100)
        # The event loop this agent processes on (captured in run_loop). Used by
        # receive_message to redispatch cross-loop deliveries — a hub event
        # emitted from inside a `to_thread` tool worker arrives on a DIFFERENT
        # loop than the one the agent's queues (asyncio.Lock/Event) are bound to,
        # which raises "bound to a different event loop" and silently drops the
        # message (seen flooding orchestrator delivery in the 2026-06-06 smokes).
        self._home_loop: Optional[asyncio.AbstractEventLoop] = None
        
        # Processing state tracking
        self._processing_state = ProcessingState.IDLE
        
        # Pending question responses (question_id -> Future)
        self._pending_questions: Dict[str, asyncio.Future] = {}
        
        # Urgent messages to inject into current conversation (true interrupt)
        self._interrupt_messages: List[Dict] = []
        
        # Message tracker for sent message status
        self._message_tracker = MessageTracker()
        
        # Hub handle for coordination (replaces CRDT observer in Cutover 5)
        self._hubs = None  # Set via set_hubs()
        
        # Track upstream task_ready senders for runtime dependency gates.
        self._upstream_ready_agents: Set[str] = set()

        # Execution mode: direct (default) vs team.
        # - team mode: focus on team orchestration and coordination actions.
        # - direct mode: normal implementation actions.
        self._execution_mode: str = "direct"
        # Round 8h Stage 1: renamed from ``_implementation_bootstrapped``
        # (which was the flag flipped by the retired
        # ``ImplementationBootstrapPolicy``). The new
        # ``KickoffBootstrapGate`` reads + writes this flag using
        # WorkHub task assignments as the bootstrap signal instead of
        # the filesystem ``design/spec.*.json`` check that deadlocked
        # post round-8e.1.
        self._kickoff_bootstrapped: bool = False
        self._active_stage: str = "action"
        # PR3.1.2 / Loop B ⑧: phase = the high-level task category the
        # step pipeline is servicing. Kickoff and implementation both
        # cycle through the same stages (hub_pulse/.../action/...), so
        # ``_active_stage`` alone cannot distinguish them. The kickoff
        # handler sets this to ``"kickoff"`` while running, and the
        # PR3.1/PR3.2 yaml levers accept a composite ``"phase:stage"``
        # key that takes precedence over the bare ``stage`` key when
        # phase is set. Without a phase, the lever falls back to the
        # bare stage key (no regression).
        self._active_phase: Optional[str] = None
        # Hub-focus model: which hub the agent has "moved to". While set, only that
        # hub's WRITE tools are offered; hub reads + cross-hub awareness stay open.
        # Switched via the focus_hub tool; surfaced to the UI via agent status.
        self._focus_hub: Optional[str] = None
        self._execution_pipeline_config: Dict[str, Any] = {}
        self._step_reminders: List[Any] = []
    
    # ==================== LIFECYCLE ====================
    
    async def run_loop(self):
        """
        Convenience method to initialize, start, and run until shutdown.
        
        This is what Orchestrator calls. It wraps the BaseAgent lifecycle.
        """
        # Capture the home loop BEFORE start() kicks off the consume side, so
        # cross-loop deliveries (events emitted from to_thread tool workers) can
        # be redispatched here by receive_message instead of erroring on the
        # queue's loop-bound Lock/Event.
        self._home_loop = asyncio.get_running_loop()
        # Initialize
        if not await self.initialize():
            self._logger.error(f"[{self.agent_id}] Failed to initialize")
            self._ready_event.set()  # Set even on failure so waiters don't hang
            return
        
        # Start (this starts _main_loop internally)
        if not await self.start():
            self._logger.error(f"[{self.agent_id}] Failed to start")
            self._ready_event.set()  # Set even on failure
            return
        
        # Signal ready - agent is now running and can accept tasks
        self._ready_event.set()
        self._logger.info(f"[{self.agent_id}] Ready to accept tasks")
        
        # Wait until shutdown is requested, checking for issues periodically
        while not self._shutdown_requested and self._running:
            # Check for urgent messages (including issues from other agents)
            try:
                while await self._check_and_handle_urgent():
                    pass  # Handle all pending urgent messages
            except Exception as e:
                self._logger.error(f"[{self.agent_id}] Error handling urgent message: {e}")
            
            await asyncio.sleep(0.5)
        
        # Stop
        await self.stop()
        await self.cleanup()
        
        self._logger.info(f"[{self.agent_id}] run_loop completed")
    
    async def wait_ready(self, timeout: float = 30.0) -> bool:
        """
        Wait until agent is ready to accept tasks.
        
        Returns:
            True if ready, False if timeout or failed to start.
        """
        try:
            await asyncio.wait_for(self._ready_event.wait(), timeout=timeout)
            return self._running  # Check if actually running (not failed)
        except asyncio.TimeoutError:
            self._logger.warning(f"[{self.agent_id}] Timeout waiting for ready")
            return False
    
    def request_shutdown(self):
        """Request the agent to shutdown gracefully."""
        self._shutdown_requested = True
    
    async def on_initialize(self) -> None:
        """Called during initialize() - setup env gen specific resources."""
        self._logger.info(f"[{self.agent_id}] Initializing environment generation agent")
        try:
            project_info = {
                "name": getattr(getattr(self, "gen_context", None), "name", "") or getattr(self, "agent_name", "Project"),
                "description": getattr(getattr(self, "gen_context", None), "description", "") or "",
            }
            self.init_memory_bank(project_info)
        except Exception as e:
            self._logger.warning(f"[{self.agent_id}] Failed to initialize memory bank: {e}")
    
    async def on_start(self) -> None:
        """Called during start() - agent is now running."""
        self._logger.info(f"[{self.agent_id}] Started, ready to process tasks")
    
    async def on_stop(self) -> None:
        """Called during stop()."""
        self._logger.info(f"[{self.agent_id}] Stopping")
    
    # ==================== TASK PROCESSING ====================
    
    async def process_task(self, task: TaskMessage) -> ResultMessage:
        """
        Process task via agentic loop.
        
        Implements the abstract method from BaseAgent.
        """
        # Extract task data from message
        task_data = task.payload if isinstance(task.payload, dict) else {}
        if isinstance(task.payload, str):
            try:
                task_data = json.loads(task.payload)
            except:
                task_data = {"description": task.payload}

        raw_requirements = task_data.get("raw_requirements")
        if raw_requirements:
            try:
                self.init_memory_bank(
                    {
                        "name": getattr(getattr(self, "gen_context", None), "name", "") or self.agent_name,
                        "description": str(raw_requirements).strip(),
                        "requirements": str(raw_requirements).strip(),
                    }
                )
            except Exception as e:
                self._logger.warning(f"[{self.agent_id}] Failed to hydrate memory bank from task context: {e}")
        
        # Pin the implementation phase so a profile's ``implementation:*``
        # stage_tool_allowlist applies (kickoff handlers pin "kickoff"; outside
        # them _active_phase is None and lanes drift into get_document/coordination
        # instead of writing code — smoke #4: backend entered edit_code 38× yet
        # called workhub_get_document/read, never write/register, 0 endpoints). Only
        # affects allowlist lookup (tooling.py:493, step_pipeline/tooling.py:112);
        # profiles without an ``implementation:*`` entry are unaffected.
        _prev_phase = getattr(self, "_active_phase", None)
        # TEST-FIX vs IMPLEMENTATION: a remediation/bug-fix task runs in the test-fix
        # phase (close the reported defect; don't start new features), not initial build.
        # Detect via explicit markers the orchestrator/debugger set on a fix task; default to
        # implementation so normal build tasks are unaffected. Pins the phase for the
        # ``test_fix:*`` stage_tool_allowlist (falls through to the full toolset if a profile
        # has no such entry — safe).
        _wf = str(task_data.get("workflow") or "").lower()
        _is_fix = (_wf in ("fix", "remediation", "test_fix")
                   or task_data.get("phase") == "test_fix"
                   or bool(task_data.get("bug_id") or task_data.get("is_remediation")))
        self._active_phase = "test_fix" if _is_fix else "implementation"
        # Keep the memory bank's live STATE in sync so a read_memory_bank reflects the
        # actual phase / lane / task — the active_context was frozen at init ("Working
        # on: initialization") and contradicted the agent's real phase, feeding drift.
        try:
            if getattr(self, "memory_bank", None) is not None:
                _foc = f"{self._active_phase} phase · lane={self._agent_id}"
                _tt = task_data.get("title") or task_data.get("task_name") or task_data.get("id")
                if _tt:
                    _foc += f" · task: {str(_tt)[:80]}"
                self.memory_bank.set_current_focus(_foc)
        except Exception:
            pass
        # Full hub-truth auto-sync: refresh the READ-ONLY memory-bank sections
        # (progress / next / blockers / issues) from authoritative hub state so the
        # digest is real without depending on the agent calling report_progress.
        self._sync_memory_bank_state()
        try:
            # Run agentic loop
            result = await self.execute(task_data)

            # Create result message
            return create_result_message(
                source_id=self._agent_id,
                target_id=task.header.source_agent_id,
                task_id=task.task_id,
                success=result.get("success", False),
                result_data=result,
            )
        finally:
            # Restore the prior phase (kickoff handlers manage their own).
            self._active_phase = _prev_phase
            # Signal completion
            self._task_complete_event.set()
            if task.task_name == "resident_message_wakeup":
                self._resident_wakeup_task_pending = False
                # #966: a wake-eligible message that landed while this wakeup was in flight
                # was dropped by the dedup guard. The inbox read inside the task may have
                # happened before it arrived, so clearing the flag here would strand it with
                # nothing left to re-trigger. Re-arm once; the woken step either finds real
                # work or finishes immediately.
                _deferred = getattr(self, "_wakeup_deferred_966", None)
                if _deferred:
                    self._wakeup_deferred_966 = None
                    self._resident_wakeup_task_pending = True
                    asyncio.create_task(
                        self._enqueue_resident_wakeup_966(**_deferred))
            if getattr(self, "_is_resident_lane", False):
                try:
                    agent_manager = getattr(self, "_agent_manager", None)
                    if agent_manager is not None and hasattr(agent_manager, "set_runtime_agent_lifecycle"):
                        agent_manager.set_runtime_agent_lifecycle(self._agent_id, "idle")
                except Exception:
                    pass

    def _sync_memory_bank_state(self) -> None:
        """FRAMEWORK auto-sync: rebuild the READ-ONLY memory-bank sections from
        authoritative hub state for THIS lane, so the digest reflects real
        progress / next / blockers / issues without depending on the agent
        calling report_progress (whose GeneratorMemory feeder path was dead).
        Derives from WorkHub task state + open bugs; REPLACES sections (live
        snapshot). Best-effort; never raises."""
        try:
            mb = getattr(self, "memory_bank", None)
            hubs = getattr(self, "_hubs", None)
            wh = getattr(hubs, "workhub", None) if hubs is not None else None
            if mb is None or wh is None or not hasattr(wh, "list_tasks"):
                return
            aid = self._agent_id

            def _title(t):
                return str((t or {}).get("title") or (t or {}).get("id") or "")[:90]

            try:
                mine = [t for t in (wh.list_tasks(assignee=aid) or []) if isinstance(t, dict)]
            except Exception:
                mine = []
            completed = [_title(t) for t in mine if t.get("status") == "completed"]
            in_progress = [_title(t) for t in mine if t.get("status") == "in_progress"]
            pending = [t for t in mine if t.get("status") == "pending"]

            # next vs blocked: a pending task is READY iff every dep is completed.
            try:
                all_tasks = wh.stores.tasks.value() or {}
            except Exception:
                all_tasks = {}

            def _dep_ok(t):
                for d in (t.get("depends_on") or []):
                    dep = all_tasks.get(d)
                    if not isinstance(dep, dict) or dep.get("status") != "completed":
                        return False
                return True

            next_steps = [_title(t) for t in pending if _dep_ok(t)]
            blockers = [f"{_title(t)} — blocked on incomplete deps"
                        for t in pending if not _dep_ok(t)]

            # Open bugs: all-open → Known Issues; bugs owned by THIS lane → also blockers.
            known_issues = []
            try:
                for b in (wh.list_open_bugs() or []):
                    st = (b.get("metadata") or {}).get("bug_state", "open")
                    known_issues.append(f"[{st}] {_title(b)}")
                for b in (wh.list_bugs_assigned_to(aid) or []):
                    blockers.append(f"bug: {_title(b)}")
            except Exception:
                pass

            mb.sync_framework_state(
                completed=completed, in_progress=in_progress,
                next_steps=next_steps, blockers=blockers, known_issues=known_issues)
        except Exception:
            pass

    async def execute(self, task: Dict) -> Dict:
        """Execute task via agentic loop."""
        system_prompt = self._compose_system_prompt()
        task_prompt = self._build_task_prompt(task)
        
        # Log prompt
        # Log using configured model name (LLM wrapper does not expose model_id)
        model_name = getattr(self.llm.config, "model_name", "unknown")
        self.log_prompt(f"{system_prompt}\n---\n{task_prompt}", model=str(model_name))
        
        return await self.run_agentic_loop(
            system_prompt=system_prompt,
            initial_prompt=task_prompt,
            max_steps=task.get("max_steps", 2000),
        )

    # ==================== HUMAN MESSAGE HANDLER (Cutover 29) ====================

    async def _handle_human_message(self, message) -> None:
        """A real human just sent us a direct message in chat.

        Was (Cutover 29): single ``_generate_text`` call with "Do not
        call any tools" in the system prompt — agent could only reply,
        never act. Now: run a bounded mini-loop (``max_steps=5``) with
        the agent's normal tool surface so it can actually do what the
        user asked, then publish the resulting summary as the reply.

        The reply goes to EventHub via ``publish_agent_reply``, where
        the bridge fans it out to all thread participants + the
        synthetic ``human_user`` inbox (which the UI ChatPanel reads).
        """
        metadata = getattr(message, "metadata", {}) or {}
        thread_id = metadata.get("thread_id") or getattr(message.header, "correlation_id", "")
        if not thread_id:
            self._logger.warning(f"[{self.agent_id}] human_message missing thread_id; skipping")
            return

        payload = getattr(message, "payload", {}) or {}
        user_text = (payload.get("text") if isinstance(payload, dict) else "") or ""
        if not user_text.strip():
            self._logger.warning(f"[{self.agent_id}] human_message with empty text; skipping")
            return

        # Compress the thread BEFORE running the mini-loop so the
        # injected "Active human directives" block uses the new summary
        # instead of replaying the entire long transcript verbatim. Best
        # effort — failures don't block the reply.
        try:
            from multi_agent.agents.runtime.human_chat import compress_thread_if_needed
            await compress_thread_if_needed(agent=self, thread_id=thread_id)
        except Exception as _cmp_err:
            self._logger.debug(
                f"[{self.agent_id}] thread compression skipped: {_cmp_err}"
            )

        # Tell the action pipeline / tool emitters this round is in
        # chat mode so they can publish ``agent_chat_step`` events to
        # the live UI. Always cleared in ``finally``.
        prev_chat_thread = getattr(self, "_chat_mode_thread_id", None)
        self._chat_mode_thread_id = thread_id
        try:
            reply_text = await self._run_chat_mini_loop(
                user_text=user_text,
                thread_id=thread_id,
                max_steps=5,
            )
        except Exception as e:
            self._logger.warning(f"[{self.agent_id}] chat mini-loop failed: {e}")
            reply_text = (
                f"(I hit an error handling your message: {e})"
            )
        finally:
            self._chat_mode_thread_id = prev_chat_thread

        reply_text = (reply_text or "").strip() or "(no response generated)"

        if self._hubs is None:
            self._logger.warning(f"[{self.agent_id}] no hubs handle; cannot publish reply")
            return

        try:
            self._hubs.eventhub.publish_agent_reply(
                thread_id=thread_id,
                agent=self.agent_id,
                text=reply_text,
            )
        except Exception as e:
            self._logger.error(f"[{self.agent_id}] publish_agent_reply failed: {e}")

    async def _run_chat_mini_loop(
        self,
        *,
        user_text: str,
        thread_id: str,
        max_steps: int = 5,
    ) -> str:
        """Bounded LLM-with-tools loop for a single human chat turn.

        Reuses the agent's normal tool surface (``_build_tool_schema_map``,
        ``_execute_tool``, ``_normalize_tool_call``) but skips the
        heavy 7-stage ReAct pipeline — chat replies need to be fast.

        Termination:
            * Agent emits text without tool calls → that text is the reply.
            * Agent calls ``finish(message=...)`` → finish message is the reply.
            * ``max_steps`` exhausted → last assistant text or a stub.

        Each tool call emits an ``agent_chat_step`` event to the
        active chat thread so the UI can show live tool-call progress
        between the typing dots and the final reply.

        Override or monkey-patch in tests by replacing this method on
        the instance.
        """
        try:
            from utils.llm import Message
        except Exception:
            # Tests / minimal harnesses that lack the LLM stack get a
            # safe canned reply rather than a hard import error.
            return f"({self.agent_id} chat mini-loop: LLM stack unavailable)"

        llm = getattr(self, "llm", None) or getattr(self, "_llm", None)
        if llm is None:
            return f"({self.agent_id}: LLM not configured)"

        # Build the chat-mode system prompt on top of the agent's normal
        # composed prompt (which already includes Active human directives).
        try:
            base_system = self._compose_system_prompt()
        except Exception:
            base_system = self._get_system_prompt() if hasattr(self, "_get_system_prompt") else ""
        chat_system = (
            f"{base_system}\n\n"
            "=== Chat mode ===\n"
            "You are mid-conversation with the real human user. You may "
            "call any of your tools to act on what they asked — claim "
            "tasks, send messages, inspect state, write code, whatever "
            "is appropriate. Keep iterations tight (small step budget). "
            "When you are done — whether you completed the work or you "
            "have nothing further to do — emit a single concise plain-"
            "text paragraph summarizing what you did and what's next. "
            "That paragraph will be sent verbatim to the user as your "
            "reply, so write it like a human (no markdown headers, no "
            "code fences). Do NOT call ``finish()`` here; the chat loop "
            "exits automatically when you respond with text and no "
            "further tool calls."
        )

        initial = (
            f"## Direct message from human user\n\n"
            f"Thread: `{thread_id}`\n\n"
            f"> {user_text}\n\n"
            f"Act on this efficiently. End with a concise plain-text summary."
        )

        # Tool surface = the agent's normal tools (whatever it has).
        try:
            tool_schema_map = self._build_tool_schema_map()
            tools = list(tool_schema_map.values()) if tool_schema_map else None
        except Exception as exc:
            self._logger.debug(f"[{self.agent_id}] chat mini-loop: tool schema build failed: {exc}")
            tools = None

        messages: list = [Message.system(chat_system), Message.user(initial)]
        last_assistant_text = ""

        # Local file tracking — mirrors step_pipeline/tooling.py:_process_tool_calls
        # so finish-policies invoked from this mini-loop see real file
        # evidence (HubConsistencyPolicy in particular needs to know what
        # the agent wrote in order to demand a hub registration). Without
        # this, the gate is handed empty lists and silently no-ops.
        chat_files_created: List[str] = []
        chat_files_modified: List[str] = []

        # NO tool-result cap (user decision 2026-06-24): tool output MUST reach the
        # agent COMPLETE — a truncated result is a correctness hazard (the agent acts
        # on a half-truth) and must never be obstructed. The run model's large context
        # absorbs full results; tools that could be enormous (file reads, listings)
        # already paginate at their own layer, so the full result here is bounded in
        # practice. (Was a 10000-char cap that silently cut large reads/dumps.)

        for step in range(max_steps):
            # Respect shutdown signals between rounds — matches the
            # canonical run_agentic_loop's check (step_runner.py).
            if getattr(self, "_shutdown_requested", False):
                self._logger.info(
                    f"[{self.agent_id}] chat mini-loop exiting on _shutdown_requested"
                )
                return last_assistant_text or "(shutdown requested)"
            # Drain any urgent message that arrived between rounds (a
            # second human_message, a cancel, etc.). Otherwise follow-up
            # messages starve until the entire 5-round mini-loop finishes
            # — user perceives the agent as ignoring them.
            try:
                drain = getattr(self, "_check_and_handle_urgent", None)
                if callable(drain):
                    # Cap to a few drains so we don't get stuck recursing.
                    for _ in range(3):
                        handled = await drain()
                        if not handled:
                            break
            except Exception as _drain_err:
                self._logger.debug(
                    f"[{self.agent_id}] mini-loop urgent drain failed: {_drain_err}"
                )

            from ..runtime.reasoning_effort import resolve_effort
            _effort = resolve_effort(
                getattr(self.workspace, "base_dir", "."),
                self.agent_id,
                getattr(self, "reasoning_effort", None),
            )
            # Bound this loop's context too: the mini-loop builds its own
            # messages list and appends assistant+tool turns each round with no
            # step-boundary condensation. Reuse the shared chokepoint guard so
            # large tool results across rounds can't blow the context window.
            _guard = getattr(self, "_maybe_condense_messages_in_place", None)
            if callable(_guard):
                try:
                    await _guard(messages)
                except Exception:
                    pass
            try:
                if hasattr(self, "call_with_retry"):
                    response = await self.call_with_retry(
                        self.llm.chat_messages, messages, tools=tools, reasoning_effort=_effort
                    )
                else:
                    response = await self.llm.chat_messages(messages, tools=tools, reasoning_effort=_effort)
            except Exception as exc:
                self._logger.warning(
                    f"[{self.agent_id}] chat mini-loop step {step} LLM call failed: {exc}"
                )
                return last_assistant_text or f"(LLM error during chat: {exc})"

            assistant_text = (getattr(response, "content", None) or "").strip()
            tool_calls = list(getattr(response, "tool_calls", []) or [])

            if assistant_text:
                last_assistant_text = assistant_text

            # Record the assistant turn so subsequent rounds see context.
            # Strict provider clients (Anthropic-style) reject ``content=''``
            # alongside tool_calls — pass content=None when empty so the
            # underlying SDK sends the canonical "tool_use only" shape.
            content_for_turn = assistant_text if assistant_text else None
            try:
                messages.append(Message.assistant(content=content_for_turn, tool_calls=tool_calls))
            except TypeError:
                # Some Message implementations don't accept both kwargs.
                try:
                    messages.append(Message.assistant(content=content_for_turn))
                except Exception:
                    pass

            if not tool_calls:
                # Plain-text response → that's the reply, we're done.
                return last_assistant_text or "(no reply)"

            for tool_call in tool_calls:
                try:
                    tool_name, tool_args, tool_call_id = self._normalize_tool_call(tool_call, step)
                except Exception:
                    continue
                if not tool_name:
                    continue

                # ``finish``/``deliver_project``/``report_completion`` here
                # mean "I'm done" — but BEFORE accepting we must run the
                # same workflow_policies (HubConsistencyPolicy,
                # ClaimAssignedTasksPolicy, RetroBeforeDeliverPolicy,
                # LaneIdleCircuitBreakerPolicy bookkeeping, …) the
                # autonomous loop uses. Otherwise chat becomes a
                # back-door around Phase A gates: an agent could emit
                # any of these in chat without registering hub entries
                # and we'd accept the reply.
                #
                # PR 2.5-fix-2 re-verify (2026-05-29): previously this
                # branch only matched ``finish``, asymmetric with
                # step_pipeline/tooling.py which routes the deliver
                # lifecycle through the same hook so the retro gate
                # fires. The chat mini-loop now matches the same
                # three names so a chat-mode delivery is gated
                # identically.
                if tool_name in ("finish", "deliver_project",
                                 "report_completion"):
                    apply_policies = getattr(self, "_apply_finish_policies", None)
                    if callable(apply_policies):
                        try:
                            outcome = await apply_policies(
                                tool_name=tool_name,
                                tool_args=tool_args,
                                tool_call=tool_call,
                                tool_call_id=tool_call_id,
                                messages=messages,
                                files_created=list(chat_files_created),
                                files_modified=list(chat_files_modified),
                            )
                        except Exception as _pol_err:
                            try:
                                self._logger.warning(
                                    f"[{self.agent_id}] mini-loop finish-policy call failed: {_pol_err}"
                                )
                            except Exception:
                                pass
                            outcome = None
                        # ``continue`` from a policy means "blocked — loop
                        # again to give the agent a chance to fix it". We
                        # honor that by skipping the early return and
                        # continuing the mini-loop's outer for-step.
                        if outcome and outcome.get("action") == "continue":
                            self._emit_chat_step(
                                thread_id=thread_id, tool_name=tool_name,
                                tool_args=tool_args,
                                result_data="blocked by workflow policy; continuing",
                                success=False,
                            )
                            # Skip the rest of this tool_call list — the
                            # policy already appended its own assistant /
                            # tool / user messages into ``messages``.
                            break  # back to the next outer step
                    # PR 2.5-fix-2 re-verify (2026-05-29): each
                    # finish-class tool exposes a different reply
                    # field. ``finish`` uses ``message``,
                    # ``deliver_project`` uses ``delivery_summary``,
                    # ``report_completion`` uses ``summary`` (or
                    # ``task``). Read the right one for the tool that
                    # actually fired; the previous always-read-
                    # ``message`` form silently dropped delivery
                    # summaries on the floor and fell back to stale
                    # last_assistant_text or "(done)".
                    if tool_name == "deliver_project":
                        finish_text = (
                            (tool_args.get("delivery_summary") or "").strip()
                        )
                    elif tool_name == "report_completion":
                        finish_text = (
                            (tool_args.get("summary") or "").strip()
                            or (tool_args.get("task") or "").strip()
                        )
                    else:
                        finish_text = (tool_args.get("message") or "").strip()
                    if not finish_text:
                        finish_text = last_assistant_text
                    self._emit_chat_step(
                        thread_id=thread_id, tool_name=tool_name, tool_args=tool_args,
                        result_data=finish_text, success=True,
                    )
                    return finish_text or "(done)"

                try:
                    result = await self._execute_tool(tool_name, tool_args)
                except Exception as exc:
                    self._emit_chat_step(
                        thread_id=thread_id, tool_name=tool_name, tool_args=tool_args,
                        result_data=f"exception: {exc}", success=False,
                    )
                    continue

                success = bool(getattr(result, "success", False))
                result_payload = (
                    getattr(result, "data", None)
                    if success
                    else getattr(result, "error_message", "(no error message)")
                )

                # File-tracking parity with step_pipeline/tooling.py:_process_tool_calls
                # — without this, finish-policies invoked from the mini-loop
                # see empty file lists and HubConsistencyPolicy silently
                # no-ops. Also mirror memory.record_file_* so cross-cutting
                # session tracking (used by other gates) stays consistent.
                _writer_path = (
                    tool_args.get("file_path")
                    or tool_args.get("path")
                ) if isinstance(tool_args, dict) else None
                if success and _writer_path:
                    if tool_name == "write":
                        chat_files_created.append(_writer_path)
                        if hasattr(self, "memory"):
                            try:
                                self.memory.record_file_created(_writer_path)
                            except Exception:
                                pass
                        _auto_stage_in_mini_loop(self, _writer_path, action="add")
                    elif tool_name in ("edit", "apply_patch"):
                        chat_files_modified.append(_writer_path)
                        if hasattr(self, "memory"):
                            try:
                                self.memory.record_file_modified(_writer_path)
                            except Exception:
                                pass
                        _auto_stage_in_mini_loop(self, _writer_path, action="add")
                    elif tool_name == "delete_file":
                        _auto_stage_in_mini_loop(self, _writer_path, action="delete")

                self._emit_chat_step(
                    thread_id=thread_id, tool_name=tool_name, tool_args=tool_args,
                    result_data=result_payload, success=success,
                )

                # Append the tool result so the next round sees what
                # happened — but cap the text to ``_TOOL_RESULT_CAP``
                # chars. Without the cap, a tool returning a large dict
                # (filesystem listing, full file body) blows the LLM
                # context window on the very next round, surfacing as
                # a cryptic 'LLM error during chat' to the user.
                try:
                    # NO cap — append the FULL tool result (user decision 2026-06-24:
                    # tool output must never be truncated/obstructed).
                    messages.append(Message.tool(str(result_payload), tool_call_id))
                except Exception:
                    pass

        # Out of steps with no plain-text response → fall back.
        return last_assistant_text or (
            f"(I worked on your request for {max_steps} rounds without finalizing. "
            f"Please check my actions or send a more specific instruction.)"
        )

    def _emit_chat_step(
        self,
        *,
        thread_id: str,
        tool_name: str,
        tool_args: Dict,
        result_data: Any,
        success: bool,
    ) -> None:
        """Publish an ``agent_chat_step`` event to the chat thread.

        Used by the chat mini-loop so the live UI can show tool-call
        progress between the typing-dots and the final reply.
        """
        hubs = getattr(self, "_hubs", None)
        if hubs is None or not hasattr(hubs, "eventhub"):
            return

        def _short(value: Any, limit: int = 240) -> str:
            if value is None:
                return ""
            try:
                if isinstance(value, str):
                    text = value
                else:
                    import json as _json
                    text = _json.dumps(value, default=str)
            except Exception:
                text = str(value)
            text = text.replace("\n", " ").strip()
            if len(text) > limit:
                text = text[: limit - 1] + "…"
            return text

        try:
            # ``recipients=[]`` is intentional: chat_step is live-UI breadcrumb
            # delivered via the SSE bridge broadcast (unfiltered by recipient).
            # Persisting it into the human_user inbox would (a) leak unread
            # rows forever — nothing consumes the human_user inbox — and
            # (b) force every downstream reader (e.g. ``list_messages``) to
            # know it must filter chat_step out as non-conversational noise.
            hubs.eventhub.publish_event(
                source_hub=self.agent_id,
                event_type="agent_chat_step",
                payload={
                    "agent": self.agent_id,
                    "tool": tool_name,
                    "args_preview": _short(tool_args),
                    "status": "done" if success else "error",
                    "result_preview": _short(result_data),
                },
                recipients=[],
                priority="normal",
                thread_id=thread_id,
            )
        except Exception as exc:
            try:
                self._logger.debug(
                    f"[{self.agent_id}] agent_chat_step emit failed: {exc}"
                )
            except Exception:
                pass

    async def _generate_text(self, system: str, user: str) -> str:
        """Single-turn text generation. Override or monkey-patch for tests.

        Reads the LLM via whatever attribute the class uses; tests typically
        override this method to return canned text.
        """
        # Find the LLM client attribute by introspection — many places use
        # `self.llm`, `self._llm`, or call through a complete() helper.
        llm = getattr(self, "llm", None) or getattr(self, "_llm", None)
        if llm is None:
            return f"({self.agent_id}: LLM not configured)"
        # Try the canonical chat_messages path first (matches _generate_answer).
        try:
            from utils.llm import Message  # local import to avoid hard dep at module load
            messages = [Message.system(system), Message.user(user)]
            chat_messages = getattr(llm, "chat_messages", None)
            if chat_messages is not None:
                if hasattr(self, "call_with_retry"):
                    response = await self.call_with_retry(chat_messages, messages)
                else:
                    result = chat_messages(messages)
                    response = await result if hasattr(result, "__await__") else result
                if isinstance(response, str):
                    return response
                content = getattr(response, "content", None)
                if content is not None:
                    return content
                return str(response)
        except Exception as e:
            self._logger.debug(f"[{self.agent_id}] chat_messages failed: {e}")

        # Fall through: try other common method names.
        messages_dict = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        for method_name in ("acomplete", "achat", "complete", "chat", "generate"):
            method = getattr(llm, method_name, None)
            if method is None:
                continue
            try:
                result = method(messages=messages_dict) if "chat" in method_name else method(user)
                if hasattr(result, "__await__"):
                    result = await result
                if isinstance(result, dict):
                    return result.get("content") or result.get("text") or str(result)
                return str(result) if result else ""
            except Exception as e:
                self._logger.debug(f"[{self.agent_id}] LLM method {method_name} failed: {e}")
                continue
        return f"({self.agent_id}: no usable LLM method found)"

    # ==================== PROMPT METHODS (OVERRIDE IN SUBCLASS) ====================
    
    def _get_system_prompt(self) -> str:
        """Get system prompt. Override in subclass to use j2 templates."""
        return f"You are {self.agent_name}. Use tools to complete tasks. Call finish() when done."

    def _compose_system_prompt(self) -> str:
        """Subclass-friendly wrapper: render the system prompt + the rolling
        "Active human directives" block.

        Call this from places that build the system prompt for an
        agentic loop. ``_get_system_prompt`` stays as the subclass
        override hook (j2 template renderers etc.); this method
        appends a fresh directive block from EventHub each call so the
        agent always sees the latest human chat instructions on every
        step.

        Inlined intentionally — extracting the directive-block builder
        as a separate method makes it harder to test with minimal
        stubs (any caller using a stand-in agent class would need to
        redeclare the helper). One method, fewer moving parts.
        """
        prompt = self._get_system_prompt()
        hubs = getattr(self, "_hubs", None)
        if hubs is None or not hasattr(hubs, "eventhub"):
            return prompt
        try:
            eh = hubs.eventhub
            # Skip threads the human has explicitly closed — once
            # ``mark_resolved`` flips ``status='resolved'``, the user
            # has signalled they're done with that conversation. Without
            # this filter, resolved chat directives persist in every
            # subsequent step's system prompt forever and silently bias
            # autonomous tool decisions.
            convs = [
                c for c in eh.list_conversations(participant=self.agent_id)
                if c.get("thread_id") and c.get("status") != "resolved"
            ]
            if not convs:
                return prompt
            convs.sort(key=lambda c: c.get("last_message_at", 0), reverse=True)
            latest = convs[:1]
            # ``list_conversations`` returns a summary view that doesn't
            # carry the persisted summary/summary_until_ts. Merge those
            # in from the canonical thread document so the renderer sees
            # them.
            threads_view = []
            for conv in latest:
                tid = conv["thread_id"]
                try:
                    stored = eh._threads.get(tid) or {}
                except Exception:
                    stored = {}
                merged = dict(conv)
                if "summary" not in merged and stored.get("summary"):
                    merged["summary"] = stored["summary"]
                    merged["summary_until_ts"] = stored.get("summary_until_ts", 0)
                    merged["summary_updated_at"] = stored.get("summary_updated_at", 0)
                threads_view.append(merged)
            transcripts = {
                c["thread_id"]: eh.get_thread_transcript(c["thread_id"])
                for c in threads_view
            }
            from multi_agent.agents.runtime.human_chat import build_directive_block
            block = build_directive_block(threads_view, transcripts, max_raw_turns=3)
        except Exception as exc:  # never fail prompt assembly because of chat
            # WARNING (not debug): if directive injection breaks silently,
            # the agent stops respecting human chat commands with zero
            # visible signal at default INFO level. Surface every failure;
            # the rate-limit is "once per failed step" which is acceptable.
            try:
                self._logger.warning(
                    f"[{self.agent_id}] directive injection failed: "
                    f"{type(exc).__name__}: {exc}"
                )
            except Exception:
                pass
            return prompt
        if block:
            prompt = f"{prompt}\n\n{block}"
        return prompt

    def _build_task_prompt(self, task: Dict) -> str:
        """Build task prompt. Override in subclass to use j2 templates."""
        description = task.get("description", "")
        related_files = task.get("related_files", [])
        
        parts = []
        if description:
            parts.append(f"## Task\n\n{description}")
        else:
            parts.append(f"## Task\n\n{safe_json_dumps(task)}")
        
        if related_files:
            files_str = "\n".join(f"- {f}" for f in related_files)
            parts.append(f"## Related Files\n\n{files_str}")
        
        parts.append("Use tools to complete this task. Call finish() when done.")
        return "\n\n".join(parts)
    
    # ==================== JINJA2 HELPERS ====================
    
    @staticmethod
    def resolve_prompt_version(template_path: str) -> str:
        """#269: pick the prompt-version directory, falling back per FILE.

        The audit (notes/prompt_audit_2026-07-22.md) measured 98-99% of every v3 template
        rendering unconditionally into every request — roughly 160M system-prompt tokens in
        a single run — and found the three biggest sections are prose restatements of rules
        a HARD gate already enforces: 22.8% of frontend_agent.j2 is about response_key and
        contract_alignment_failed still fired in 43% of 72 runs; 16.2% is about placeholders
        and placeholder_stub_handler still fired in 46%. The topics with the SMALLEST prompt
        footprint (dead nav link 1.3%, real map 1.3%) failed in 3% and 0%.

        v4 rewrites only those sections. Falling back per file means v4 can be introduced
        one lane at a time and any file can be reverted by deleting it — the comparison the
        audit's own risk clause needs: if a compressed section makes its gate fail MORE
        often, that section was doing real preventive work and goes back.
        """
        want = str(os.environ.get("ENVGEN_PROMPT_VERSION", "") or "").strip()
        if not want or "/" not in template_path:
            return template_path
        head, _, tail = template_path.partition("/")
        if not head.startswith("v") or head == want:
            return template_path
        candidate = f"{want}/{tail}"
        if (PROMPTS_DIR / candidate).exists():
            return candidate
        return template_path

    def render_template(self, template_path: str, **kwargs) -> str:
        """Render a Jinja2 template."""
        template_path = self.resolve_prompt_version(template_path)
        try:
            template = self._jinja_env.get_template(template_path)
            return template.render(**kwargs)
        except Exception as e:
            self._logger.warning(f"Template error {template_path}: {e}")
            return ""
    
    def render_macro(self, template_path: str, macro_name: str, **kwargs) -> str:
        """Render a specific macro from a template."""
        template_path = self.resolve_prompt_version(template_path)   # #269
        try:
            template = self._jinja_env.get_template(template_path)
            macro = getattr(template.module, macro_name, None)
            if macro:
                # Jinja macros may reject unknown kwargs; filter context vars
                # to declared macro arguments unless macro accepts **kwargs.
                call_kwargs = kwargs
                try:
                    if not getattr(macro, "catch_kwargs", False):
                        accepted = set(getattr(macro, "arguments", ()) or ())
                        call_kwargs = {k: v for k, v in kwargs.items() if k in accepted}
                except Exception:
                    call_kwargs = kwargs
                return macro(**call_kwargs)
            self._logger.warning(f"Macro {macro_name} not found in {template_path}")
            return ""
        except Exception as e:
            self._logger.warning(f"Macro error {template_path}.{macro_name}: {e}")
            return ""
    
    # ==================== EXTERNAL MESSAGEBUS ====================
    
    def set_message_bus(self, bus: MessageBus):
        """Set external MessageBus and register with it."""
        self._external_bus = bus
        # Expose for communication tools (they read _message_bus)
        self._message_bus = bus
        bus.register_agent(self)
        self._logger.info(f"[{self.agent_id}] Registered with external MessageBus")
    
    # ==================== TASK API FOR ORCHESTRATOR ====================
    
    async def send_task(self, task: Dict) -> asyncio.Event:
        """
        Send task to this agent. Returns completion event.
        
        Used by Orchestrator to send tasks without going through MessageBus.
        """
        self._task_complete_event.clear()
        
        # Create TaskMessage
        from uuid import uuid4
        task_id = str(uuid4())
        header = MessageHeader(
            message_id=str(uuid4()),
            source_agent_id="orchestrator",
            target_agent_id=self._agent_id,
            priority=MessagePriority.NORMAL,
        )
        
        task_msg = TaskMessage(
            header=header,
            task_id=task_id,
            task_name=task.get("name", "task"),
            payload=task,
        )
        
        # Put in message queue (inherited from BaseAgent)
        await self.receive_message(task_msg)
        
        return self._task_complete_event
    
    # ==================== CONTEXT SETTERS ====================
    
    def set_gen_context(self, context):
        """Set generation context (ports, settings)."""
        self.gen_context = context
    
    def set_requirements(self, requirements: Dict):
        """Set project requirements."""
        self._requirements = requirements
    
    def set_design_docs(self, docs: Dict[str, str]):
        """Set design documents."""
        self._design_docs = docs

    def set_step_reminders(self, reminders: Optional[List[Any]]) -> None:
        """Replace the pinned reminder payload injected at the start of every step."""
        self._step_reminders = list(reminders or [])

    def add_step_reminder(self, reminder: Any) -> None:
        """Append one pinned step reminder."""
        if not hasattr(self, "_step_reminders") or self._step_reminders is None:
            self._step_reminders = []
        self._step_reminders.append(reminder)

    def upsert_step_reminder(
        self,
        title: str,
        content: Any,
        *,
        ttl_steps: Optional[int] = None,
        auto_clear_on_finish: bool = False,
    ) -> None:
        """Upsert a named reminder shown at the start of each step."""
        reminder = {
            "title": str(title).strip(),
            "content": content,
        }
        if ttl_steps is not None:
            reminder["ttl_steps"] = max(1, int(ttl_steps))
        if auto_clear_on_finish:
            reminder["auto_clear_on_finish"] = True
        items = list(getattr(self, "_step_reminders", []) or [])
        replaced = False
        for idx, item in enumerate(items):
            if isinstance(item, dict) and str(item.get("title", "")).strip() == reminder["title"]:
                items[idx] = reminder
                replaced = True
                break
        if not replaced:
            items.append(reminder)
        self._step_reminders = items

    def advance_step_reminders(self) -> None:
        """Consume one step from TTL-bound reminders after they are shown."""
        current = list(getattr(self, "_step_reminders", []) or [])
        next_items: List[Any] = []
        for item in current:
            if not isinstance(item, dict):
                next_items.append(item)
                continue
            ttl_raw = item.get("ttl_steps")
            if ttl_raw is None:
                next_items.append(item)
                continue
            try:
                ttl_value = int(ttl_raw)
            except Exception:
                next_items.append(item)
                continue
            ttl_value -= 1
            if ttl_value > 0:
                updated = dict(item)
                updated["ttl_steps"] = ttl_value
                next_items.append(updated)
        self._step_reminders = next_items

    def clear_finish_step_reminders(self) -> None:
        """Clear reminders marked to auto-clear once the current task finishes."""
        current = list(getattr(self, "_step_reminders", []) or [])
        self._step_reminders = [
            item for item in current
            if not (isinstance(item, dict) and bool(item.get("auto_clear_on_finish", False)))
        ]

    def clear_step_reminders(self) -> None:
        """Clear pinned step reminders."""
        self._step_reminders = []
    
    def init_memory_bank(self, project_info: Dict):
        """Initialize persistent memory bank."""
        if not self.workspace:
            return
        workspace_root = Path(self.workspace.base_dir)
        canonical_memory_dir = workspace_root / "memory-bank" / self.agent_id
        legacy_root = workspace_root / ".memory" / self.agent_id
        legacy_memory_dir = legacy_root / "memory-bank"
        shared_legacy_memory_dir = workspace_root / "memory-bank"

        # One-time migration from legacy per-agent memory path.
        if (not canonical_memory_dir.exists()) and legacy_memory_dir.exists():
            try:
                canonical_memory_dir.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(legacy_memory_dir, canonical_memory_dir)
                self._logger.info(
                    f"[{self.agent_id}] Migrated memory bank from {legacy_memory_dir} to {canonical_memory_dir}"
                )
            except Exception as e:
                self._logger.warning(
                    f"[{self.agent_id}] Failed to migrate legacy memory bank ({legacy_memory_dir}): {e}"
                )
        elif (
            not canonical_memory_dir.exists()
            and shared_legacy_memory_dir.exists()
            and (shared_legacy_memory_dir / "project_brief.md").exists()
        ):
            try:
                canonical_memory_dir.mkdir(parents=True, exist_ok=True)
                for filename in [
                    "project_brief.md",
                    "tech_context.md",
                    "system_patterns.md",
                    "active_context.md",
                    "progress.md",
                ]:
                    src = shared_legacy_memory_dir / filename
                    if src.exists():
                        shutil.copy2(src, canonical_memory_dir / filename)
                self._logger.info(
                    f"[{self.agent_id}] Seeded agent memory bank from shared legacy memory bank"
                )
            except Exception as e:
                self._logger.warning(
                    f"[{self.agent_id}] Failed to seed agent memory bank from shared legacy path ({shared_legacy_memory_dir}): {e}"
                )

        self.memory_bank = MemoryBank(
            root_dir=workspace_root,
            memory_dir=canonical_memory_dir,
            model=getattr(self.config, "model_name", None),
        )
        self.memory_bank.initialize(project_info or {})
        
        # Bind MemoryBank to GeneratorMemory for auto-sync
        if hasattr(self, 'memory') and self.memory_bank:
            self.memory.bind_memory_bank(self.memory_bank)

        self._bind_memory_bank_to_progress_tools()

    def _bind_memory_bank_to_progress_tools(self) -> None:
        """Attach this agent's MemoryBank to already-registered progress tools."""
        if not self.memory_bank:
            return
        for tool in getattr(self, "_tool_instances", {}).values():
            if hasattr(tool, "_memory_bank"):
                try:
                    tool._memory_bank = self.memory_bank
                except Exception:
                    pass
    
    # ==================== FILE HELPERS ====================
    
    def list_files(self, directory: str = "") -> List[str]:
        """List files in workspace."""
        try:
            target = Path(self.workspace.base_dir) / directory
            if target.exists():
                return [str(f.relative_to(self.workspace.base_dir)) for f in target.rglob("*") if f.is_file()]
        except:
            pass
        return []
    
    def read_file(self, path: str) -> Optional[str]:
        """Read file from workspace."""
        try:
            file_path = Path(self.workspace.base_dir) / path
            if file_path.exists():
                return file_path.read_text()
        except:
            pass
        return None
