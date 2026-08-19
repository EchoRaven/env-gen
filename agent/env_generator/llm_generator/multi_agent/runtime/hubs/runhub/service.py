"""RunHub service - 5th hub. Tracks app run sessions and emits run events.

This file holds the persistence + lifecycle bookkeeping; `start_run` (the
docker-compose + probe orchestration) is added in Task 5.
"""

from __future__ import annotations

import logging
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from .stores import RunHubStores

_logger = logging.getLogger(__name__)


_VALID_STATUSES = (
    "starting", "starting_compose", "healthy", "probing",
    "failed", "aborted", "completed",
)


def _resolve_compose_file(generated_dir: str) -> Optional[str]:
    """#293 — locate the generated compose file under an env root.

    The generated compose lives at ``<env_root>/docker/docker-compose.yml``
    (the framework-wide convention: validation_runner, visual_fidelity,
    heal_pipeline and docker_tools all invoke ``docker compose -f
    <env_root>/docker/docker-compose.yml``). ``start_run`` previously built
    ``ComposeLifecycle(cwd=env_root)`` with ``compose_file=None`` → ``docker
    compose up`` ran in the ROOT, where there is no compose file → every run
    aborted with ``"no configuration file provided"`` (r76 live: 16/16 aborted,
    0 successful → hard deadlock). Search docker/ first, then a root compose,
    mirroring docker_tools' order. Returns None if none exists (caller keeps
    the cwd-relative behaviour rather than inventing a path)."""
    root = Path(generated_dir)
    candidates = (
        root / "docker" / "docker-compose.yml",
        root / "docker" / "docker-compose.dev.yml",
        root / "docker-compose.yml",
        root / "docker-compose.yaml",
    )
    for c in candidates:
        try:
            if c.exists():
                # #754: ABSOLUTE, because the caller hands this to a subprocess whose cwd is
                # `generated_dir`, not ours. When `generated_dir` arrives relative — and some
                # call paths pass it that way — `exists()` succeeds here (evaluated against OUR
                # cwd, repo/agent) and the very same string is then unresolvable in the child.
                # The failure is not "no compose file", it is a path checked in one directory
                # and used in another, and it reads as the former:
                #
                #   compose up FAILED (rc=1) — Cause: CRITICAL:podman_compose:missing files:
                #   ['generated/netflix-web-r149/docker/docker-compose.yml']
                #
                # while `agent/generated/netflix-web-r149/docker/docker-compose.yml` is right
                # there, 3464 bytes. r149 hit it 5 times; the corpus holds 216 recorded boot
                # failures and none of them said why until #748 started logging the cause —
                # this is the first defect that finding paid for.
                return str(c.resolve())
        except OSError:
            continue
    return None


class RunHub:
    def __init__(self, hub_dir: Path, eventhub: Any = None):
        self.hub_dir = Path(hub_dir)
        self.hub_dir.mkdir(parents=True, exist_ok=True)
        self.stores = RunHubStores.create(self.hub_dir)
        self.eventhub = eventhub
        self.registryhub: Any = None  # attached by HubRegistry
        # PR 4 (hub-responsibility-split plan, rank 4): MCP surface
        # moved out of RegistryHub; RunHub queries it directly.
        self.mcp_registry: Any = None  # attached by HubRegistry

    def attach_registryhub(self, registryhub: Any) -> None:
        self.registryhub = registryhub

    def attach_mcp_registry(self, mcp_registry: Any) -> None:
        self.mcp_registry = mcp_registry

    # ------------------------------------------------------------------ #
    # Persistence
    # ------------------------------------------------------------------ #

    # Phase 0.3 INERT anchor — Phase 2.5 agent-vs-runtime write split.
    #
    # The Phase 2.5 plan (docs/progressive_elaboration_refactor.md
    # lines 1340-1342) requires that probe records only be authored by
    # the runtime, not by agents. ``record_probe`` is installed today
    # as the canonical entry point so the Phase 2.5 mechanism PR can
    # add the ``agent != 'runhub'`` denial in the >= 2.5 branch without
    # touching the call sites again.
    def record_probe(
        self,
        run_id: str,
        probe: dict,
        *,
        agent: str = "",
    ) -> dict:
        """Append a probe record to ``run_id``.

        Pre-Phase-2.5 (default unset OR phase < 2.5): any caller may
        append.

        Only the RunHub runtime itself may write probe records —
        ``agent != 'runhub'`` is rejected with PermissionError. This
        closes the agent-fabricates-evidence attack surface. Empty
        agent ('' / None) falls through (system / test paths); only
        EXPLICIT non-runhub actors raise.
        """
        from ..._role_gate import require_runtime_actor
        require_runtime_actor(
            method_name="record_probe",
            agent=agent,
            runtime_name="runhub",
            target_label="RunHub.record_probe",
            error_extra=(
                "agents cannot author probe records directly — RunHub "
                "runs the probe and writes the record itself. Trigger a "
                "probe via run_start instead of recording one."
            ),
        )
        run = self.stores.runs.get(run_id)
        if not run:
            raise ValueError(f"run not found: {run_id}")
        probes = list(run.get("probes") or [])
        probes.append(dict(probe))
        actor = agent or "runhub"
        return self.update_run_status(
            run_id,
            run.get("status", "probing"),
            agent=actor,
            probes=probes,
        )

    def record_run(self, branch: str, generated_dir: str, agent: str = "") -> dict:
        now = time.time()
        run_id = f"run_{uuid.uuid4().hex[:10]}"
        run = {
            "id": run_id,
            "branch": branch,
            "generated_dir": str(generated_dir),
            "status": "starting",
            "started_at": now,
            "updated_at": now,
            "finished_at": None,
            "healthcheck": None,
            "probes": [],
            "fail_count": 0,
            "started_by": agent,
        }
        self.stores.runs.update(lambda m: m.set(run_id, run, agent),
                                 change_info={"agent": agent})
        return run

    def update_run_status(self, run_id: str, status: str, agent: str = "",
                           **field_updates) -> dict:
        if status not in _VALID_STATUSES:
            raise ValueError(f"invalid status: {status!r}")
        run = self.stores.runs.get(run_id)
        if not run:
            raise ValueError(f"run not found: {run_id}")
        updated = dict(run)
        updated["status"] = status
        updated["updated_at"] = time.time()
        if status in ("failed", "aborted", "completed"):
            updated["finished_at"] = updated["updated_at"]
        for k, v in field_updates.items():
            updated[k] = v
        self.stores.runs.update(lambda m: m.set(run_id, updated, agent),
                                 change_info={"agent": agent})
        return updated

    def get_run(self, run_id: str) -> Optional[dict]:
        return self.stores.runs.get(run_id)

    def list_runs(self, limit: int = 50) -> List[dict]:
        runs = list((self.stores.runs.value() or {}).values())
        runs.sort(key=lambda r: r.get("started_at", 0.0), reverse=True)
        return runs[:limit]

    def last_successful_run_since(self, since_ts: float) -> Optional[dict]:
        """Return the most recent run that:
        - was started at or after since_ts
        - finished with status="completed" AND fail_count==0
        Returns None if no qualifying run exists.
        """
        runs = self.list_runs(limit=1000)
        qualifying = []
        for r in runs:
            if r.get("status") != "completed":
                continue
            if r.get("fail_count", 0) != 0:
                continue
            if r.get("started_at", 0.0) < since_ts:
                continue
            qualifying.append(r)
        if not qualifying:
            return None
        # list_runs returns most-recent-first, so first matching is latest
        return qualifying[0]

    # ------------------------------------------------------------------ #
    # Versions / snapshot (HubRegistry interface)
    # ------------------------------------------------------------------ #

    def get_versions(self) -> Dict[str, int]:
        return self.stores.versions()

    def snapshot(self) -> Dict[str, Any]:
        return self.stores.snapshot()

    # ------------------------------------------------------------------ #
    # Orchestration
    # ------------------------------------------------------------------ #

    def start_run(self, *,
                   branch: str,
                   generated_dir: str,
                   base_url: str,
                   agent: str = "",
                   compose: Any = None,
                   healthcheck: Any = None,
                   probe_runner: Any = None,
                   mcp_stdio_probe: Any = None,
                   mcp_http_probe: Any = None,
                   timeout_s: int = 300) -> dict:
        from .probes import plan_probe, classify_probe_result, ProbePlan, ProbeSkip
        from .compose import ComposeLifecycle, HealthcheckProbe

        run = self.record_run(branch=branch, generated_dir=generated_dir, agent=agent)
        run_id = run["id"]

        # #754: resolve the cwd too. Leaving it relative works only while the parent's cwd
        # happens to be the one it was built against, which is exactly the coupling that made
        # the compose path fail — same bug, one argument over.
        try:
            _gd754 = str(Path(generated_dir).resolve())
        except Exception:
            _gd754 = str(generated_dir)
        compose = compose or ComposeLifecycle(
            cwd=_gd754,
            compose_file=_resolve_compose_file(_gd754))
        healthcheck = healthcheck or HealthcheckProbe(
            url=base_url.rstrip("/") + "/health", poll_interval_s=2.0, timeout_s=60.0)
        probe_runner = probe_runner or self._default_probe_runner()

        probes: list = []
        fail_count = 0

        try:
            # Stage 1: compose up. FIX #113: `up` implicit-builds when images are
            # missing — re-stage design assets first so a lane checkout window that
            # dropped tracked public/assets/ files can't bake an asset-less image.
            try:
                from ...frontend_scaffold import ensure_assets_staged_for_build
                ensure_assets_staged_for_build(generated_dir)
            except Exception:
                pass
            self.update_run_status(run_id, "starting_compose", agent="runhub")
            up_result = compose.up()
            if up_result.returncode != 0:
                # #748: THE REASON WAS CAPTURED AND WITHHELD. `compose_stderr` was written to
                # the run record here and read NOWHERE — one writer, zero readers, across the
                # whole tree. It is not empty filler: 216 records in the corpus carry it and
                # **all 216 are non-empty**, holding the actual cause
                # ("CRITICAL:podman_compose:missing files: ['…/docker/docker-compose.yml']").
                # Meanwhile the EVENT that everyone downstream reacts to carried the bare label
                # `compose_up_failed`, so the orchestrator and the lanes were told the app would
                # not boot and not why. Same shape as #677 (1778 bare "Connection refused"),
                # #690 and #740: the diagnosis exists at the moment of failure and is kept from
                # the party that has to act on it. Log it and put it in the event; the store
                # write is unchanged.
                _stderr748 = (up_result.stderr or "").strip()
                self.update_run_status(run_id, "aborted", agent="runhub",
                                        compose_stderr=_stderr748[:500])
                _logger.warning(
                    "compose up FAILED for run %s (rc=%s) — the app never booted, so every "
                    "check after this is measuring nothing. Cause: %s",
                    run_id, up_result.returncode,
                    _stderr748[:400] or "(compose produced no stderr — check the compose file "
                                        "exists and the daemon is reachable)")
                self._emit("run_completed", run_id,
                           {"reason": "compose_up_failed",
                            # #748: the payload carries the cause, not just the label.
                            "compose_stderr": _stderr748[:500],
                            "returncode": up_result.returncode},
                            priority="high")
                return self.get_run(run_id)

            # Stage 2: healthcheck
            hc_result = healthcheck.wait()
            self.update_run_status(run_id, "healthy" if hc_result.healthy else "aborted",
                                    agent="runhub",
                                    healthcheck={
                                        "healthy": hc_result.healthy,
                                        "status_code": hc_result.status_code,
                                        "attempts": hc_result.attempts,
                                        "elapsed_s": hc_result.elapsed_s,
                                        "last_error": hc_result.last_error,
                                    })
            if not hc_result.healthy:
                self._emit("run_completed", run_id, {"reason": "healthcheck_failed"},
                            priority="high")
                return self.get_run(run_id)

            # Stage 3: probe
            self.update_run_status(run_id, "probing", agent="runhub")
            endpoints = self._list_registryhub_endpoints()
            for ep in endpoints:
                plan_or_skip = plan_probe(ep, base_url=base_url)
                if isinstance(plan_or_skip, ProbeSkip):
                    probes.append({
                        "method": ep.get("method"), "path": ep.get("path"),
                        "verdict": "skipped", "reason": plan_or_skip.reason,
                    })
                    continue
                plan = plan_or_skip
                raw = probe_runner(plan)
                outcome = classify_probe_result(
                    status_code=raw.get("status_code"),
                    body_excerpt=raw.get("body_excerpt", ""),
                    auth_required=bool(ep.get("auth_required")),
                    transport_error=raw.get("transport_error"),
                    # #1001: hand over the headers #1000 preserved. Without this the
                    # classifier cannot quote `Allow` and a 405 stays "unexpected status".
                    headers=raw.get("headers"),
                )
                probe_record = {
                    "method": plan.method, "path": ep.get("path"), "url": plan.url,
                    "verdict": outcome.verdict, "severity": outcome.severity,
                    "note": outcome.note,
                    "status_code": raw.get("status_code"),
                    "transport_error": raw.get("transport_error"),
                    "latency_ms": raw.get("latency_ms"),
                }
                # Phase 2.5 evidence-bound probe record extension.
                # docs/progressive_elaboration_refactor.md lines
                # 1308-1313 require probe records to carry their own
                # evidence (body_excerpt + duration_ms + screenshot
                # path + row_count + ssim_score, where applicable) so
                # the delivery gate can audit each probe directly
                # rather than trusting an agent's summary.
                #
                # Pre-Phase-2.5: bare probe record (method/path/url/
                # verdict/severity/note/status_code/transport_error/
                # latency_ms). Byte-identical to v0.x.
                #
                # body_excerpt truncated to 256B (safe for downstream
                # JSON serialization + gate inspection). latency_ms is
                # already in record. screenshot/row_count/ssim_score
                # populated only for UI/DB-specific probes — out of
                # scope for the generic endpoint-probe path.
                body_raw = raw.get("body_excerpt", "")
                body_str = str(body_raw or "")
                if len(body_str) > 256:
                    body_str = body_str[:256]
                probe_record["body_excerpt"] = body_str
                probes.append(probe_record)
                if outcome.verdict == "fail":
                    fail_count += 1
                    self._publish_run_failed(run_id, branch, plan, ep, raw, outcome)

            # Cutover 22: MCP server probes
            mcp_probes: list = []
            mcp_stdio = mcp_stdio_probe or self._default_mcp_stdio_probe()
            mcp_http = mcp_http_probe or self._default_mcp_http_probe()
            mcp_servers = self._list_registryhub_mcp_servers()
            for server in mcp_servers:
                transport = server.get("transport") or "stdio"
                verdict_record = {
                    "server": server["name"],
                    "transport": transport,
                    "endpoint": server.get("endpoint"),
                    "provider": server.get("provider"),
                }
                if transport == "websocket":
                    verdict_record["verdict"] = "skipped"
                    verdict_record["reason"] = "websocket_not_supported"
                    mcp_probes.append(verdict_record)
                    continue
                if transport == "stdio":
                    raw = mcp_stdio(server)
                elif transport in ("http", "sse"):
                    raw = mcp_http(server)
                else:
                    verdict_record["verdict"] = "skipped"
                    verdict_record["reason"] = f"unknown_transport:{transport}"
                    mcp_probes.append(verdict_record)
                    continue
                healthy = bool(raw.get("healthy"))
                verdict_record["verdict"] = "pass" if healthy else "fail"
                verdict_record["detail"] = raw.get("detail")
                mcp_probes.append(verdict_record)
                if not healthy:
                    fail_count += 1
                    self._publish_mcp_failure(run_id, branch, server, raw)

            final_status = "failed" if fail_count > 0 else "completed"
            self.update_run_status(run_id, final_status, agent="runhub",
                                    probes=probes, fail_count=fail_count,
                                    mcp_probes=mcp_probes)
            self._emit("run_completed", run_id,
                        {"status": final_status, "fail_count": fail_count,
                         "probe_count": len(probes)},
                        priority="high" if fail_count else "normal")
            return self.get_run(run_id)
        finally:
            try:
                compose.down()
            except Exception as e:
                _logger.warning(
                    "swallowed: RunHub start_run compose.down raised %r "
                    "(run_id=%s) — container leak risk",
                    e,
                    run_id,
                )

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def _list_registryhub_endpoints(self) -> list:
        if self.registryhub is None:
            return []
        eps = self.registryhub.get_endpoints() if hasattr(self.registryhub, "get_endpoints") else {}
        return list((eps or {}).values())

    def _publish_run_failed(self, run_id: str, branch: str, plan, ep: dict,
                             raw: dict, outcome) -> None:
        if self.eventhub is None:
            return
        payload = {
            "source": "runhub",
            "severity": outcome.severity,
            "title": f"{plan.method} {ep.get('path')} returned {raw.get('status_code')}",
            "bug_artifacts": {
                "affected_endpoint": f"{plan.method} {ep.get('path')}",
                "expected": "2xx",
                "actual": str(raw.get("status_code")),
                "response_body_excerpt": (raw.get("body_excerpt") or "")[:500],
                "request_body": plan.body,
                "run_id": run_id,
                "branch": branch,
                "latency_ms": raw.get("latency_ms"),
                "transport_error": raw.get("transport_error"),
                "owner_hint": ep.get("provider"),
            },
        }
        self.eventhub.publish_event(
            source_hub="runhub", event_type="run_failed",
            payload=payload, priority="high",
            caller="runhub")  # Phase 4.1c owner-equals

    def _emit(self, event_type: str, run_id: str, extra: dict, priority: str = "normal") -> None:
        if self.eventhub is None:
            return
        self.eventhub.publish_event(
            source_hub="runhub", event_type=event_type,
            payload={"run_id": run_id, **extra},
            priority=priority,
            caller="runhub")  # Phase 4.1c owner-equals

    def _default_probe_runner(self):
        # Lazy import - httpx is preferred, urllib is fallback
        def _runner(plan):
            import time as _time
            try:
                import httpx
                t0 = _time.time()
                if plan.method == "GET":
                    resp = httpx.get(plan.url, headers=plan.headers, timeout=10.0)
                else:
                    resp = httpx.request(plan.method, plan.url, json=plan.body,
                                          headers=plan.headers, timeout=10.0)
                latency = (_time.time() - t0) * 1000.0
                body = ""
                try:
                    body = (resp.text or "")[:500]
                except Exception as e:
                    _logger.warning(
                        "swallowed: probe body decode failed for %s %s: %r",
                        plan.method,
                        plan.url,
                        e,
                    )
                # #1000: carry the response HEADERS to the verdict. A 405 without its
                # `Allow` header is a number the lane has to reproduce; with it, the lane is
                # told which methods the running app bound. r162 spent 17 tasks on one 405
                # because every layer downstream — the smoke verdict, the verifier's
                # paraphrase, the orchestrator's dispatch — was working from a bare integer.
                _hdrs = {}
                try:
                    for _k, _v in dict(getattr(resp, "headers", {}) or {}).items():
                        if str(_k).lower() in ("allow", "content-type", "location", "www-authenticate"):
                            _hdrs[str(_k).lower()] = str(_v)[:200]
                except Exception:
                    pass
                return {"status_code": resp.status_code, "body_excerpt": body,
                        "headers": _hdrs,
                        "transport_error": None, "latency_ms": latency}
            except Exception as e:
                kind = type(e).__name__.lower()
                terr = "timeout" if "timeout" in kind else (
                    "connection_refused" if "connect" in kind else kind)
                return {"status_code": None, "body_excerpt": "",
                        "transport_error": terr, "latency_ms": 0.0}
        return _runner

    # ------------------------------------------------------------------ #
    # MCP probe helpers (Cutover 22)
    # ------------------------------------------------------------------ #

    def _list_registryhub_mcp_servers(self) -> list:
        if self.mcp_registry is None or not hasattr(self.mcp_registry, "get_mcp_servers"):
            return []
        return [s for s in (self.mcp_registry.get_mcp_servers() or {}).values()
                if s.get("status") == "defined"]

    def _publish_mcp_failure(self, run_id: str, branch: str,
                                server: dict, raw: dict) -> None:
        if self.eventhub is None:
            return
        payload = {
            "source": "runhub",
            "severity": "P1",
            "title": (f"MCP server {server['name']!r} failed "
                       f"{server.get('transport')} liveness probe"),
            "bug_artifacts": {
                "affected_mcp_server": server["name"],
                "transport": server.get("transport"),
                "endpoint": server.get("endpoint"),
                "expected": "reachable",
                "actual": raw.get("detail"),
                "run_id": run_id,
                "branch": branch,
                "owner_hint": server.get("provider"),
            },
        }
        self.eventhub.publish_event(
            source_hub="runhub", event_type="run_failed",
            payload=payload, priority="high",
            caller="runhub")  # Phase 4.1c owner-equals

    def _default_mcp_stdio_probe(self):
        import subprocess
        import time as _time
        def _probe(server):
            cmd = server.get("endpoint")
            if not cmd:
                return {"healthy": False, "detail": "no endpoint configured"}
            try:
                proc = subprocess.Popen(
                    cmd if isinstance(cmd, list) else cmd.split(),
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE)
                # Poll for early exit within the 2s liveness window.
                # Pre-O9 this was a hard `_time.sleep(2.0)` which wasted
                # ~2s × (N-1) on multi-MCP sessions where any probe died
                # within milliseconds. Now we early-return on death.
                deadline = _time.monotonic() + 2.0
                while _time.monotonic() < deadline:
                    if proc.poll() is not None:
                        return {"healthy": False,
                                "detail": f"process exited rc={proc.returncode}"}
                    _time.sleep(0.05)
                if proc.poll() is not None:
                    return {"healthy": False,
                            "detail": f"process exited rc={proc.returncode}"}
                proc.terminate()
                try:
                    proc.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    proc.kill()
                return {"healthy": True, "detail": "alive after 2s"}
            except FileNotFoundError:
                return {"healthy": False, "detail": f"binary not found: {cmd}"}
            except Exception as e:
                return {"healthy": False, "detail": f"spawn failed: {e}"}
        return _probe

    def _default_mcp_http_probe(self):
        def _probe(server):
            endpoint = server.get("endpoint")
            if not endpoint:
                return {"healthy": False, "detail": "no endpoint configured"}
            try:
                import httpx
                resp = httpx.get(endpoint, timeout=5.0)
                if 200 <= resp.status_code < 400:
                    return {"healthy": True, "detail": f"HTTP {resp.status_code}"}
                return {"healthy": False,
                        "detail": f"HTTP {resp.status_code}"}
            except Exception as e:
                return {"healthy": False, "detail": f"transport: {e}"}
        return _probe
