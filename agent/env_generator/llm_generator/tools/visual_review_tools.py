"""Visual review LLM tools (Cutover 20)."""

from __future__ import annotations

from typing import Any, Optional

from utils.tool import BaseTool, ToolCategory, ToolResult, create_tool_param


class _VisualReviewToolBase(BaseTool):
    def __init__(self, *, hub_registry=None):
        super().__init__(name=self.NAME, category=ToolCategory.KNOWLEDGE)
        self.hub_registry = hub_registry


class RegisterVisualReviewTaskTool(_VisualReviewToolBase):
    NAME = "register_visual_review_task"
    DESCRIPTION = ("Register a UI route for visual review. Frontend agent calls this "
                    "for each route that has a reference image. critical=True for "
                    "routes that must pass visual review before deliver_project().")

    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME, description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "route": {"type": "string"},
                    "screenshot_path": {"type": "string"},
                    "reference_path": {"type": "string"},
                    "critical": {"type": "boolean", "default": True},
                },
                "required": ["route", "screenshot_path", "reference_path"],
            }, required=["route", "screenshot_path", "reference_path"])

    async def execute(self, *, route: str, screenshot_path: str,
                       reference_path: str, critical: bool = True,
                       **_kw) -> ToolResult:
        page = self.hub_registry.gate_registry.register_visual_review_task(
            route=route, screenshot_path=screenshot_path,
            reference_path=reference_path, critical=critical,
            agent=getattr(self, "_agent_id", ""))
        return ToolResult.ok(data={"page": page})


class SubmitVisualReviewTool(_VisualReviewToolBase):
    NAME = "submit_visual_review"
    DESCRIPTION = ("Visual reviewer submits a structured review. For state='approve', "
                    "you MUST supply similarity_score in [0,1] (>=0.75 for critical "
                    "routes), at least 3 substantive deviations (each with "
                    "aspect/expected/actual/severity), and a >=20-char summary.")

    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME, description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "page_id": {"type": "string"},
                    "state": {"type": "string",
                               "enum": ["approve", "needs_revision", "comment"]},
                    "similarity_score": {"type": "number"},
                    "deviations": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "aspect": {"type": "string"},
                                "expected": {"type": "string"},
                                "actual": {"type": "string"},
                                "severity": {"type": "string"},
                            },
                            "required": ["aspect", "expected", "actual", "severity"],
                        },
                    },
                    "summary": {"type": "string"},
                },
                "required": ["page_id", "state"],
            }, required=["page_id", "state"])

    async def execute(self, *, page_id: str, state: str,
                       similarity_score: Optional[float] = None,
                       deviations: Optional[list] = None, summary: str = "",
                       **_kw) -> ToolResult:
        result = self.hub_registry.gate_registry.submit_visual_review(
            page_id=page_id,
            reviewer=getattr(self, "_agent_id", ""),
            state=state, similarity_score=similarity_score,
            deviations=deviations or [], summary=summary)
        if isinstance(result, dict) and result.get("error"):
            return ToolResult.fail(error_message=result["error"])
        return ToolResult.ok(data={"page": result})


class ListPendingVisualReviewsTool(_VisualReviewToolBase):
    NAME = "list_pending_visual_reviews"
    DESCRIPTION = "List visual review tasks awaiting reviewer attention."

    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME, description=self.DESCRIPTION,
            parameters={"type": "object", "properties": {}}, required=[])

    async def execute(self, **_kw) -> ToolResult:
        pending = self.hub_registry.gate_registry.list_pending_visual_reviews()
        out = [{"id": p["id"],
                "route": (p.get("metadata") or {}).get("route"),
                "critical": (p.get("metadata") or {}).get("critical"),
                "screenshot_path": (p.get("metadata") or {}).get("screenshot_path"),
                "reference_path": (p.get("metadata") or {}).get("reference_path")}
               for p in pending]
        return ToolResult.ok(data={"pending": out})


class GetVisualReviewStatusTool(_VisualReviewToolBase):
    NAME = "get_visual_review_status"
    DESCRIPTION = "Get current status of a visual review task by page_id."

    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME, description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {"page_id": {"type": "string"}},
                "required": ["page_id"],
            }, required=["page_id"])

    async def execute(self, *, page_id: str, **_kw) -> ToolResult:
        page = self.hub_registry.gate_registry.get_visual_review(page_id)
        if page is None:
            return ToolResult.fail(
                error_message=f"visual_review page not found: {page_id}")
        meta = page.get("metadata") or {}
        return ToolResult.ok(data={
            "page_id": page_id, "status": page.get("status"),
            "route": meta.get("route"),
            "critical": bool(meta.get("critical")),
            "review_count": len(meta.get("review_history") or []),
            "approved": page.get("status") == "approved",
        })


_VISUAL_TOOLS = [RegisterVisualReviewTaskTool, SubmitVisualReviewTool,
                  ListPendingVisualReviewsTool, GetVisualReviewStatusTool]


def create_visual_review_tools(hub_registry=None) -> list:
    return [cls(hub_registry=hub_registry) for cls in _VISUAL_TOOLS]


__all__ = [
    "RegisterVisualReviewTaskTool", "SubmitVisualReviewTool",
    "ListPendingVisualReviewsTool", "GetVisualReviewStatusTool",
    "create_visual_review_tools",
]
