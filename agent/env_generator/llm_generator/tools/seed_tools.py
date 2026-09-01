"""Seed data LLM tools (Cutover 21)."""

from __future__ import annotations

from typing import Any, List, Optional

from utils.tool import BaseTool, ToolCategory, ToolResult, create_tool_param

from multi_agent.runtime.seed_audit import audit_seed_data


def _project_dir_1202q(hub_registry):
    """The project root, so the seed audit can do its LIVE row count. (#1202q)

    Both agent-facing seed tools called `audit_seed_data(hub_registry)` with no project_dir,
    and without one the live path cannot even find the compose file — so an agent asking
    "audit the seeds" always got the fallback filter instead, which is
    `status == "defined"` and, per this module's own comment, "examines 0 tables in 145 of
    147 runs" and "skips 1729 of 1745 corpus tables".

    Measured across r22-r26 and r30: the live row count has succeeded ZERO times in any run,
    while `SEED AUDIT EXAMINED 0 OF N TABLES` fires 40-156 times per run. r26 shipped on that
    silence: its seed declares 8 `continue_watching` rows and its delivered database holds 1,
    because the child rows reference `profile_id: 1` while the parents were inserted with
    fresh ids (26-30). Nothing looked, so nothing said so.

    `HubRegistry.base_dir` is that root. Best-effort: an audit must not raise.
    """
    try:
        return getattr(hub_registry, "base_dir", None)
    except Exception:
        return None


class _SeedToolBase(BaseTool):
    def __init__(self, *, hub_registry=None):
        super().__init__(name=self.NAME, category=ToolCategory.KNOWLEDGE)
        self.hub_registry = hub_registry


class RegisterSeedDataTool(_SeedToolBase):
    NAME = "register_seed_data"
    DESCRIPTION = ("Backend agent (or its database_worker spawn) records "
                    "that a table has been seeded. row_count must be the "
                    "actual row count after seeding. sample_excerpt "
                    "provides 1-3 representative rows for placeholder-"
                    "quality detection.")

    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME, description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "table_name": {"type": "string"},
                    "row_count": {"type": "integer", "minimum": 0},
                    "sample_excerpt": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "1-3 representative seeded rows",
                    },
                },
                "required": ["table_name", "row_count", "sample_excerpt"],
            }, required=["table_name", "row_count", "sample_excerpt"])

    async def execute(self, *, table_name: str, row_count: int,
                       sample_excerpt: list, **_kw) -> ToolResult:
        record = self.hub_registry.schema_hub.register_seed_data(
            table_name=table_name, row_count=row_count,
            sample_excerpt=sample_excerpt,
            agent=getattr(self, "_agent_id", ""))
        if isinstance(record, dict) and record.get("error"):
            return ToolResult.fail(error_message=record["error"])
        return ToolResult.ok(data={"record": record})


class SeedAuditCheckTool(_SeedToolBase):
    NAME = "seed_audit_check"
    DESCRIPTION = ("Audit seed data coverage across all registered tables. "
                    "Returns flagged tables with reasons (missing_seed | "
                    "low_row_count | placeholder_content) and details.")

    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME, description=self.DESCRIPTION,
            parameters={"type": "object", "properties": {}}, required=[])

    async def execute(self, **_kw) -> ToolResult:
        report = audit_seed_data(self.hub_registry, _project_dir_1202q(self.hub_registry))
        return ToolResult.ok(data=report.to_dict())


class ListSeedIssuesTool(_SeedToolBase):
    NAME = "list_seed_issues"
    DESCRIPTION = ("List current seed issues with table+reason pairs. "
                    "Convenience over seed_audit_check for the orchestrator's "
                    "deliver-readiness checklist.")

    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME, description=self.DESCRIPTION,
            parameters={"type": "object", "properties": {}}, required=[])

    async def execute(self, **_kw) -> ToolResult:
        report = audit_seed_data(self.hub_registry, _project_dir_1202q(self.hub_registry))
        issues = [
            {"table": f["table"], "reason": f["reason"], "detail": f["detail"]}
            for f in report.flagged_tables
        ]
        return ToolResult.ok(data={"issues": issues, "count": len(issues)})


_SEED_TOOLS = [RegisterSeedDataTool, SeedAuditCheckTool, ListSeedIssuesTool]


def create_seed_tools(hub_registry=None) -> list:
    return [cls(hub_registry=hub_registry) for cls in _SEED_TOOLS]


__all__ = ["RegisterSeedDataTool", "SeedAuditCheckTool", "ListSeedIssuesTool",
            "create_seed_tools"]
