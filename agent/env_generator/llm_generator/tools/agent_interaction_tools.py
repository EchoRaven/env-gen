"""
Agent Interaction Tools - Tools for memory access and task completion

Provides:
- ReadMemoryBankTool: Read project context from Memory Bank
- UpdateMemoryBankTool: Structured updates to the project Memory Bank
- FinishTool: Signal task completion
- DeliverProjectTool: Signal final delivery (coordinating lane only)

For inter-agent communication, use communication_tools.py instead:
- SendMessageTool, AskAgentTool, BroadcastTool, CheckInboxTool, etc.
"""

from pathlib import Path
from typing import TYPE_CHECKING, List, Optional

from ._base import (
    BaseTool,
    ToolResult,
    ToolCategory,
    create_tool_param,
    Workspace,
)

if TYPE_CHECKING:
    from multi_agent.agents.base import EnvGenAgent

# Import PlanTool for finish verification (avoid circular import by using late import)


# ============================================================================
# Read Memory Bank Tool
# ============================================================================

class ReadMemoryBankTool(BaseTool):
    """
    Read project context from Memory Bank.
    
    Memory Bank contains structured project knowledge:
    - project_brief: Core requirements and goals
    - tech_context: Technologies and constraints
    - system_patterns: Architecture and design patterns
    - active_context: Current work focus
    - progress: Completed features and known issues
    """
    
    NAME = "read_memory_bank"
    
    DESCRIPTION = """Read project context from the Memory Bank.

Memory Bank contains persistent project knowledge:
- project_brief: Core requirements, goals, scope
- tech_context: Tech stack, dependencies, setup
- system_patterns: Architecture, design patterns, decisions
- active_context: Current focus, recent changes, next steps
- progress: Completed features, in-progress, known issues

Use this in retrieve_context when you need your own project-local memory.
Prefer mode="digest" for normal steps. Use mode="full" only when editing or repairing a specific memory file.

Examples:
    read_memory_bank()                    # Read all memory files
    read_memory_bank(file="progress")     # Read specific file
    read_memory_bank(file="active_context")
"""
    
    def __init__(self, workspace: Workspace = None, agent_id: Optional[str] = None, model: Optional[str] = None):
        super().__init__(name=self.NAME, category=ToolCategory.AGENT)
        self.workspace = workspace
        self.agent_id = agent_id
        self.model = model
    
    @property
    def tool_definition(self):
        return self.get_tool_param()
    
    def get_tool_param(self):
        return create_tool_param(
            name=self.NAME,
            description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "file": {
                        "type": "string",
                        "enum": ["all", "project_brief", "tech_context", "system_patterns", "active_context", "progress"],
                        "description": "Which memory file to read (default: all)"
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["digest", "full"],
                        "description": "digest (default) returns a concise summary; full returns complete file contents"
                    }
                },
                "required": []
            }
        )
    
    def execute(self, file: str = "all", mode: str = "digest") -> ToolResult:
        if not self.workspace:
            return ToolResult(
                success=False,
                error_message="Workspace not configured for ReadMemoryBankTool"
            )
        
        memory_dir = self._resolve_memory_dir()
        file_map = {
            "project_brief": "project_brief.md",
            "tech_context": "tech_context.md",
            "system_patterns": "system_patterns.md",
            "active_context": "active_context.md",
            "progress": "progress.md",
        }

        if not memory_dir.exists():
            try:
                from memory.memory_bank import MemoryBank

                mb = MemoryBank(root_dir=self.workspace.code_root, memory_dir=memory_dir, model=self.model)
                mb.initialize(
                    {
                        "name": self.workspace.name,
                        "description": "",
                    }
                )
            except Exception:
                if file == "all":
                    return ToolResult(
                        success=True,
                        data={
                            "files_read": list(file_map.keys()),
                            "mode": mode,
                            "content": "",
                            "info": "Memory bank not initialized yet.",
                        },
                    )
                return ToolResult(
                    success=True,
                    data={
                        "file": file,
                        "mode": mode,
                        "content": "",
                        "info": f"Memory bank file '{file}' is not initialized yet.",
                    },
                )
        
        if file == "all":
            if mode == "full":
                contents = {}
                for key, filename in file_map.items():
                    file_path = memory_dir / filename
                    if file_path.exists():
                        contents[key] = file_path.read_text(encoding="utf-8")
                    else:
                        contents[key] = "(file not found)"

                sections = []
                for key, content in contents.items():
                    sections.append(f"=== {key.upper()} ===\n{content}")

                content_out = "\n\n".join(sections)
            else:
                # Digest mode: use MemoryBank's digest to avoid dumping huge context.
                try:
                    from memory.memory_bank import MemoryBank
                    mb = MemoryBank(root_dir=self.workspace.code_root, memory_dir=memory_dir, model=self.model)
                    content_out = mb.get_digest()
                except Exception:
                    # Fallback to active_context + progress only
                    ac = (memory_dir / file_map["active_context"]).read_text(encoding="utf-8") if (memory_dir / file_map["active_context"]).exists() else ""
                    prog = (memory_dir / file_map["progress"]).read_text(encoding="utf-8") if (memory_dir / file_map["progress"]).exists() else ""
                    content_out = f"=== ACTIVE_CONTEXT ===\n{ac}\n\n=== PROGRESS ===\n{prog}"

            return ToolResult(
                success=True,
                data={
                    "files_read": list(file_map.keys()),
                    "mode": mode,
                    "content": content_out,
                    "info": f"Read memory bank ({mode})."
                }
            )
        
        elif file in file_map:
            file_path = memory_dir / file_map[file]
            if file_path.exists():
                content = file_path.read_text(encoding="utf-8")
                return ToolResult(
                    success=True,
                    data={
                        "file": file,
                        "mode": "full",
                        "content": content,
                        "info": f"Read memory bank file: {file}"
                    }
                )
            else:
                return ToolResult(
                    success=True,
                    data={
                        "file": file,
                        "mode": "full",
                        "content": "",
                        "info": f"Memory bank file '{file}' is not initialized yet."
                    }
                )
        
        else:
            return ToolResult(
                success=False,
                error_message=f"Unknown file '{file}'. Valid options: all, project_brief, tech_context, system_patterns, active_context, progress"
            )

    def _resolve_memory_dir(self) -> Path:
        """Resolve this agent's memory-bank directory.

        Current runs store memory under memory-bank/<agent_id>/. Older runs may
        have a shared memory-bank/ or .memory/<agent_id>/memory-bank/.
        """
        root = self.workspace.code_root
        if self.agent_id:
            agent_dir = root / "memory-bank" / self.agent_id
            if agent_dir.exists():
                return agent_dir
            legacy_agent_dir = root / ".memory" / self.agent_id / "memory-bank"
            if legacy_agent_dir.exists():
                return legacy_agent_dir
            return agent_dir

        shared_dir = root / "memory-bank"
        if (shared_dir / "project_brief.md").exists():
            return shared_dir

        return shared_dir


# ============================================================================
# Update Memory Bank Tool
# ============================================================================

class UpdateMemoryBankTool(BaseTool):
    """
    Structured updates for the agent's project Memory Bank.
    """

    NAME = "update_memory_bank"
    DESCRIPTION = """Write to YOUR NOTEBOOK — the agent-owned half of the Memory Bank.

This writes ONLY to your private, writable notebook.md (it persists across all your
wakes and is never committed). It does NOT touch the framework-maintained files
(project_brief / tech_context / system_patterns / active_context / progress) — those
are read-only truth you see in the auto-provided digest.

Use this near the end of a meaningful step to record what your NEXT wake should not
have to re-derive. Keep entries concise and durable:
- decisions: design/API/schema/implementation decisions with rationale
- issues: gotchas, blockers, validation failures, or unresolved risks
- tech_notes: durable setup, dependency, command, port, or architecture notes
- next_step: the next concrete action
- focus / recent_change / completed: a running log line of what you did

Do not use this for transient chain-of-thought. Store only what helps your future steps.
"""

    def __init__(self):
        super().__init__(name=self.NAME, category=ToolCategory.AGENT)
        self.agent = None

    def set_agent(self, agent):
        self.agent = agent

    @property
    def tool_definition(self):
        return self.get_tool_param()

    def get_tool_param(self):
        return create_tool_param(
            name=self.NAME,
            description=self.DESCRIPTION,
            parameters={
                "focus": {
                    "type": "string",
                    "description": "Current durable work focus. Example: 'Working on backend API contract alignment'",
                },
                "next_step": {
                    "type": "string",
                    "description": "Next concrete action to take.",
                },
                "recent_change": {
                    "type": "string",
                    "description": "Recent meaningful change or observation.",
                },
                "completed": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Completed milestones or artifacts.",
                },
                "issues": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Current blockers, bugs, or validation failures.",
                },
                "decisions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Durable design/API/schema/implementation decisions.",
                },
                "tech_notes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Durable technical notes such as commands, ports, dependencies, or setup constraints.",
                },
            },
            required=[],
        )

    def execute(
        self,
        focus: str = None,
        next_step: str = None,
        recent_change: str = None,
        completed: List[str] = None,
        issues: List[str] = None,
        decisions: List[str] = None,
        tech_notes: List[str] = None,
    ) -> ToolResult:
        memory_bank = getattr(self.agent, "memory_bank", None) if self.agent else None
        if not memory_bank:
            return ToolResult(success=False, error_message="Agent Memory Bank is not available")

        try:
            # Write ONLY to the agent-owned notebook — the SEPARATE, writable
            # half of the bank. The framework-synced CORE files (active_context /
            # progress / system_patterns / tech_context) are NOT touched here;
            # they stay read-only truth (user requirement: the file an agent
            # edits must not be the file the framework auto-syncs).
            updated = memory_bank.append_notebook(
                focus=focus,
                next_step=next_step,
                recent_change=recent_change,
                completed=completed,
                issues=issues,
                decisions=decisions,
                tech_notes=tech_notes,
            )

            if not updated:
                return ToolResult(
                    success=True,
                    data={"updated": [], "info": "No notebook updates were provided."},
                )

            return ToolResult(
                success=True,
                data={
                    "updated": updated,
                    "memory_dir": str(getattr(memory_bank, "memory_dir", "")),
                    "info": f"Notebook updated (sections: {', '.join(updated)}). "
                            "Framework-synced files were not touched.",
                },
            )
        except Exception as e:
            return ToolResult(success=False, error_message=f"Failed to update notebook: {e}")


# ============================================================================
# Finish Tool
# ============================================================================

class FinishTool(BaseTool):
    """
    Signal that agent's current task is complete.
    
    Key features:
    - Can automatically notify downstream agents to start their work
    - Ends the current agentic loop
    - Agent remains available for new tasks/issues
    """
    
    NAME = "finish"
    
    DESCRIPTION = """Signal your current task is complete.

## Basic Usage
```
finish(message="Completed database schema and seed data")
```

## Notify Downstream Agents (RECOMMENDED!)
Use `notify` to automatically push your work to downstream agents.
Live resident lanes: orchestrator, design, backend, frontend, verifier,
debugger, knowledge. Backend owns DB + API; verifier owns visual review.

```
# Orchestrator notifies backend + frontend after kickoff finalizes
finish(
    message="Kickoff contract published — RegistryHub + WorkHub have the canonical endpoint/table/page set.",
    notify=["backend", "frontend"],
    notify_content="Contract registered. Backend: implement the API + schema from registryhub_list_endpoints/registryhub_list_tables. Frontend: build Phase A from the kickoff section + reference images."
)

# Backend notifies frontend after registering endpoints
finish(
    message="API + schema complete with 12 endpoints, 4 tables",
    notify=["frontend"],
    notify_content="API ready at :8000. Endpoints: /auth/*, /flights/*, /bookings/*. See RegistryHub for response_keys. Schema tables registered."
)

# Frontend notifies verifier after wiring api.js + critical flows
finish(
    message="UI implementation complete; critical flows wired",
    notify=["verifier"],
    notify_content="Frontend ready. registryhub_register_consumer called per consumed endpoint. Critical flows ready for ui_flow validation."
)
```

The notify feature:
- Sends HIGH priority messages to specified agents
- Automatically tags with ["task_ready", "from_<your_agent>"]
- Receivers can filter for these with check_inbox(tags=["task_ready"])

## After finish()
- Current task loop ends
- You remain available for issues/questions from other agents
- If you receive an issue, you'll automatically start working on it
"""
    
    def __init__(self, agent_id: str = None, agent: "EnvGenAgent" = None):
        super().__init__(name=self.NAME, category=ToolCategory.AGENT)
        self.agent_id = agent_id or "default"
        self.agent = agent
    
    def set_agent(self, agent: "EnvGenAgent"):
        """Inject agent reference for message sending."""
        self.agent = agent
        self.agent_id = agent.agent_id
    
    @property
    def tool_definition(self):
        return self.get_tool_param()
    
    def get_tool_param(self):
        return create_tool_param(
            name=self.NAME,
            description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "Summary of completed work"
                    },
                    "notify": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Agents to notify (e.g., ['frontend', 'backend'])"
                    },
                    "notify_content": {
                        "type": "string",
                        "description": "Message content for notified agents (defaults to your message)"
                    },
                    "outputs": {
                        "type": "object",
                        "description": "Any output data"
                    }
                },
                "required": ["message"]
            }
        )
    
    def execute(
        self, 
        message: str, 
        notify: list = None,
        notify_content: str = None,
        outputs: dict = None
    ) -> ToolResult:
        from .reasoning_tools import PlanTool
        
        plan_tool = PlanTool.get_instance(self.agent_id)
        plan_status = plan_tool.get_plan_status()
        
        warnings = []
        notifications_sent = []
        
        # Warning 1: Check if there's an incomplete plan (warning only, not blocking)
        if plan_status["has_plan"] and not plan_status["all_complete"]:
            incomplete_count = len(plan_status["incomplete"])
            warnings.append(f"Note: You have {incomplete_count} incomplete plan items.")
        
        # Send notifications to downstream agents
        # NOTE: This is synchronous - notifications will be sent after this method returns
        # by storing them for the agent to process
        if notify and self.agent:
            from uuid import uuid4
            from utils.message import MessageHeader, MessageType, MessagePriority, BaseMessage
            
            bus = getattr(self.agent, "_external_bus", None) or getattr(self.agent, "_message_bus", None)
            
            if bus:
                content = notify_content or f"[{self.agent_id.upper()}] Task complete: {message}"
                tags = ["task_ready", f"from_{self.agent_id}"]
                
                # Store pending notifications on agent for async delivery
                pending = getattr(self.agent, "_pending_notifications", None)
                if pending is None:
                    self.agent._pending_notifications = []
                    pending = self.agent._pending_notifications
                
                for target in notify:
                    try:
                        if str(target).strip() == str(self.agent_id).strip():
                            warnings.append(f"Skipped self-notify target '{target}'.")
                            continue
                        header = MessageHeader(
                            message_id=str(uuid4()),
                            source_agent_id=self.agent_id,
                            target_agent_id=target,
                            priority=MessagePriority.HIGH,
                        )
                        msg = BaseMessage(
                            header=header,
                            message_type=MessageType.STATUS,
                            payload=content,
                            metadata={
                                "msg_type": "task_ready",
                                "tags": tags,
                                "persist": False,
                                "read": False,
                            }
                        )
                        # Store for async delivery instead of create_task (thread-safe)
                        pending.append((bus, msg))
                        notifications_sent.append(target)
                    except Exception as e:
                        warnings.append(f"Failed to notify {target}: {e}")
        
        # Build response info
        info = f"Task completed: {message}"
        if notifications_sent:
            info += f"\nNotified agents: {', '.join(notifications_sent)}"
        if warnings:
            info += "\n\nNotes:\n" + "\n".join(f"  - {w}" for w in warnings)
        
        return ToolResult(
            success=True,
            data={
                "outputs": outputs or {}, 
                "finished": True,
                "notified": notifications_sent,
                "info": info
            }
        )


# ============================================================================
# Deliver Project Tool (coordinating lane only)
# ============================================================================

class DeliverProjectTool(BaseTool):
    """
    Signal that the project is ready for delivery to the user.
    
    This tool is ONLY for the coordinating lane (typically `orchestrator`) and
    triggers the overall shutdown.
    - Only call this when ALL criteria are met (no bugs, fully functional, etc.)
    - This is different from finish() which just ends the current task
    - deliver_project() ends the entire generation process
    """
    
    NAME = "deliver_project"
    
    DESCRIPTION = """Signal that the project is complete and ready for delivery.

CRITICAL: This tool triggers the END of the entire generation process!

Only call this when ALL of these are true:
1. NO outstanding bugs or issues
2. ALL project requirements are satisfied
3. Application is FULLY functional and usable
4. Docker setup is correct and containers run successfully
5. Application is ready for end-users

This is NOT the same as finish()!
- finish() = end current task, stay available for more work
- deliver_project() = generation complete, shutdown all agents

Args:
    confirmation: Must be exactly "CONFIRMED" to proceed
    delivery_summary: Summary of what's being delivered
    checklist: Dict with verification results
"""
    
    def __init__(self, agent: "EnvGenAgent" = None):
        super().__init__(name=self.NAME, category=ToolCategory.AGENT)
        self.agent = agent
        self._delivered = False
    
    def set_agent(self, agent: "EnvGenAgent"):
        """Set the agent that will use this tool."""
        self.agent = agent
    
    @property
    def tool_definition(self):
        return self.get_tool_param()
    
    def get_tool_param(self):
        return create_tool_param(
            name=self.NAME,
            description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "confirmation": {
                        "type": "string",
                        "description": "Must be exactly 'CONFIRMED' to proceed with delivery"
                    },
                    "delivery_summary": {
                        "type": "string",
                        "description": "Summary of what is being delivered"
                    },
                    "checklist": {
                        "type": "object",
                        "description": "Verification checklist: {no_bugs: bool, requirements_met: bool, fully_functional: bool, docker_ok: bool}",
                        "properties": {
                            "no_bugs": {"type": "boolean"},
                            "requirements_met": {"type": "boolean"},
                            "fully_functional": {"type": "boolean"},
                            "docker_ok": {"type": "boolean"}
                        }
                    },
                    "force_deliver": {
                        "type": "boolean",
                        "description": (
                            "Orchestrator-only audited bypass of the coverage "
                            "gate. Use when dead artifacts exist but shipping "
                            "anyway is intentional. Logs a dead_code_bypass "
                            "EventHub event."
                        )
                    }
                },
                "required": ["confirmation", "delivery_summary", "checklist"]
            }
        )

    def execute(self, confirmation: str, delivery_summary: str,
                checklist: dict = None, force_deliver: bool = False) -> ToolResult:
        # PR 6 review (2026-05-30) deleted five gate blocks that
        # used to live here (retro / coverage / visual / seed /
        # runhub-since-session). All five were dead-on-production:
        # they read ``getattr(self.agent, "hub_registry", None)``
        # but production agents expose hubs as ``self._hubs`` — the
        # ``hub_registry`` attribute was never set anywhere outside
        # test MagicMocks. ``if registry is not None`` short-
        # circuited every block on the agent-driven deliver path.
        #
        # Enforcement that remains intact AFTER deletion:
        #   * retro — RetroBeforeDeliverPolicy fires through
        #     _apply_finish_policies on tool_name='deliver_project'
        #     (PR 2.5-fix-2 wired this; LIVE).
        #   * coverage / visual / seed / runhub — enforced on the
        #     UI-driven deliver path (``deliver_project_call`` in
        #     live_monitor_server, which calls
        #     ``compute_deliverability``). NOT enforced on the
        #     agent-driven deliver path post-deletion; the dead
        #     code wasn't enforcing it either.
        #
        # If the agent-driven deliver path SHOULD enforce
        # coverage/visual/seed/runhub, that's a separate wire-fix
        # (replace dead ``self.agent.hub_registry`` reads with the
        # live ``self.agent._hubs``) — flagged as follow-up. The
        # current commit is a pure correctness-neutral deletion of
        # never-executed code, not a behavior change.
        #
        # Lint guard pin lives in
        # ``tests/test_deliver_project_tool_no_dead_hub_registry_reads.py``.

        # Verify confirmation
        if confirmation != "CONFIRMED":
            return ToolResult(
                success=False,
                error_message=f"Confirmation must be exactly 'CONFIRMED', got '{confirmation}'. "
                              "This is to prevent accidental project delivery."
            )
        
        # Verify checklist
        checklist = checklist or {}
        required_checks = ["no_bugs", "requirements_met", "fully_functional", "docker_ok"]
        failed_checks = []
        
        for check in required_checks:
            if not checklist.get(check, False):
                failed_checks.append(check)
        
        if failed_checks:
            return ToolResult(
                success=False,
                error_message=f"Cannot deliver project. Failed checks: {failed_checks}. "
                              "Please ensure all criteria are met before delivery."
            )

        # GUARD 1 (milestone-completeness, ALWAYS-ON): deliver_project is the FINAL
        # delivery — it ENDS the run. During an earlier milestone of a multi-milestone
        # plan it must NOT fire; the framework cuts that milestone's release and advances
        # to the next milestone. Default True (single-milestone / unknown → allowed, so
        # byte-identical for single-milestone runs). The orchestrator runtime stamps
        # ``_is_final_milestone`` + ``_milestone_progress`` onto this agent per milestone.
        _is_final = getattr(self.agent, "_is_final_milestone", True) if self.agent else True
        if not _is_final:
            _prog = getattr(self.agent, "_milestone_progress", None) if self.agent else None
            _prog_s = (f" (currently milestone {_prog[0]} of {_prog[1]})"
                       if isinstance(_prog, (tuple, list)) and len(_prog) == 2 else "")
            return ToolResult(
                success=False,
                error_message=(
                    f"deliver_project is the FINAL delivery and ENDS the run, but this is "
                    f"NOT the last milestone{_prog_s}. Do NOT call deliver_project yet — the "
                    f"framework cuts this milestone's release and advances to the next "
                    f"milestone automatically. deliver_project is valid ONLY on the final "
                    f"milestone, once every milestone's work is complete."
                ),
            )

        # GUARD 2 (LIVE deliverability gate, DEFAULT-ON — 2026-07-01): the checklist above is
        # SELF-ASSERTED by the LLM. On the FINAL milestone deliver_project ENDS the run — it
        # sets ``_project_delivered_event`` and EXITS the coordination loop. A PREMATURE call
        # (the milestone's backend/validation not yet converged) then FAILS the orchestrator's
        # post-loop hard gate → ``RuntimeError("Delivery gate failed")`` → shutdown watchdog
        # kills the run (run-18 delivered M1 then died at M4 exactly this way; run-20 delivered
        # M1+M2+M3 then died at M4 the same way). Re-verify against the LIVE hubs and REJECT a
        # premature deliver — returning a ToolResult(success=False) keeps the run CONVERGING the
        # milestone (as the non-final milestones already do) instead of exiting into a failed
        # gate. Checks the two things the post-loop gate catches from hubs alone: every business
        # endpoint 'implemented', and business_chain green (missing/failing/coverage/isolation);
        # a chain that never ran on an unvalidated milestone is 'failing', so this also catches
        # "no successful run". Never blocks on an eval error; ENVGEN_DELIVER_GATE=0 disables.
        import os as _os
        if (_os.environ.get("ENVGEN_DELIVER_GATE", "1").strip().lower()
                not in ("0", "false", "no", "off")) and self.agent is not None:
            try:
                _hubs = getattr(self.agent, "_hubs", None)
                _rh = getattr(_hubs, "registryhub", None) if _hubs is not None else None
                if _rh is not None and hasattr(_rh, "get_endpoints"):
                    from multi_agent.runtime.lifecycle import all_business_endpoints_implemented
                    from multi_agent.runtime.delivery_gate import business_chain_blockers
                    _blockers = []
                    if not all_business_endpoints_implemented(_rh.get_endpoints() or {}):
                        _blockers.append("not every business endpoint is 'implemented'")
                    try:
                        _bc = business_chain_blockers(_hubs)
                        if isinstance(_bc, dict) and _bc.get("reason"):
                            _blockers.append(str(_bc["reason"]))
                    except Exception:
                        pass
                    # GUARD 2b (#39, runs 31+32 both FAILED this way): the checks above pass
                    # while FRONTEND work is mid-flight — every backend endpoint implemented +
                    # chains frozen-green, but a registered ui_page is not yet WIRED (its route
                    # absent from App.jsx / component file missing). deliver_project then exits
                    # the loop straight into the post-loop gate's deliverability sweep →
                    # 'deliverability_ui_page_unwired' → RuntimeError → watchdog kill. Re-use
                    # the SAME deliverability aggregator the post-loop gate maps its checks
                    # from, so a deliver that would fail the gate is rejected (run keeps
                    # converging) instead of killing the run. session_start_ts=0 keeps the
                    # RunHub recency check LOOSER than the gate's — never stricter.
                    try:
                        from pathlib import Path as _Path
                        from multi_agent.runtime.deliverability import compute_deliverability
                        _base = getattr(_hubs, "base_dir", None)
                        if _base:
                            _app = _Path(_base) / "app"
                            if not _app.exists():
                                _app = _Path(_base)
                            _rep = compute_deliverability(_hubs, _app, session_start_ts=0.0)
                            for _bl in (getattr(_rep, "blockers", None) or []):
                                _blockers.append(str(_bl)[:160])
                    except Exception:
                        pass
                    if _blockers:
                        return ToolResult(
                            success=False,
                            error_message=(
                                "deliver_project BLOCKED — the checklist is self-asserted but "
                                "the LIVE delivery gate is NOT clear: " + "; ".join(_blockers)
                                + ". This is the FINAL milestone, so delivering now would exit "
                                "the run straight into a failed post-loop gate (watchdog kill). "
                                "Keep going: finish implementation and re-run run_validation until "
                                "every endpoint is 'implemented' and business_chain is GREEN, THEN "
                                "call deliver_project."
                            ),
                        )
            except Exception:
                pass  # never block delivery on a gate-eval error

        # GUARD 2c (FIX #117, run-32 autopsy): the FINAL milestone's VISUAL gate is not
        # part of the objective gate report the LLM sees, so a mid-deferral
        # deliver_project (run-32: 1406s into a 3600s remediation window, scores
        # 0.1-0.4 vs 0.65) exits the coordination loop, TERMINATES the lanes, and the
        # post-loop path cuts the release mid-convergence — silently voiding
        # #112/#112b's whole point. The orchestrator runtime stamps
        # ``_visual_defer_check`` (bound to Orchestrator._visual_delivery_defer_active)
        # alongside ``_is_final_milestone``; it returns False the moment the gate
        # passes OR the bounded escape fires, so this can never deadlock. A missing or
        # broken check never blocks (back-compat + fail-open).
        _vf_check = getattr(self.agent, "_visual_defer_check", None) if self.agent else None
        if callable(_vf_check):
            try:
                _vf_defer = bool(_vf_check())
            except Exception:
                _vf_defer = False
            if _vf_defer:
                return ToolResult(
                    success=False,
                    error_message=(
                        "deliver_project DEFERRED — the final milestone's VISUAL fidelity "
                        "gate is still converging (it is not part of the objective gate "
                        "report). The frontend is inside its bounded remediation window: "
                        "let it digest the visual remediation tasks (capture_webpage / "
                        "zoom_compare against the references, then fix). The framework "
                        "will deliver automatically when the gate passes or its bounded "
                        "escape fires — do NOT keep calling deliver_project; work the "
                        "remediation tasks instead."
                    ),
                )

        # Set delivered flag
        self._delivered = True
        
        # Also set on agent if available - this triggers shutdown
        if self.agent:
            self.agent._project_delivered = True
            # Set the event that orchestrator is waiting for
            if hasattr(self.agent, '_project_delivered_event'):
                self.agent._project_delivered_event.set()
        
        return ToolResult(
            success=True,
            data={
                "delivered": True,
                "summary": delivery_summary,
                "checklist": checklist,
                "info": "Project successfully delivered! Generation process will now shutdown."
            }
        )
    
    def is_delivered(self) -> bool:
        """Check if project has been delivered."""
        return self._delivered


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "ReadMemoryBankTool",
    "UpdateMemoryBankTool",
    "FinishTool",
    "DeliverProjectTool",
]

