"""
Reasoning Tools - Agent thinking and planning tools

Provides:
- PlanTool: Create and track implementation plans with checklist
- VerifyPlanTool: Verification test plan tracking for QA

These tools support agent self-reflection and structured task management.
"""

from ._base import (
    BaseTool,
    ToolResult,
    ToolCategory,
    create_tool_param,
)


# ============================================================================
# Wait Tool
# ============================================================================

class GetTimeTool(BaseTool):
    """
    Get current time and elapsed time since generation started.
    
    Helps agents understand how much time has passed and make time-based decisions.
    """
    
    NAME = "get_time"
    
    DESCRIPTION = """Get current time and how long the generation has been running.

Use this to:
- Check how much time has passed
- Decide if you've been waiting long enough
- Know the current time for logging/debugging

Returns:
- current_time: Current time (e.g., "14:30:45")
- elapsed_minutes: Minutes since generation started
- elapsed_formatted: Human-readable elapsed time (e.g., "5 minutes 30 seconds")

Example:
    get_time()  # Returns {"current_time": "14:30:45", "elapsed_minutes": 5.5, ...}
"""
    
    # Class variable to store generation start time
    _start_time = None
    
    @classmethod
    def set_start_time(cls):
        """Called at generation start to record the start time."""
        from datetime import datetime
        cls._start_time = datetime.now()
    
    def __init__(self):
        super().__init__(name=self.NAME, category=ToolCategory.AGENT)
        # Initialize start time if not set
        if GetTimeTool._start_time is None:
            GetTimeTool.set_start_time()
    
    def tool_definition(self):
        return self.get_tool_param()
    
    def get_tool_param(self):
        return create_tool_param(
            name=self.NAME,
            description=self.DESCRIPTION,
            parameters={},
            required=[]
        )
    
    def execute(self) -> ToolResult:
        from datetime import datetime
        
        now = datetime.now()
        current_time = now.strftime("%H:%M:%S")
        current_datetime = now.strftime("%Y-%m-%d %H:%M:%S")
        
        # Calculate elapsed time
        if GetTimeTool._start_time:
            elapsed = now - GetTimeTool._start_time
            elapsed_seconds = elapsed.total_seconds()
            elapsed_minutes = elapsed_seconds / 60
            
            # Format elapsed time
            mins = int(elapsed_seconds // 60)
            secs = int(elapsed_seconds % 60)
            if mins > 0:
                elapsed_formatted = f"{mins} minute{'s' if mins != 1 else ''} {secs} second{'s' if secs != 1 else ''}"
            else:
                elapsed_formatted = f"{secs} second{'s' if secs != 1 else ''}"
        else:
            elapsed_minutes = 0
            elapsed_formatted = "unknown"
        
        return ToolResult(
            success=True,
            data={
                "current_time": current_time,
                "current_datetime": current_datetime,
                "elapsed_minutes": round(elapsed_minutes, 1),
                "elapsed_formatted": elapsed_formatted,
                "info": f"Current time: {current_time}, Elapsed: {elapsed_formatted}"
            }
        )


class WaitTool(BaseTool):
    """
    Wait/pause for a specified duration.
    
    Use this when you need to wait for other agents to complete their work,
    or when you're in a monitoring/polling loop and want to avoid rapid API calls.
    """
    
    NAME = "wait"
    
    DESCRIPTION = """Wait for a specified number of seconds before continuing.

Use this tool when:
- Waiting for other agents to complete their work
- In a monitoring loop (e.g., periodically checking inbox)
- After sending messages, giving agents time to respond
- Avoiding rapid polling that wastes API tokens

Example:
    wait(seconds=30)  # Wait 30 seconds before next action
    wait(seconds=10, reason="Waiting for backend agent to process request")

Recommended wait times:
- Quick check: 5-10 seconds
- Waiting for agent response: 15-30 seconds
- Waiting for major work: 60+ seconds
"""
    
    def __init__(self):
        super().__init__(name=self.NAME, category=ToolCategory.AGENT)
    
    def tool_definition(self):
        return self.get_tool_param()
    
    def get_tool_param(self):
        return create_tool_param(
            name=self.NAME,
            description=self.DESCRIPTION,
            parameters={
                "seconds": {
                    "type": "integer",
                    "description": "Number of seconds to wait (1-300)",
                    "minimum": 1,
                    "maximum": 300
                },
                "reason": {
                    "type": "string",
                    "description": "Optional: Why you're waiting (for logging)"
                }
            },
            required=["seconds"]
        )
    
    async def execute(self, seconds: int, reason: str = None) -> ToolResult:
        import asyncio
        
        # Clamp to reasonable range
        seconds = max(1, min(300, seconds))
        
        # Use asyncio.sleep so event loop can process urgent messages during wait
        await asyncio.sleep(seconds)
        
        info = f"Waited {seconds} seconds"
        if reason:
            info += f" ({reason})"
        
        return ToolResult(
            success=True,
            data={"waited_seconds": seconds, "reason": reason, "info": info}
        )


# ============================================================================
# Plan Tool - Enhanced with Stages and Task Assignment
# ============================================================================

from dataclasses import dataclass, field
from typing import Optional, Dict, List, Any
from datetime import datetime
from pathlib import Path
import json


@dataclass
class AcceptanceBundle:
    """Structured acceptance criteria attached to a plan, stage, or task."""
    functional: List[Dict[str, Any]] = field(default_factory=list)
    artifacts: List[Dict[str, Any]] = field(default_factory=list)
    updated_at: Optional[str] = None


@dataclass
class PlanTask:
    """A single task within a stage."""
    id: str
    description: str
    assignee: Optional[str] = None  # agent_id or None for self
    status: str = "pending"  # pending, in_progress, completed, blocked
    result: Optional[str] = None
    dependencies: List[str] = field(default_factory=list)
    acceptance: AcceptanceBundle = field(default_factory=AcceptanceBundle)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    completed_at: Optional[str] = None


@dataclass
class PlanStage:
    """A stage containing multiple tasks."""
    id: str
    name: str
    description: str
    tasks: Dict[str, PlanTask] = field(default_factory=dict)
    status: str = "pending"  # pending, in_progress, completed
    acceptance: AcceptanceBundle = field(default_factory=AcceptanceBundle)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    completed_at: Optional[str] = None


@dataclass
class StagedPlan:
    """A complete plan with multiple stages."""
    name: str
    description: str
    stages: Dict[str, PlanStage] = field(default_factory=dict)
    current_stage_id: Optional[str] = None
    stage_order: List[str] = field(default_factory=list)
    acceptance: AcceptanceBundle = field(default_factory=AcceptanceBundle)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    

class PlanTool(BaseTool):
    """
    Enhanced plan tool with stages, task assignment, and acceptance tracking.
    
    Supports engineering-like development cycles with:
    - Stage-based planning (design → implement → test → deploy)
    - Task assignment to team members
    - Functional and artifact acceptance at plan/stage/task level
    """
    
    NAME = "plan"
    
    DESCRIPTION = """Create and manage staged development plans with task assignment and acceptance criteria.

This enhanced plan tool supports engineering development cycles:
- **Stages**: Organize work into phases (e.g., design, implement, test)
- **Tasks**: Break each stage into assignable tasks
- **Assignments**: Assign tasks to team members (other agents)
- **Acceptance**: Track feature acceptance and file/artifact acceptance
- **Parties**: Run stage sync sessions for the current plan participants

## Actions

### Plan Management
- "create": Create a new staged plan
- "status": View current plan status
- "clear": Clear the current plan

### Stage Management
- "add_stage": Add a new stage to the plan
- "start_stage": Begin working on a stage
- "complete_stage": Mark a stage as complete

### Task Management
- "add_task": Add a task to a stage
- "assign_task": Assign a task to an agent
- "start_task": Mark a task as in_progress
- "complete_task": Mark a task as completed
- "block_task": Mark a task as blocked
- "list_tasks": List tasks (optionally filtered)

### Acceptance Management
- "set_acceptance": Attach or update acceptance at plan/stage/task scope
- "show_acceptance": Inspect acceptance state and unresolved items
- "update_acceptance_item": Update one acceptance criterion status/evidence
- "sync_acceptance_from_validation": Bind one acceptance criterion to validation refs or hub validation checks

## Examples

Creating a staged plan:
```
plan(
    action="create",
    plan_name="Build User Dashboard",
    plan_description="Implement user dashboard with analytics",
    stages=[
        {"id": "design", "name": "Design Phase", "description": "Create specs and mockups"},
        {"id": "implement", "name": "Implementation", "description": "Build frontend and backend"},
        {"id": "test", "name": "Testing", "description": "Verify functionality"}
    ]
)
```

Adding tasks to a stage:
```
plan(
    action="add_task",
    stage_id="implement",
    task_id="api_endpoints",
    task_description="Create REST API endpoints",
    assignee="backend"
)
```

"""
    
    # Class-level registry of instances by agent_id
    _instances: dict = {}
    
    def __init__(self, agent_id: str = None):
        super().__init__(name=self.NAME, category=ToolCategory.AGENT)
        self.agent_id = agent_id or "default"
        self._hubs = None
        self._workspace_root: Optional[Path] = None
        self._plan: Optional[StagedPlan] = None
        # Bound WorkHub task id. None while the agent plans exploratorily
        # (pre-claim); set by attach_to_task after claim so subsequent
        # syncs flush to ``task.plan``.
        self._task_id: Optional[str] = None
        PlanTool._instances[self.agent_id] = self

    def set_agent(self, agent) -> None:
        """
        Bind runtime agent reference.
        Ensures dynamic agents use unique plan namespace (agent_id),
        and enables hub synchronization of plan indexes.
        """
        runtime_agent_id = getattr(agent, "agent_id", None)
        if runtime_agent_id and runtime_agent_id != self.agent_id:
            # Remove stale key if it points to this instance.
            if PlanTool._instances.get(self.agent_id) is self:
                PlanTool._instances.pop(self.agent_id, None)
            self.agent_id = runtime_agent_id
            PlanTool._instances[self.agent_id] = self
        self._hubs = getattr(agent, "_hubs", None)
        workspace_manager = getattr(agent, "workspace", None)
        if workspace_manager and hasattr(workspace_manager, "base_dir"):
            self._workspace_root = Path(workspace_manager.base_dir)
    
    @classmethod
    def get_instance(cls, agent_id: str = None) -> "PlanTool":
        """Get PlanTool instance for a specific agent_id."""
        agent_id = agent_id or "default"
        if agent_id not in cls._instances:
            cls._instances[agent_id] = PlanTool(agent_id=agent_id)
        return cls._instances[agent_id]
    
    def reset(self):
        """Reset plan state."""
        self._plan = None
        self._task_id = None

    def attach_to_task(self, task_id: str) -> None:
        """Bind the PlanTool to a claimed WorkHub task. Subsequent
        ``_sync_plan_index`` calls flush the plan to ``task.plan``.
        Idempotent; re-attaching to a different task rebinds."""
        self._task_id = task_id

    def detach_from_task(self) -> None:
        """Unbind from any WorkHub task. Called on terminal-state
        transitions. ``self._plan`` stays in memory for inspection."""
        self._task_id = None

    @staticmethod
    def _acceptance_status_done(status: Optional[str]) -> bool:
        return str(status or "").strip().lower() in {"passed", "done", "accepted", "waived"}

    @staticmethod
    def _normalize_acceptance_entry(
        value: Any,
        *,
        kind: str,
        default_prefix: str,
        index: int,
    ) -> Dict[str, Any]:
        now = datetime.now().isoformat()
        if isinstance(value, str):
            title = value.strip()
            return {
                "id": f"{default_prefix}_{index}",
                "title": title or f"{kind}_{index}",
                "description": title,
                "kind": kind,
                "status": "pending",
                "required": True,
                "evidence": [],
                "notes": None,
                "ref": None,
                "updated_at": now,
            }

        if isinstance(value, dict):
            title = (
                value.get("title")
                or value.get("name")
                or value.get("path")
                or value.get("spec")
                or value.get("id")
                or f"{kind}_{index}"
            )
            evidence = value.get("evidence", [])
            if isinstance(evidence, str):
                evidence = [evidence]
            elif not isinstance(evidence, list):
                evidence = []
            return {
                "id": str(value.get("id") or f"{default_prefix}_{index}"),
                "title": str(title),
                "description": value.get("description") or value.get("summary") or str(title),
                "kind": kind,
                "status": str(value.get("status") or "pending"),
                "required": bool(value.get("required", True)),
                "evidence": evidence,
                "notes": value.get("notes"),
                "ref": value.get("ref") or value.get("verification_ref") or value.get("task_suite_ref"),
                "updated_at": value.get("updated_at") or now,
                "metadata": dict(value.get("metadata") or {}),
            }

        return {
            "id": f"{default_prefix}_{index}",
            "title": f"{kind}_{index}",
            "description": str(value),
            "kind": kind,
            "status": "pending",
            "required": True,
            "evidence": [],
            "notes": None,
            "ref": None,
            "updated_at": now,
        }

    def _normalize_artifact_acceptance(self, raw: Any) -> List[Dict[str, Any]]:
        entries: List[Any]
        if raw is None:
            entries = []
        elif isinstance(raw, list):
            entries = raw
        elif isinstance(raw, dict):
            entries = []
            for key in ("required_files", "required_dirs", "required_specs", "owned_files"):
                values = raw.get(key) or []
                if isinstance(values, (str, dict)):
                    values = [values]
                for idx, item in enumerate(values, start=1):
                    if isinstance(item, str):
                        entries.append(
                            {
                                "id": f"{key}_{idx}",
                                "title": item,
                                "description": f"{key}: {item}",
                                "metadata": {"source": key},
                            }
                        )
                    elif isinstance(item, dict):
                        payload = dict(item)
                        payload.setdefault("id", f"{key}_{idx}")
                        payload.setdefault("title", payload.get("path") or payload.get("spec") or payload.get("name") or payload["id"])
                        payload.setdefault("description", f"{key}: {payload.get('title')}")
                        payload.setdefault("metadata", {})
                        payload["metadata"] = dict(payload["metadata"] or {})
                        payload["metadata"].setdefault("source", key)
                        entries.append(payload)
            extra_items = raw.get("items") or raw.get("artifacts") or []
            if isinstance(extra_items, (str, dict)):
                extra_items = [extra_items]
            entries.extend(extra_items)
        else:
            entries = [raw]
        return [
            self._normalize_acceptance_entry(item, kind="artifact", default_prefix="artifact", index=index)
            for index, item in enumerate(entries, start=1)
        ]

    def _normalize_functional_acceptance(self, raw: Any) -> List[Dict[str, Any]]:
        if raw is None:
            entries = []
        elif isinstance(raw, list):
            entries = raw
        elif isinstance(raw, dict):
            entries = raw.get("items") or raw.get("checklist") or raw.get("criteria") or []
            if not entries:
                entries = [raw]
        else:
            entries = [raw]
        return [
            self._normalize_acceptance_entry(item, kind="functional", default_prefix="functional", index=index)
            for index, item in enumerate(entries, start=1)
        ]

    def _normalize_acceptance_bundle(
        self,
        *,
        acceptance: Any = None,
        functional_acceptance: Any = None,
        artifact_acceptance: Any = None,
    ) -> AcceptanceBundle:
        functional_raw = functional_acceptance
        artifact_raw = artifact_acceptance
        if isinstance(acceptance, AcceptanceBundle):
            return acceptance
        if isinstance(acceptance, dict):
            if functional_raw is None:
                functional_raw = acceptance.get("functional") or acceptance.get("functional_acceptance")
            if artifact_raw is None:
                artifact_raw = acceptance.get("artifacts") or acceptance.get("artifact_acceptance")
        elif acceptance is not None and functional_raw is None and artifact_raw is None:
            functional_raw = acceptance
        return AcceptanceBundle(
            functional=self._normalize_functional_acceptance(functional_raw),
            artifacts=self._normalize_artifact_acceptance(artifact_raw),
            updated_at=datetime.now().isoformat(),
        )

    @staticmethod
    def _merge_acceptance_bundles(current: AcceptanceBundle, incoming: AcceptanceBundle) -> AcceptanceBundle:
        def _merge_items(existing: List[Dict[str, Any]], updates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
            merged: Dict[str, Dict[str, Any]] = {
                str(item.get("id")): dict(item)
                for item in existing
                if isinstance(item, dict) and item.get("id")
            }
            passthrough = [
                dict(item)
                for item in existing
                if isinstance(item, dict) and not item.get("id")
            ]
            for item in updates:
                if not isinstance(item, dict):
                    continue
                key = str(item.get("id") or f"item_{len(merged) + len(passthrough) + 1}")
                merged[key] = dict(item)
            return list(merged.values()) + passthrough

        return AcceptanceBundle(
            functional=_merge_items(current.functional, incoming.functional),
            artifacts=_merge_items(current.artifacts, incoming.artifacts),
            updated_at=datetime.now().isoformat(),
        )

    @staticmethod
    def _acceptance_bundle_to_dict(bundle: AcceptanceBundle) -> Dict[str, Any]:
        return {
            "functional": [dict(item) for item in bundle.functional],
            "artifacts": [dict(item) for item in bundle.artifacts],
            "updated_at": bundle.updated_at,
        }

    def _build_validation_lookup(self) -> Dict[str, Any]:
        if not self._hubs or not hasattr(self._hubs, "get_validation_results"):
            return {"by_task_id": {}, "by_check": {}, "summary": {}}
        try:
            records = self._hubs.get_validation_results(limit=500) or []
        except Exception:
            records = []
        by_task_id: Dict[str, Dict[str, Any]] = {}
        by_check: Dict[str, Dict[str, Any]] = {}
        for record in records:
            if not isinstance(record, dict):
                continue
            task_id = str(record.get("task_id") or "").strip()
            if task_id and task_id not in by_task_id:
                by_task_id[task_id] = record
            metadata = record.get("metadata", {}) or {}
            check_name = str(metadata.get("check") or "").strip()
            if check_name and check_name not in by_check:
                by_check[check_name] = record
        try:
            summary = self._hubs.get_validation_summary() or {}
        except Exception:
            summary = {}
        return {"by_task_id": by_task_id, "by_check": by_check, "summary": summary}

    def _resolve_runtime_acceptance_item(
        self,
        item: Dict[str, Any],
        *,
        validation_lookup: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        resolved = dict(item)
        metadata = dict(resolved.get("metadata") or {})
        raw_status = str(resolved.get("status") or "pending")
        effective_status = raw_status
        auto_source = None
        auto_evidence = list(resolved.get("evidence") or [])

        if resolved.get("kind") == "functional":
            lookup = validation_lookup or self._build_validation_lookup()
            by_task_id = lookup.get("by_task_id", {}) or {}
            by_check = lookup.get("by_check", {}) or {}
            summary = lookup.get("summary", {}) or {}
            ref = str(
                resolved.get("ref")
                or metadata.get("validation_task_id")
                or metadata.get("task_suite_ref")
                or metadata.get("verification_ref")
                or ""
            ).strip()
            validation_kind = str(metadata.get("validation_kind") or metadata.get("check") or "").strip()
            matched = None
            if ref and ref in by_task_id:
                matched = by_task_id[ref]
                auto_source = f"validation:{ref}"
            elif validation_kind and validation_kind in by_check:
                matched = by_check[validation_kind]
                auto_source = f"validation_check:{validation_kind}"
            elif ref == "validation_summary:all_passed" or validation_kind == "all_passed":
                effective_status = "passed" if summary.get("all_passed") else "pending"
                auto_source = "validation_summary"
            if matched:
                matched_status = str(matched.get("status") or "").strip().lower()
                if matched_status in {"passed", "failed", "skipped", "error"}:
                    effective_status = "passed" if matched_status == "passed" else "failed" if matched_status in {"failed", "error"} else "pending"
                auto_evidence.extend([str(path) for path in matched.get("artifacts", []) if str(path)])
                matched_summary = matched.get("summary")
                if matched_summary and not resolved.get("notes"):
                    resolved["notes"] = matched_summary

        elif resolved.get("kind") == "artifact":
            candidate = (
                metadata.get("path")
                or metadata.get("relative_path")
                or metadata.get("title")
                or resolved.get("title")
            )
            if candidate and self._workspace_root:
                path = Path(str(candidate))
                full_path = path if path.is_absolute() else (self._workspace_root / path)
                source = str(metadata.get("source") or "").strip()
                exists = full_path.exists()
                is_valid = exists
                if source == "required_dirs":
                    is_valid = exists and full_path.is_dir()
                elif source in {"required_files", "required_specs", "owned_files"}:
                    is_valid = exists and full_path.is_file()
                if is_valid:
                    effective_status = "passed"
                    auto_source = f"artifact:{source or 'path'}"
                    try:
                        auto_evidence.append(str(full_path.relative_to(self._workspace_root)))
                    except Exception:
                        auto_evidence.append(str(full_path))
                elif raw_status == "passed":
                    effective_status = raw_status

        deduped_evidence: List[str] = []
        seen: set[str] = set()
        for entry in auto_evidence:
            value = str(entry).strip()
            if not value or value in seen:
                continue
            seen.add(value)
            deduped_evidence.append(value)
        resolved["effective_status"] = effective_status
        resolved["runtime_resolution"] = {
            "source": auto_source,
            "raw_status": raw_status,
            "effective_status": effective_status,
        }
        resolved["evidence"] = deduped_evidence
        return resolved

    def _effective_acceptance_items(self, bundle: AcceptanceBundle) -> List[Dict[str, Any]]:
        lookup = self._build_validation_lookup()
        items = list(bundle.functional) + list(bundle.artifacts)
        return [
            self._resolve_runtime_acceptance_item(dict(item), validation_lookup=lookup)
            for item in items
            if isinstance(item, dict)
        ]

    def _effective_acceptance_bundle_to_dict(self, bundle: AcceptanceBundle) -> Dict[str, Any]:
        items = self._effective_acceptance_items(bundle)
        return {
            "functional": [item for item in items if item.get("kind") == "functional"],
            "artifacts": [item for item in items if item.get("kind") == "artifact"],
            "updated_at": bundle.updated_at,
        }

    def _summarize_validation_driven_acceptance(self, bundle: AcceptanceBundle) -> Dict[str, Any]:
        items = self._effective_acceptance_items(bundle)
        linked: List[Dict[str, Any]] = []
        for item in items:
            runtime = item.get("runtime_resolution") or {}
            source = str(runtime.get("source") or "").strip()
            if not source.startswith(("validation:", "validation_check:", "validation_summary")):
                continue
            linked.append(
                {
                    "id": item.get("id"),
                    "title": item.get("title"),
                    "status": item.get("effective_status") or item.get("status"),
                    "source": source,
                }
            )
        return {
            "count": len(linked),
            "resolved": sum(1 for item in linked if self._acceptance_status_done(item.get("status"))),
            "items": linked,
        }

    def _acceptance_counts(self, bundle: AcceptanceBundle) -> Dict[str, int]:
        items = self._effective_acceptance_items(bundle)
        required = [item for item in items if bool(item.get("required", True))]
        resolved = [item for item in required if self._acceptance_status_done(item.get("effective_status") or item.get("status"))]
        unresolved = [item for item in required if not self._acceptance_status_done(item.get("effective_status") or item.get("status"))]
        failed = [item for item in required if str(item.get("effective_status") or item.get("status") or "").lower() == "failed"]
        return {
            "total": len(items),
            "required": len(required),
            "resolved": len(resolved),
            "unresolved": len(unresolved),
            "failed": len(failed),
        }

    def _list_unresolved_acceptance(self, bundle: AcceptanceBundle) -> List[Dict[str, Any]]:
        items = self._effective_acceptance_items(bundle)
        unresolved: List[Dict[str, Any]] = []
        for item in items:
            if not bool(item.get("required", True)):
                continue
            if self._acceptance_status_done(item.get("effective_status") or item.get("status")):
                continue
            unresolved.append(
                {
                    "id": item.get("id"),
                    "title": item.get("title"),
                    "kind": item.get("kind"),
                    "status": item.get("effective_status") or item.get("status"),
                    "runtime_resolution": item.get("runtime_resolution"),
                }
            )
        return unresolved

    def _resolve_acceptance_target(
        self,
        scope: str,
        *,
        stage_id: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> tuple[Any, str]:
        if not self._plan:
            raise ValueError("No plan exists.")
        normalized_scope = str(scope or "").strip().lower()
        if normalized_scope == "plan":
            return self._plan, "plan"
        if normalized_scope == "stage":
            if not stage_id or stage_id not in self._plan.stages:
                raise ValueError(self._stage_not_found(stage_id).error_message)
            return self._plan.stages[stage_id], f"stage:{stage_id}"
        if normalized_scope == "task":
            if not stage_id or stage_id not in self._plan.stages:
                raise ValueError(self._stage_not_found(stage_id).error_message)
            stage = self._plan.stages[stage_id]
            resolved_task_id = self._resolve_task_id(stage, task_id or "")
            if not resolved_task_id:
                raise ValueError(f"Task '{task_id}' not found. Available tasks: {list(stage.tasks.keys())}")
            return stage.tasks[resolved_task_id], f"task:{stage_id}:{resolved_task_id}"
        raise ValueError("scope must be one of: plan, stage, task")

    def _set_acceptance_bundle(
        self,
        scope: str,
        *,
        stage_id: Optional[str] = None,
        task_id: Optional[str] = None,
        acceptance: Any = None,
        functional_acceptance: Any = None,
        artifact_acceptance: Any = None,
        merge: bool = True,
    ) -> Dict[str, Any]:
        target, target_label = self._resolve_acceptance_target(scope, stage_id=stage_id, task_id=task_id)
        incoming = self._normalize_acceptance_bundle(
            acceptance=acceptance,
            functional_acceptance=functional_acceptance,
            artifact_acceptance=artifact_acceptance,
        )
        current = getattr(target, "acceptance", AcceptanceBundle())
        target.acceptance = self._merge_acceptance_bundles(current, incoming) if merge else incoming
        summary = self._acceptance_counts(target.acceptance)
        return {
            "scope": scope,
            "target": target_label,
            "acceptance": self._acceptance_bundle_to_dict(target.acceptance),
            "summary": summary,
        }

    def _update_acceptance_item(
        self,
        scope: str,
        *,
        criterion_id: str,
        stage_id: Optional[str] = None,
        task_id: Optional[str] = None,
        status: Optional[str] = None,
        notes: Optional[str] = None,
        evidence: Optional[List[str]] = None,
        required: Optional[bool] = None,
    ) -> Dict[str, Any]:
        if not criterion_id:
            raise ValueError("criterion_id is required")
        target, target_label = self._resolve_acceptance_target(scope, stage_id=stage_id, task_id=task_id)
        bundle = getattr(target, "acceptance", AcceptanceBundle())
        for collection_name in ("functional", "artifacts"):
            collection = getattr(bundle, collection_name)
            for item in collection:
                if str(item.get("id")) != str(criterion_id):
                    continue
                if status is not None:
                    item["status"] = status
                if notes is not None:
                    item["notes"] = notes
                if evidence is not None:
                    item["evidence"] = list(evidence)
                if required is not None:
                    item["required"] = bool(required)
                item["updated_at"] = datetime.now().isoformat()
                summary = self._acceptance_counts(bundle)
                return {
                    "scope": scope,
                    "target": target_label,
                    "criterion": dict(item),
                    "summary": summary,
                }
        raise ValueError(f"criterion_id '{criterion_id}' not found in {target_label}")

    def _sync_acceptance_from_validation(
        self,
        scope: str,
        *,
        criterion_id: str,
        stage_id: Optional[str] = None,
        task_id: Optional[str] = None,
        validation_task_id: Optional[str] = None,
        validation_kind: Optional[str] = None,
        verification_ref: Optional[str] = None,
        task_suite_ref: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not criterion_id:
            raise ValueError("criterion_id is required")
        if not any([validation_task_id, validation_kind, verification_ref, task_suite_ref]):
            raise ValueError(
                "At least one of validation_task_id, validation_kind, verification_ref, or task_suite_ref is required"
            )
        target, target_label = self._resolve_acceptance_target(scope, stage_id=stage_id, task_id=task_id)
        bundle = getattr(target, "acceptance", AcceptanceBundle())
        for collection_name in ("functional", "artifacts"):
            collection = getattr(bundle, collection_name)
            for item in collection:
                if str(item.get("id")) != str(criterion_id):
                    continue
                metadata = dict(item.get("metadata") or {})
                if validation_task_id:
                    metadata["validation_task_id"] = str(validation_task_id).strip()
                    item["ref"] = str(validation_task_id).strip()
                if validation_kind:
                    metadata["validation_kind"] = str(validation_kind).strip()
                if verification_ref:
                    metadata["verification_ref"] = str(verification_ref).strip()
                    if not item.get("ref"):
                        item["ref"] = str(verification_ref).strip()
                if task_suite_ref:
                    metadata["task_suite_ref"] = str(task_suite_ref).strip()
                    if not item.get("ref"):
                        item["ref"] = str(task_suite_ref).strip()
                item["metadata"] = metadata
                item["updated_at"] = datetime.now().isoformat()
                resolved = self._resolve_runtime_acceptance_item(dict(item))
                summary = self._acceptance_counts(bundle)
                return {
                    "scope": scope,
                    "target": target_label,
                    "criterion": dict(item),
                    "effective_criterion": resolved,
                    "summary": summary,
                }
        raise ValueError(f"criterion_id '{criterion_id}' not found in {target_label}")

    def _ensure_acceptance_resolved(self, bundle: AcceptanceBundle, label: str) -> Optional[ToolResult]:
        unresolved = self._list_unresolved_acceptance(bundle)
        if not unresolved:
            return None
        return ToolResult(
            success=False,
            error_message=f"Cannot complete {label}: unresolved required acceptance criteria remain.",
            data={"unresolved_acceptance": unresolved},
        )
    
    def get_plan_status(self) -> dict:
        """Get current plan status."""
        if not self._plan:
            return {
                "has_plan": False,
                "all_complete": False,
                "incomplete": [],
            }
        
        total_tasks = 0
        completed_tasks = 0
        stages_info = []
        plan_acceptance = self._acceptance_counts(self._plan.acceptance)
        plan_validation_links = self._summarize_validation_driven_acceptance(self._plan.acceptance)

        for stage_id in self._plan.stage_order:
            stage = self._plan.stages.get(stage_id)
            if stage:
                stage_tasks = len(stage.tasks)
                stage_completed = sum(1 for t in stage.tasks.values() if t.status == "completed")
                total_tasks += stage_tasks
                completed_tasks += stage_completed
                acceptance_summary = self._acceptance_counts(stage.acceptance)
                validation_links = self._summarize_validation_driven_acceptance(stage.acceptance)
                unresolved_task_acceptance = 0
                task_validation_links = 0
                for task in stage.tasks.values():
                    task_summary = self._acceptance_counts(task.acceptance)
                    unresolved_task_acceptance += task_summary["unresolved"]
                    task_validation_links += self._summarize_validation_driven_acceptance(task.acceptance)["count"]
                stages_info.append({
                    "id": stage_id,
                    "name": stage.name,
                    "status": stage.status,
                    "tasks": f"{stage_completed}/{stage_tasks}",
                    "is_current": stage_id == self._plan.current_stage_id,
                    "acceptance": acceptance_summary,
                    "validation_links": validation_links,
                    "task_validation_links": task_validation_links,
                    "task_acceptance_unresolved": unresolved_task_acceptance,
                })
        
        return {
            "has_plan": True,
            "name": self._plan.name,
            "description": self._plan.description,
            "acceptance": self._acceptance_bundle_to_dict(self._plan.acceptance),
            "acceptance_summary": plan_acceptance,
            "validation_links": plan_validation_links,
            "total_stages": len(self._plan.stages),
            "total_tasks": total_tasks,
            "completed_tasks": completed_tasks,
            "current_stage": self._plan.current_stage_id,
            "stages": stages_info,
            "progress_percent": round(completed_tasks / total_tasks * 100, 1) if total_tasks > 0 else 0,
            "all_complete": total_tasks > 0 and completed_tasks == total_tasks,
            "incomplete": [
                {
                    "stage_id": stage_id,
                    "task_id": task.id,
                }
                for stage_id in self._plan.stage_order
                for task in (
                    self._plan.stages.get(stage_id).tasks.values()
                    if self._plan.stages.get(stage_id) else []
                )
                if task.status != "completed"
            ],
        }
    
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
                    "action": {
                        "type": "string",
                        "enum": [
                            "create", "status", "clear",
                            "add_stage", "start_stage", "complete_stage",
                            "add_task", "assign_task", "start_task", "complete_task", "block_task", "list_tasks",
                            "set_acceptance", "show_acceptance", "update_acceptance_item", "sync_acceptance_from_validation"
                        ],
                        "description": "Action to perform"
                    },
                    "plan_name": {
                        "type": "string",
                        "description": "Name of the plan (for 'create' action)"
                    },
                    "plan_description": {
                        "type": "string",
                        "description": "Description of the plan (for 'create' action)"
                    },
                    "stages": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "name": {"type": "string"},
                                "description": {"type": "string"}
                            }
                        },
                        "description": "Initial stages (for 'create' action)"
                    },
                    "stage_id": {
                        "type": "string",
                        "description": "Stage identifier"
                    },
                    "stage_name": {
                        "type": "string",
                        "description": "Stage name (for 'add_stage' action)"
                    },
                    "stage_description": {
                        "type": "string",
                        "description": "Stage description"
                    },
                    "task_id": {
                        "type": "string",
                        "description": "Task identifier"
                    },
                    "task_description": {
                        "type": "string",
                        "description": "Task description"
                    },
                    "assignee": {
                        "type": "string",
                        "description": "Agent ID to assign task to"
                    },
                    "dependencies": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Task IDs this task depends on"
                    },
                    "result": {
                        "type": "string",
                        "description": "Task result/outcome (for 'complete_task' action)"
                    },
                    "filter_status": {
                        "type": "string",
                        "enum": ["pending", "in_progress", "completed", "blocked"],
                        "description": "Filter tasks by status"
                    },
                    "filter_assignee": {
                        "type": "string",
                        "description": "Filter tasks by assignee"
                    },
                    "scope": {
                        "type": "string",
                        "enum": ["plan", "stage", "task"],
                        "description": "Acceptance target scope for acceptance actions"
                    },
                    "acceptance": {
                        "type": "object",
                        "description": "Combined acceptance bundle with optional functional/artifact sections."
                    },
                    "functional_acceptance": {
                        "description": "Feature/behavior acceptance items. Prefer strings or objects with id/title/status/evidence.",
                        "anyOf": [
                            {"type": "array"},
                            {"type": "object"},
                            {"type": "string"}
                        ]
                    },
                    "artifact_acceptance": {
                        "description": "File/artifact acceptance items or maps like required_files/required_dirs/required_specs.",
                        "anyOf": [
                            {"type": "array"},
                            {"type": "object"},
                            {"type": "string"}
                        ]
                    },
                    "merge_acceptance": {
                        "type": "boolean",
                        "description": "If true, merge acceptance items into existing ones; otherwise replace."
                    },
                    "criterion_id": {
                        "type": "string",
                        "description": "Acceptance criterion id to update."
                    },
                    "criterion_status": {
                        "type": "string",
                        "enum": ["pending", "in_progress", "passed", "failed", "waived"],
                        "description": "New status for an acceptance criterion."
                    },
                    "criterion_notes": {
                        "type": "string",
                        "description": "Optional notes when updating acceptance criteria."
                    },
                    "criterion_evidence": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Evidence paths or references for an acceptance criterion."
                    },
                    "criterion_required": {
                        "type": "boolean",
                        "description": "Override whether an acceptance criterion is required."
                    },
                    "validation_task_id": {
                        "type": "string",
                        "description": "Explicit hub validation task id to bind to an acceptance criterion."
                    },
                    "validation_kind": {
                        "type": "string",
                        "description": "Validation kind/check name to bind to an acceptance criterion (for example api_smoke)."
                    },
                    "verification_ref": {
                        "type": "string",
                        "description": "Verification reference or external validation ref for this criterion."
                    },
                    "task_suite_ref": {
                        "type": "string",
                        "description": "Task suite task id or suite ref used to resolve this criterion from validation results."
                    }
                },
                "required": ["action"]
            }
        )
    
    def execute(self, action: str, **kwargs) -> ToolResult:
        """Execute plan action and sync shared plan index to hub."""
        result: ToolResult

        # Plan Management
        if action == "create":
            result = self._create_plan(
                kwargs.get("plan_name"),
                kwargs.get("plan_description"),
                kwargs.get("stages", [])
            )
        elif action == "status":
            result = self._get_status()
        elif action == "clear":
            result = self._clear_plan()

        # Stage Management
        elif action == "add_stage":
            result = self._add_stage(
                kwargs.get("stage_id"),
                kwargs.get("stage_name"),
                kwargs.get("stage_description")
            )
        elif action == "start_stage":
            result = self._start_stage(kwargs.get("stage_id"))
        elif action == "complete_stage":
            result = self._complete_stage(kwargs.get("stage_id"))

        # Task Management
        elif action == "add_task":
            result = self._add_task(
                kwargs.get("stage_id"),
                kwargs.get("task_id"),
                kwargs.get("task_description"),
                kwargs.get("assignee"),
                kwargs.get("dependencies", [])
            )
        elif action == "assign_task":
            result = self._assign_task(
                kwargs.get("stage_id"),
                kwargs.get("task_id"),
                kwargs.get("assignee")
            )
        elif action == "start_task":
            result = self._update_task_status(
                kwargs.get("stage_id"),
                kwargs.get("task_id"),
                "in_progress"
            )
        elif action == "complete_task":
            result = self._complete_task(
                kwargs.get("stage_id"),
                kwargs.get("task_id"),
                kwargs.get("result")
            )
        elif action == "block_task":
            result = self._update_task_status(
                kwargs.get("stage_id"),
                kwargs.get("task_id"),
                "blocked",
                kwargs.get("result")  # Use result as blocker reason
            )
        elif action == "list_tasks":
            result = self._list_tasks(
                kwargs.get("stage_id"),
                kwargs.get("filter_status"),
                kwargs.get("filter_assignee")
            )

        # Acceptance Management
        elif action == "set_acceptance":
            try:
                payload = self._set_acceptance_bundle(
                    kwargs.get("scope") or "plan",
                    stage_id=kwargs.get("stage_id"),
                    task_id=kwargs.get("task_id"),
                    acceptance=kwargs.get("acceptance"),
                    functional_acceptance=kwargs.get("functional_acceptance"),
                    artifact_acceptance=kwargs.get("artifact_acceptance"),
                    merge=bool(kwargs.get("merge_acceptance", True)),
                )
                result = ToolResult(
                    success=True,
                    data={
                        "action": "acceptance_set",
                        **payload,
                        "info": f"Acceptance updated for {payload['target']}.",
                    },
                )
            except Exception as e:
                result = ToolResult(success=False, error_message=str(e))
        elif action == "show_acceptance":
            try:
                target, target_label = self._resolve_acceptance_target(
                    kwargs.get("scope") or "plan",
                    stage_id=kwargs.get("stage_id"),
                    task_id=kwargs.get("task_id"),
                )
                bundle = getattr(target, "acceptance", AcceptanceBundle())
                summary = self._acceptance_counts(bundle)
                result = ToolResult(
                    success=True,
                    data={
                        "action": "acceptance_status",
                        "scope": kwargs.get("scope") or "plan",
                        "target": target_label,
                        "acceptance": self._acceptance_bundle_to_dict(bundle),
                        "effective_acceptance": self._effective_acceptance_bundle_to_dict(bundle),
                        "summary": summary,
                        "unresolved": self._list_unresolved_acceptance(bundle),
                    },
                )
            except Exception as e:
                result = ToolResult(success=False, error_message=str(e))
        elif action == "update_acceptance_item":
            try:
                payload = self._update_acceptance_item(
                    kwargs.get("scope") or "plan",
                    criterion_id=kwargs.get("criterion_id"),
                    stage_id=kwargs.get("stage_id"),
                    task_id=kwargs.get("task_id"),
                    status=kwargs.get("criterion_status"),
                    notes=kwargs.get("criterion_notes"),
                    evidence=kwargs.get("criterion_evidence"),
                    required=kwargs.get("criterion_required"),
                )
                result = ToolResult(
                    success=True,
                    data={
                        "action": "acceptance_item_updated",
                        **payload,
                        "info": f"Acceptance criterion '{kwargs.get('criterion_id')}' updated.",
                    },
                )
            except Exception as e:
                result = ToolResult(success=False, error_message=str(e))
        elif action == "sync_acceptance_from_validation":
            try:
                payload = self._sync_acceptance_from_validation(
                    kwargs.get("scope") or "plan",
                    criterion_id=kwargs.get("criterion_id"),
                    stage_id=kwargs.get("stage_id"),
                    task_id=kwargs.get("task_id"),
                    validation_task_id=kwargs.get("validation_task_id"),
                    validation_kind=kwargs.get("validation_kind"),
                    verification_ref=kwargs.get("verification_ref"),
                    task_suite_ref=kwargs.get("task_suite_ref"),
                )
                result = ToolResult(
                    success=True,
                    data={
                        "action": "acceptance_synced_from_validation",
                        **payload,
                        "info": f"Acceptance criterion '{kwargs.get('criterion_id')}' bound to validation signals.",
                    },
                )
            except Exception as e:
                result = ToolResult(success=False, error_message=str(e))

        else:
            result = ToolResult(
                success=False,
                error_message=f"Unknown action '{action}'. See tool description for available actions."
            )

        # Keep a shared, read-only plan index in hub for cross-agent visibility.
        if result.success:
            self._sync_plan_index(source_action=action)
        return result

    def _build_plan_index_payload(self, source_action: str = "") -> Dict[str, Any]:
        if not self._plan:
            return {
                "agent_id": self.agent_id,
                "has_plan": False,
                "source_action": source_action,
                "stage_order": [],
                "stages": {},
                "current_stage_id": None,
                "acceptance_summary": {"total": 0, "required": 0, "resolved": 0, "unresolved": 0, "failed": 0},
            }

        stages_payload: Dict[str, Any] = {}
        for sid in self._plan.stage_order:
            stage = self._plan.stages.get(sid)
            if not stage:
                continue
            stage_acceptance = self._acceptance_counts(stage.acceptance)
            stages_payload[sid] = {
                "name": stage.name,
                "status": stage.status,
                "acceptance": stage_acceptance,
                "tasks": {
                    tid: {
                        "status": task.status,
                        "assignee": task.assignee,
                        "acceptance": self._acceptance_counts(task.acceptance),
                    }
                    for tid, task in stage.tasks.items()
                },
            }

        return {
            "agent_id": self.agent_id,
            "has_plan": True,
            "source_action": source_action,
            "plan_name": self._plan.name,
            "plan_description": self._plan.description,
            "current_stage_id": self._plan.current_stage_id,
            "stage_order": list(self._plan.stage_order),
            "acceptance_summary": self._acceptance_counts(self._plan.acceptance),
            "stages": stages_payload,
        }

    def _sync_plan_index(self, source_action: str = "") -> None:
        """Flush the current plan to ``task.plan`` when bound via
        ``attach_to_task``. Pre-claim/unbound: no-op. Best-effort —
        never raises (plan stays in memory either way)."""
        if not self._hubs:
            return
        try:
            payload = self._build_plan_index_payload(source_action=source_action)
            self._flush_to_task_plan(payload, self._hubs.hubs.workhub)
        except Exception:
            pass

    def _flush_to_task_plan(self, payload: Dict[str, Any], workhub: Any) -> None:
        """Write the plan payload to ``task.plan`` if bound. Flush
        failure (terminal task / claim mismatch) auto-detaches."""
        if not self._task_id:
            return
        try:
            result = workhub.update_task_plan(
                self._task_id, payload, agent=self.agent_id,
            )
        except Exception:
            return
        if isinstance(result, dict) and result.get("error"):
            self.detach_from_task()


    # =========================================================================
    # Plan Management
    # =========================================================================
    
    def _create_plan(self, name: str, description: str, stages: List[Dict]) -> ToolResult:
        """Create a new staged plan."""
        if not name:
            return ToolResult(success=False, error_message="plan_name is required")
        
        self._plan = StagedPlan(
            name=name,
            description=description or "",
            stages={},
            stage_order=[],
            acceptance=self._normalize_acceptance_bundle(),
        )
        
        # Add initial stages if provided
        for stage_data in stages:
            stage_id = stage_data.get("id", f"stage_{len(self._plan.stages)}")
            self._plan.stages[stage_id] = PlanStage(
                id=stage_id,
                name=stage_data.get("name", stage_id),
                description=stage_data.get("description", ""),
                acceptance=self._normalize_acceptance_bundle(
                    acceptance=stage_data.get("acceptance"),
                    functional_acceptance=stage_data.get("functional_acceptance"),
                    artifact_acceptance=stage_data.get("artifact_acceptance"),
                ),
            )
            self._plan.stage_order.append(stage_id)
        
        # Set first stage as current if any
        if self._plan.stage_order:
            self._plan.current_stage_id = self._plan.stage_order[0]
        
        return ToolResult(
            success=True,
            data={
                "action": "plan_created",
                "name": name,
                "stages_count": len(self._plan.stages),
                "stages": [{"id": s, "name": self._plan.stages[s].name} for s in self._plan.stage_order],
                "info": f"Plan '{name}' created with {len(stages)} stages. Use add_task to add tasks to each stage."
            }
        )
    
    def _get_status(self) -> ToolResult:
        """Get detailed plan status."""
        status = self.get_plan_status()
        
        if not status["has_plan"]:
            return ToolResult(
                success=True,
                data={"info": "No plan exists. Use plan(action='create', ...) to create one."}
            )
        
        # Build detailed status view
        output_lines = [
            f"📋 Plan: {status['name']}",
            f"   {status['description']}",
            f"",
            f"📊 Progress: {status['completed_tasks']}/{status['total_tasks']} tasks ({status['progress_percent']}%)",
            f"✅ Plan acceptance: {status['acceptance_summary']['resolved']}/{status['acceptance_summary']['required']} required items resolved",
            f""
        ]
        if status.get("validation_links", {}).get("count"):
            plan_links = status["validation_links"]
            output_lines.extend(
                [
                    f"🔗 Validation-linked acceptance: {plan_links['resolved']}/{plan_links['count']} resolved",
                    *[
                        f"   - {item['title']} [{item['status']}] <- {item['source']}"
                        for item in plan_links.get("items", [])[:3]
                    ],
                    "",
                ]
            )

        for stage_info in status["stages"]:
            marker = "▶️" if stage_info["is_current"] else "  "
            status_icon = {"pending": "⬜", "in_progress": "🔵", "completed": "✅"}.get(stage_info["status"], "⬜")
            output_lines.append(f"{marker} {status_icon} [{stage_info['id']}] {stage_info['name']} ({stage_info['tasks']})")
            output_lines.append(
                f"      acceptance: {stage_info['acceptance']['resolved']}/{stage_info['acceptance']['required']} resolved"
            )
            if stage_info.get("validation_links", {}).get("count"):
                validation_links = stage_info["validation_links"]
                output_lines.append(
                    f"      validation-linked acceptance: {validation_links['resolved']}/{validation_links['count']} resolved"
                )
            if stage_info.get("task_validation_links"):
                output_lines.append(
                    f"      task validation links: {stage_info['task_validation_links']}"
                )
            if stage_info.get("task_acceptance_unresolved"):
                output_lines.append(
                    f"      task acceptance unresolved: {stage_info['task_acceptance_unresolved']}"
                )

            # Show tasks for current stage
            if stage_info["is_current"] and self._plan:
                stage = self._plan.stages.get(stage_info["id"])
                if stage and stage.tasks:
                    for task_id, task in stage.tasks.items():
                        task_icon = {"pending": "⬜", "in_progress": "🔄", "completed": "✅", "blocked": "🚫"}.get(task.status, "⬜")
                        assignee_str = f" @{task.assignee}" if task.assignee else ""
                        task_acceptance = self._acceptance_counts(task.acceptance)
                        task_validation_links = self._summarize_validation_driven_acceptance(task.acceptance)
                        acceptance_suffix = ""
                        if task_acceptance["required"] > 0:
                            acceptance_suffix = (
                                f" [acceptance {task_acceptance['resolved']}/{task_acceptance['required']}]"
                            )
                        if task_validation_links["count"] > 0:
                            acceptance_suffix += (
                                f" [validation {task_validation_links['resolved']}/{task_validation_links['count']}]"
                            )
                        output_lines.append(
                            f"      {task_icon} {task_id}: {task.description}{assignee_str}{acceptance_suffix}"
                        )
        
        return ToolResult(
            success=True,
            data={
                **status,
                "display": "\n".join(output_lines)
            }
        )
    
    def _clear_plan(self) -> ToolResult:
        """Clear the current plan."""
        had_plan = self._plan is not None
        self.reset()
        return ToolResult(
            success=True,
            data={
                "action": "cleared",
                "info": "Plan cleared." if had_plan else "No plan to clear."
            }
        )
    
    # =========================================================================
    # Stage Management
    # =========================================================================

    def _available_stage_ids(self) -> List[str]:
        if not self._plan:
            return []
        return list(self._plan.stage_order or list(self._plan.stages.keys()))

    def _stage_not_found(self, stage_id: str) -> ToolResult:
        available = self._available_stage_ids()
        alias_map = {
            "coordination": "design",
            "implement": "implementation",
            "impl": "implementation",
            "test": "testing",
            "validate": "validation",
            "delivery": "delivery",
        }
        alt = alias_map.get((stage_id or "").strip().lower())
        if alt and alt in available:
            return ToolResult(
                success=False,
                error_message=(
                    f"Stage '{stage_id}' not found. "
                    f"Did you mean '{alt}'? Available stages: {available}"
                ),
            )

        return ToolResult(
            success=False,
            error_message=f"Stage '{stage_id}' not found. Available stages: {available}.",
        )

    def _resolve_task_id(self, stage: PlanStage, task_id: str) -> Optional[str]:
        if task_id in stage.tasks:
            return task_id
        target = (task_id or "").strip().lower().replace("-", "_")
        if not target:
            return None

        normalized_map = {
            tid.lower().replace("-", "_"): tid
            for tid in stage.tasks.keys()
        }
        if target in normalized_map:
            return normalized_map[target]

        # Soft fuzzy: single contains match.
        contains = [tid for tid in stage.tasks.keys() if target in tid.lower().replace("-", "_")]
        if len(contains) == 1:
            return contains[0]
        return None
    
    def _add_stage(self, stage_id: str, name: str, description: str) -> ToolResult:
        """Add a new stage to the plan."""
        if not self._plan:
            return ToolResult(success=False, error_message="No plan exists. Create one first.")
        if not stage_id:
            return ToolResult(success=False, error_message="stage_id is required")
        if stage_id in self._plan.stages:
            return ToolResult(success=False, error_message=f"Stage '{stage_id}' already exists")
        
        self._plan.stages[stage_id] = PlanStage(
            id=stage_id,
            name=name or stage_id,
            description=description or ""
        )
        self._plan.stage_order.append(stage_id)
        
        return ToolResult(
            success=True,
            data={
                "action": "stage_added",
                "stage_id": stage_id,
                "name": name,
                "position": len(self._plan.stage_order),
                "info": f"Stage '{name}' added to plan."
            }
        )
    
    def _start_stage(self, stage_id: str) -> ToolResult:
        """Start working on a stage."""
        if not self._plan:
            return ToolResult(success=False, error_message="No plan exists.")
        if not stage_id:
            return ToolResult(success=False, error_message="stage_id is required")
        if stage_id not in self._plan.stages:
            return self._stage_not_found(stage_id)
        
        stage = self._plan.stages[stage_id]
        stage.status = "in_progress"
        self._plan.current_stage_id = stage_id
        
        # List tasks for this stage
        tasks_info = []
        for task_id, task in stage.tasks.items():
            tasks_info.append(f"  - {task_id}: {task.description} (@{task.assignee or 'unassigned'})")
        
        return ToolResult(
            success=True,
            data={
                "action": "stage_started",
                "stage_id": stage_id,
                "stage_name": stage.name,
                "tasks_count": len(stage.tasks),
                "tasks": tasks_info,
                "info": f"Started stage '{stage.name}' with {len(stage.tasks)} tasks."
            }
        )
    
    def _complete_stage(self, stage_id: str) -> ToolResult:
        """Complete a stage (all tasks must be done)."""
        if not self._plan:
            return ToolResult(success=False, error_message="No plan exists.")
        if not stage_id:
            return ToolResult(success=False, error_message="stage_id is required")
        if stage_id not in self._plan.stages:
            return self._stage_not_found(stage_id)
        
        stage = self._plan.stages[stage_id]
        
        # Check all tasks are completed
        incomplete = [t for t in stage.tasks.values() if t.status != "completed"]
        if incomplete:
            return ToolResult(
                success=False,
                error_message=f"Cannot complete stage: {len(incomplete)} tasks not done.",
                data={"incomplete_tasks": [t.id for t in incomplete]}
            )
        acceptance_gate = self._ensure_acceptance_resolved(stage.acceptance, f"stage '{stage_id}'")
        if acceptance_gate:
            return acceptance_gate
        
        stage.status = "completed"
        stage.completed_at = datetime.now().isoformat()
        
        # Move to next stage if available
        next_stage_id = None
        current_idx = self._plan.stage_order.index(stage_id)
        if current_idx + 1 < len(self._plan.stage_order):
            next_stage_id = self._plan.stage_order[current_idx + 1]
            self._plan.current_stage_id = next_stage_id
        
        return ToolResult(
            success=True,
            data={
                "action": "stage_completed",
                "stage_id": stage_id,
                "next_stage": next_stage_id,
                "info": f"Stage '{stage.name}' completed!" + 
                       (f" Next: {next_stage_id}" if next_stage_id else " All stages done! 🎉")
            }
        )
    
    # =========================================================================
    # Task Management
    # =========================================================================
    
    def _add_task(self, stage_id: str, task_id: str, description: str, 
                  assignee: str = None, dependencies: List[str] = None) -> ToolResult:
        """Add a task to a stage."""
        if not self._plan:
            return ToolResult(success=False, error_message="No plan exists.")
        if not stage_id or stage_id not in self._plan.stages:
            return self._stage_not_found(stage_id)
        if not task_id:
            return ToolResult(success=False, error_message="task_id is required")
        if not description:
            return ToolResult(success=False, error_message="task_description is required")
        
        stage = self._plan.stages[stage_id]
        if task_id in stage.tasks:
            return ToolResult(success=False, error_message=f"Task '{task_id}' already exists in stage")
        
        stage.tasks[task_id] = PlanTask(
            id=task_id,
            description=description,
            assignee=assignee,
            dependencies=dependencies or []
        )
        
        return ToolResult(
            success=True,
            data={
                "action": "task_added",
                "stage_id": stage_id,
                "task_id": task_id,
                "assignee": assignee or "unassigned",
                "info": f"Task '{task_id}' added to stage '{stage_id}'."
            }
        )
    
    def _assign_task(self, stage_id: str, task_id: str, assignee: str) -> ToolResult:
        """Assign a task to an agent."""
        if not self._plan:
            return ToolResult(success=False, error_message="No plan exists.")
        if not stage_id or stage_id not in self._plan.stages:
            return self._stage_not_found(stage_id)
        
        stage = self._plan.stages[stage_id]
        resolved_task_id = self._resolve_task_id(stage, task_id)
        if not resolved_task_id:
            return ToolResult(
                success=False,
                error_message=f"Task '{task_id}' not found. Available tasks: {list(stage.tasks.keys())}",
            )
        
        task = stage.tasks[resolved_task_id]
        old_assignee = task.assignee
        task.assignee = assignee
        
        return ToolResult(
            success=True,
            data={
                "action": "task_assigned",
                "task_id": resolved_task_id,
                "assignee": assignee,
                "previous_assignee": old_assignee,
                "info": f"Task '{resolved_task_id}' assigned to {assignee}."
            }
        )
    
    def _update_task_status(self, stage_id: str, task_id: str, 
                            status: str, reason: str = None) -> ToolResult:
        """Update task status."""
        if not self._plan:
            return ToolResult(success=False, error_message="No plan exists.")
        if not stage_id or stage_id not in self._plan.stages:
            return self._stage_not_found(stage_id)
        
        stage = self._plan.stages[stage_id]
        resolved_task_id = self._resolve_task_id(stage, task_id)
        if not resolved_task_id:
            return ToolResult(
                success=False,
                error_message=f"Task '{task_id}' not found. Available tasks: {list(stage.tasks.keys())}",
            )
        
        task = stage.tasks[resolved_task_id]
        old_status = task.status
        task.status = status
        if reason:
            task.result = reason
        
        return ToolResult(
            success=True,
            data={
                "action": f"task_{status}",
                "task_id": resolved_task_id,
                "old_status": old_status,
                "new_status": status,
                "info": f"Task '{resolved_task_id}' status: {old_status} → {status}"
            }
        )
    
    def _complete_task(self, stage_id: str, task_id: str, result: str = None) -> ToolResult:
        """Complete a task with optional result."""
        if not self._plan:
            return ToolResult(success=False, error_message="No plan exists.")
        if not stage_id or stage_id not in self._plan.stages:
            return self._stage_not_found(stage_id)
        
        stage = self._plan.stages[stage_id]
        resolved_task_id = self._resolve_task_id(stage, task_id)
        if not resolved_task_id:
            return ToolResult(
                success=False,
                error_message=f"Task '{task_id}' not found. Available tasks: {list(stage.tasks.keys())}",
            )
        
        task = stage.tasks[resolved_task_id]
        acceptance_gate = self._ensure_acceptance_resolved(task.acceptance, f"task '{resolved_task_id}'")
        if acceptance_gate:
            return acceptance_gate
        task.status = "completed"
        task.completed_at = datetime.now().isoformat()
        if result:
            task.result = result
        
        # Check stage progress
        completed = sum(1 for t in stage.tasks.values() if t.status == "completed")
        total = len(stage.tasks)
        
        return ToolResult(
            success=True,
            data={
                "action": "task_completed",
                "task_id": resolved_task_id,
                "result": result,
                "stage_progress": f"{completed}/{total}",
                "stage_complete": completed == total,
                "info": f"Task '{resolved_task_id}' completed. Stage progress: {completed}/{total}"
            }
        )
    
    def _list_tasks(self, stage_id: str = None, filter_status: str = None, 
                    filter_assignee: str = None) -> ToolResult:
        """List tasks with optional filters."""
        if not self._plan:
            return ToolResult(success=False, error_message="No plan exists.")
        
        tasks_output = []
        stages_to_check = [stage_id] if stage_id else self._plan.stage_order
        
        for sid in stages_to_check:
            if sid not in self._plan.stages:
                continue
            stage = self._plan.stages[sid]
            stage_tasks = []
            
            for task_id, task in stage.tasks.items():
                if filter_status and task.status != filter_status:
                    continue
                if filter_assignee and task.assignee != filter_assignee:
                    continue
                stage_tasks.append({
                    "id": task_id,
                    "description": task.description,
                    "status": task.status,
                    "assignee": task.assignee,
                    "result": task.result,
                    "acceptance": self._acceptance_counts(task.acceptance),
                })
            
            if stage_tasks:
                tasks_output.append({
                    "stage_id": sid,
                    "stage_name": stage.name,
                    "tasks": stage_tasks
                })
        
        total_count = sum(len(s["tasks"]) for s in tasks_output)
        
        return ToolResult(
            success=True,
            data={
                "action": "tasks_listed",
                "total": total_count,
                "filters": {"status": filter_status, "assignee": filter_assignee},
                "stages": tasks_output
            }
        )


# ============================================================================
# Verify Plan Tool (for verification coverage)
# ============================================================================

class VerifyPlanTool(BaseTool):
    """
    Verification plan tracker for verifier/coordinator coverage.

    This is intentionally separate from PlanTool (CodeAgent implementation plan).
    It tracks *verification test cases* so the verifier can ensure coverage
    (e.g., System menu toggle, navigation back/forward, Create Issue flow).
    """

    NAME = "verify_plan"

    DESCRIPTION = """Track a verification test plan as a checklist.

Use this during verification (frontend/final verification) to ensure you:
- Create a test plan table/checklist
- Execute each test and mark it complete

Actions:
- create: set a new verification checklist
- status: show current completion status
- complete: mark a checklist item complete

Examples:
    verify_plan(action="create", items=["[P0] NAV-001: Switch pages and return works", ...])
    verify_plan(action="status")
    verify_plan(action="complete", item_text="NAV-001")
"""

    _instances: dict = {}

    def __init__(self, agent_id: str = None):
        super().__init__(name=self.NAME, category=ToolCategory.AGENT)
        self.agent_id = agent_id or "default"
        self._current_plan: list = []
        self._plan_completed: list = []
        self._plan_results: list = []
        VerifyPlanTool._instances[self.agent_id] = self

    def set_agent(self, agent) -> None:
        runtime_agent_id = getattr(agent, "agent_id", None)
        if runtime_agent_id and runtime_agent_id != self.agent_id:
            if VerifyPlanTool._instances.get(self.agent_id) is self:
                VerifyPlanTool._instances.pop(self.agent_id, None)
            self.agent_id = runtime_agent_id
            VerifyPlanTool._instances[self.agent_id] = self

    def reset(self):
        """Reset verification plan state."""
        self._current_plan = []
        self._plan_completed = []
        self._plan_results = []

    def get_plan_status(self) -> dict:
        """Get current verification plan status."""
        total = len(self._current_plan)
        completed = sum(self._plan_completed)
        passed = self._plan_results.count("pass")
        failed = self._plan_results.count("fail")
        skipped = self._plan_results.count("skip")
        incomplete = [
            self._current_plan[i]
            for i in range(total)
            if not self._plan_completed[i]
        ]
        return {
            "has_plan": total > 0,
            "total": total,
            "completed": completed,
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "incomplete": incomplete,
            "all_complete": total > 0 and completed == total,
        }

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
                    "action": {
                        "type": "string",
                        "enum": ["create", "status", "complete"],
                        "description": "Action to perform"
                    },
                    "items": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of test items (for 'create')"
                    },
                    "item_index": {
                        "type": "integer",
                        "description": "Index of item to mark complete"
                    },
                    "item_text": {
                        "type": "string",
                        "description": "Text/ID of item to mark complete"
                    },
                    "result": {
                        "type": "string",
                        "enum": ["pass", "fail", "skip"],
                        "description": "Result of the test case"
                    },
                    "notes": {
                        "type": "string",
                        "description": "Notes about the test result"
                    }
                },
                "required": ["action"]
            }
        )

    def execute(
        self,
        action: str,
        items: list = None,
        item_index: int = None,
        item_text: str = None,
        result: str = "pass",
        notes: str = None
    ) -> ToolResult:
        
        if action == "create":
            if not items:
                return ToolResult(
                    success=False,
                    error_message="'items' required for 'create' action."
                )
            self._current_plan = items
            self._plan_completed = [False] * len(items)
            self._plan_results = [""] * len(items)
            checklist = "\n".join(f"  [ ] {i+1}. {item}" for i, item in enumerate(items))
            return ToolResult(
                success=True,
                data={
                    "action": "created",
                    "total_items": len(items),
                    "checklist": checklist,
                    "info": f"Verification plan created with {len(items)} test cases."
                }
            )

        elif action == "status":
            status = self.get_plan_status()
            if not status["has_plan"]:
                return ToolResult(
                    success=True,
                    data={"info": "No verification plan. Use verify_plan(action='create', items=[...])."}
                )
            lines = []
            for i, item in enumerate(self._current_plan):
                if self._plan_completed[i]:
                    res = self._plan_results[i]
                    mark = "[PASS]" if res == "pass" else "[FAIL]" if res == "fail" else "[SKIP]"
                else:
                    mark = "[    ]"
                lines.append(f"  {mark} {i+1}. {item}")
            return ToolResult(
                success=True,
                data={
                    "total": status["total"],
                    "completed": status["completed"],
                    "passed": status["passed"],
                    "failed": status["failed"],
                    "skipped": status["skipped"],
                    "checklist": "\n".join(lines),
                    "info": f"Progress: {status['completed']}/{status['total']} ({status['passed']} pass, {status['failed']} fail)"
                }
            )

        elif action == "complete":
            if not self._current_plan:
                return ToolResult(
                    success=False,
                    error_message="No verification plan exists."
                )
            target = None
            if item_index is not None and 0 <= item_index < len(self._current_plan):
                target = item_index
            elif item_text:
                for i, item in enumerate(self._current_plan):
                    if item_text.lower() in item.lower():
                        target = i
                        break
            if target is None:
                return ToolResult(
                    success=False,
                    error_message="Could not find item to complete."
                )
            self._plan_completed[target] = True
            self._plan_results[target] = result
            status = self.get_plan_status()
            return ToolResult(
                success=True,
                data={
                    "action": "marked_complete",
                    "item": self._current_plan[target],
                    "result": result,
                    "notes": notes,
                    "progress": f"{status['completed']}/{status['total']}",
                    "info": f"[{result.upper()}] {self._current_plan[target]}"
                }
            )

        return ToolResult(
            success=False,
            error_message=f"Unknown action '{action}'."
        )


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "GetTimeTool",
    "WaitTool",
    "PlanTool",
    "VerifyPlanTool",
]

