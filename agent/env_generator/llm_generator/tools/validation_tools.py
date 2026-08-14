"""run_validation — one-call deterministic api_smoke for the verifier (§6).

The verifier used to drive validation as a free-agentic multi-step loop
(docker_up → test_api × N → judge) and stalled before reaching the runtime checks
(smoke #7). This tool is the framework-driven ``[P]`` step: ONE call runs the whole
api_smoke (clean docker boot → backend health → embedded-AS register → every
business endpoint reachable → 401-without-token) and returns a structured verdict.
The verifier's job shrinks to "call run_validation(); record the verdict."

The business contract is read from the LIVE RegistryHub (``self._hubs.registryhub``) — the
same source of truth the rest of the pipeline registers against — wired in via
``set_agent``. A persisted-state fallback (``shared/hubs/registryhub_endpoints.json``)
keeps the tool usable in unit tests where no live registry is attached.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List, Optional

from utils.tool import BaseTool, ToolResult, ToolCategory, create_tool_param
from workspace import Workspace


def _import_lifecycle():
    """Import lifecycle.business_endpoints regardless of which sys.path prefix
    is active (the agent runtime exposes ``multi_agent.*``)."""
    try:
        from multi_agent.runtime.lifecycle import business_endpoints
    except Exception:  # pragma: no cover - alt path
        from env_generator.llm_generator.multi_agent.runtime.lifecycle import business_endpoints
    return business_endpoints


def _import_runner():
    try:
        from multi_agent.runtime.validation_runner import run_smoke_validation
    except Exception:  # pragma: no cover - alt path
        from env_generator.llm_generator.multi_agent.runtime.validation_runner import run_smoke_validation
    return run_smoke_validation


class RunValidationTool(BaseTool):
    NAME = "run_validation"
    DESCRIPTION = """Run the full deterministic api_smoke for the generated env in ONE call.

Brings the env up CLEAN (docker compose down -v && up --build), checks backend
/health, registers a user via the embedded OAuth2 AS, hits every BUSINESS endpoint
(asserting it's reachable / doesn't 5xx), and checks a no-token request returns 401
— then tears the env down. Returns {passed, summary, checks:[{name,status,detail}]}.

Use this as your SINGLE validation action when validation is ready: call it once,
then record the verdict. Do NOT hand-orchestrate docker_up + test_api yourself.
"""

    def __init__(self, *, workspace: Optional[Workspace] = None, agent_id: str = ""):
        super().__init__(name=self.NAME, category=ToolCategory.RUNTIME)
        self.workspace = workspace
        self._agent_id = agent_id
        self._hubs = None  # bound by set_agent

    def set_agent(self, agent) -> None:
        """Bind the live hub registry + caller identity (mirrors HubTool)."""
        self._agent_id = getattr(agent, "agent_id", self._agent_id)
        hubs = getattr(agent, "_hubs", None)
        if hubs is not None:
            self._hubs = hubs

    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME,
            description=self.DESCRIPTION,
            parameters={"type": "object", "properties": {}, "required": []},
        )

    # ---- contract resolution -------------------------------------------------
    def _project_dir(self) -> Optional[Path]:
        """The generated app root: prefer the live hub registry's base_dir."""
        if self._hubs is not None and getattr(self._hubs, "base_dir", None):
            return Path(self._hubs.base_dir)
        if self.workspace is not None and getattr(self.workspace, "base_root", None):
            return Path(self.workspace.base_root)
        return None

    def _live_endpoints(self) -> Optional[dict]:
        """Endpoints map from the LIVE RegistryHub, or None if no registry attached."""
        hubs = self._hubs
        registryhub = getattr(hubs, "registryhub", None) if hubs is not None else None
        if registryhub is None:
            return None
        try:
            return registryhub.get_endpoints()
        except Exception:
            return None

    def _persisted_endpoints(self, project_dir: Path) -> dict:
        """Fallback: endpoints map from persisted RegistryHub JsonStore (tests)."""
        eps_file = project_dir / "shared" / "hubs" / "registryhub_endpoints.json"
        try:
            raw = json.loads(eps_file.read_text(encoding="utf-8"))
        except Exception:
            return {}
        if not isinstance(raw, dict):
            return {}
        # JsonStore shape: {"_meta": {...}, "<id>": <endpoint>, ...}
        return {k: v for k, v in raw.items() if k != "_meta" and isinstance(v, dict)}

    def _business_endpoints(self, project_dir: Path) -> List[dict]:
        business_endpoints = _import_lifecycle()
        eps = self._live_endpoints()
        if eps is None:
            eps = self._persisted_endpoints(project_dir)
        return [e for e in business_endpoints(eps or {}) if e.get("path")]

    # ---- execution -----------------------------------------------------------
    async def execute(self) -> ToolResult:
        project_dir = self._project_dir()
        if project_dir is None:
            return ToolResult.fail(
                "run_validation: no project directory resolved (no live hub registry "
                "and no workspace). Cannot locate the generated env to validate."
            )
        # TOOL-LEVEL PRECONDITION (round 35 behavioral fix): the verifier's
        # cheapest path is "call run_validation, record, finish" — prompt text
        # asking it to author chains FIRST lost to that imperative in 3
        # straight runs (round 35 needed 20 re-nudges). Make the dependency a
        # WALL: validation refuses to run until the chains file exists, so
        # the lazy path IS the correct path.
        from multi_agent.runtime.chain_executor import (
            AUTHORING_INSTRUCTIONS, load_verifier_chains)
        if not load_verifier_chains(project_dir):
            return ToolResult.fail(
                "run_validation BLOCKED: no verification chains registered. "
                "Register them FIRST via registryhub_register_verification_chain "
                "(one call per chain), then call run_validation again. "
                + AUTHORING_INSTRUCTIONS,
                not_ready=True,
            )
        biz = self._business_endpoints(project_dir)
        if not biz:
            return ToolResult.fail(
                "run_validation: no business endpoints registered yet — the backend "
                "contract is not ready. Defer and retry once endpoints are implemented.",
                not_ready=True,
            )
        run_smoke_validation = _import_runner()
        # Leave the env UP: the verifier's downstream ui_smoke/ui_flow + release
        # checks (and the orchestrator's delivery probe) run against the SAME
        # running env. The clean boot (down -v && up) at the runner's start is
        # what guarantees freshness — teardown is the orchestrator's job at the end.
        report = run_smoke_validation(project_dir, biz, teardown=False)
        # §0.5 framework consequence: the verifier's api_smoke evidence (one
        # registryhub_record_contract_test per endpoint, which the delivery gate +
        # integrity check audit) is a deterministic CONSEQUENCE of this one call,
        # not a hand-driven per-endpoint loop the LLM has to remember to run.
        recorded = self._record_contract_tests(report.get("endpoints") or [])
        # §6/§7 framework-driven delivery evidence: run_validation IS a real
        # validation run (clean docker boot + a live probe of every endpoint), so
        # it ALSO records a RunHub run — the canonical evidence the delivery gate
        # audits (compute_deliverability blocker #1: "no successful RunHub run").
        # The orchestrator already runs run_validation (the verifier LLM drifts
        # and won't), so this is what actually lets a healthy app reach delivery.
        runhub_run_id = self._record_runhub_run(report, project_dir)
        # The delivery gate's verification checklist keys on four build:* CodeHub
        # checks (delivery_gate.py: build:{database,docker,frontend,backend}). The
        # framework never recorded them — the verifier was expected to (its prompt
        # even falsely claimed they auto-record) and drifts / records the wrong
        # names / stops after one → checklist stuck "not ready" forever even on a
        # healthy app (smoke run #7: reached delivery, only build:frontend recorded).
        # run_validation OWNS the per-service docker-up + health outcome, so record
        # them deterministically here (failure self-corrects: a broken build keeps
        # the gate honestly blocked).
        self._record_build_checks(report)
        self._record_frontend_build_check(report)
        self._record_chain_status(report)
        self._record_api_smoke_check(report)
        data = {
            "passed": report["passed"],
            "summary": report["summary"],
            "checks": report["checks"],
            "backend_port": report.get("backend_port"),
            "endpoints_tested": len(biz),
            "contract_tests_recorded": recorded,
            "runhub_run_id": runhub_run_id,
        }
        # A FAIL is a real, actionable verdict (not a tool error) — surface it as
        # data so the verifier records it + routes the fix to the owning lane.
        if not report["passed"]:
            data["verdict"] = "fail"
        return ToolResult.ok(data=data)

    def _record_contract_tests(self, endpoint_results: List[dict]) -> int:
        """Emit one registryhub_record_contract_test per probed endpoint. Recorded
        with FRAMEWORK authority (``agent=""`` → the role-gate's system
        fallthrough) because run_validation is a deterministic framework
        procedure whose probes are REAL — so the evidence lands whether the
        verifier OR the orchestrator invoked it (the verifier LLM drifts and
        won't; the orchestrator does). Best-effort: never fails the verdict."""
        hubs = self._hubs
        registryhub = getattr(hubs, "registryhub", None) if hubs is not None else None
        if registryhub is None or not hasattr(registryhub, "record_api_test"):
            return 0
        n = 0
        for er in endpoint_results:
            ep_id = er.get("id")
            if not ep_id:
                continue
            # ``passed`` is the GATE verdict (reachable AND implemented-when-
            # claimed, GATE-C1); ``reachable`` alone is just the transport fact
            # and recorded 404s on registered-implemented endpoints as pass.
            passed = bool(er.get("passed", er.get("reachable")))
            try:
                registryhub.record_api_test(
                    ep_id,
                    result={"passed": passed, "verdict": "pass" if passed else "fail",
                            "status_code": er.get("status_code")},
                    evidence={"trace": er.get("trace"), "status_code": er.get("status_code"),
                              "source": "run_validation", "error": er.get("error")},
                    agent="",  # framework/system authority (see docstring)
                )
                n += 1
            except Exception:
                continue
        return n

    def _record_chain_status(self, report: dict) -> int:
        """Sync each verification chain's pass/fail verdict back through the LIVE
        registryhub so it reaches the MAIN registry the DELIVERY GATE reads.

        ROOT CAUSE (run v20): the business_chain delivery gate is FLAG-BASED — it
        blocks unless every authored chain's registry ``status == "passing"``
        (delivery_gate.evaluate_business_chains). That status is set by
        chain_executor.run_chains via a DIRECT JsonStore write to the caller's
        ``project_dir`` hub file. But validation resolves project_dir from
        ``self._hubs.base_dir`` — when the verifier (or any lane) runs validation
        inside its OWN WORKTREE, the status write lands in the worktree's hub file,
        NOT the shared registry the orchestrator's gate audits. register_verification_chain
        (a synced hub write) put the chains in the MAIN registry as ``registered``;
        the run-pass status never propagated there → the chains PASS live yet the gate
        sees stale ``registered`` forever → business_chain_failing deadlocks delivery
        (v20: 3 chains pass 15/15, gate red 78min → no-convergence abort).

        Fix: route the verdict through the live registryhub (record_chain_result),
        exactly like _record_contract_tests / _record_build_checks route their
        evidence — framework authority (agent=''), best-effort, never affects the
        verdict. The gate's verdict is thus grounded in ACTUAL chain execution
        against the validated app, not a flag that silently diverges by worktree."""
        hubs = self._hubs
        registryhub = getattr(hubs, "registryhub", None) if hubs is not None else None
        if registryhub is None or not hasattr(registryhub, "record_chain_result"):
            return 0
        n = 0
        for ch in (report.get("chains") or []):
            name = ch.get("name") if isinstance(ch, dict) else None
            if not name:
                continue
            try:
                registryhub.record_chain_result(
                    str(name),
                    result={"broken": ch.get("broken") or [],
                            "steps": ch.get("steps") or []},
                    agent="",  # framework/system authority (see docstring)
                )
                n += 1
            except Exception:
                continue
        return n

    def _record_build_checks(self, report: dict) -> int:
        """Record the four ``build:*`` CodeHub checks the delivery-gate verification
        checklist keys on, derived from run_validation's OWN docker-up + health
        outcome (not the verifier's error-prone manual recording). Framework
        authority (``agent=""`` → CodeHub's system fallthrough); best-effort, never
        affects the verdict. Component map matches delivery_gate's checklist:
        build:docker←docker_up, build:backend←backend_health,
        build:frontend←frontend_reachable, build:database←business_writes_persist."""
        hubs = self._hubs
        codehub = getattr(hubs, "codehub", None) if hubs is not None else None
        if codehub is None or not hasattr(codehub, "record_check"):
            return 0
        by_name = {c.get("name"): (c.get("status") == "pass")
                   for c in (report.get("checks") or []) if c.get("name")}
        docker_ok = by_name.get("docker_up", False)
        mapping = {
            "build:docker": docker_ok,
            "build:backend": by_name.get("backend_health", docker_ok),
            "build:frontend": by_name.get("frontend_reachable", docker_ok),
            "build:database": by_name.get("business_writes_persist", docker_ok),
        }
        n = 0
        for name, ok in mapping.items():
            try:
                codehub.record_check(
                    pr_id="main", name=name,
                    status="success" if ok else "failure",
                    evidence={"source": "run_validation"}, agent="")
                n += 1
            except Exception:
                continue
        return n

    def _record_api_smoke_check(self, report: dict) -> int:
        """FIX #286 (tiktok r68/r70/r71, live): the delivery gate's api_smoke_pass keys on a
        validation record with ``status=passed`` and ``metadata.check='api_smoke'`` — but
        run_validation only recorded per-endpoint contract_tests (status='recorded') + a RunHub
        run, NEVER that record. So a healthy app that passed api_smoke still tripped
        ``validation_api_smoke_missing``, the verifier was expected to hand-write the record
        (its prompt even claims it auto-records), it drifts, and the run idled through both
        converging-grace windows to fail-fast — on three separate runs. api_smoke IS this call's
        own deterministic outcome, exactly like the contract_tests/build/runhub it already
        records; emit the gate's record too. Framework authority (agent=''); best-effort, never
        affects the verdict. (ui_smoke stays the verifier's browser job — run_validation is
        api-only and does not probe the UI.)"""
        hubs = self._hubs
        codehub = getattr(hubs, "codehub", None) if hubs is not None else None
        if codehub is None or not hasattr(codehub, "record_check"):
            return 0
        try:
            codehub.record_check(
                pr_id="main", name="validation:api_smoke",
                status="success" if report.get("passed") else "failure",
                evidence={"check": "api_smoke", "source": "run_validation",
                          "summary": str(report.get("summary") or "")[:300]},
                agent="")
            return 1
        except Exception:
            return 0

    def _record_frontend_build_check(self, report: dict) -> int:
        """Sibling of FIX #286 for the FRONTEND BUILD. ``validate_build_evidence``
        (delivery_gate) keys on a validation record with ``metadata.check ==
        'frontend_build'``, but the only frontend-build evidence written was a CodeHub
        ``build:frontend`` check with NO ``check`` field — so the gate stayed blind and
        raised ``frontend_build_not_recorded`` even on an app whose frontend built and
        served (netflix r1). run_validation's own docker-up IS that evidence; emit the
        gate's record too. Framework authority (agent=''); best-effort, never affects
        the verdict."""
        hubs = self._hubs
        codehub = getattr(hubs, "codehub", None) if hubs is not None else None
        if codehub is None or not hasattr(codehub, "record_check"):
            return 0
        by_name = {c.get("name"): (c.get("status") == "pass")
                   for c in (report.get("checks") or []) if c.get("name")}
        fe_ok = by_name.get("frontend_reachable", by_name.get("docker_up", False))
        try:
            codehub.record_check(
                pr_id="main", name="validation:frontend_build",
                status="success" if fe_ok else "failure",
                evidence={"check": "frontend_build", "source": "run_validation",
                          "summary": "frontend container built + reachable"
                                     if fe_ok else "frontend not reachable"},
                agent="")
            return 1
        except Exception:
            return 0

    def _record_runhub_run(self, report: dict, project_dir) -> Optional[str]:
        """Record a RunHub run from this validation's live endpoint probes —
        the canonical evidence ``compute_deliverability`` audits (blocker #1:
        "no successful RunHub run since session start; ... fail_count==0").

        run_validation already did a clean docker boot + a real HTTP probe of
        every business endpoint, so this is a genuine run, recorded with
        framework authority (``agent=""`` → RunHub's system fallthrough; NOT an
        agent fabricating evidence — the probes are real). ``fail_count`` is the
        count of endpoints whose probe verdict failed (unreachable, or 404/405 on
        a registered-implemented route — GATE-C1), so a stale/broken app records
        a run that the gate still rejects. Best-effort: never raises."""
        hubs = self._hubs
        runhub = getattr(hubs, "runhub", None) if hubs is not None else None
        eps = report.get("endpoints") or []
        if runhub is None or not hasattr(runhub, "record_run") or not eps:
            return None
        # Only a clean api_smoke (health + auth ok) should record a completed
        # run — else the partial endpoint list could understate failures.
        if not report.get("passed"):
            return None
        try:
            branch = "integration"
            ch = getattr(hubs, "codehub", None)
            if ch is not None and hasattr(ch, "current_branch"):
                try:
                    branch = ch.current_branch() or branch
                except Exception:
                    pass
            run = runhub.record_run(branch=branch, generated_dir=str(project_dir), agent="")
            run_id = run.get("id")
            fails = 0
            for er in eps:
                ok = bool(er.get("passed", er.get("reachable")))
                if not ok:
                    fails += 1
                runhub.record_probe(run_id, {
                    "verdict": "pass" if ok else "fail",
                    "endpoint_id": er.get("id"),
                    "method": er.get("method"),
                    "path": er.get("path"),
                    "status_code": er.get("status_code"),
                    "body_excerpt": (str(er.get("trace") or ""))[:256],
                    "transport_error": er.get("error"),
                    "latency_ms": 0.0,
                }, agent="")
            runhub.update_run_status(run_id, "completed", agent="", fail_count=fails)
            return run_id
        except Exception:
            return None


def create_validation_tools(workspace: Optional[Workspace] = None) -> List[BaseTool]:
    """Factory for the framework-driven validation tool(s)."""
    return [RunValidationTool(workspace=workspace)]


__all__ = ["RunValidationTool", "create_validation_tools"]
