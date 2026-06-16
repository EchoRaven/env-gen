"""Design-page LLM tools.

Tools:
  - design_get_status:           Downstream agents check design status before acting

The submit_for_review / submit_review / list_pending_review tools were
retired on 2026-06-02 along with the GateRegistry methods that backed
them. Design approval is now decided in the orchestrator-hosted
kickoff meeting (see ``multi_agent/runtime/kickoff/`` and
``docs/pipeline_supervision_charter.md`` §kickoff). ``design_get_status``
remains so downstream agents (backend/database/frontend) can read the
status of a design page before starting work.

All classes follow the existing `HubTool` convention from `tools/hub_tools.py`:
async `_run(...)` returning `ToolResult(data=...)`, accessing hubs via
`self._hubs.<hub>` and identity via `self._agent_id`. `_finalize_hub_tools` is
applied so each class gets a default `execute` wrapper for the agent runtime.
"""

from __future__ import annotations

from typing import Any

from ._base import ToolResult
from .hub_tools import HubTool, _finalize_hub_tools


class DesignGetStatusTool(HubTool):
    NAME = "design_get_status"
    DESCRIPTION = (
        "Get the current status of a design page. Used by downstream agents "
        "(backend/database/frontend) BEFORE starting work: refuse if not "
        "'approved'."
    )
    PARAMETERS = {
        "type": "object",
        "properties": {"page_id": {"type": "string"}},
        "required": ["page_id"],
    }

    async def _run(self, *, page_id: str) -> ToolResult:
        page = self._hubs.gate_registry.get_design_page(page_id)
        if page is None:
            return ToolResult(
                success=False,
                error_message=f"design page not found: {page_id}",
            )
        return ToolResult(success=True, data={
            "page_id": page_id,
            "status": page.get("status"),
            "approved": page.get("status") == "approved",
            "review_count": len(
                (page.get("metadata") or {}).get("review_history") or []
            ),
        })


DESIGN_TOOL_CLASSES = [
    DesignGetStatusTool,
]


_finalize_hub_tools(DESIGN_TOOL_CLASSES)


def create_design_tools(agent_id: str = "", hub_workspace: Any = None) -> list:
    return [cls(agent_id=agent_id, hub_workspace=hub_workspace)
            for cls in DESIGN_TOOL_CLASSES]


__all__ = [
    "DesignGetStatusTool",
    "DESIGN_TOOL_CLASSES", "create_design_tools",
]
