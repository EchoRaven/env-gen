"""Milestone-management LLM tools — the orchestrator's tool surface over the
``MilestoneRegistry`` (hubs.milestones).

Used during KICKOFF: on the kickoff signal the orchestrator (with its full system
prompt + hub context) reviews the roadmap and MAY revise the FUTURE (not-yet-started)
milestones — add / update / remove — and MUST set the CURRENT milestone's detailed
plan (its milestone detail). DELIVERED milestones are frozen; the active one cannot be removed.

Follows the ``HubTool`` convention (see tools/bug_tools.py): async ``_run`` returning
``ToolResult``, hubs via ``self._hubs.milestones``, identity via ``self._agent_id``.
"""
from __future__ import annotations

from typing import Any, List, Optional

from ._base import ToolResult
from .hub_tools import HubTool, _finalize_hub_tools


class MilestoneListTool(HubTool):
    NAME = "milestone_list"
    DESCRIPTION = (
        "List the milestone roadmap: each phase's index, name, version, status "
        "(pending/active/delivered), rough scope, and whether a milestone detail is set. "
        "Read this FIRST at kickoff to see the plan and what's already delivered."
    )
    PARAMETERS = {"type": "object", "properties": {}}

    async def _run(self) -> ToolResult:
        ms = self._hubs.milestones.list_milestones()
        return ToolResult(data={"milestones": [
            {"index": m.get("index"), "id": m.get("id"), "name": m.get("name"),
             "version": m.get("version"), "status": m.get("status"),
             "description_slice": m.get("description_slice"),
             "has_detail": bool(m.get("detail"))}
            for m in ms]})


class MilestoneAddTool(HubTool):
    NAME = "milestone_add"
    DESCRIPTION = (
        "Add a NEW future milestone to the roadmap. Default appends at the end; pass "
        "after_index to insert right after that 1-based phase (later phases shift "
        "down). Only adds FUTURE phases — delivered ones are frozen. Use when the "
        "remaining plan needs another phase given what's been built."
    )
    PARAMETERS = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "version": {"type": "string"},
            "description_slice": {"type": "string",
                                  "description": "the rough scope of this new phase"},
            "acceptance": {"type": "array", "items": {"type": "string"}},
            "after_index": {"type": "integer",
                            "description": "insert after this 1-based milestone index; omit to append"},
        },
        "required": ["name", "description_slice"],
    }

    async def _run(self, name: str, description_slice: str, version: str = "",
                   acceptance: Optional[List[str]] = None,
                   after_index: Optional[int] = None) -> ToolResult:
        rec = self._hubs.milestones.add(
            name=name, version=version, description_slice=description_slice,
            acceptance=acceptance, after_index=after_index, agent=self._agent_id)
        return ToolResult(data=rec)


class MilestoneUpdateTool(HubTool):
    NAME = "milestone_update"
    DESCRIPTION = (
        "Re-scope a NOT-yet-delivered milestone (rename, re-version, change its rough "
        "scope / acceptance). Delivered milestones are frozen and cannot change. "
        "Identify it by 1-based index (e.g. '3') or id."
    )
    PARAMETERS = {
        "type": "object",
        "properties": {
            "milestone": {"type": "string", "description": "milestone index (e.g. '3') or id"},
            "name": {"type": "string"},
            "version": {"type": "string"},
            "description_slice": {"type": "string"},
            "acceptance": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["milestone"],
    }

    async def _run(self, milestone: str, name: Optional[str] = None,
                   version: Optional[str] = None,
                   description_slice: Optional[str] = None,
                   acceptance: Optional[List[str]] = None) -> ToolResult:
        rec = self._hubs.milestones.update(
            milestone, name=name, version=version,
            description_slice=description_slice, acceptance=acceptance,
            agent=self._agent_id)
        if isinstance(rec, dict) and rec.get("error"):
            return ToolResult(success=False, error_message=rec["error"])
        return ToolResult(data=rec)


class MilestoneRemoveTool(HubTool):
    NAME = "milestone_remove"
    DESCRIPTION = (
        "Remove a NOT-yet-started (pending, future) milestone; remaining phases "
        "reindex. The active and delivered milestones cannot be removed."
    )
    PARAMETERS = {
        "type": "object",
        "properties": {
            "milestone": {"type": "string", "description": "milestone index or id"},
        },
        "required": ["milestone"],
    }

    async def _run(self, milestone: str) -> ToolResult:
        rec = self._hubs.milestones.remove(milestone, agent=self._agent_id)
        if isinstance(rec, dict) and rec.get("error"):
            return ToolResult(success=False, error_message=rec["error"])
        return ToolResult(data=rec)


class MilestoneSetDetailTool(HubTool):
    NAME = "milestone_set_detail"
    DESCRIPTION = (
        "Set the DETAILED plan (the milestone detail) for a milestone — the concrete, actionable plan the "
        "build lanes execute THIS phase: exactly which endpoints / pages / components "
        "/ data to ADD, the acceptance, and what is ALREADY shipped (don't rebuild). "
        "REQUIRED for the current milestone at kickoff (it becomes the lanes' scope)."
    )
    PARAMETERS = {
        "type": "object",
        "properties": {
            "milestone": {"type": "string", "description": "milestone index or id"},
            "detail": {"type": "string", "description": "the detailed phase detail (markdown ok)"},
        },
        "required": ["milestone", "detail"],
    }

    async def _run(self, milestone: str, detail: str) -> ToolResult:
        rec = self._hubs.milestones.set_detail(milestone, detail, agent=self._agent_id)
        if isinstance(rec, dict) and rec.get("error"):
            return ToolResult(success=False, error_message=rec["error"])
        return ToolResult(data=rec)


MILESTONE_TOOL_CLASSES = [
    MilestoneListTool, MilestoneAddTool, MilestoneUpdateTool,
    MilestoneRemoveTool, MilestoneSetDetailTool,
]

_finalize_hub_tools(MILESTONE_TOOL_CLASSES)


def create_milestone_tools(agent_id: str = "", hub_workspace: Any = None,
                           include_names: set | None = None) -> list:
    tools = [cls(agent_id=agent_id, hub_workspace=hub_workspace)
             for cls in MILESTONE_TOOL_CLASSES]
    if include_names:
        tools = [t for t in tools if getattr(t, "NAME", "") in include_names]
    return tools


__all__ = [
    "MilestoneListTool", "MilestoneAddTool", "MilestoneUpdateTool",
    "MilestoneRemoveTool", "MilestoneSetDetailTool",
    "MILESTONE_TOOL_CLASSES", "create_milestone_tools",
]
