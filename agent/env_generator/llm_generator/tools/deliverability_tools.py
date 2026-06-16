"""Deliverability LLM tools (Cutover 24)."""

from __future__ import annotations

from typing import Any, Optional

from utils.tool import BaseTool, ToolCategory, ToolResult, create_tool_param

from multi_agent.runtime.deliverability import compute_deliverability


class _DeliverabilityToolBase(BaseTool):
    def __init__(self, *, hub_registry=None, app_root: Optional[str] = None,
                 session_start_ts: float = 0.0):
        super().__init__(name=self.NAME, category=ToolCategory.KNOWLEDGE)
        self.hub_registry = hub_registry
        self.app_root = app_root
        self.session_start_ts = session_start_ts


class DeliverabilityCheckTool(_DeliverabilityToolBase):
    NAME = "deliverability_check"
    DESCRIPTION = ("Evidence-based unified deliverability report: latest RunHub "
                    "run + endpoint/MCP probe counts + coverage + seed + visual "
                    "reviews. Replaces LLM-judged checklist. Verdict = "
                    "'deliverable' iff blockers list is empty.")

    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME, description=self.DESCRIPTION,
            parameters={"type": "object", "properties": {}}, required=[])

    async def execute(self, **_kw) -> ToolResult:
        report = compute_deliverability(
            self.hub_registry, self.app_root, self.session_start_ts)
        return ToolResult.ok(data=report.to_dict())


class DeliverabilitySummaryTool(_DeliverabilityToolBase):
    NAME = "deliverability_summary"
    DESCRIPTION = ("One-line summary of deliverability: verdict + blocker count "
                    "+ first blocker. Use this for quick checks; use "
                    "deliverability_check for the full report.")

    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME, description=self.DESCRIPTION,
            parameters={"type": "object", "properties": {}}, required=[])

    async def execute(self, **_kw) -> ToolResult:
        report = compute_deliverability(
            self.hub_registry, self.app_root, self.session_start_ts)
        return ToolResult.ok(data={
            "verdict": report.verdict,
            "blocker_count": len(report.blockers),
            "first_blocker": report.blockers[0] if report.blockers else None,
            "run_within_session": report.run_within_session,
        })


_DELIVERABILITY_TOOLS = [DeliverabilityCheckTool, DeliverabilitySummaryTool]


def create_deliverability_tools(hub_registry=None,
                                 app_root: Optional[str] = None,
                                 session_start_ts: float = 0.0) -> list:
    return [cls(hub_registry=hub_registry, app_root=app_root,
                session_start_ts=session_start_ts)
            for cls in _DELIVERABILITY_TOOLS]


__all__ = [
    "DeliverabilityCheckTool", "DeliverabilitySummaryTool",
    "create_deliverability_tools",
]
