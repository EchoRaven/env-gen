"""Coverage audit LLM tools (Cutover 19)."""

from __future__ import annotations

from typing import Any, Optional

from utils.tool import BaseTool, ToolCategory, ToolResult, create_tool_param

from multi_agent.runtime.coverage_audit import compute_coverage


class _CoverageToolBase(BaseTool):
    def __init__(self, *, hub_registry=None, app_root: Optional[str] = None):
        super().__init__(name=self.NAME, category=ToolCategory.KNOWLEDGE)
        self.hub_registry = hub_registry
        self.app_root = app_root


class CoverageAuditCheckTool(_CoverageToolBase):
    NAME = "coverage_audit_check"
    DESCRIPTION = ("Scan RegistryHub provider/consumer graphs and the generated app's "
                    "source tree. Returns dead endpoints / tables / source files.")

    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME, description=self.DESCRIPTION,
            parameters={"type": "object", "properties": {}}, required=[])

    async def execute(self, **_kw) -> ToolResult:
        if self.hub_registry is None or self.app_root is None:
            return ToolResult.fail(
                error_message="coverage_audit_check requires hub_registry + app_root context")
        report = compute_coverage(self.hub_registry, self.app_root)
        return ToolResult.ok(data=report.to_dict())


class MarkIntentionallyDeadTool(_CoverageToolBase):
    NAME = "mark_intentionally_dead"
    DESCRIPTION = ("Whitelist a path (file:X / endpoint:METHOD PATH / table:NAME) "
                    "as intentionally dead with a reason. Used to override the "
                    "coverage gate when a component is behind a feature flag or "
                    "kept for backward compatibility.")

    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME, description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string",
                              "description": "file:..., endpoint:..., or table:..."},
                    "reason": {"type": "string"},
                },
                "required": ["path", "reason"],
            },
            required=["path", "reason"])

    async def execute(self, *, path: str, reason: str, **_kw) -> ToolResult:
        result = self.hub_registry.gate_registry.mark_path_intentionally_dead(
            path=path, reason=reason, agent="orchestrator")
        if isinstance(result, dict) and result.get("error"):
            return ToolResult.fail(error_message=result["error"])
        return ToolResult.ok(data={"entry": result})


class ListDeadAllowlistTool(_CoverageToolBase):
    NAME = "list_dead_allowlist"
    DESCRIPTION = "List all paths currently whitelisted as intentionally dead."

    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME, description=self.DESCRIPTION,
            parameters={"type": "object", "properties": {}}, required=[])

    async def execute(self, **_kw) -> ToolResult:
        entries = self.hub_registry.gate_registry.list_coverage_allowlist()
        return ToolResult.ok(data={"allowlist": entries})


_COVERAGE_TOOLS = [CoverageAuditCheckTool, MarkIntentionallyDeadTool, ListDeadAllowlistTool]


def create_coverage_tools(hub_registry=None, app_root: Optional[str] = None) -> list:
    return [cls(hub_registry=hub_registry, app_root=app_root)
            for cls in _COVERAGE_TOOLS]


__all__ = [
    "CoverageAuditCheckTool", "MarkIntentionallyDeadTool", "ListDeadAllowlistTool",
    "create_coverage_tools",
]
