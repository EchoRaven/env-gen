"""RunHub LLM tools (Cutover 11).

Tools:
  - run_start:   Spin up generated app via docker compose, probe RegistryHub
                 endpoints, publish run_failed events for any failures.
  - run_status:  Summary view of a single run by id.
  - run_list:    Most recent runs (summaries; default limit 20).
  - run_get:     Full run record including all probe results.

All classes follow the existing `HubTool` convention from `tools/hub_tools.py`:
async `_run(...)` returning `ToolResult(data=...)`, accessing hubs via
`self._hubs.<hub>` and identity via `self._agent_id`. `_finalize_hub_tools` is
applied so each class gets a default `execute` wrapper for the agent runtime.
"""

from __future__ import annotations

from typing import Any

from ._base import ToolResult
from .hub_tools import HubTool, _finalize_hub_tools


class RunStartTool(HubTool):
    NAME = "run_start"
    DESCRIPTION = (
        "Spin up the generated app via docker compose, run healthcheck + "
        "HTTP probes against RegistryHub-registered endpoints, publish run_failed "
        "events for any failures. Returns the run summary."
    )
    PARAMETERS = {
        "type": "object",
        "properties": {
            "branch": {"type": "string", "description": "git branch being verified"},
            "generated_dir": {
                "type": "string",
                "description": "Optional — directory containing docker-compose.yml. "
                               "Auto-derived from the env root if omitted.",
            },
            "base_url": {
                "type": "string",
                "description": "base URL the app exposes",
                "default": "http://localhost:8000",
            },
        },
        "required": ["branch"],
    }

    async def _run(self, *, branch: str, generated_dir: str = "",
                   base_url: str = "http://localhost:8000") -> ToolResult:
        try:
            # generated_dir is framework CONTEXT (the env root holding
            # docker-compose.yml), not something the model can know — auto-derive
            # from the shared hub registry's base_dir when omitted (the model
            # called run_start with branch+base_url only → missing-arg crash).
            if not generated_dir:
                generated_dir = str(getattr(self._hubs, "base_dir", "") or "")
            run = self._hubs.runhub.start_run(
                branch=branch,
                generated_dir=generated_dir,
                base_url=base_url,
                agent=self._agent_id,
            )
            return ToolResult(success=True, data={"run": run})
        except Exception as e:
            return ToolResult(success=False, error_message=str(e))


class RunStatusTool(HubTool):
    NAME = "run_status"
    DESCRIPTION = "Get the current status of a run by run_id."
    PARAMETERS = {
        "type": "object",
        "properties": {"run_id": {"type": "string"}},
        "required": ["run_id"],
    }

    async def _run(self, *, run_id: str) -> ToolResult:
        run = self._hubs.runhub.get_run(run_id)
        if not run:
            return ToolResult(success=False, error_message=f"run not found: {run_id}")
        return ToolResult(success=True, data={"run": {
            "id": run["id"],
            "status": run["status"],
            "branch": run.get("branch"),
            "fail_count": run.get("fail_count", 0),
            "started_at": run.get("started_at"),
            "finished_at": run.get("finished_at"),
        }})


class RunListTool(HubTool):
    NAME = "run_list"
    DESCRIPTION = "List most recent runs (default limit 20)."
    PARAMETERS = {
        "type": "object",
        "properties": {"limit": {"type": "integer", "default": 20}},
    }

    async def _run(self, *, limit: int = 20) -> ToolResult:
        runs = self._hubs.runhub.list_runs(limit=limit)
        # Return summaries, not full probe arrays — keep payload small
        summaries = [{
            "id": r["id"],
            "branch": r.get("branch"),
            "status": r.get("status"),
            "fail_count": r.get("fail_count", 0),
            "started_at": r.get("started_at"),
            "finished_at": r.get("finished_at"),
        } for r in runs]
        return ToolResult(success=True, data={"runs": summaries})


class RunGetTool(HubTool):
    NAME = "run_get"
    DESCRIPTION = "Get the full run record (including all probe results) by run_id."
    PARAMETERS = {
        "type": "object",
        "properties": {"run_id": {"type": "string"}},
        "required": ["run_id"],
    }

    async def _run(self, *, run_id: str) -> ToolResult:
        run = self._hubs.runhub.get_run(run_id)
        if not run:
            return ToolResult(success=False, error_message=f"run not found: {run_id}")
        return ToolResult(success=True, data={"run": run})


RUN_TOOL_CLASSES = [RunStartTool, RunStatusTool, RunListTool, RunGetTool]


_finalize_hub_tools(RUN_TOOL_CLASSES)


def create_run_tools(agent_id: str = "", hub_workspace: Any = None) -> list:
    return [cls(agent_id=agent_id, hub_workspace=hub_workspace)
            for cls in RUN_TOOL_CLASSES]


__all__ = [
    "RunStartTool", "RunStatusTool", "RunListTool", "RunGetTool",
    "RUN_TOOL_CLASSES", "create_run_tools",
]
