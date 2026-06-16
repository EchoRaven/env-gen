"""Observability LLM tool (Cutover 17). Generates a static HTML dashboard."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from utils.tool import BaseTool, ToolCategory, ToolResult, create_tool_param

from multi_agent.runtime.observability.dashboard import render_dashboard
from multi_agent.runtime.observability.log_parser import aggregate_logs


class ObservabilityDashboardTool(BaseTool):
    NAME = "observability_dashboard"
    DESCRIPTION = ("Generate a self-contained HTML observability dashboard from "
                    "agent/.agent_logs/. Returns summary stats + writes HTML to output_path.")

    def __init__(self):
        super().__init__(name=self.NAME, category=ToolCategory.KNOWLEDGE)

    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME, description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "logs_dir": {"type": "string",
                                  "description": "Path to .agent_logs directory"},
                    "output_path": {"type": "string",
                                     "description": "Output .html path"},
                },
                "required": ["logs_dir", "output_path"],
            })

    async def execute(self, *, logs_dir: str, output_path: str, **_kw) -> ToolResult:
        try:
            stats = aggregate_logs(Path(logs_dir))
            render_dashboard(stats, output_path=Path(output_path))
            return ToolResult(success=True, data={
                "total_agents": stats.total_agents,
                "total_events": stats.total_events,
                "output_path": output_path,
            })
        except Exception as e:
            return ToolResult(success=False, error_message=str(e))


def create_observability_tools() -> list:
    return [ObservabilityDashboardTool()]


__all__ = ["ObservabilityDashboardTool", "create_observability_tools"]
