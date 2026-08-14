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

# #626: owner of last resort for a bug no artifact and no vocabulary can place. The debugger is
# spawned in every run (56 of 56 kept trees have the worktree) and triage is its role; it can
# reassign, which an unassigned task cannot do for itself.
_TRIAGE_OWNER_626 = "debugger"


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
            # #742: NAME THE FORMAT, NOT JUST THE SLOT. This was a bare list of key names with
            # no shape for any of them, and `resolve_owning_agent` needs two of them to PARSE:
            # `affected_endpoint` is split on the first space and matched against RegistryHub,
            # and `affected_files` is scanned for a lane segment. Measured over the 1467 bugs
            # in the 148-run corpus, of the 1129 that set `affected_endpoint`:
            #     449  match a registered endpoint exactly
            #     339  have nothing path-shaped after the method
            #     308  carry prose inside the path ("GET /api/titles?kind=series (or however
            #          the shows page filters titles)", "frontend nginx")
            #      20  differ only in the parameter NAME  (/titles/{title_id} vs /titles/{id})
            # 216 bugs end up with NO owner at all, and an unassigned bug is nobody's job by
            # construction — #626 measured those sitting a median 46 minutes into a released
            # run. Same fix shape as #732/#733: the model writes what the description names,
            # so the description states the exact form each consumer parses.
            "bug_artifacts": {
                "type": "object",
                "description": (
                    "Structured evidence. At least one of failing_test, stack_trace, "
                    "affected_endpoint, affected_files, expected, actual. Two of these are "
                    "PARSED, not just read, so their form matters: `affected_endpoint` must be "
                    "exactly '<METHOD> <path>' as REGISTERED in RegistryHub (e.g. "
                    "'GET /api/titles/{id}') — no query string, no parentheses, no prose, and "
                    "the parameter name must be the registered one; `affected_files` must be "
                    "repo-relative paths (e.g. 'app/frontend/src/App.jsx'), because the owning "
                    "lane is resolved from a path segment. Put uncertainty in `description`, "
                    "never inside these two."),
                "properties": {
                    "failing_test": {"type": "string",
                                     "description": "chain/step or test id that failed"},
                    "stack_trace": {"type": "string"},
                    "affected_endpoint": {
                        "type": "string",
                        "description": "'<METHOD> <registered path>', e.g. 'POST /api/my-list'"},
                    "affected_table": {"type": "string",
                                       "description": "table name as registered in SchemaHub"},
                    "affected_files": {
                        "type": "array", "items": {"type": "string"},
                        "description": "repo-relative paths, e.g. app/backend/custom_routes.py"},
                    "expected": {"type": "string"},
                    "actual": {"type": "string"},
                },
            },
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
        # Route the bug to its OWNING lane on creation so a real fixer is woken directly
        # (assigned task_created → for-self wakeup), instead of leaving it unassigned+pending
        # for a debugger that may never wake. Run v14: the verifier filed the DELETE
        # /api/posts/{id} FK-500 bug, but bug_found's source_hub (=source, e.g.
        # "business_chain") didn't match the debugger's ('verifier','bug_found') subscription
        # → the debugger stayed idle → the bug sat unassigned 7 cycles → fail-fast abort, no
        # delivery. resolve_owning_agent maps affected_endpoint/table/files → the lane; the
        # debugger still receives bug_found (below) to triage/reassign. Best-effort.
        try:
            from multi_agent.runtime.bug_triage import resolve_owning_agent
            _owner = resolve_owning_agent(self._hubs, bug_artifacts or {})
        except Exception:
            _owner = None
        if not _owner:
            # Fallback for a bug with NO resolvable endpoint/table/file artifact — e.g. a
            # build failure ("Frontend build fails: npm run build returns code 1", run v15)
            # whose artifacts are a stack trace, not a route. Infer the owning lane from the
            # source/title keywords so it still routes to a fixer instead of sitting
            # unassigned (the debugger does not reliably wake to triage it). Frontend vs
            # backend by domain words; leave None only if genuinely ambiguous.
            _hay = f"{source} {title} {description}".lower()
            _fe = any(w in _hay for w in ("frontend", "npm", "vite", "jsx", "tsx", "react", "tailwind", " ui ", "ui_", "build fail"))
            _be = any(w in _hay for w in ("backend", "fastapi", "pydantic", "sqlalchemy", "/api/", "endpoint", " sql", "psycopg", "database", "migration"))
            if _fe and not _be:
                _owner = "frontend"
            elif _be and not _fe:
                _owner = "backend"
        if not _owner:
            # #626: AMBIGUOUS IS NOT UNKNOWN, AND UNKNOWN IS NOT NOBODY.
            # Both branches above fall through to None — when NEITHER vocabulary matches (46 of
            # the 59 unassigned P0s: "Landing page (/) crashes with 'Cn is not a function'"
            # names no framework word at all) and when BOTH do (the other 13). The result was a
            # P0 with no assignee, which is nobody's job by construction: they sat a median of
            # 46 minutes and every affected run released with them still open.
            #
            # Assignment is also what WAKES a fixer — see the comment above: "assigned
            # task_created → for-self wakeup". Leaving it None is the one choice guaranteed to
            # wake no one. A triage owner may reassign; nobody cannot. Cost is small and
            # measured: 114 bugs over 27 runs, median 2 per run.
            _owner = _TRIAGE_OWNER_626
        task = self._hubs.workhub.create_task(
            title=title,
            description=description,
            agent=self._agent_id,
            assignee=_owner,
            priority=severity if severity in ("P0", "P1", "P2", "P3") else "P2",
            kind=bug_schema.KIND,
            severity=severity,
            bug_state=bug_schema.STATE_INITIAL,
            source=source,
            parent_bug_id=parent_bug_id,
            bug_artifacts=bug_artifacts or {},
            triage_history=[],
        )
        # #628 — NAME THE TRIAGE OWNER; DO NOT WAIT TO BE SUBSCRIBED TO.
        # This call passed no `recipients`, so delivery depended entirely on a matching
        # subscription existing AT THAT MOMENT. Measured over 45 runs: 443 of 555 bug_found
        # events reached nobody, and the model is exact — of the 16 runs that ever record a
        # bug_found subscription, 144 undelivered events were filed BEFORE it existed and **0**
        # after. The other 29 runs never subscribe at all, so every bug is broadcast into the
        # void. (The code's own older note blamed a source_hub mismatch; that is NOT the cause —
        # verifier-sourced events go undelivered 312 of 408 times, and browser_test_user ones do
        # get through 15 times. It is timing, not source.)
        #
        # `_record_breaking_change` already shows the right shape: name the recipients, do not
        # hope a subscription exists. publish_event UNIONS explicit recipients with subscription
        # matches, so this can only add.
        #
        # The ASSIGNEE is deliberately excluded — create_task(assignee=...) already wakes them
        # ("assigned task_created → for-self wakeup"), and waking the same agent twice for one
        # bug is noise. This informs the triage role about bugs it would otherwise never see.
        _notify = [a for a in (_TRIAGE_OWNER_626,) if a and a != _owner]
        try:
            self._hubs.eventhub.publish_event(
                source_hub=source or "verifier",
                event_type="bug_found",
                payload={"task_id": task["id"], "severity": severity, "title": title},
                recipients=_notify,
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
