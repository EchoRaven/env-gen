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


# #1202ln: A DEFAULT PORT IS A GUESS, AND THIS ONE PROBED POSTGRES.
#
# `run_start`'s base_url defaulted to `http://localhost:8000`. The framework assigns each run
# its own FREE host ports, so 8000 belongs to whatever that run happened to get. tiktok-r121
# gave it to the DATABASE:
#
#     docker-compose.yml:  PGPORT: 8000   ports: - "8000:8000"
#     runhub record:       {"status": "aborted", "healthcheck": {
#                            "url": "http://localhost:8000/health", "attempts": 31,
#                            "elapsed_s": 60.8,
#                            "last_error": "Server disconnected without sending a response."}}
#
# That error is Postgres closing an HTTP request it cannot parse -- not a dead backend. The
# run's real API was on 3001 and answering (`GET http://localhost:3001/api/feed -> 200` in the
# same ledger). SEVEN of r121's 25 RunHub runs aborted this way, and the last one did it at
# 00:00:52, ninety seconds after the delivery gate had gone COMPLETELY CLEAR (failed_checks
# []). The orchestrator minted `task_p0_backend_health_abort_after_noop_fix` from it, the gate
# re-opened, and the run died on its wall-clock cap 23 minutes later having delivered nothing.
#
# #207 fixed this exact shape for the visual gate and wrote the rule in `_resolve_app_port`:
# "NEVER a magic fallback (:8080/:3001 host a persistent gmaps demo -- a fixed fallback made
# the visual gate screenshot the WRONG app)". The rule never reached this tool. The tool's own
# docstring for `generated_dir` states the same principle one field above -- "NOT something
# the model can know ... never let a model guess" -- and then leaves base_url to a constant.
_BAD_DEFAULT_BASE_URL_1202LN = "http://localhost:8000"


#: #1202lq: the same resolution, for the FRONTEND. `task_suite_executor` prefixed bare routes
#: with `http://localhost:3000`, which is the frontend's CONTAINER-internal port — from the
#: host it is whatever compose published (r121: 8081, and nothing at all was on 3000).
_BACKEND_SERVICES_1202LN = ("backend", "api", "server", "app")
_FRONTEND_SERVICES_1202LQ = ("frontend", "ui", "web", "client")


def _resolved_base_url_1202ln(generated_dir, services=_BACKEND_SERVICES_1202LN):
    """The run's OWN base URL for `services`, read from its OWN compose file. None if
    unresolvable.

    Reuses `validation_runner._service_host_port` (which carries #962/#1136's guard against
    resolving a *stranger's* container) rather than keeping a second copy -- #665's lesson is
    that the copy drifts, and #1136 WAS that drift.
    """
    try:
        from pathlib import Path as _P
        try:
            from multi_agent.runtime.validation_runner import _service_host_port
        except Exception:
            from env_generator.llm_generator.multi_agent.runtime.validation_runner import (
                _service_host_port)
        root = _P(str(generated_dir or "")).expanduser()
        compose = root / "docker" / "docker-compose.yml"
        if not compose.is_file():
            return None
        for svc in services:
            try:
                port = _service_host_port(compose, compose.parent, svc)
            except Exception:
                port = None
            if port:
                return "http://localhost:%d" % int(port)
        return None
    except Exception:
        return None


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
                "description": "Optional -- the app's base URL. Auto-resolved from this "
                               "run's own docker-compose.yml; leave it out. Host ports are "
                               "assigned per run, so a guessed port can address another "
                               "service entirely (#1202ln).",
            },
        },
        "required": ["branch"],
    }

    async def _run(self, *, branch: str, generated_dir: str = "",
                   base_url: str = "") -> ToolResult:
        try:
            # generated_dir is framework CONTEXT (the env root holding
            # docker-compose.yml), NOT something the model can know — the schema
            # marks it auto-derived. The orchestrator LLM has called run_start
            # both with the arg OMITTED and with a bad GUESS (r75 live: a
            # relative 'app'/'docker' → ComposeLifecycle(cwd=...) →
            # subprocess FileNotFoundError → the run crashes, so the milestone
            # never gets a clean RunHub validation run and delivery falls back
            # to the force_deliver bypass). base_dir is the single authoritative
            # env root for this process, so prefer it whenever the framework has
            # one — never let a model guess (which on a shared box could even
            # name a *different* env's dir) override it. Only honor an explicit
            # value when there is no base_dir to derive from.
            base_dir = str(getattr(self._hubs, "base_dir", "") or "")
            if base_dir:
                generated_dir = base_dir
            # #1202ln: base_url is framework CONTEXT for exactly the reason generated_dir is
            # -- the host port is assigned at compose-generation time and no model can know
            # it. Resolve it from this run's own compose file; a caller-supplied value is
            # honoured ONLY when resolution fails AND it is not the old magic constant.
            _resolved = _resolved_base_url_1202ln(generated_dir)
            if _resolved:
                base_url = _resolved
            elif not base_url or base_url == _BAD_DEFAULT_BASE_URL_1202LN:
                # #207's "skip honestly": probing a port we cannot attribute is worse than
                # not probing. An aborted run that named the wrong service mints a P0 against
                # the lane and re-opens a clear delivery gate -- r121 died that way.
                return ToolResult(
                    success=False,
                    error_message=(
                        "run_start: could not resolve this run's backend host port from "
                        "%s/docker/docker-compose.yml, and will not fall back to a fixed "
                        "port -- host ports are per-run, so :8000 may be this run's DATABASE "
                        "(it was in tiktok-r121, and seven runs aborted probing it). Bring "
                        "the stack up (or pass the port from the compose file) and retry. "
                        "(#1202ln)" % (generated_dir or "<no generated_dir>")))
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
