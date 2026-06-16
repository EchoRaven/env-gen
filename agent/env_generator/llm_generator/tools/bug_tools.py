"""Bug-triage LLM tools (Cutover 10).

Tools:
  - bug_create:            Verifier / RunHub / orchestrator create a new bug task
  - bug_list_open:         Debugger lists open bugs (P0-first)
  - bug_list_assigned_to:  any agent lists bugs assigned to itself
  - bug_triage:            Debugger analyzes + assigns
  - bug_update_state:      assignee transitions bug through lifecycle
  - bug_close:             assignee closes bug with fix evidence
  - bug_escalate:          Debugger escalates after failed fixes

All classes follow the existing `HubTool` convention from `tools/hub_tools.py`:
async `_run(...)` returning `ToolResult(data=...)`, accessing hubs via
`self._hubs.<hub>` and identity via `self._agent_id`. `_finalize_hub_tools` is
applied so each class gets a default `execute` wrapper for the agent runtime.
"""

from __future__ import annotations

from typing import Any, Optional

from multi_agent.runtime import bug_schema

from ._base import ToolResult
from .hub_tools import HubTool, _finalize_hub_tools


# Re-exported for the schema parity scanner — both sides reference
# the same constants so they cannot drift.
_VALID_SEVERITY = bug_schema.VALID_SEVERITIES


class BugCreateTool(HubTool):
    NAME = "bug_create"
    DESCRIPTION = (
        "Create a new bug task on WorkHub with structured artifacts. "
        "Use this from Verifier / RunHub when a regression or runtime failure "
        "is observed. Severity must be one of P0/P1/P2/P3. Also publishes a "
        "'bug_found' event so the Debugger pulse picks it up."
    )
    PARAMETERS = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "source": {"type": "string", "description": "verifier|runhub|codehub_check|manual"},
            "severity": {"type": "string", "enum": list(_VALID_SEVERITY)},
            "bug_artifacts": {"type": "object", "description": "failing_test, stack_trace, affected_endpoint, affected_files, expected, actual, ..."},
            "description": {"type": "string"},
            "parent_bug_id": {"type": "string", "description": "Set if this is a recurrence of an earlier bug."},
        },
        "required": ["title", "source", "severity", "bug_artifacts"],
    }

    async def _run(self, title: str, source: str, severity: str,
                   bug_artifacts: dict, description: str = "",
                   parent_bug_id: Optional[str] = None) -> ToolResult:
        if severity not in _VALID_SEVERITY:
            return ToolResult(success=False, error_message=f"invalid severity: {severity!r}")
        # Reject empty title / artifact-less bug reports — the triage
        # orchestrator can't route a bug that has neither a name nor any
        # evidence. A clear error here lets the verifier retry with
        # actual context instead of silently filing a useless ticket.
        if not isinstance(title, str) or not title.strip():
            return ToolResult(success=False,
                               error_message="bug_create: title must be non-empty")
        if not isinstance(bug_artifacts, dict) or not bug_artifacts:
            return ToolResult(success=False,
                               error_message=(
                                   "bug_create: bug_artifacts must include at least "
                                   "one of failing_test, stack_trace, affected_endpoint, "
                                   "affected_files, expected, actual."
                               ))
        task = self._hubs.workhub.create_task(
            title=title,
            description=description,
            agent=self._agent_id,
            kind=bug_schema.KIND,
            severity=severity,
            bug_state=bug_schema.STATE_INITIAL,
            source=source,
            parent_bug_id=parent_bug_id,
            bug_artifacts=bug_artifacts or {},
            triage_history=[],
        )
        try:
            self._hubs.eventhub.publish_event(
                source_hub=source or "verifier",
                event_type="bug_found",
                payload={"task_id": task["id"], "severity": severity, "title": title},
                priority="high" if severity in ("P0", "P1") else "normal",
            )
        except Exception:
            # Event publication is best-effort; the bug task is the source of truth.
            pass
        return ToolResult(data=task)


class BugListOpenTool(HubTool):
    NAME = "bug_list_open"
    DESCRIPTION = (
        "List all open bugs (P0-first, then oldest-first). "
        "Used by the Debugger at the start of each step."
    )
    PARAMETERS = {"type": "object", "properties": {}}

    async def _run(self) -> ToolResult:
        return ToolResult(data={"bugs": self._hubs.workhub.list_open_bugs()})


class BugListAssignedToTool(HubTool):
    NAME = "bug_list_assigned_to"
    DESCRIPTION = (
        "List bugs assigned to an agent. Defaults to the caller (self._agent_id) "
        "when 'agent' is omitted."
    )
    PARAMETERS = {
        "type": "object",
        "properties": {
            "agent": {"type": "string", "description": "Agent id to look up. Defaults to caller."},
        },
    }

    async def _run(self, agent: Optional[str] = None) -> ToolResult:
        target = agent or self._agent_id
        return ToolResult(data={
            "agent": target,
            "bugs": self._hubs.workhub.list_bugs_assigned_to(target),
        })


class BugTriageTool(HubTool):
    NAME = "bug_triage"
    DESCRIPTION = (
        "Debugger action: record the root cause hypothesis on the "
        "bug, identify the owning agent (via RegistryHub provider or file-path "
        "heuristics), and transition state through triaged -> assigned. "
        "Pass 'assignee' to override the resolver."
    )
    PARAMETERS = {
        "type": "object",
        "properties": {
            "task_id": {"type": "string"},
            "root_cause": {"type": "string"},
            "assignee": {"type": "string", "description": "Optional explicit owner; overrides resolver."},
        },
        "required": ["task_id", "root_cause"],
    }

    async def _run(self, task_id: str, root_cause: str,
                   assignee: Optional[str] = None) -> ToolResult:
        # Local import keeps tool module importable even if runtime path differs.
        from multi_agent.runtime.bug_triage import resolve_owning_agent

        wh = self._hubs.workhub
        task = wh.stores.tasks.get(task_id) or {}
        artifacts = (task.get("metadata") or {}).get("bug_artifacts") or {}
        owner = assignee or resolve_owning_agent(self._hubs, artifacts)
        if not owner:
            return ToolResult(
                success=False,
                error_message="could not resolve owning agent and no assignee supplied",
            )
        wh.update_bug_state(
            task_id, "triaged",
            agent=self._agent_id,
            note="root cause recorded",
            root_cause_hypothesis=root_cause,
        )
        updated = wh.update_bug_state(
            task_id, "assigned",
            agent=self._agent_id,
            note=f"assigned to {owner}",
            assignee=owner,
        )
        return ToolResult(data=updated)


class BugUpdateStateTool(HubTool):
    NAME = "bug_update_state"
    DESCRIPTION = (
        "Transition a bug's lifecycle state (open|triaged|assigned|in_progress|"
        "fix_proposed|fix_verified|closed|escalated). Use bug_close / bug_escalate "
        "for the terminal transitions when fix-evidence / reason is needed."
    )
    PARAMETERS = {
        "type": "object",
        "properties": {
            "task_id": {"type": "string"},
            "new_state": {"type": "string"},
            "note": {"type": "string"},
        },
        "required": ["task_id", "new_state"],
    }

    async def _run(self, task_id: str, new_state: str, note: str = "") -> ToolResult:
        updated = self._hubs.workhub.update_bug_state(
            task_id, new_state, agent=self._agent_id, note=note,
        )
        return ToolResult(data=updated)


class BugCloseTool(HubTool):
    NAME = "bug_close"
    DESCRIPTION = (
        "Close a bug after the fix is verified. fix_evidence is required (e.g., "
        "{pr: 'PR-42', verified_by_test: 'test_x'})."
    )
    PARAMETERS = {
        "type": "object",
        "properties": {
            "task_id": {"type": "string"},
            "fix_evidence": {"type": "object"},
        },
        "required": ["task_id", "fix_evidence"],
    }

    async def _run(self, task_id: str, fix_evidence: dict) -> ToolResult:
        updated = self._hubs.workhub.close_bug(
            task_id, agent=self._agent_id, fix_evidence=fix_evidence,
        )
        return ToolResult(data=updated)


class BugEscalateTool(HubTool):
    NAME = "bug_escalate"
    DESCRIPTION = (
        "Escalate a bug to the main Orchestrator after N failed fix attempts or "
        "an unresolvable root cause. Reason is required."
    )
    PARAMETERS = {
        "type": "object",
        "properties": {
            "task_id": {"type": "string"},
            "reason": {"type": "string"},
        },
        "required": ["task_id", "reason"],
    }

    async def _run(self, task_id: str, reason: str) -> ToolResult:
        updated = self._hubs.workhub.escalate_bug(
            task_id, agent=self._agent_id, reason=reason,
        )
        return ToolResult(data=updated)


BUG_TOOL_CLASSES = [
    BugCreateTool,
    BugListOpenTool,
    BugListAssignedToTool,
    BugTriageTool,
    BugUpdateStateTool,
    BugCloseTool,
    BugEscalateTool,
]


_finalize_hub_tools(BUG_TOOL_CLASSES)


def create_bug_tools(agent_id: str = "", hub_workspace: Any = None,
                     include_names: set | None = None) -> list:
    tools = [cls(agent_id=agent_id, hub_workspace=hub_workspace)
             for cls in BUG_TOOL_CLASSES]
    if include_names:
        tools = [t for t in tools if getattr(t, "NAME", "") in include_names]
    return tools


__all__ = [
    "BugCreateTool", "BugListOpenTool", "BugListAssignedToTool",
    "BugTriageTool", "BugUpdateStateTool", "BugCloseTool", "BugEscalateTool",
    "BUG_TOOL_CLASSES", "create_bug_tools",
]
