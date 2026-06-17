"""
Orchestrator - Multi-Agent Coordination

Coordinates agents via MessageBus:
1. Creates agents
2. Starts their message loops
3. Sends tasks to coordinate phases
4. Waits for completion
"""

import asyncio
import json
import logging
import os
import re
import socket
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from utils.communication import MessageBus
from utils.config import LLMConfig
from utils.llm import LLM

from .workspace_manager import WorkspaceManager
from . import delivery as _contract
from .agent_spawn_service import AgentSpawnRequest, AgentSpawnService
from .agents.configurable_agent import get_resident_lane_specs
from .team_runtime import (
    DynamicAgentManager,
    ParallelReasoningProtocol,
    PlanDecisionProtocol,
    PersonaCatalog,
    TeamPracticeStore,
)

# Import existing systems
import sys
_llm_gen_dir = Path(__file__).parent.parent
if str(_llm_gen_dir) not in sys.path:
    sys.path.insert(0, str(_llm_gen_dir))

from checkpoint import CheckpointManager
from context import GenerationContext
from progress import (
    EventEmitter as ProgressEmitter,
    EventType,
    ConsoleListener,
    JsonlEventLogger,
)


@dataclass
class GenerationResult:
    """Result of environment generation."""
    success: bool
    project_path: str
    phases_completed: List[str] = field(default_factory=list)
    issues_found: int = 0
    issues_fixed: int = 0
    duration: float = 0.0
    summary: str = ""


# Track allocated ports to avoid duplicates
_allocated_ports: set = set()

def find_free_port(preferred: List[int] = None, range_start: int = 8000, range_end: int = 9000) -> int:
    """Find an available port that hasn't been allocated yet."""
    global _allocated_ports
    preferred = preferred or []
    
    for port in preferred:
        if port in _allocated_ports:
            continue
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('localhost', port))
                _allocated_ports.add(port)
                return port
        except OSError:
            pass
    
    for port in range(range_start, range_end):
        if port in _allocated_ports:
            continue
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('localhost', port))
                _allocated_ports.add(port)
                return port
        except OSError:
            pass
    
    raise RuntimeError(f"No free port found in range {range_start}-{range_end}")

def reset_allocated_ports():
    """Reset allocated ports (call at start of new generation)."""
    global _allocated_ports
    _allocated_ports = set()


# Runnable BASE backend entrypoint, committed to the git base pre-spawn (see
# Orchestrator._seed_base_scaffold). The backend lane ADDS business route handlers
# to this; the OAuth2 AS + /health + uvicorn entrypoint are framework-owned.
_BASE_MAIN_PY = '''"""FastAPI application entrypoint.

Framework-scaffolded BASE. The backend lane ADDS the app's business route handlers
below (``@app.<method>(...)`` handlers, or ``from <x>_routes import router as r;
app.include_router(r)``). The embedded OAuth2 AS (/oauth/*, /.well-known/*,
/auth/register, /auth/login) and /health are wired here and MUST NOT be re-authored.
"""
import os
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="app")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Framework OAuth2 AS — provides /oauth/*, /.well-known/*, /auth/register, /auth/login.
try:
    from oauth_store import OAuthStore
    from jwt_manager import JWTManager
    from oauth_routes import build_router as _as_build_router
    app.include_router(_as_build_router(OAuthStore(), JWTManager()))
except Exception as _as_exc:  # pragma: no cover
    logging.getLogger("uvicorn").warning("AS wiring skipped: %s", _as_exc)


@app.get("/health")
def health():
    return {"status": "healthy"}


# ============================================================================
# BUSINESS ROUTES — the backend lane implements the app's endpoints below.
# Add @app.<method>(...) handlers or include_router(...) for your route modules.
# ============================================================================


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("API_PORT", "8081")))
'''

# Base reset.sh — the backend's Dockerfile ``COPY reset.sh /reset.sh`` fails the
# image build if it's absent (the lane writes the Dockerfile referencing it but
# may not author the script). Best-effort generic business-data reset over the
# ORM; never fails the build (skips cleanly if models/db aren't importable). The
# backend MAY overwrite with an app-specific version.
_BASE_RESET_SH = '''#!/usr/bin/env bash
set -euo pipefail
python - <<'PY'
try:
    from database import SessionLocal, Base
    with SessionLocal() as db:
        for table in reversed(Base.metadata.sorted_tables):
            if table.name not in ("users", "tenants"):
                db.execute(table.delete())
        db.commit()
    print("backend business data reset complete")
except Exception as exc:
    print(f"reset skipped: {exc}")
PY
'''


# ── deterministic-rescue pacing (PIPE-C2 / PIPE-C3, 2026-06-12) ──────────────
# The framework-validation and visual-deferral loops are attempt-capped to stop
# docker churn, but the caps used to HARD-STOP — so a sig-stable app failing on a
# transient environmental hiccup (docker contention) never recorded the RunHub
# run the gate needs (silent budget death), and a churning frontend lane reset the
# visual clock every tick (livelock). These pure predicates decouple "stop
# churning" (cap the FAST retries) from "stop trying" (never give up — slow down,
# and let a wall-clock escape end the deferral). Kept module-level + side-effect-
# free so the state machine is unit-tested without the docker/vision machinery.

FWVAL_FAST_CAP = 6           # fast (every-tick) validation attempts before slowdown
FWVAL_SLOW_INTERVAL_S = 300  # past the cap, retry at most once per this interval
# RESILIENCE (stuck-loop breaker): once the FAST cap is exhausted on an UNCHANGING
# failure set with NO lane progress, the orchestrator was re-running the SAME
# validation cycle (merge → regen skeleton → regen DDL → run_validation → fail)
# every ~60s indefinitely (observed: 36 identical cycles, zero agent activity).
# These bound the escalation: after the cap is spent on a stable failure set we
# RE-DISPATCH the owning lane (FWVAL_STUCK_REDISPATCH_AFTER), then if STILL no
# progress we surface a terminal "stuck on <blocker>" signal (FWVAL_STUCK_TERMINAL_AFTER)
# instead of churning to wall-clock.
FWVAL_STUCK_REDISPATCH_AFTER = 2   # validations on the same failure set (past cap) → re-dispatch owner
FWVAL_STUCK_TERMINAL_AFTER = 4     # validations on the same failure set (past cap) → surface stuck signal
VISUAL_DEFERRAL_ESCAPE_S = 900   # max wall-clock a milestone may defer on visuals
VISUAL_TOTAL_JUDGMENTS_CAP = 10  # per-milestone hard cap on real visual judgments


def _fwval_should_attempt(attempts: int, last_attempt_ts: float, now: float,
                          *, cap: int = FWVAL_FAST_CAP,
                          slow_interval: float = FWVAL_SLOW_INTERVAL_S) -> bool:
    """Should framework validation run THIS tick? Below the cap, yes (fast retry
    while the app converges). At/past the cap the app is sig-stable and still
    failing — don't churn docker every tick, but DON'T hard-stop either: allow one
    SLOW retry per ``slow_interval`` so a transient environmental failure still
    eventually records the gate-required RunHub run (PIPE-C2)."""
    if attempts < cap:
        return True
    return (now - (last_attempt_ts or 0.0)) >= slow_interval


def _fwval_failure_set(data) -> frozenset:
    """The set of FAILING check ids from a run_validation result — the stable
    signal of the app's *functional* state, driven by lane progress (NOT by the
    orchestrator's own idempotent heal/skeleton regeneration, which churns the
    file-content signature every cycle without changing what's failing). Keyed on
    the check NAME only (details carry transient docker/boot noise). Domain-agnostic."""
    checks = (data or {}).get("checks") or []
    return frozenset(
        str(c.get("name"))
        for c in checks
        if isinstance(c, dict) and c.get("status") == "fail" and c.get("name")
    )


def _fwval_stuck_decision(stuck_count: int, *,
                          redispatch_after: int = FWVAL_STUCK_REDISPATCH_AFTER,
                          terminal_after: int = FWVAL_STUCK_TERMINAL_AFTER) -> str:
    """Escalation stage for a failure set that has persisted (with NO lane
    progress) across ``stuck_count`` post-cap validations. Returns:
      * ``"wait"``      — still inside the fast budget / early; keep iterating.
      * ``"redispatch"``— re-wake the lane that owns the failing dimension.
      * ``"terminal"``  — re-dispatch did not help; surface a clear "stuck" signal
                          (so the run stops churning to wall-clock and the UI shows
                          the real blocker) instead of spinning the same cycle.
    Pure + side-effect-free so the escalation ladder is unit-tested without the
    docker/dispatch machinery."""
    if stuck_count >= terminal_after:
        return "terminal"
    if stuck_count >= redispatch_after:
        return "redispatch"
    return "wait"


def _visual_release_decision(deferred_since, attempts: int, total_judgments: int,
                             now: float, *, attempt_cap: int = 3,
                             escape_s: float = VISUAL_DEFERRAL_ESCAPE_S,
                             total_cap: int = VISUAL_TOTAL_JUDGMENTS_CAP) -> str:
    """Decide the visual-blocked delivery path. Returns:
      * ``"defer"``  — keep blocking the release; the lane should iterate.
      * ``"release"``— escape: deliver anyway (recorded below-threshold).
    Escapes (so the deferral ALWAYS terminates — PIPE-C3): the per-milestone
    wall-clock since the FIRST defer exceeds ``escape_s`` (anchored, NOT reset by
    lane churn), OR the per-source attempt budget is spent, OR the per-milestone
    total real-judgment cap is hit (vision-cost backstop)."""
    if deferred_since is not None and (now - deferred_since) > escape_s:
        return "release"
    if total_judgments >= total_cap:
        return "release"
    if attempts >= attempt_cap:
        return "release"
    return "defer"


class Orchestrator:
    """Multi-Agent Orchestrator."""
    
    def __init__(
        self,
        llm_config: LLMConfig,
        output_dir: Path,
        name: str = "generated_app",
        reference_images: List[str] = None,
        verbose: bool = False,
    ):
        self._logger = logging.getLogger("Orchestrator")
        if verbose:
            self._logger.setLevel(logging.DEBUG)
        
        # LLM
        self.llm_config = llm_config
        self.llm = LLM(llm_config)
        
        # Output
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self._reference_images = list(reference_images or [])
        # Merge in any reference images the UI (or a prior step) already dropped
        # into <workspace>/references/ — that is the store the monitor's
        # References page reads from, and in the UI flow it's the ONLY place refs
        # land. Without this, UI-uploaded references never reach the agents.
        try:
            ui_refs_dir = self.output_dir / "references"
            if ui_refs_dir.is_dir():
                have = {Path(r).name for r in self._reference_images}
                for p in sorted(ui_refs_dir.iterdir()):
                    if p.is_file() and p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".gif") and p.name not in have:
                        self._reference_images.append(str(p))
        except Exception as merge_err:
            self._logger.warning(f"Failed to merge UI references: {merge_err}")
        # Copy reference images into screenshots/ (the agent-facing store).
        # The monitor's References page reads `references/` AND `screenshots/`
        # (union), so a single physical copy here is enough — no duplication.
        try:
            screenshots_dir = self.output_dir / "screenshots"
            screenshots_dir.mkdir(parents=True, exist_ok=True)
            for ref in self._reference_images:
                src = Path(ref)
                if src.exists():
                    dest = screenshots_dir / src.name
                    if not dest.exists():
                        dest.write_bytes(src.read_bytes())
        except Exception as copy_err:
            self._logger.warning(f"Failed to copy reference images: {copy_err}")
        
        # Dynamic ports - reset allocation tracking first
        reset_allocated_ports()
        self.context = GenerationContext(
            name=name,
            api_port=find_free_port([3000, 3001]),
            ui_port=find_free_port([8080, 8081]),
        )
        self.context.db_port = find_free_port([5432, 5433])
        self.context.backend_internal_port = find_free_port([8080], range_start=8080, range_end=8100)
        
        self._logger.info(f"Ports: API={self.context.api_port}, UI={self.context.ui_port}, DB={self.context.db_port}")
        
        # Infrastructure
        self.workspace = WorkspaceManager(self.output_dir)
        self.message_bus = MessageBus()

        # Hub Registry — unified hub handle
        from .runtime.hub_registry import HubRegistry
        self.hubs = HubRegistry(
            self.output_dir,
            message_bus=self.message_bus,
            project_name=name,
            project_description=getattr(self, "_description", "") or "",
        )

        # System-level metrics (token usage, performance, retries)
        # Stored under shared/hubs/ directory; no hub runtime dependency.
        from tools.system_tools import SystemMetrics
        self.metrics = SystemMetrics(self.output_dir)
        
        # Shared spawn runtime: both resident core agents and dynamic agents
        # should go through the same low-level creation/start path.
        self.spawn_service = AgentSpawnService(self)

        # Team Protocols (inspired by Claude Code Agent Teams)
        self.agent_manager = DynamicAgentManager(self)
        self.persona_catalog = PersonaCatalog()
        self.plan_decision = PlanDecisionProtocol(self.message_bus, lead_agent_id="orchestrator")
        
        # Team Practice Store - Learn from successful team collaborations
        self.team_practice_store = TeamPracticeStore(
            storage_path=self.output_dir / ".team_practices.json"
        )
        
        self.parallel_reasoning = ParallelReasoningProtocol(
            self.agent_manager,
            self.message_bus,
            practice_store=self.team_practice_store,  # Enable practice recording
        )
        
        self.progress = ProgressEmitter()
        self.progress.on_all(ConsoleListener())
        progress_log_path = self.output_dir / "logs" / "progress_events.jsonl"
        progress_log_path.parent.mkdir(parents=True, exist_ok=True)
        self.progress.on_all(JsonlEventLogger(str(progress_log_path)))
        self.checkpoint = CheckpointManager(self.output_dir / ".checkpoint")
        
        # Agents
        self._agents: Dict[str, Any] = {}
        self._agent_tasks: Dict[str, asyncio.Task] = {}

        # Lifecycle-aware reviewer gating: RegistryHub consults this to reject
        # requests like ``registryhub_request_review(reviewers=["backend"])``
        # at design time, before backend is spawned. ``_agents`` is the
        # canonical "currently spawned" set — agent_spawn_service.terminate
        # pops on exit, so we just expose its keys.
        self.hubs.attach_live_agents_provider(lambda: list(self._agents.keys()))

        # Pin a stable generation id for this run so consumers (retro
        # gate, future run-scoped policies) can distinguish "this run"
        # from prior workspace state on disk.
        #
        # The id is a fresh ``uuid.uuid4()`` per Orchestrator instance —
        # NOT derived from the workspace path or any deterministic
        # input. That's intentional: scoping wants "this Orchestrator
        # process" to differ from any prior run that wrote into the
        # same workspace. Stable across all lookups for the lifetime
        # of THIS Orchestrator instance.
        #
        # --resume semantics: a resumed run constructs a new
        # Orchestrator → fresh gen_id → any retro from the original
        # run does NOT satisfy the retro-before-deliver gate on the
        # resume. Operators should expect to call submit_retro again
        # before delivering a resumed run. This matches "every actual
        # delivery gets its own retro" rather than "logical project
        # only gets retro'd once" — appropriate for the gate's intent.
        import uuid as _uuid
        self._generation_id = f"gen_{_uuid.uuid4().hex[:12]}"
        self.hubs.attach_generation_id(self._generation_id)

        # Tracking
        self._issues_found = 0
        self._issues_fixed = 0
    
    async def _spawn_core_agents(self):
        """Spawn all resident core agents through the shared spawn runtime."""
        # Initialize project info in WorkHub
        self.hubs.workhub.set_project_info(
            name=self.context.name,
            description=f"Generated environment: {self.context.name}"
        )
        self._enter_project_phase("init", reason="orchestrator setup")

        for lane_spec in get_resident_lane_specs():
            agent_id = str(lane_spec["agent_id"])
            await self.spawn_service.spawn(
                AgentSpawnRequest(
                    agent_id=agent_id,
                    agent_type=str(lane_spec.get("profile_id") or agent_id),
                    config_key=str(lane_spec.get("profile_id") or agent_id),
                    resident=bool(lane_spec.get("resident", True)),
                    metadata={
                        "spawn_origin": "orchestrator_core_boot",
                        "resident_role": agent_id,
                        "resident_profile": str(lane_spec.get("profile_id") or agent_id),
                    },
                )
            )
            self._logger.info(f"Spawned core resident agent: {agent_id}")

    async def _respawn_core_lanes(self):
        """Terminate + re-spawn every resident core lane for a NEW milestone.

        Multi-milestone: each milestone runs a FRESH lane-set so the LLM context
        starts clean, but the on-disk app must survive. Terminating a core
        (non-``worker_*``) lane KEEPS its git worktree (see
        AgentSpawnService.terminate), so re-spawning gives the next milestone's
        lanes fresh context over M(i-1)'s delivered+merged code.

        Mirrors ``_spawn_core_agents`` exactly (same lane specs / same
        AgentSpawnRequest). Best-effort per lane: a failure on one lane logs and
        continues so a single bad terminate/spawn can't abort the milestone.
        """
        for lane_spec in get_resident_lane_specs():
            agent_id = str(lane_spec["agent_id"])
            try:
                await self.spawn_service.terminate(agent_id, wait=True)
            except Exception as term_err:
                self._logger.warning(
                    f"Respawn: terminate of core lane {agent_id} failed "
                    f"(continuing): {term_err}"
                )
            try:
                await self.spawn_service.spawn(
                    AgentSpawnRequest(
                        agent_id=agent_id,
                        agent_type=str(lane_spec.get("profile_id") or agent_id),
                        config_key=str(lane_spec.get("profile_id") or agent_id),
                        resident=bool(lane_spec.get("resident", True)),
                        metadata={
                            "spawn_origin": "orchestrator_core_boot",
                            "resident_role": agent_id,
                            "resident_profile": str(lane_spec.get("profile_id") or agent_id),
                        },
                    )
                )
                self._logger.info(f"Respawned core resident lane: {agent_id}")
            except Exception as spawn_err:
                self._logger.error(
                    f"Respawn: spawn of core lane {agent_id} failed: {spawn_err}"
                )

    async def _stop_agents(self):
        """Stop all agents."""
        agent_ids = list(self._agents.keys())
        for agent_id in agent_ids:
            await self.spawn_service.terminate(agent_id, wait=False)

        if self._agent_tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*self._agent_tasks.values(), return_exceptions=True),
                    timeout=10.0
                )
            except asyncio.TimeoutError:
                for task in self._agent_tasks.values():
                    task.cancel()

    def _enter_project_phase(self, phase: str, reason: str = "") -> None:
        """
        Centralized project phase transition helper.

        Keeps hub phase transitions consistent and easy to audit.
        """
        current = self.hubs.workhub.get_project_status(self.context.name) or {}
        previous = current.get("phase")
        if previous == phase:
            return

        self.hubs.workhub.set_project_phase(self.context.name, phase, agent="orchestrator")
        if reason:
            self._logger.info(f"Project phase: {previous or 'unknown'} -> {phase} ({reason})")
        else:
            self._logger.info(f"Project phase: {previous or 'unknown'} -> {phase}")

    def _get_validation_checks(self) -> list:
        """Read validation checks from CodeHub."""
        try:
            checks = self.hubs.codehub.list_checks()
            return [c for c in checks if c.get("name", "").startswith("validation:")]
        except Exception:
            return []

    def _get_validation_results(self, limit: int = 200) -> list:
        """Return validation records shaped for legacy orchestrator consumers."""
        checks = self._get_validation_checks()
        records = []
        for c in checks:
            ev = c.get("evidence", {}) or {}
            records.append({
                "task_id": c.get("name", "").removeprefix("validation:"),
                "status": c.get("status", "error"),
                "summary": ev.get("summary", ""),
                "execution_mode": ev.get("execution_mode", "auto"),
                "duration_seconds": ev.get("duration_seconds"),
                "artifacts": ev.get("artifacts", []),
                "evidence": ev,
                "metadata": ev,
                "recorded_by": c.get("agent", ""),
                "recorded_at": c.get("updated_at", 0),
            })
        records.sort(key=lambda r: r.get("recorded_at", 0), reverse=True)
        return records[:max(1, int(limit))]

    def _get_validation_summary(self) -> dict:
        """Return validation summary for legacy orchestrator consumers."""
        records = self._get_validation_results(limit=9999)
        by_status: dict = {"passed": 0, "failed": 0, "skipped": 0, "error": 0}
        total_duration = 0.0
        counted_duration = 0
        retry_pending_count = 0
        retry_exhausted_count = 0
        retries_used_total = 0
        for r in records:
            by_status[r.get("status", "error")] = by_status.get(r.get("status", "error"), 0) + 1
            dur = r.get("duration_seconds")
            if isinstance(dur, (int, float)):
                total_duration += float(dur)
                counted_duration += 1
            meta = r.get("metadata", {}) or {}
            retries_used_total += int(meta.get("auto_retry_attempts", 0) or 0)
            if meta.get("auto_retry_decision") == "retry":
                retry_pending_count += 1
            if meta.get("auto_retry_decision") == "remediate":
                retry_exhausted_count += 1
        all_passed = len(records) > 0 and by_status.get("failed", 0) == 0 and by_status.get("error", 0) == 0
        return {
            "total": len(records),
            "by_status": by_status,
            "all_passed": all_passed,
            "average_duration_seconds": round(total_duration / counted_duration, 3) if counted_duration else None,
            "retries_used_total": retries_used_total,
            "retry_pending_count": retry_pending_count,
            "retry_exhausted_count": retry_exhausted_count,
            "recent_results": records[:10],
        }

    async def _preflight_check(self) -> Dict[str, Any]:
        """Pre-flight environment check before generation."""
        import subprocess
        import shutil
        
        results = {
            "docker": {"available": False, "message": ""},
            "node": {"available": False, "message": ""},
            "ports": {"available": True, "blocked": []},
        }
        
        # Check Docker
        try:
            docker_result = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                timeout=10,
            )
            if docker_result.returncode == 0:
                results["docker"]["available"] = True
                results["docker"]["message"] = "Docker daemon running"
            else:
                results["docker"]["message"] = "Docker daemon not running"
        except FileNotFoundError:
            results["docker"]["message"] = "Docker not installed"
        except subprocess.TimeoutExpired:
            results["docker"]["message"] = "Docker check timed out"
        except Exception as e:
            results["docker"]["message"] = f"Docker check failed: {e}"
        
        # Check Node.js
        try:
            node_result = subprocess.run(
                ["node", "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if node_result.returncode == 0:
                results["node"]["available"] = True
                results["node"]["message"] = f"Node.js {node_result.stdout.strip()}"
        except FileNotFoundError:
            results["node"]["message"] = "Node.js not installed"
        except Exception as e:
            results["node"]["message"] = f"Node check failed: {e}"
        
        # Check common ports
        common_ports = [
            self.context.api_port, 
            self.context.ui_port, 
            self.context.db_port,
            3000, 5432, 8080, 8083
        ]
        
        for port in set(common_ports):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(1)
                    s.bind(('localhost', port))
            except OSError:
                results["ports"]["blocked"].append(port)
        
        if results["ports"]["blocked"]:
            results["ports"]["available"] = False
        
        return results
    
    async def run(
        self,
        goal: str,
        requirements: List[str] = None,
        resume: bool = False,
        milestones: Optional[List[Dict[str, Any]]] = None,
    ) -> GenerationResult:
        """Run environment generation."""
        start_time = datetime.now()
        # Multi-milestone: run N milestones sequentially, each a FRESH lane-set
        # implementing a slice on the GROWING app. The degenerate (single
        # milestone) case is synthesized below so the one-milestone path is
        # byte-for-byte identical to a no-``milestones`` run.
        _milestones_explicit = bool(milestones)
        if not milestones:
            milestones = [{
                "name": "M1",
                "version": "1.0.0",
                "description_slice": (requirements[0] if requirements else goal),
            }]
        # NOTE: ``self._session_start_ts`` (the session-start epoch the
        # autonomous-deliver gate reads) is pinned at the TOP of each milestone
        # iteration below — each milestone forces a fresh api_smoke gate so a
        # prior milestone's RunHub run does not silently satisfy the next one.
        phases_completed = []
        success = False
        workflow_phase_started = False

        # Cutover 26: mark project active at start of run
        try:
            self.hubs.touch()
        except Exception as touch_err:
            self._logger.warning(f"Failed to touch project metadata: {touch_err}")

        # Pre-flight environment check
        self._logger.info("Running pre-flight environment check...")
        preflight = await self._preflight_check()
        
        # Log results
        for check, result in preflight.items():
            if isinstance(result, dict):
                available = result.get("available", False)
                msg = result.get("message", "")
                status = "OK" if available else "WARN"
                self._logger.info(f"  [{status}] {check}: {msg}")
                if check == "ports" and result.get("blocked"):
                    self._logger.warning(f"  Blocked ports: {result['blocked']}")
        
        # Store preflight results in context for agents to access
        self.context.preflight = preflight
        
        # Warn if Docker is not available
        if not preflight["docker"]["available"]:
            self._logger.warning(
                "Docker is not available. Docker-based testing will fail.\n"
                "  → Start Docker Desktop or docker daemon before testing.\n"
                "  → Agents will use docker_compose_reset() to clean up stale state."
            )
        
        await self.message_bus.start()
        
        # Phase 3b.6 (2026-06-05): seed the FIXED contract surface into the git
        # base BEFORE any agent worktree is created. The embedded OAuth2 AS
        # modules are runtime-owned and imported by the backend's main.py;
        # committing them to base means every agent/<id> worktree (branched off
        # HEAD) + the integration branch inherit them by construction — git, not
        # a prompt convention, owns the "do not author these" boundary.
        await self._seed_base_scaffold()

        agents_started = False
        try:
            await self._spawn_core_agents()
            agents_started = True
        except Exception as start_err:
            self._logger.error(f"Failed to start agents: {start_err}")
            await self._stop_agents()
            await self.message_bus.stop()
            raise
        
        self.progress.emit(
            EventType.GENERATION_START,
            f"Starting: {goal[:50]}...",
            {"name": self.context.name, "goal": goal},
        )
        
        checkpoint_already_complete = False
        if resume:
            if not self.checkpoint.load():
                raise RuntimeError("Resume requested but no valid checkpoint was found.")
            summary = self.checkpoint.get_summary()
            if summary["status"] == "complete":
                self._logger.info("Checkpoint indicates generation is already complete. Skipping workflow execution.")
                checkpoint_already_complete = True
            if (not checkpoint_already_complete) and (not self.checkpoint.can_resume()):
                raise RuntimeError(
                    f"Checkpoint status '{summary['status']}' is not resumable."
                )
            if not checkpoint_already_complete:
                self.checkpoint.resume_generation()
                self._logger.info(
                    f"Resuming from checkpoint (phase={summary.get('current_phase')}, resumes={summary.get('resume_count', 0) + 1})"
                )
        else:
            self.checkpoint.start_generation(name=self.context.name, description=goal, domain_type="web_app")
        
        try:
            # ============================================================
            # AGENT-DRIVEN WORKFLOW
            # ============================================================
            # All phases are coordinated by agents via messages.
            # Orchestrator just:
            # 1. Sends initial task to the resident orchestrator lane with raw requirements
            # 2. Waits for that lane to call deliver_project()
            #
            # Workflow (defined in agent prompts):
            # - Orchestrator lane: refine requirements/context → notify design
            # - Design lane: create design → broadcast → notify implementation lanes
            # - Implementation lanes: wait for design → develop → notify completion
            # - Verifier/orchestrator: validate → deliver_project()
            # ============================================================
            
            if checkpoint_already_complete:
                self._enter_project_phase("test", reason="validate resumed-complete checkpoint")
                gate = self._validate_delivery_gate()
                if not gate["ok"]:
                    report = self._format_delivery_gate_report(gate)
                    raise RuntimeError(
                        f"Delivery gate failed on resumed-complete checkpoint.\n{report}"
                    )
                self._enter_project_phase("done", reason="delivery gate passed (resumed)")
                phases_completed = ["requirements", "design", "code", "docker", "testing"]
                success = True
            else:
                self.progress.emit(EventType.PHASE_START, "Agent Workflow", {})
                self.checkpoint.start_phase("agent_workflow")
                workflow_phase_started = True
                self._enter_project_phase("implement", reason="start agent workflow")
            
                # Prepare initial context for the resident orchestrator lane
                raw_req = goal + ("\n" + "\n".join(requirements) if requirements else "")

                # REFERENCE MATERIALS: users may hand us more than screenshots —
                # HTML pages, PDFs, markdown feature docs, MCP tool docs. Split
                # images (visual gate + lane vision) from documents, stage the
                # documents into the workspace, then COMPILE everything into a
                # machine-usable spec with this run's model — required screens /
                # endpoints / entities / MCP tools — which (a) extends the
                # kickoff requirements and (b) becomes deliverability gates.
                raw_req = await self._compile_reference_materials(raw_req)

                # Set reference images on all agents that might need them.
                # Round-8e.1: design+frontend merged — frontend owns
                # reference-image manifest + ui_pages + user_flows + auth.
                # 2026-06-10: backend too — its contract (tables + endpoints)
                # derives from what the screens show and afford, not just the
                # requirements text.
                for agent_id in ["frontend", "backend"]:
                    if agent_id in self._agents:
                        self._agents[agent_id]._reference_images = self._reference_images
            
                # Generate docker-compose.yml upfront. Ports are dynamically allocated
                # from this run's context, and agents with docker/ write scope may
                # adjust host mappings if validation discovers conflicts.
                await self._generate_docker()

                # Emit the STATIC backend build infra (uv Dockerfile + pyproject +
                # reset.sh) upfront too — contract-independent, so it can land now.
                # Without it the backend build context is empty when validation
                # first runs, and an agent improvises a BROKEN Dockerfile (run #6:
                # the orchestrator hand-wrote `pip install poetry` → docker build
                # exit 2, though the project is uv/pyproject). The full skeleton
                # later re-asserts these byte-identically + adds models/handlers.
                try:
                    from .runtime.backend_skeleton import write_backend_build_infra
                    res = write_backend_build_infra(self.output_dir)
                    self._logger.info("backend build infra emitted upfront: %s", res.get("written"))
                except Exception as _bi_err:
                    self._logger.warning("upfront backend build infra failed: %s", _bi_err)
                # Same for the frontend: the verifier saw BOTH backend AND frontend
                # build contexts missing Dockerfiles at first validation. The
                # frontend baseline is infra-only + never clobbers lane files, so
                # emitting it upfront gives docker a buildable frontend context from
                # the start (the lane's real UI merges over it later).
                try:
                    self._scaffold_frontend_baseline()
                except Exception as _fb_err:
                    self._logger.warning("upfront frontend baseline failed: %s", _fb_err)

                # §4 D4.1 (2026-06-05): register the FIXED contract surface
                # (spine tables + the embedded-AS /auth/oauth + tenant/health
                # control plane, kind-tagged) BEFORE the kickoff meeting opens.
                # It's constructed + contract-independent, so nothing blocks
                # early registration — and doing so means the lanes SEE it via
                # registryhub_list_endpoints during the meeting, the meeting
                # negotiates business-only, and the cross-check resolves a
                # frontend /auth/login reference against a real kind=auth
                # endpoint (D4.2) instead of false-flagging it "undefined".
                self._register_contract_surface()

                # ============================================================
                # MULTI-MILESTONE LOOP
                # ============================================================
                # Each milestone is a FRESH lane-set implementing a slice on the
                # GROWING app (the app persists across milestones via the git
                # integration branch + per-agent worktrees). M1 is byte-for-byte
                # identical to the legacy single-milestone path; the
                # ``milestones`` list always has len>=1 (synthesized at the top
                # of run() when absent). M2+ re-declare M1's endpoints (harmless,
                # idempotent merge-upserts) and add their slice's new endpoints
                # as ``defined`` — which reopens the all-implemented gate.
                # AGENT-PLANNED MILESTONES (2026-06-11, user direction): when
                # the user supplies no --milestones, the RUN'S OWN MODEL plans
                # the roadmap from the requirements + compiled reference spec —
                # a small app stays ONE milestone, a large one splits into ≤6
                # coherent slices. User-provided milestones always win; planner
                # failure falls back to the single synthesized milestone.
                if not _milestones_explicit:
                    try:
                        from .runtime.reference_materials import plan_milestones
                        _planned = await plan_milestones(
                            self.llm, raw_req,
                            getattr(self, "_reference_spec", None) or {})
                    except Exception as exc:
                        self._logger.error("milestone planning raised: %s", exc)
                        _planned = None
                    if _planned:
                        milestones = _planned
                        self._logger.warning(
                            "MILESTONE PLAN (agent-decided): %d milestone(s): %s",
                            len(milestones),
                            [f"{m['name']}@{m['version']}" for m in milestones])
                    else:
                        self._logger.warning(
                            "Milestone planning unavailable — single milestone.")

                for _m_idx, _milestone in enumerate(milestones, start=1):
                    # Human-in-the-loop approval (ask mode): pause before STARTING
                    # each milestone so the user can verify it (after seeing the
                    # prior milestone land). Milestones aren't a tool, so this is
                    # the milestone analog of the tool-level approval gate. Reject
                    # → skip this milestone (feedback logged). No-op in auto mode.
                    try:
                        from .runtime.approval import request_decision as _appr_decision
                        _m_dec = await _appr_decision(
                            self.hubs, "orchestrator", "milestone",
                            f"Start milestone {_m_idx}/{len(milestones)}: "
                            f"{_milestone.get('name', '?')} @ {_milestone.get('version', '?')}",
                            {"index": _m_idx, "name": _milestone.get("name"),
                             "version": _milestone.get("version"),
                             "description": _milestone.get("description", "")})
                        if not _m_dec.get("approved"):
                            self._logger.warning(
                                "milestone %d (%s) REJECTED by reviewer — skipping. feedback: %s",
                                _m_idx, _milestone.get("name"), _m_dec.get("feedback") or "(none)")
                            continue
                    except Exception as _m_appr_err:
                        self._logger.warning(
                            "milestone approval gate error (proceeding): %s", _m_appr_err)
                    # Pin a fresh session-start epoch for THIS milestone so its
                    # api_smoke gate cannot be satisfied by a prior milestone's
                    # RunHub run (see _validate_delivery_gate / compute_deliverability).
                    self._session_start_ts = time.time()
                    self._current_milestone_version = _milestone.get("version", "1.0.0")
                    # VISUAL GATE SCOPE (2026-06-11 round 31): intermediate
                    # milestones ship partial UIs by definition ("Page Under
                    # Construction" feed at M1) — judging the full reference
                    # set against them burns the attempt budget early, and the
                    # exhausted counter then waves EVERY later milestone
                    # through ("exhausted — delivering anyway" 5 min into M2).
                    # Blocking applies to the FINAL milestone only; earlier
                    # ones still judge + file remediation (advisory) so the
                    # lane converges throughout. Deferral clock resets too.
                    self._is_final_milestone = (_m_idx == len(milestones))
                    # Per-milestone visual state: anchor the deferral clock and the
                    # total-judgment backstop to THIS milestone (PIPE-C3 — within a
                    # milestone neither is reset by lane churn).
                    self._vf_deferred_since = None
                    self._vf_total_judgments = 0
                    # This milestone's requirement slice → kickoff input. When
                    # milestones were NOT explicitly supplied, the single
                    # synthesized M1 MUST receive the exact legacy ``raw_req``
                    # (byte-for-byte transparency at N=1). For explicit
                    # milestones, use the slice, falling back to raw_req only if
                    # a slice is empty.
                    if not _milestones_explicit:
                        _milestone_req = raw_req
                    else:
                        _slice = str(_milestone.get("description_slice") or "").strip()
                        _milestone_req = _slice or raw_req
                        # The compiled REFERENCE SPEC is milestone-independent
                        # ground truth — a slice replacing raw_req must not
                        # drop it (it carries the binding endpoint/MCP lists).
                        _spec_block = getattr(self, "_reference_spec_summary", "")
                        if _spec_block and _spec_block not in _milestone_req:
                            _milestone_req = _milestone_req + _spec_block

                    if _m_idx > 1:
                        # New milestone: reset per-milestone delivery state so the
                        # framework-deliver / framework-validation paths start
                        # clean, then re-spawn the core lanes for FRESH LLM
                        # context over M(i-1)'s delivered+merged code.
                        self._project_delivered = False
                        self._framework_validation_attempts = 0
                        self._fwval_last_attempt_ts = 0.0  # PIPE-C2: fresh slow-retry clock
                        self._fwval_healed_sig = None
                        # RESILIENCE (stuck-loop breaker): fresh failure-set / stuck
                        # tracking per milestone — a new milestone's failures are
                        # genuinely new work, not a continuation of the prior stall.
                        self._fwval_failure_set = None
                        self._fwval_stuck_count = 0
                        self._fwval_stuck_blocker = None
                        self._silent_lane_nudges = {}
                        try:
                            _orch_lane = self._agents.get("orchestrator")
                            if _orch_lane is not None:
                                _orch_lane._project_delivered_event.clear()
                        except Exception as _clear_err:
                            self._logger.warning(
                                "Milestone %s: clearing prior delivery event failed: %s",
                                _m_idx, _clear_err,
                            )
                        await self._respawn_core_lanes()

                    # Charter §8: orchestrator wire is ONE call site — boot
                    # the kickoff coordinator. start_kickoff opens the
                    # meeting page on WorkHub + broadcasts kickoff_request
                    # via EventHub. Each resident lane wakes via its default
                    # ('orchestrator','kickoff_request','high') subscription
                    # and runs its kickoff_response prompt. The orchestrator
                    # lane wakes on workhub.meeting_decision_added events
                    # and runs its kickoff_synthesis_prompt — which finalizes
                    # the meeting (and emits kickoff_complete) once every
                    # gate passes, OR queues a single revision round on
                    # conflict, OR no-ops while awaiting decisions.
                    from .runtime.kickoff import run_kickoff
                    self._logger.info(
                        "Starting kickoff coordinator (M%s: %s)...",
                        _m_idx, _milestone.get("name", f"M{_m_idx}"),
                    )
                    self._kickoff_handle = run_kickoff.start_kickoff(
                        hubs=self.hubs,
                        milestone_index=_m_idx,
                        requirements=(
                            [_milestone_req] if _milestone_req else []
                        ),
                        # Round-8e.1: design absorbed into frontend; kickoff
                        # attendees 4 → 3. Frontend now owns ui_pages +
                        # user_flows + auth + reference_image_manifest +
                        # screens (the union of legacy design + frontend
                        # kickoff sections).
                        attendees=["backend", "frontend", "verifier"],
                        agent="orchestrator",
                    )
                    # ROADMAP AS A MEETING ARTIFACT (2026-06-11, user direction:
                    # "milestones 应该是会议创建的"): the milestone plan — agent-
                    # planned or user-provided — is recorded as the FIRST
                    # decision of the project's first kickoff meeting
                    # (section="roadmap"), so the plan lives in the meeting
                    # record (auditable, monitor-visible) rather than as
                    # framework-private state. Attendees then author their
                    # sections against slice 1 of this recorded roadmap.
                    if _m_idx == 1:
                        try:
                            _mid = (self._kickoff_handle or {}).get("meeting_id")
                            if _mid:
                                self.hubs.workhub.add_meeting_decision(
                                    meeting_id=_mid,
                                    decision={
                                        "section": "roadmap",
                                        "kind": "milestone_plan",
                                        "content": {
                                            "section": "roadmap",
                                            "source": ("user_provided"
                                                       if _milestones_explicit
                                                       else "agent_planned"),
                                            "milestones": [
                                                {"name": m.get("name"),
                                                 "version": m.get("version"),
                                                 "summary": str(m.get(
                                                     "description_slice", "")
                                                 )[:300]}
                                                for m in milestones
                                            ],
                                        },
                                    },
                                    agent="orchestrator",
                                    milestone_index=1,
                                )
                        except Exception as exc:
                            self._logger.error(
                                "roadmap decision recording failed: %s", exc)
                    # FIX #42 (#1 guaranteed contract): stow the project description on
                    # the handle so the synthesizer can deterministically backstop an
                    # empty LLM-drafted contract from the spec (the kickoff can then
                    # never abort with an empty endpoints/data_model contract).
                    try:
                        if isinstance(self._kickoff_handle, dict):
                            # FIX #42 backstops an empty LLM-drafted contract by
                            # extracting `- METHOD /path` lines from this description.
                            # For multi-milestone, the CURRENT milestone's endpoints
                            # live in `_milestone_req` (the slice) — NOT self._description
                            # (the brief overall goal). Use the slice so the per-milestone
                            # backstop has the real endpoints; fall back to the overall.
                            self._kickoff_handle["description"] = (
                                _milestone_req or getattr(self, "_description", "") or "")
                    except Exception:
                        pass
                    # Round-8c Fix #1 (per round-8b reviewer correction):
                    # the kickoff coordinator helpers (try_synthesize /
                    # finalize_kickoff) are pure §8 functions, NOT LLM
                    # tools. The orchestrator's LLM lane has nothing it
                    # can call to advance the meeting, so the kickoff sat
                    # headless until the round-8b smoke. Drive it
                    # deterministically here in pure Python BEFORE the
                    # resident lane is allowed to dispatch any work.
                    #
                    # Charter §6.D + §8: contract MUST register before any
                    # task_ready dispatch — finalize_kickoff is the single
                    # call site that registers endpoints / tables / tasks
                    # under actor='orchestrator' (the only allowed_set hit
                    # for register_endpoint / register_table). Driving
                    # this synchronously here means the resident lane
                    # never sees a pre-contract state.
                    # HARD OUTER BOUND (2026-06-11, live M3 freeze): the driver
                    # has its own 1200s timeout, but a wedged INTERNAL await
                    # (observed: every coroutine starved at the timeout
                    # boundary; loop fully idle for 33 min) means the driver
                    # itself can hang. This wait_for is the process-level
                    # last resort: a wedged driver degrades to the same
                    # deterministic reconcile/fallback as a normal timeout.
                    try:
                        kickoff_receipt = await asyncio.wait_for(
                            self._drive_kickoff_to_completion(
                                self._kickoff_handle
                            ),
                            timeout=run_kickoff.KICKOFF_TIMEOUT_SEC + 600,
                        )
                    except asyncio.TimeoutError:
                        self._logger.error(
                            "Kickoff DRIVER wedged past %.0fs — forcing "
                            "deterministic reconcile/fallback.",
                            run_kickoff.KICKOFF_TIMEOUT_SEC + 600,
                        )
                        try:
                            _ls = run_kickoff.try_synthesize(
                                self.hubs, self._kickoff_handle)
                        except Exception:
                            _ls = {"status": "unknown"}
                        kickoff_receipt = self._kickoff_fallback_or_reconcile(
                            self._kickoff_handle, _ls, "driver_wedged",
                        )
                    if kickoff_receipt.get("phase") == "timeout_fallback":
                        raise RuntimeError(
                            "Kickoff timed out after "
                            f"{run_kickoff.KICKOFF_TIMEOUT_SEC:.0f}s without "
                            "a ready synthesis. Missing="
                            f"{kickoff_receipt.get('missing')} "
                            f"last_status={kickoff_receipt.get('last_status')!r}. "
                            "kickoff_failed event emitted; aborting."
                        )
                    if kickoff_receipt.get("phase") != "finalized":
                        raise RuntimeError(
                            "Kickoff did not finalize cleanly: phase="
                            f"{kickoff_receipt.get('phase')!r}, "
                            f"failures={kickoff_receipt.get('failures')}"
                        )
                    # Round 8h Patch B baseline: anchor "silent since
                    # kickoff" detection at the moment finalize_kickoff
                    # returned. Any resident lane that fails to record an
                    # agent_status event after this timestamp is treated
                    # as having missed its kickoff_complete subscription
                    # (the exact failure mode smoke #18 surfaced: Frontend
                    # + Verifier never emitted a single agent_status
                    # despite being subscribed).
                    kickoff_finalized_at = time.time()

                    # B1 (2026-06-05): now that finalize_kickoff has registered
                    # every table to SchemaHub, deterministically author
                    # app/database/ (Dockerfile + init/01_schema.sql) from the
                    # contract. The runtime is the sole owner of app/database/
                    # — compose's `build: ../app/database` and the delivery
                    # gate's `app/database/*.sql` requirement are satisfied
                    # by-construction, independent of LLM-lane recipe variance.
                    await self._generate_database()

                    # §4 D4.1: the FIXED contract surface (spine tables + AS/auth +
                    # control plane) is now registered BEFORE the meeting (see above),
                    # so nothing to register here. The business contract was just
                    # registered by finalize_kickoff; the spine DDL was authored by
                    # _generate_database. Idempotent re-registration of the fixed
                    # surface is unnecessary.

                    # Phase 3c (2026-06-05): project the FastMCP server
                    # (mcp_server/<env>/) 1:1 from the registered BUSINESS endpoints
                    # + register the server & its tools. Like the DB DDL (and unlike
                    # the AS modules) this depends on the contract, so it is a
                    # post-kickoff untracked output_dir write — agentsuite-red's pool
                    # launches it as a subprocess; no agent worktree imports it.
                    await self._generate_mcp()

                    # Frontend analogue of the backend skeleton / _generate_database:
                    # project a page stub per registered ui_page + wire React-Router
                    # routes, so the frontend lane FILLS pages instead of authoring N
                    # from scratch (run #13 build-asymmetry root) and the app is
                    # navigable-by-construction. Lane-owned once it drops the marker.
                    self._scaffold_frontend_pages()

                    # §4 D4.3 / §5-entry (2026-06-05): kickoff finalized + the runtime
                    # construct (DDL/AS/MCP) is in place + the task tree is assigned —
                    # deterministically hand the implementation phase to the lanes
                    # (orchestrator task_ready → KickoffBootstrapGate → claim+implement)
                    # and reset their idle counters so the kickoff-reply phase doesn't
                    # pre-halt implementation. Replaces the kickoff_complete-subscription
                    # + late-nudge race that left the lanes idle-halted (smoke #3).
                    await self._dispatch_implementation_phase()

                    self._silent_lane_nudges: Dict[str, int] = {}
                    # The orchestrator's resident lane now wakes on
                    # workhub.meeting_decision_added (its default
                    # subscription) — no synchronous send_task needed.
                    # Construct a satisfied placeholder event so the
                    # existing post-kickoff coord-tick loop downstream
                    # (which expects `orchestrator_task_done_event`) has a
                    # ready-event to wait on for its first iteration.
                    orchestrator_task_done_event = asyncio.Event()
                    orchestrator_task_done_event.set()
            
                    # Wait for Orchestrator to call deliver_project() (NOT finish()!).
                    # Hard run budget: a confused run must fail deterministically rather
                    # than tick (and burn LLM budget) forever. Caps are env-overridable.
                    orchestrator_lane = self._agents["orchestrator"]
                    tick_count = 0
                    idle_tick_count = 0
                    loop_start = time.time()
                    # Round 8h Patch B v2: stall-escalation cadence is
                    # decoupled from the tick boundary. Smoke #19
                    # (2026-06-03) caught the v1 wiring bug — Patch B was
                    # nested inside `if orchestrator_task_done_event.is_set()`,
                    # so when the orchestrator lane never finished tick #1
                    # (busy in a 162-step LLM self-loop reading inbox /
                    # writing memory_bank), idle_tick_count was stuck at
                    # 1 and the nudge never fired. v2 fires the nudge in
                    # the outer `wait_for` timeout branch on a wall-clock
                    # cadence:
                    #   * grace_sec_before_first_nudge: lanes get this
                    #     many seconds post-finalize before we start
                    #     nudging (give kickoff_complete subscribers a
                    #     chance to wake naturally before assuming bug).
                    #   * nudge_interval_sec: minimum gap between
                    #     consecutive nudge attempts; per-lane state
                    #     tracked in self._silent_lane_nudges.
                    last_nudge_attempt_at = 0.0
                    nudge_grace_sec = float(
                        os.environ.get("ENVGEN_NUDGE_GRACE_SEC", "120")
                    )
                    nudge_interval_sec = float(
                        os.environ.get("ENVGEN_NUDGE_INTERVAL_SEC", "60")
                    )
                    # Defect B (coordination-tick decouple, YOUTUBE_RUN_STALL_REVIEW):
                    # the tick re-dispatch was gated SOLELY on
                    # ``orchestrator_task_done_event.is_set()``, which stays False
                    # forever when the resident orchestrator's tick #1 LLM-loops
                    # without finishing (smoke #19 decoupled the NUDGE this way but
                    # missed the tick). Wall-clock fallback so the orchestrator is
                    # re-woken to escalate/deliver even when that event is stuck —
                    # bounded to one extra tick per stuck window (no flood).
                    last_coordination_tick_at = 0.0
                    coordination_tick_stuck_sec = float(
                        os.environ.get("ENVGEN_COORD_TICK_STUCK_SEC", "300")
                    )
                    # Run budget: initial caps come from env (the UI sets them on spawn);
                    # thereafter we re-read run_budget.json each tick so the UI can raise
                    # the cap live, and we write usage there so the UI can show progress.
                    env_caps = {
                        "max_wall_sec": float(os.environ.get("ENVGEN_MAX_WALLCLOCK_SEC", "7200")),
                        "max_ticks": int(os.environ.get("ENVGEN_MAX_TICKS", "240")),
                        "unlimited": str(os.environ.get("ENVGEN_BUDGET_UNLIMITED", "")).strip().lower() in ("1", "true", "yes"),
                    }
                    caps = self._load_run_budget_caps(env_caps)
                    self._write_run_budget(caps, loop_start, 0.0, 0, "running")
                    budget_exceeded: Optional[str] = None
                    while not orchestrator_lane._project_delivered_event.is_set():
                        try:
                            await asyncio.wait_for(
                                orchestrator_lane._project_delivered_event.wait(),
                                timeout=60.0,
                            )
                            break
                        except asyncio.TimeoutError:
                            pass

                        caps = self._load_run_budget_caps(env_caps)  # pick up live cap raises
                        elapsed = time.time() - loop_start
                        self._write_run_budget(caps, loop_start, elapsed, tick_count, "running")
                        if not caps.get("unlimited"):  # admins run with no budget ceiling
                            if elapsed > caps["max_wall_sec"]:
                                budget_exceeded = f"wall-clock {elapsed:.0f}s exceeded cap {caps['max_wall_sec']:.0f}s"
                            elif tick_count >= caps["max_ticks"]:
                                budget_exceeded = f"coordination ticks {tick_count} reached cap {caps['max_ticks']}"
                        if budget_exceeded:
                            self._logger.error(
                                "Run budget exceeded (%s) before delivery; aborting generation.",
                                budget_exceeded,
                            )
                            self._write_run_budget(caps, loop_start, elapsed, tick_count, "budget_exceeded")
                            break

                        # Round 8h Patch B v2: wall-clock stall escalation.
                        # Fires independently of orchestrator_task_done_event
                        # so a stuck orchestrator-lane LLM-loop (smoke #19's
                        # 162-step self-loop) cannot block the nudge. Each
                        # `wait_for` timeout iteration is one chance to nudge.
                        # Gating decision lives in
                        # ``_should_attempt_silent_lane_nudge`` (pure, tested
                        # in isolation).
                        now_ts = time.time()
                        if self._should_attempt_silent_lane_nudge(
                            now_ts,
                            kickoff_finalized_at,
                            last_nudge_attempt_at,
                            nudge_grace_sec,
                            nudge_interval_sec,
                        ):
                            last_nudge_attempt_at = now_ts
                            try:
                                nudged = await self._nudge_silent_resident_lanes(
                                    kickoff_finalized_at,
                                )
                            except Exception as _nudge_err:
                                self._logger.error(
                                    "Stall escalation: _nudge_silent_resident_lanes raised %s",
                                    _nudge_err,
                                )
                                nudged = []
                            if nudged:
                                self._logger.warning(
                                    "Stall escalation (wall-clock cadence, elapsed=%.0fs since finalize): "
                                    "dispatched urgent task_ready to silent resident lanes %s "
                                    "(nudge counts: %s)",
                                    now_ts - kickoff_finalized_at,
                                    sorted(nudged),
                                    {k: self._silent_lane_nudges[k] for k in sorted(nudged)},
                                )

                        # Deterministic api_smoke (framework-driven validation) — run
                        # EVERY coordination loop iteration, NOT only when the lane is
                        # idle: the orchestrator LLM frequently SPINS in coordination
                        # (check_inbox / list_tasks), so ``orchestrator_task_done_event``
                        # is never set and the idle-gated call never fired (smoke #13:
                        # merge resolved, 0 completed RunHub run, orchestrator spun →
                        # killed). The verifier/orchestrator LLMs run run_validation too
                        # early (pre-merge → fast-fail) and don't retry, so a WORKING app
                        # never records the RunHub run the delivery gate requires (gate
                        # blocker #1). This runs it until it passes — guaranteeing the
                        # evidence for a healthy app regardless of LLM coordination
                        # behaviour. Internally guarded (skips once a passing run exists;
                        # attempt-capped) so it's cheap after the first success.
                        await self._maybe_run_framework_validation()
                        # Deterministic delivery: the orchestrator LLM drifts — it
                        # checks deliverability repeatedly without ever firing
                        # deliver_project (smoke #19: 30x deliverability_check, 0
                        # deliver_project, even with the gate FULLY clear). Once the
                        # delivery gate has NO failed checks (a validated, gate-clear
                        # app), cut the release + signal delivery here so the run
                        # completes regardless of LLM behaviour.
                        await self._maybe_framework_deliver()
                        # Propagate a framework delivery to the LANE's termination
                        # event (the one this loop's shutdown checks at :876) — the
                        # deterministic deliver sets the Orchestrator object's flag,
                        # which is a DIFFERENT object than ``orchestrator_lane``. This
                        # makes the run shut down cleanly right after the auto-release
                        # instead of coordinating on (burning key).
                        if getattr(self, "_project_delivered", False):
                            try:
                                orchestrator_lane._project_delivered_event.set()
                            except Exception:
                                pass

                        _now_tick = time.time()
                        if self._coordination_tick_due(
                            event_set=orchestrator_task_done_event.is_set(),
                            now=_now_tick,
                            last_tick_at=last_coordination_tick_at,
                            loop_start=loop_start,
                            stuck_sec=coordination_tick_stuck_sec,
                        ):
                            # MILESTONE-ADVANCE GUARD (2026-06-10, live M3→M4 hang):
                            # the framework deliver above can set the delivered
                            # flag in THIS iteration — scheduling another
                            # coordination tick then awaits a lane that may be
                            # busy/wedged, and the while-condition never gets
                            # re-checked → the next milestone never starts
                            # (22:06 delivered, 25 min of silence). Once
                            # delivered, stop coordinating immediately.
                            if orchestrator_lane._project_delivered_event.is_set():
                                break
                            tick_count += 1
                            idle_tick_count += 1
                            last_coordination_tick_at = _now_tick  # reset cadence (Defect B decouple)
                            stalled = idle_tick_count >= 3
                            gate = self._validate_delivery_gate()
                            gate_report = self._format_delivery_gate_report(gate)
                            self._logger.info(
                                "Resident orchestrator lane is idle before delivery; scheduling coordination tick #%s",
                                tick_count,
                            )
                            # Bounded dispatch: a wedged lane must not freeze the
                            # milestone loop — on timeout we loop back and re-check
                            # delivered/budget instead of hanging forever.
                            try:
                                orchestrator_task_done_event = await asyncio.wait_for(
                                    orchestrator_lane.send_task({
                                "name": "resident_coordination_tick",
                                "workflow": "resident_tick",
                                "raw_requirements": raw_req,
                                "reference_images": self._reference_images,
                                "instruction": (
                                    "You are a resident coordinator lane. Do not treat this tick as final delivery. "
                                    "Check inbox, hub plan/status, runtime team status, verifier results, and blockers. "
                                    "Here is the current objective delivery gate report:\n"
                                    f"{gate_report}\n\n"
                                    "If validation has passed and deliverables are ready, call deliver_project(). "
                                    "If the gate has missing or failed validation/build evidence, wake Verifier with msg_type='task_ready' "
                                    "and require `record_build(...)` plus `record_validation_result(...)` entries. "
                                    "If validation records already show failed/error checks, convert them into remediation work with "
                                    "`create_dev_task_from_validation_failure(...)` or send task_ready to the owning static lane. "
                                    "If Docker reports host port conflicts, tell the responsible agent/verifier to edit "
                                    "`docker/docker-compose.yml` host port mappings; ports are run-specific and not fixed. "
                                    "If work is still pending, send/route any necessary messages and remain idle for the next tick. "
                                    + (
                                        "IMPORTANT: This is the third consecutive idle tick without delivery. Do not keep waiting on the same blocker. "
                                        "Escalate actively: wake the responsible resident agent with task_ready, spawn a focused worker, rerun validation, "
                                        "or convert the blocker into an actionable dev task before finishing this tick."
                                        if stalled else ""
                                    )
                                ),
                                }), timeout=900.0)
                            except asyncio.TimeoutError:
                                self._logger.error(
                                    "coordination-tick dispatch timed out (900s) — "
                                    "lane wedged; looping to re-check delivered/budget.")
                                continue
                    if orchestrator_lane._project_delivered_event.is_set():
                        self._write_run_budget(caps, loop_start, time.time() - loop_start, tick_count, "delivered")
                    # Deterministic failure when the run budget was hit before delivery.
                    if budget_exceeded and not orchestrator_lane._project_delivered_event.is_set():
                        raise RuntimeError(
                            f"Run budget exceeded ({budget_exceeded}) without delivery; "
                            f"aborted after {tick_count} coordination ticks. "
                            f"Adjust via ENVGEN_MAX_WALLCLOCK_SEC / ENVGEN_MAX_TICKS."
                        )

                # Hard gate: objective validation before marking generation successful.
                self._enter_project_phase("test", reason="run delivery gate checks")
                gate = self._validate_delivery_gate()
                if not gate["ok"]:
                    report = self._format_delivery_gate_report(gate)
                    raise RuntimeError(f"Delivery gate failed.\n{report}")
            
                self._enter_project_phase("done", reason="delivery gate passed")
                phases_completed = ["requirements", "design", "code", "docker", "testing"]
                self.progress.emit(EventType.PHASE_COMPLETE, "Agent Workflow", {})
                self.checkpoint.complete_phase("agent_workflow")
                self.checkpoint.complete_generation(success=True)
                success = True
            
        except Exception as e:
            self._enter_project_phase("implement", reason="generation failed, remediation required")
            self._logger.error(f"Generation failed: {e}")
            import traceback
            self._logger.error(traceback.format_exc())
            if workflow_phase_started:
                self.progress.emit(EventType.PHASE_ERROR, "Agent Workflow", {"error": str(e)})
            self.progress.emit(EventType.GENERATION_ERROR, str(e), {})
            self.checkpoint.fail_generation(error=str(e), phase="agent_workflow")
            success = False
        finally:
            # FINAL FLUSH: merge every lane's committed work into integration on
            # disk before the run exits. Deterministic delivery can fire (and cut
            # the release) while a core lane is STILL committing its final
            # milestone work — observed (instagram MM, 2026-06-08): the backend
            # committed the last milestone's routes 11s AFTER delivery fired, so
            # they never reached integration and the on-disk app was missing 3
            # already-implemented endpoints. Flushing here guarantees the on-disk
            # integration tree reflects all committed lane code (idempotent,
            # conflict-safe, never raises) even when delivery raced ahead or the
            # run exited abnormally (timeout/kill).
            try:
                self._merge_committed_agent_work()
                # SKELETON根治: the FINAL on-disk backend the user boots is the
                # deterministic, by-construction skeleton from the contract (not the
                # lane's variably-structured output). Generated AFTER the last merge so
                # nothing overwrites it; the route projector below then no-ops.
                self._generate_backend_skeleton()
                # Frontend INFRA parity: re-force the known-good build/serve tooling
                # AFTER the final merge too — the heal-time pin runs pre-validation,
                # but the merge re-imports the lane's broken infra (v1.0.0 shipped a
                # start.sh whose envsubst var didn't match the nginx template, a
                # port-mismatched compose target, and no vite.config.js → blank page).
                self._scaffold_frontend_baseline()
                # …and reconcile api.js exports with what pages import (the merge
                # re-imports the lane's api.js; projected pages need apiGet/apiPost).
                self._repair_frontend_api()
                # Project missing routes AFTER the final merge so the on-disk app
                # the user boots is contract-complete — this merge is the LAST one,
                # so nothing follows to stash/drop the projection (the bug that
                # would otherwise leave the final app hollow).
                self._project_missing_routes()
                # …and missing UI pages (frontend analog): declared-but-unbuilt
                # screens get a functional, API-wired, navigable page so the booted
                # app is not thin/unreachable.
                # COMMIT the framework writes above on integration — mirrors the
                # happy-path delivery (see _commit_framework_delivery before
                # create_release). The skeleton/infra/projection are working-tree-only
                # until committed, and a release is cut from the COMMITTED head; without
                # this, a release cut after an abnormal exit (timeout/kill) — or any
                # later consumer of the integration ref — ships a HOLLOW tree (every
                # framework-generated artifact: backend models/db/schemas, app/database,
                # docker, mcp_server) even though the on-disk docker build looks green.
                # Idempotent + best-effort (nothing-to-commit is fine; never raises).
                self._commit_framework_delivery()
            except Exception as _final_merge_err:
                self._logger.warning(
                    "final merge-committed-agent-work flush failed: %s",
                    _final_merge_err,
                )
            duration = (datetime.now() - start_time).total_seconds()
            try:
                if self.checkpoint.get_status() == "running":
                    if workflow_phase_started and success:
                        self.checkpoint.complete_phase("agent_workflow")
                    if success:
                        self.checkpoint.complete_generation(success=True)
                    else:
                        self.checkpoint.fail_generation(phase="agent_workflow")
                self.progress.emit(
                    EventType.GENERATION_COMPLETE,
                    f"Done in {duration:.1f}s",
                    {"success": success},
                )
            except Exception as finalize_err:
                self._logger.error(f"Finalization bookkeeping failed: {finalize_err}")

            # Cutover 26: persist terminal project status
            try:
                self.hubs.set_project_status("completed" if success else "failed")
            except Exception as status_err:
                self._logger.warning(
                    f"Failed to mark project {'completed' if success else 'failed'}: {status_err}"
                )

            try:
                if agents_started:
                    await self._stop_agents()
            except Exception as stop_err:
                self._logger.error(f"Agent cleanup failed: {stop_err}")

            try:
                await self.message_bus.stop()
            except Exception as bus_err:
                self._logger.error(f"Message bus shutdown failed: {bus_err}")

        duration = (datetime.now() - start_time).total_seconds()
        
        return GenerationResult(
            success=success,
            project_path=str(self.output_dir),
            phases_completed=phases_completed,
            issues_found=self._issues_found,
            issues_fixed=self._issues_fixed,
            duration=duration,
            summary=f"Generated {self.context.name} in {duration:.1f}s",
        )
    
    async def _distribute_design_docs(self):
        """Send design docs to code agents."""
        design_dir = self.output_dir / "design"
        if not design_dir.exists():
            return
        
        docs = {}
        for spec_file in design_dir.glob("*.json"):
            try:
                docs[spec_file.stem] = spec_file.read_text()
            except:
                pass
        
        for agent_id in ["database", "backend", "frontend"]:
            self._agents[agent_id].set_design_docs(docs)

    def _finalize_kickoff_and_author(
        self,
        kickoff_handle: Dict[str, Any],
        synthesis: Dict[str, Any],
        *,
        poll_count: int,
        elapsed: float,
    ) -> Dict[str, Any]:
        """Register a READY synthesis (finalize_kickoff) + author the
        milestone/roadmap/briefing docs, returning the finalize receipt.

        Shared by the two finalize sites in ``_drive_kickoff_to_completion``:
        the deterministic synth=ready fast-path and the LLM-facilitator
        ``consensus`` branch. finalize_kickoff is a pure §8 function — it is
        the single writer of the registered contract + task_ready dispatch —
        so a ready synthesis NEVER needs the LLM to bless it; centralizing the
        finalize keeps both paths byte-identical. Doc authoring failures are
        non-fatal (the contract has already shipped).
        """
        from .runtime.kickoff import run_kickoff
        receipt = run_kickoff.finalize_kickoff(
            hubs=self.hubs,
            kickoff_handle=kickoff_handle,
            synthesis=synthesis,
            agent="orchestrator",
        )
        self._logger.info(
            "Kickoff finalize receipt: phase=%s endpoints=%d tables=%d "
            "tasks=%d predicates=%d failures=%d",
            receipt.get("phase"),
            receipt.get("endpoints_registered", 0),
            receipt.get("tables_registered", 0),
            receipt.get("tasks_created", 0),
            receipt.get("predicates_persisted", 0),
            len(receipt.get("failures") or []),
        )
        try:
            self._author_kickoff_docs(synthesis)
        except Exception as _auth_err:
            self._logger.warning(
                "kickoff authoring failed (non-fatal): %s", _auth_err,
            )
        return receipt

    async def _drive_kickoff_to_completion(
        self,
        kickoff_handle: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Round-8f.1 driver: pure-Python facilitator-led meeting loop.

        Background (round-8c → 8f.1): the original 8c driver polled
        ``try_synthesize`` and short-circuited any non-``ready`` status
        straight to ``synthesize_fallback``. That treated the kickoff as
        a one-shot paper-submission rather than a real meeting. Round-8f
        introduces the orchestrator-as-facilitator turn (see
        ``runtime/kickoff/facilitate.py``):

          Round 1: attendees author initial proposals (no change).
          Facilitator turn: orchestrator LLM reads all decisions, emits a
            ``facilitator_note`` whose ``content.action`` is one of
            ``consensus``, ``request_revision``, or ``escalate``.
          Round N>1 (only on request_revision): the flagged revisers
            re-author their sections, then the facilitator runs again.
          After ``KICKOFF_MAX_ROUNDS`` rounds the driver falls back.

        This driver is the pure-Python state machine that wires those
        events together; it does NOT call the LLM directly. The
        facilitator LLM runs inside the orchestrator's resident lane via
        its ``_handle_kickoff_facilitate_request`` handler.

        Returns the kickoff receipt (finalize_kickoff's normal return
        shape) on consensus; a ``synthesize_fallback`` dict on
        timeout / escalate / max_rounds. Caller inspects ``phase``.
        """
        from .runtime.kickoff import run_kickoff
        from .runtime.kickoff import facilitate
        from .runtime.kickoff.schema_tolerance import (
            coerce_facilitator_action,
        )
        # NOTE: use ``is None`` not ``or`` — 0.0 is a valid (if degenerate)
        # started_at and ``or`` would silently replace it with time.time(),
        # masking a timeout-driven abort in tests/production alike.
        started_at = kickoff_handle.get("started_at")
        if started_at is None:
            started_at = time.time()
        poll_count = 0
        expected_attendees = list(kickoff_handle.get("expected_attendees") or [])
        meeting_id = kickoff_handle.get("meeting_id")
        # Round-8g: track which (round, phase) broadcasts have fired so
        # we don't re-broadcast on every poll. In-memory state — only
        # valid for the lifetime of this driver call. If the driver
        # restarts mid-meeting (it doesn't today), we'd have to persist
        # this in workhub but for now in-process is fine.
        broadcasts_fired: set = set()

        while True:
            poll_count += 1
            elapsed = time.time() - started_at

            # Timeout check FIRST — overrides any other state machine
            # decision. Matches the 8c contract that ``test_driver_timeout
            # _falls_through_to_fallback`` pins.
            if elapsed > run_kickoff.KICKOFF_TIMEOUT_SEC:
                try:
                    last_synth = run_kickoff.try_synthesize(self.hubs, kickoff_handle)
                except Exception:
                    last_synth = {"status": "unknown"}
                self._logger.error(
                    "Kickoff timed out after %.0fs (poll %s); attempting "
                    "deterministic reconcile before kickoff_failed.",
                    elapsed, poll_count,
                )
                return self._kickoff_fallback_or_reconcile(
                    kickoff_handle, last_synth, "timeout",
                )

            # Round-8g: derive the meeting's current phase from
            # decisions[]. Phases iterate per round:
            #   initial → comment → reply → facilitator
            #   → (consensus | request_revision | escalate)
            phase = facilitate.current_phase(
                self.hubs, meeting_id, expected_attendees,
            )
            cur_round = facilitate.current_round(self.hubs, meeting_id)

            if phase == "initial":
                # Initial drafts still being authored (kickoff_request
                # was broadcast by start_kickoff for round 1; revisions
                # are dispatched via kickoff_revision_request when a
                # facilitator says request_revision).
                self._logger.info(
                    "Kickoff phase=initial (round %d, poll %s, %.0fs); "
                    "waiting for attendees to record initial proposals.",
                    cur_round, poll_count, elapsed,
                )
                await asyncio.sleep(run_kickoff.KICKOFF_POLL_INTERVAL_SEC)
                continue

            if phase == "comment":
                # Initial drafts done — fire kickoff_comment_phase_request
                # once for this (round, phase), then wait for all
                # attendees to ack the comment phase.
                key = (cur_round, "comment")
                if key not in broadcasts_fired:
                    self._logger.info(
                        "Kickoff phase=comment (round %d, poll %s, "
                        "%.0fs); broadcasting kickoff_comment_phase_request.",
                        cur_round, poll_count, elapsed,
                    )
                    facilitate.request_comment_phase(
                        self.hubs, kickoff_handle,
                    )
                    broadcasts_fired.add(key)
                else:
                    acked = facilitate.phase_acked_by(
                        self.hubs, meeting_id, cur_round, "comment",
                    )
                    self._logger.info(
                        "Kickoff phase=comment (round %d, poll %s, "
                        "%.0fs); waiting on %s.",
                        cur_round, poll_count, elapsed,
                        [a for a in expected_attendees if a not in acked],
                    )
                await asyncio.sleep(run_kickoff.KICKOFF_POLL_INTERVAL_SEC)
                continue

            if phase == "reply":
                # Comment phase done — fire kickoff_reply_phase_request
                # once, then wait for all attendees to ack reply phase.
                key = (cur_round, "reply")
                if key not in broadcasts_fired:
                    self._logger.info(
                        "Kickoff phase=reply (round %d, poll %s, %.0fs); "
                        "broadcasting kickoff_reply_phase_request.",
                        cur_round, poll_count, elapsed,
                    )
                    facilitate.request_reply_phase(
                        self.hubs, kickoff_handle,
                    )
                    broadcasts_fired.add(key)
                else:
                    acked = facilitate.phase_acked_by(
                        self.hubs, meeting_id, cur_round, "reply",
                    )
                    self._logger.info(
                        "Kickoff phase=reply (round %d, poll %s, "
                        "%.0fs); waiting on %s.",
                        cur_round, poll_count, elapsed,
                        [a for a in expected_attendees if a not in acked],
                    )
                await asyncio.sleep(run_kickoff.KICKOFF_POLL_INTERVAL_SEC)
                continue

            if phase == "facilitator":
                # synth=ready is TERMINAL — finalize deterministically rather
                # than waiting for the LLM facilitator to record a "consensus"
                # note. The facilitation pass exists only to RESOLVE non-ready
                # statuses (conflict / validation_failed); an already-ready
                # synthesis has cleared every gate (quorum + cross-checks +
                # roadmap validation), so gating its finalize on the
                # orchestrator-LLM behaving is pure fragility. youtube run #12
                # (2026-06-16): synthesis reached ready but the orchestrator-
                # facilitator was handed backend implementation context, never
                # recorded a consensus note, and a fully-ready kickoff polled to
                # its 1200s timeout with the lanes stuck in kickoff:action stage.
                # Finalize here; the LLM only sees facilitation when there is an
                # actual conflict to adjudicate (the consensus branch below
                # remains for the after-revisions-became-ready case).
                try:
                    ready_synth = run_kickoff.try_synthesize(
                        self.hubs, kickoff_handle,
                    )
                except Exception as exc:
                    self._logger.error(
                        "try_synthesize raised at facilitator ready-check "
                        "(round %d, poll %s): %s", cur_round, poll_count, exc,
                    )
                    ready_synth = {"status": "unknown"}
                if ready_synth.get("status") == "ready":
                    self._logger.info(
                        "synth=ready at facilitator phase — finalizing "
                        "deterministically (poll %s, %.0fs); no LLM consensus "
                        "required.", poll_count, elapsed,
                    )
                    return self._finalize_kickoff_and_author(
                        kickoff_handle, ready_synth,
                        poll_count=poll_count, elapsed=elapsed,
                    )
                # Not ready — fire kickoff_facilitate_request once, then wait
                # for orchestrator's facilitator_note to resolve the conflict.
                key = (cur_round, "facilitator")
                if key not in broadcasts_fired:
                    try:
                        synthesis = run_kickoff.try_synthesize(
                            self.hubs, kickoff_handle,
                        )
                    except Exception as exc:
                        self._logger.error(
                            "try_synthesize raised before facilitator "
                            "turn (round %d, poll %s): %s",
                            cur_round, poll_count, exc,
                        )
                        raise
                    self._logger.info(
                        "Kickoff phase=facilitator (round %d, poll %s, "
                        "%.0fs, synth=%s); requesting facilitation.",
                        cur_round, poll_count, elapsed,
                        synthesis.get("status"),
                    )
                    facilitate.request_facilitation(
                        self.hubs, kickoff_handle, synthesis,
                    )
                    broadcasts_fired.add(key)
                await asyncio.sleep(run_kickoff.KICKOFF_POLL_INTERVAL_SEC)
                continue

            # phase ∈ {consensus, request_revision, escalate} — the
            # facilitator has spoken. Read the actual note for content.
            note = facilitate.read_facilitator_decision(
                self.hubs, kickoff_handle,
            )
            if note is None:
                # current_phase said facilitator-action but the note was
                # racy — give it one more poll.
                self._logger.warning(
                    "Kickoff phase=%s but no facilitator_note found yet "
                    "for round %d; one more poll.",
                    phase, cur_round,
                )
                await asyncio.sleep(run_kickoff.KICKOFF_POLL_INTERVAL_SEC)
                continue

            note_content = note.get("content") or {}
            # Round 8h follow-up: facilitate.current_phase() already
            # coerced any invented action string (e.g.
            # "accept_revision_and_recenter") to a canonical
            # FACILITATOR_ACTIONS value when deciding ``phase`` above.
            # Re-coerce here so this branch sees the SAME canonical
            # action — otherwise the if/elif chain below would
            # fall through to "Unknown facilitator action" and
            # synthesize_fallback, exactly the failure mode Fix #O
            # was meant to prevent.
            action = coerce_facilitator_action(note_content.get("action"))
            # Re-run try_synthesize so the rest of the loop (consensus
            # → finalize, escalate → fallback) has fresh state.
            try:
                synthesis = run_kickoff.try_synthesize(self.hubs, kickoff_handle)
            except Exception as exc:
                self._logger.error(
                    "try_synthesize raised post-facilitator (round %d): %s",
                    cur_round, exc,
                )
                raise

            if action == "consensus":
                # Trust the facilitator's verdict, but re-poll
                # try_synthesize once more — the latest revisions may
                # have just made it ready. If still not ready, fall back
                # rather than finalize with a bad synthesis.
                if synthesis.get("status") != "ready":
                    synthesis = run_kickoff.try_synthesize(
                        self.hubs, kickoff_handle
                    )
                if synthesis.get("status") == "ready":
                    self._logger.info(
                        "Facilitator declared consensus (poll %s, "
                        "%.0fs); finalizing.",
                        poll_count, elapsed,
                    )
                    return self._finalize_kickoff_and_author(
                        kickoff_handle, synthesis,
                        poll_count=poll_count, elapsed=elapsed,
                    )
                self._logger.warning(
                    "Facilitator declared consensus but try_synthesize "
                    "still %r; attempting reconcile before fallback.",
                    synthesis.get("status"),
                )
                return self._kickoff_fallback_or_reconcile(
                    kickoff_handle, synthesis, "consensus_not_ready",
                )

            if action == "request_revision":
                cur_round = facilitate.current_round(
                    self.hubs, kickoff_handle["meeting_id"]
                )
                if cur_round >= facilitate.KICKOFF_MAX_ROUNDS:
                    self._logger.error(
                        "Kickoff hit max_rounds=%d; attempting reconcile "
                        "before fallback",
                        facilitate.KICKOFF_MAX_ROUNDS,
                    )
                    return self._kickoff_fallback_or_reconcile(
                        kickoff_handle, synthesis, "max_rounds",
                    )
                revisers = note_content.get("revisers") or []
                if not revisers:
                    self._logger.error(
                        "Facilitator requested revision but listed no "
                        "revisers; attempting reconcile before fallback."
                    )
                    return self._kickoff_fallback_or_reconcile(
                        kickoff_handle, synthesis, "no_revisers",
                    )
                self._logger.info(
                    "Facilitator requested revision from %s (round %d "
                    "-> %d).",
                    revisers, cur_round, cur_round + 1,
                )
                facilitate.request_revisions(
                    self.hubs, kickoff_handle, revisers, note,
                )
                # broadcasts_fired keys are (round, phase) tuples — the
                # new round will use fresh keys (round+1, *), so no
                # explicit reset needed. The current_phase computation
                # for round+1 will see no decisions yet for that round
                # and return "initial".
                await asyncio.sleep(run_kickoff.KICKOFF_POLL_INTERVAL_SEC)
                continue

            if action == "escalate":
                self._logger.error(
                    "Facilitator escalated kickoff; attempting reconcile "
                    "before fallback. rationale=%r",
                    note_content.get("rationale"),
                )
                return self._kickoff_fallback_or_reconcile(
                    kickoff_handle, synthesis, "escalate",
                )

            # Unknown action — fail loud (do NOT keep polling: an
            # unrecognized verdict means a contract drift, not a
            # transient state).
            self._logger.error(
                "Unknown facilitator action %r; attempting reconcile before "
                "fallback", action,
            )
            return self._kickoff_fallback_or_reconcile(
                kickoff_handle, synthesis, "unknown_action",
            )

    def _attempt_reconciled_finalize(self, kickoff_handle, reason: str):
        """Last-resort deterministic kickoff convergence (charter §8).

        Before aborting a kickoff that won't reach consensus, re-synthesize with
        ``reconcile=True`` — which prunes frontend api_calls to UNDEFINED
        endpoints (a UI call into the void; e.g. an invented ``GET /api/stories``)
        — and, if that makes the synthesis ``ready``, finalize the contract
        instead of failing the whole run. Returns the finalize receipt on
        success, or ``None`` (caller proceeds to ``synthesize_fallback``) when
        reconciliation can't produce a ready synthesis (a non-reconcilable
        conflict — dead endpoint, data-model drift — still aborts honestly).
        """
        from .runtime.kickoff import run_kickoff
        try:
            synth = run_kickoff.try_synthesize(
                self.hubs, kickoff_handle, reconcile=True,
            )
        except Exception as exc:  # pragma: no cover - defensive
            self._logger.warning(
                "Kickoff reconcile attempt raised (%s): %s", reason, exc,
            )
            return None
        if synth.get("status") != "ready":
            # Diagnostic: surface what's still blocking after pruning dangling
            # UI calls + downgrading dead endpoints, so the run log pinpoints
            # any residual runtime-fatal drift (e.g. api↔data_model) instead of
            # an opaque "still conflict".
            findings = synth.get("findings") or []
            details = [
                # cross-check findings carry detail/offending_field; roadmap
                # validation findings carry section/id/message — log whichever.
                (f.get("message") or f.get("detail")
                 or f.get("offending_field")
                 or f.get("id") or f.get("section"))
                for f in findings if isinstance(f, dict)
            ][:8]
            self._logger.warning(
                "Kickoff reconcile (%s) did not reach ready (status=%s); "
                "residual findings=%s — falling through to fallback.",
                reason, synth.get("status"), details,
            )
            return None
        added = synth.get("reconciled_added") or []
        normalized = synth.get("reconciled_normalized") or []
        self._logger.warning(
            "🔧 KICKOFF RECONCILE (%s): auto-registered %d endpoint(s) for frontend "
            "call(s) the backend didn't declare %s (the skeleton generates them); "
            "normalized %d endpoint-shape issue(s) %s → synthesis ready; finalizing "
            "instead of aborting the run.",
            reason, len(added), added, len(normalized), normalized[:6],
        )
        receipt = run_kickoff.finalize_kickoff(
            hubs=self.hubs,
            kickoff_handle=kickoff_handle,
            synthesis=synth,
            agent="orchestrator",
        )
        try:
            self._author_kickoff_docs(synth)
        except Exception as _auth_err:  # pragma: no cover - doc bug, not kickoff
            self._logger.warning(
                "kickoff authoring failed (non-fatal): %s", _auth_err,
            )
        return receipt

    def _kickoff_fallback_or_reconcile(
        self, kickoff_handle, last_synthesis, reason: str,
    ):
        """Try a deterministic reconcile-and-finalize before the hard abort.

        Wraps every kickoff abort site: if dangling-UI-call reconciliation can
        finalize the contract, return that receipt; otherwise fall through to
        the honest ``synthesize_fallback`` (kickoff_failed) path.
        """
        from .runtime.kickoff import run_kickoff
        receipt = self._attempt_reconciled_finalize(kickoff_handle, reason)
        if receipt is not None:
            return receipt
        return run_kickoff.synthesize_fallback(
            hubs=self.hubs,
            kickoff_handle=kickoff_handle,
            last_synthesis=last_synthesis,
            agent="orchestrator",
        )

    @staticmethod
    def _coordination_tick_due(
        *,
        event_set: bool,
        now: float,
        last_tick_at: float,
        loop_start: float,
        stuck_sec: float,
    ) -> bool:
        """Pure gate for the resident coordination-tick re-dispatch (Defect B,
        YOUTUBE_RUN_STALL_REVIEW).

        Fires when EITHER the lane's done-event is set (a clean tick finish) OR a
        wall-clock ``stuck_sec`` window has elapsed since the last tick. The latter
        is the decouple: the done-event stays False forever when the resident
        orchestrator's tick LLM-loops without finishing, which wedged the run
        (smoke #19 fixed this for the nudge but missed the tick). Bounded to one
        tick per stuck window (no flood). ``max(last_tick_at, loop_start)`` makes
        the first tick fire within ``stuck_sec`` even if the event never sets.
        Kept pure so the cadence is testable in isolation."""
        if event_set:
            return True
        return (now - max(last_tick_at, loop_start)) >= stuck_sec

    @staticmethod
    def _should_attempt_silent_lane_nudge(
        now: float,
        kickoff_finalized_at: float,
        last_nudge_attempt_at: float,
        grace_sec: float,
        interval_sec: float,
    ) -> bool:
        """Round 8h Patch B v2: pure decision for whether the
        coordination loop should run a silent-lane nudge attempt on
        the current wait_for-timeout iteration.

        Returns True iff BOTH:
          * At least ``grace_sec`` has elapsed since
            ``kickoff_finalized_at`` (lets kickoff_complete subscribers
            wake naturally before we assume bug).
          * At least ``interval_sec`` has elapsed since the previous
            nudge attempt (don't spam the bus / inbox).

        Kept pure so the wall-clock cadence is testable in isolation
        without booting the full coordination loop. Smoke #19 surfaced
        the v1 wiring bug (nested inside `if task_done.is_set()` which
        was False forever when the orchestrator lane LLM-looped on
        inbox reads) — this helper guarantees v2 cannot regress to
        the same gating mistake by accident.
        """
        if now - kickoff_finalized_at < grace_sec:
            return False
        if now - last_nudge_attempt_at < interval_sec:
            return False
        return True

    async def _dispatch_implementation_phase(self) -> List[str]:
        """§5-entry / D4.3 (reframed): deterministically hand the implementation
        phase to the lanes the moment kickoff finalizes.

        finalize_kickoff already created + assigned the task tree; this is the
        ``[P]`` dispatch step (pipeline_process_design.md §4 D4.3 / §5.1). Smoke
        #3 (2026-06-05) proved the old "lanes wake on kickoff_complete + a later
        nudge" path fails: kickoff_complete isn't a ``task_ready`` so it doesn't
        pass ``KickoffBootstrapGate`` (allowed_starters=['orchestrator']), and the
        lanes burn their idle budget on empty kickoff-reply finishes and get
        ``LaneIdleCircuitBreaker``-halted before they ever implement.

        So, right after finalize, we:
          1. RESET each lane's idle counters — the kickoff-reply phase must not
             pre-halt the implementation phase (fresh budget at the boundary).
          2. DISPATCH an orchestrator ``task_ready`` to each implementation lane
             with assigned work — which passes ``KickoffBootstrapGate`` and makes
             the lane claim + implement (one-pass), no subscription/nudge race.

        The verifier is intentionally NOT dispatched here — it self-triggers on
        impl-completion (the §6 / ⚠2 validation-ready hub signal)."""
        from tools.communication_tools import _create_message

        # 1. Reset idle counters at the kickoff→implement boundary.
        for lane_id, agent in self._agents.items():
            if agent is None:
                continue
            agent._consecutive_idle_steps = 0
            agent._last_idle_tier = 0
            agent._lane_idle_tier3_failed = False
            # None forces the breaker to re-seed its "owned" baseline on the next
            # finish — so the first implementation step is never counted as idle.
            agent._lane_idle_prev_owned = None

        # 2. Which lanes have assigned implementation tasks?
        try:
            tasks = self.hubs.workhub.list_tasks() or {}
            task_iter = tasks.values() if isinstance(tasks, dict) else tasks
        except Exception:
            task_iter = []
        assignees = set()
        for t in task_iter:
            if not isinstance(t, dict):
                continue
            a = str(t.get("owner") or t.get("assignee") or "").strip().lower()
            if a:
                assignees.add(a)
        # The code-writing impl lanes (verifier validates later; orchestrator
        # coordinates; knowledge is an observer).
        impl_lanes = {"backend", "frontend"}
        targets = [
            lane for lane in self._agents
            if lane in impl_lanes and (lane in assignees or True)
        ]

        dispatched: List[str] = []
        for lane_id in targets:
            msg = _create_message(
                source_agent_id="orchestrator",
                target_agent_id=lane_id,
                content=(
                    "Kickoff finalized — the M1 contract (endpoints/tables/pages) "
                    "and your assigned task_tree entries are registered in "
                    "RegistryHub/WorkHub. Claim your tasks now "
                    f"(workhub_list_tasks assignee='{lane_id}', status='pending') "
                    "and implement them in one pass. Do NOT ack-and-wait."
                ),
                msg_type="task_ready",
                priority="urgent",
                persist=True,
                tags=["kickoff_dispatch", "implementation_start"],
            )
            try:
                if await self.message_bus.send(msg):
                    dispatched.append(lane_id)
            except Exception as exc:
                self._logger.warning("impl dispatch to %s failed: %s", lane_id, exc)
        self._logger.info(
            "Dispatched implementation phase task_ready to: %s",
            ", ".join(dispatched) or "none",
        )
        return dispatched

    async def _nudge_silent_resident_lanes(
        self,
        kickoff_finalized_at: float,
    ) -> List[str]:
        """Round 8h Patch B: dispatch urgent task_ready to any resident
        lane that has produced ZERO ``agent_status`` events since
        ``kickoff_finalized_at`` — the structural fix for the smoke #18
        Frontend/Verifier never-woke pathology.

        The orchestrator coordination loop calls this at
        ``idle_tick_count >= 3``. Pre-fix the only escalation was a
        textual instruction on the resident_coordination_tick prompt
        ("you've been idle 3 ticks; escalate") which had no effect
        when the OTHER lanes were the ones never waking — the
        orchestrator lane is the one reading that prompt, and it
        cannot wake a peer by reading text.

        Behavior:
          * Reads ``eventhub.get_all_agent_statuses()`` and finds the
            last agent_status timestamp per resident lane id.
          * A lane is "silent" if it has NO agent_status entry OR
            its latest entry is older than ``kickoff_finalized_at``.
          * For each silent lane (excluding the orchestrator itself,
            which is by design the polling coordinator), construct a
            ``msg_type=task_ready`` message with URGENT priority and
            send it through the message bus.
          * Increment ``self._silent_lane_nudges[lane_id]`` so a
            future iteration can detect "still silent after N nudges"
            and escalate further (loud log; structural failure of the
            subscription path).

        Returns the list of lane ids that were nudged this call. An
        empty list means every lane has emitted at least one
        agent_status since finalize — no escalation needed.

        Charter §8: this is closed-by-construction (the orchestrator
        either gets evidence of liveness or sends a structured wake
        signal — no "log and hope" path).
        """
        from tools.communication_tools import _create_message
        try:
            all_statuses = self.hubs.eventhub.get_all_agent_statuses() or {}
        except Exception as exc:
            self._logger.warning(
                "Could not read agent statuses for stall escalation: %s",
                exc,
            )
            return []

        nudged: List[str] = []
        for lane_id in self._agents:
            if lane_id == "orchestrator":
                continue
            status = all_statuses.get(lane_id) or {}
            last_at = status.get("_event_created_at", 0.0)
            if last_at and last_at > kickoff_finalized_at:
                # Lane has emitted an agent_status post-finalize, so
                # it is provably alive. Reset its nudge counter so the
                # next stall episode starts clean.
                self._silent_lane_nudges.pop(lane_id, None)
                continue

            prior_nudges = self._silent_lane_nudges.get(lane_id, 0)
            # FIX #41 (speed): cap stall nudges per lane per stall-episode. A lane
            # silent after several urgent nudges is STUCK (long LLM self-loop or
            # genuinely wedged) — re-sending an urgent persist=True task_ready every
            # 60s for the rest of the run just FLOODS its inbox (163-msg inboxes
            # observed), and since every lane re-scans its whole inbox each step,
            # the flood slows the ENTIRE run (good runs hit the 2h wall-clock cap
            # this way) without ever un-sticking the lane. The counter resets the
            # moment the lane emits any agent_status (line above), so this caps per
            # episode, not for the whole run.
            _MAX_SILENT_NUDGES = int(os.environ.get("ENVGEN_MAX_SILENT_NUDGES", "4"))
            if prior_nudges >= _MAX_SILENT_NUDGES:
                if prior_nudges == _MAX_SILENT_NUDGES:
                    self._silent_lane_nudges[lane_id] = prior_nudges + 1  # bump once so we log once
                    self._logger.warning(
                        "Stall escalation: lane %s still silent after %d nudges — "
                        "SUPPRESSING further nudges this episode (avoid inbox flood "
                        "that stalls the whole run).",
                        lane_id, prior_nudges,
                    )
                continue
            message = _create_message(
                source_agent_id="orchestrator",
                target_agent_id=lane_id,
                content=(
                    "Stall escalation: kickoff_complete fired but you "
                    "have produced no agent_status events since finalize. "
                    "Pick up your assigned kickoff task_tree entries from "
                    "WorkHub and start executing. Do not ack and wait — "
                    "run your one-pass step_contract NOW."
                ),
                msg_type="task_ready",
                priority="urgent",
                persist=True,
                tags=["stall_escalation", "kickoff_followup"],
            )
            try:
                delivered = await self.message_bus.send(message)
            except Exception as exc:
                self._logger.error(
                    "Stall escalation: bus.send to %s raised %s",
                    lane_id, exc,
                )
                continue
            if not delivered:
                self._logger.error(
                    "Stall escalation: bus.send to %s returned False "
                    "(target not registered with bus). Lane "
                    "spawn-time wiring is broken upstream.",
                    lane_id,
                )
                continue
            self._silent_lane_nudges[lane_id] = prior_nudges + 1
            nudged.append(lane_id)
        return nudged

    def _author_kickoff_docs(
        self, synthesis: Dict[str, Any],
    ) -> None:
        """Round 8f.2: after finalize_kickoff returns a clean receipt,
        materialize the human-readable milestone docs to disk.

        Writes (under ``self.output_dir``):
          * ``docs/milestones/MILESTONE_M{n}.md`` (overwrite)
          * ``docs/ROADMAP.md`` (idempotent append/replace by M-section)
          * ``docs/briefings/BRIEFING_M{n}_{agent}.md`` per attendee

        Uses :mod:`runtime.kickoff.authoring` — pure-Python rendering,
        no LLM call. Determinism is enforced by passing the same
        synthesis_result the driver already used for finalize_kickoff.

        Errors are intentionally swallowed by the caller: the contract
        ALREADY shipped via finalize_kickoff before this runs; a
        markdown-write failure must not invalidate that. The caller
        logs at WARNING so a debug pass can pick up the failure.
        """
        from .runtime.kickoff.authoring import author_all
        # Read existing ROADMAP.md (if any) so we append/replace
        # idempotently rather than blowing away prior milestones.
        roadmap_path = self.output_dir / "docs" / "ROADMAP.md"
        prior_roadmap_md: Optional[str] = None
        if roadmap_path.exists():
            try:
                prior_roadmap_md = roadmap_path.read_text(encoding="utf-8")
            except OSError as _e:
                self._logger.warning(
                    "Could not read existing %s (%s); rewriting from scratch.",
                    roadmap_path, _e,
                )
        project_name = getattr(self.context, "name", None) or "Project"
        outputs = author_all(
            synthesis,
            project_name=project_name,
            prior_roadmap_md=prior_roadmap_md,
        )
        # Write artifacts. Paths in `outputs["paths"]` are relative; we
        # anchor under output_dir so they land alongside the project
        # workspace (CI repo / live_monitor inspection / etc.).
        milestone_path = self.output_dir / outputs["paths"]["milestone"]
        milestone_path.parent.mkdir(parents=True, exist_ok=True)
        milestone_path.write_text(outputs["milestone"], encoding="utf-8")

        roadmap_path.parent.mkdir(parents=True, exist_ok=True)
        roadmap_path.write_text(outputs["roadmap"], encoding="utf-8")

        for agent_id, briefing_md in (outputs.get("briefings") or {}).items():
            rel = outputs["paths"]["briefings"][agent_id]
            briefing_path = self.output_dir / rel
            briefing_path.parent.mkdir(parents=True, exist_ok=True)
            briefing_path.write_text(briefing_md, encoding="utf-8")

        self._logger.info(
            "Authored kickoff docs: %s + %s + %d briefings",
            milestone_path, roadmap_path,
            len(outputs.get("briefings") or {}),
        )

    async def _generate_docker(self):
        """Generate docker-compose.yml."""
        db_port = self.context.db_port
        backend_port = self.context.backend_internal_port
        api_port = self.context.api_port
        ui_port = self.context.ui_port
        
        docker_compose = f'''version: '3.8'

# Generated with run-specific free host ports.
# Target = forgingground/agentsuite env (see docs/target_env_architecture.md):
# FastAPI backend + stock postgres (schema delivered via init/ mount, NOT a
# custom db image) + React/Vite frontend. Agents may edit host-side port
# mappings if validation finds conflicts.

services:
  database:
    image: postgres:16
    environment:
      POSTGRES_USER: sandbox
      POSTGRES_PASSWORD: sandbox
      POSTGRES_DB: app
      PGPORT: {db_port}
    volumes:
      - ../app/database/init:/docker-entrypoint-initdb.d:ro
    ports:
      - "{db_port}:{db_port}"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U sandbox -d app -p {db_port}"]
      interval: 5s
      timeout: 5s
      retries: 20
      start_period: 30s

  backend:
    build: ../app/backend
    environment:
      DATABASE_URL: postgresql+psycopg://sandbox:sandbox@database:{db_port}/app
      API_PORT: {backend_port}
      # Embedded OAuth2 AS (zoom-style): the env mints its OWN RS256 tokens.
      # OAUTH_ISSUER is intentionally unset → derived from request.base_url.
      OAUTH_DEFAULT_AUDIENCE: app-api
      OAUTH_DEFAULT_SCOPE: app.read app.write app.admin
      OAUTH_ACCESS_TOKEN_TTL: "3600"
      JWT_DATA_DIR: /var/lib/app-auth
      APP_PASSWORD_SALT: app_sandbox_salt_2024
    volumes:
      - app_auth_keys:/var/lib/app-auth   # persist the RSA signing key across restarts
    ports:
      - "{api_port}:{backend_port}"
    depends_on:
      database:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:{backend_port}/health', timeout=5)"]
      interval: 10s
      timeout: 5s
      retries: 10
      start_period: 30s

  frontend:
    build: ../app/frontend
    environment:
      UI_PORT: 3000
      API_URL: http://backend:{backend_port}
    ports:
      - "{ui_port}:3000"
    depends_on:
      - backend

volumes:
  app_auth_keys:
'''
        
        docker_dir = self.output_dir / "docker"
        docker_dir.mkdir(exist_ok=True)
        (docker_dir / "docker-compose.yml").write_text(docker_compose)

    async def _generate_database(self):
        """Author ``app/database/`` deterministically from the registered
        SchemaHub tables.

        Closed-by-construction sibling to ``_generate_docker``: the
        compose file unconditionally declares a ``database`` service whose
        build context is ``../app/database`` and the delivery gate requires
        ``app/database/*.sql``, but no LLM lane reliably wrote that dir
        (0/10 across smokes #38-49). The kickoff validator guarantees every
        registered table carries a non-empty ``columns: [{name, type}]``
        list, so once kickoff finalizes the runtime holds everything needed
        to emit a faithful ``CREATE TABLE`` schema — no agent, no variance.
        The runtime is the SOLE owner of ``app/database/``.

        Called once, post-``finalize_kickoff`` (tables are registered by
        then). Idempotent — overwrites so the scaffold always reflects the
        current contract."""
        from .runtime.database_scaffold import write_database_scaffold

        tables = self.hubs.schema_hub.list_tables() or {}
        paths = write_database_scaffold(self.output_dir, tables)
        self._logger.info(
            "Authored app/database/ scaffold: %d table(s) → %s",
            paths["table_count"], paths["schema_sql"],
        )

    def _generate_backend_skeleton(self) -> None:
        """SKELETON根治 (2026-06-09, user-chosen): generate the ENTIRE backend
        DETERMINISTICALLY from the contract (SchemaHub tables + RegistryHub endpoints) — ORM
        models, all CRUD handlers, fixed storage/auth/infra — OVERWRITING whatever the
        lane wrote. This removes the lane's STRUCTURAL non-determinism at the source
        (across runs it wrote ORM/raw-SQL/file-based-JSON/fragmented apps that DB-centric
        repairs couldn't all cover): the same contract now always yields a consistent,
        complete, auth-enforced, all-2xx backend with real persistence (reconstruction-
        proven by a docker build+boot). The lane's role shrinks to AUTHORING THE
        CONTRACT. Best-effort; idempotent (deterministic → byte-identical)."""
        try:
            out_dir = getattr(self, "output_dir", None)
            if not out_dir:
                return
            from .runtime.backend_skeleton import write_backend_skeleton
            from .runtime.lifecycle import business_endpoints
            sh = getattr(self.hubs, "schema_hub", None)
            registryhub = getattr(self.hubs, "registryhub", None)
            tables = (sh.list_tables() if sh else {}) or {}
            endpoints = business_endpoints(registryhub.get_endpoints() or {}) if registryhub else []
            if not tables and not endpoints:
                return  # contract not finalized yet — nothing to project
            res = write_backend_skeleton(out_dir, endpoints, tables)
            self._logger.warning(
                "BACKEND SKELETON generated by-construction from the contract "
                "(%d tables, %d endpoints) — the whole backend is framework-owned "
                "(deterministic, consistent, auth-enforced): %s",
                len(tables), len(endpoints), res.get("written"))
            # Mechanism #43 (round 32: 17 endpoint tasks cancelled in cascade):
            # the skeleton just MATERIALIZED every contract table as ORM+DDL,
            # but their RegistryHub status stayed 'defined' — so the impl.table.*
            # dispatch tasks never auto-completed, every impl.endpoint.* task
            # stayed depends_on-blocked, and the backend talked the
            # orchestrator into bulk-cancelling the plan. Flip the generated
            # tables to implemented (by-construction truth); register_table
            # cascades sync_impl_table_completed → tasks complete → deps clear.
            if registryhub is not None:
                for _tname in (tables or {}):
                    try:
                        _cur = registryhub.get_table(_tname) or {}
                        if (_cur.get("status") or "").lower() != "implemented":
                            registryhub.register_table(
                                _tname, agent="orchestrator", status="implemented")
                    except Exception:
                        pass
        except Exception as exc:
            self._logger.debug("backend skeleton generation skipped: %s", exc)
        # Mechanism #50: audit the registered ui_pages against the actual
        # frontend code and flip defined→implemented (cascades impl.page.*
        # completion) — the frontend's analog of the table flip above.
        try:
            from .runtime.frontend_audit import sync_ui_page_statuses
            _pa = sync_ui_page_statuses(self.output_dir, self.hubs.workhub,
                                        registryhub=getattr(self.hubs, "registryhub", None))
            if _pa.get("implemented") or _pa.get("regressed"):
                self._logger.warning(
                    "UI-PAGE LIFECYCLE: implemented=%s regressed=%s pending=%s",
                    _pa.get("implemented"), _pa.get("regressed"),
                    list((_pa.get("pending") or {}).keys()))
        except Exception:
            pass

    async def _seed_base_scaffold(self):
        """Seed the FIXED contract surface into the git base, pre-spawn.

        The target env IS its own OAuth2 AS (zoom-style); its three modules —
        ``jwt_manager.py`` (RS256 sign + JWKS), ``oauth_store.py`` (psycopg3 store
        over the spine), ``oauth_routes.py`` (authorize/token/register + PKCE
        S256) — are pure infrastructure with zero business logic, and the
        backend's ``main.py`` IMPORTS them. Re-authoring an OAuth2 AS per run via
        an LLM lane is the textbook drift source (a salt mismatch, a missing PKCE
        check, a ``sub`` that isn't the user id → no token mints or verifies).

        So the runtime emits them verbatim AND commits them to the git base
        BEFORE any agent worktree exists. Because every ``agent/<id>`` worktree
        branches off base HEAD (and ``integration`` is bootstrapped from the
        first agent branch), all lanes inherit the AS modules by construction:
        the backend's imports/lint resolve in-worktree, and git — not a prompt
        convention — owns the "do not author these" boundary. Idempotent."""
        from .runtime.oauth_scaffold import write_oauth_as, AS_MODULES

        # ensure the git repo exists before we commit (it is otherwise lazily
        # init'd by the first register_agent_worktree, which runs during spawn).
        self.hubs.codehub.ensure_repo()
        result = write_oauth_as(self.output_dir)
        rel_paths = [f"app/backend/{m}" for m in AS_MODULES]
        # Scaffold a runnable BASE ``main.py`` too. The backend lane BLOCKS trying to
        # READ app/backend/main.py to add its route handlers — but nothing creates it
        # (the framework owns only the AS modules), so the lane spins reporting
        # "scaffold exists but main.py absent" instead of writing code. Provide a
        # valid FastAPI app (AS wired, /health, uvicorn entrypoint) committed to the
        # git base pre-spawn so every lane inherits it; the backend then ADDS business
        # routes to it. Same "framework owns the boilerplate" basis as the AS modules.
        main_py = self.output_dir / "app" / "backend" / "main.py"
        if not main_py.exists():
            main_py.parent.mkdir(parents=True, exist_ok=True)
            main_py.write_text(_BASE_MAIN_PY, encoding="utf-8")
            rel_paths.append("app/backend/main.py")
        # The backend Dockerfile COPYs reset.sh; scaffold a base one so the image
        # always builds (the lane may overwrite it with an app-specific reset).
        reset_sh = self.output_dir / "app" / "backend" / "reset.sh"
        if not reset_sh.exists():
            reset_sh.parent.mkdir(parents=True, exist_ok=True)
            reset_sh.write_text(_BASE_RESET_SH, encoding="utf-8")
            try:
                reset_sh.chmod(0o755)
            except Exception:
                pass
            rel_paths.append("app/backend/reset.sh")
        sha = self.hubs.codehub.commit_runtime_scaffold(
            rel_paths,
            "bootstrap: embedded OAuth2 AS modules + base main.py (runtime-owned)",
        )
        self._logger.info(
            "Seeded base scaffold (commit %s): %s",
            (sha or "noop")[:12], ", ".join(Path(p).name for p in result["written"]),
        )

    def _register_contract_surface(self):
        """Register the FIXED contract surface (spine tables + AS/auth endpoints)
        in RegistryHub/SchemaHub under actor='orchestrator', post-kickoff.

        Consistency-by-construction: the tenancy spine tables and the embedded-AS
        / first-party-auth endpoints are deterministic and runtime-owned, so the
        orchestrator publishes them to the contract truth-source rather than
        relying on prose + a hardcoded delivery-gate exemption. The AS/auth
        endpoints are tagged ``kind='auth'|'oauth'`` so the frontend's
        response_key-keyed api.js generator SKIPS them (they are fixed-spec with
        heterogeneous shapes — a 302 redirect, a {access_token}, a JWKS doc).

        Idempotent: RegistryHub/SchemaHub register_* are merge-upserts keyed on
        (method, path) / table name (Charter §8 — re-registration never errors)."""
        from .runtime.database_scaffold import SPINE_TABLE_RECORDS
        from .runtime.oauth_scaffold import AS_CONTRACT_ENDPOINTS
        from .runtime.control_plane import CONTROL_SURFACE_ENDPOINTS

        tables_n = 0
        for rec in SPINE_TABLE_RECORDS:
            try:
                self.hubs.schema_hub.register_table(
                    name=rec["name"],
                    schema={"columns": rec["columns"]},
                    provider="backend",
                    agent="orchestrator",
                    status="implemented",
                    kind="spine",
                )
                tables_n += 1
            except Exception as exc:  # never block the run on a contract publish
                self._logger.warning("spine table register failed (%s): %s", rec["name"], exc)

        eps_n = 0
        for ep in (*AS_CONTRACT_ENDPOINTS, *CONTROL_SURFACE_ENDPOINTS):
            try:
                self.hubs.registryhub.register_endpoint(
                    method=ep["method"],
                    path=ep["path"],
                    schema={"request": ep.get("request", {}), "response": ep.get("response", {})},
                    provider="backend",
                    agent="orchestrator",
                    status="implemented",
                    kind=ep["kind"],
                    auth_required=ep.get("auth_required", False),
                    summary=ep.get("summary", ""),
                )
                eps_n += 1
            except Exception as exc:
                self._logger.warning("fixed endpoint register failed (%s %s): %s",
                                     ep["method"], ep["path"], exc)

        self._logger.info(
            "Registered fixed contract surface: %d spine table(s) + %d auth/oauth/infra endpoint(s)",
            tables_n, eps_n,
        )

    async def _generate_mcp(self):
        """Project the FastMCP server (``mcp_server/<env>/``) 1:1 from the
        registered BUSINESS endpoints + register the server and its tools.

        Consistency-by-construction (Phase 3c): the MCP tool surface is a
        deterministic projection of the RegistryHub business contract, so it cannot
        drift from the endpoints — the runtime emits it; an LLM never re-authors
        an MCP server. Only BUSINESS endpoints become tools; the fixed
        auth/oauth/infra/spine surface is excluded (it's protocol/infra, not an
        agent-drivable operation).

        Registered with ``status='implemented'`` — which (a) exempts the tools
        from the dead-tool coverage gate (they are consumed by the EXTERNAL
        red-team agent, not the env's own frontend, so zero internal consumers is
        correct by construction) and (b) makes RunHub skip the in-run liveness
        probe (the agentsuite-red pool launches + probes the MCP, not env-gen).
        Post-kickoff, untracked ``output_dir`` write (like the DB DDL)."""
        from .runtime.mcp_scaffold import write_mcp_server, business_endpoints

        endpoints = self.hubs.registryhub.get_endpoints() or {}
        if not business_endpoints(endpoints):
            self._logger.info("No business endpoints registered — skipping MCP projection.")
            return

        env_name = "app"
        # SPEC TOOL NAMES (2026-06-11): when the compiled reference spec binds
        # MCP tools to endpoints, the server emits the SPEC'S semantic names
        # (get_profile_info, publish_media, ...) — the 22 mcp_tool_exists
        # deliverability gates then bind by construction instead of failing on
        # derived endpoint-style names.
        _aliases = {}
        try:
            from .runtime.mcp_scaffold import spec_tool_aliases
            import json as _json
            _spec_path = Path(self.output_dir) / "design" / "reference_spec.json"
            if _spec_path.is_file():
                _aliases = spec_tool_aliases(_json.loads(_spec_path.read_text()))
                if _aliases:
                    self._logger.info("MCP spec tool aliases: %d bound", len(_aliases))
        except Exception:
            _aliases = {}
        result = write_mcp_server(self.output_dir, endpoints, env_name=env_name,
                                  tool_aliases=_aliases)

        mcp_reg = getattr(self.hubs, "mcp_registry", None)
        if mcp_reg is None:
            self._logger.warning(
                "mcp_registry unavailable — emitted mcp_server/%s/ (%d tools) but did not register.",
                env_name, result["tool_count"],
            )
            return

        try:
            mcp_reg.register_mcp_server(
                name=env_name, transport="http",
                endpoint=f"mcp_server/{env_name}/main.py",
                provider="backend", agent="orchestrator", status="implemented",
            )
            registered = 0
            for rec in result["tools"]:
                res = mcp_reg.register_mcp_tool(
                    server_name=env_name, tool_name=rec["tool_name"],
                    schema=rec["schema"], provider="backend",
                    agent="orchestrator", status="implemented",
                )
                if isinstance(res, dict) and res.get("error"):
                    self._logger.warning("MCP tool register failed (%s): %s",
                                         rec["tool_name"], res["error"])
                else:
                    registered += 1
            self._logger.info(
                "Projected MCP server mcp_server/%s/: %d tool(s) emitted, %d registered.",
                env_name, result["tool_count"], registered,
            )
        except Exception as exc:  # never block the run on a contract publish
            self._logger.warning("MCP registration failed: %s", exc)

    @staticmethod
    def _verifier_trigger_due(impl_epoch: int, last_triggered_epoch: int) -> bool:
        """Re-armable guard for the orchestrator→verifier validation trigger
        (Design A). Fire when the current implemented-endpoint epoch differs from
        the epoch we last triggered on — so the verifier is triggered ONCE per
        impl epoch (no wakeup storm) yet RE-ARMS when the impl lanes implement
        more endpoints (i.e. after they fix the bugs the verifier filed). A
        permanent boolean would validate once and never again after a fix — the
        trap this avoids. Pure → unit-tested in test_verifier_validation_trigger."""
        return impl_epoch != last_triggered_epoch

    async def _maybe_run_framework_validation(self) -> None:
        """Deterministically run api_smoke + record the RunHub run when the
        contract is fully implemented and no gate-passing run exists yet.

        WHY: the verifier/orchestrator LLMs run run_validation too early
        (pre-merge → ~700ms fast-fail) and don't retry, so a WORKING app (proven:
        run_smoke_validation passes manually on the generated tree) never records
        the RunHub run the delivery gate requires (compute_deliverability blocker
        #1). This runs the SAME deterministic procedure (RunValidationTool: clean
        docker boot + live probe of every business endpoint + record_run/probes
        with framework authority) once per idle tick until it passes — natural
        retry across ticks as the merge/app settles. Capped so a genuinely broken
        app doesn't churn docker forever. Best-effort: never raises into the loop."""
        try:
            from .runtime.lifecycle import all_business_endpoints_implemented
            registryhub = getattr(self.hubs, "registryhub", None)
            if registryhub is None:
                return
            # FIX #25: surface committed agent-branch work to integration every
            # tick (before the gate), so the integrated app reflects code the
            # lanes wrote+committed even before they finish-merge.
            self._merge_committed_agent_work()
            # design/README.md is a delivery-gate required artifact but lives outside
            # the app-source signature, so scaffold it unconditionally (write-if-
            # missing) — cheap, and keeps the final delivery gate from failing an
            # otherwise-working app on a missing doc.
            self._scaffold_design_readme()
            # OPTIMIZATION (heal-on-change): the deterministic heal repairs
            # (frontend baseline/api.js, backend entrypoint/AS-wiring/auth, ORM-DDL)
            # are idempotent, but re-running them EVERY coordination tick is wasteful
            # (the ORM introspection spawns a subprocess; file IO) and needlessly
            # races the lanes. Gate them on a CONTENT signature of the integrated app
            # source: heal only when the lanes actually changed something. CRUCIALLY,
            # reset the validation attempt-cap on that same change — FIX #31 only
            # reset on endpoint-COUNT increase, so an app made deliverable by a REPAIR
            # (e.g. the DDL/auth fix, not a new endpoint) stayed capped and never got
            # re-validated → no delivery. Now any real source change → fresh budget.
            _app_sig = self._compute_app_source_signature()
            if _app_sig is None or _app_sig != getattr(self, "_fwval_healed_sig", None):
                # SKELETON根治: regenerate the WHOLE backend from the contract FIRST, so
                # validation runs on the deterministic, by-construction app — not on the
                # lane's variably-structured one. The backend repairs below then no-op on
                # a correct skeleton (kept as a safety net); the frontend repairs still
                # matter (skeleton is backend-only).
                self._generate_backend_skeleton()
                self._scaffold_frontend_baseline()
                self._repair_frontend_api()
                # FRONTEND SKELETON: project the contract-derived page set BEFORE
                # validation, so the frontend_navigable gate validates the real
                # deliverable (idempotent — only fills routes that don't exist; with
                # zero declared ui_pages the page set derives from the API contract).
                self._repair_backend_entrypoint()
                self._repair_backend_as_wiring()
                self._repair_backend_auth()
                self._repair_backend_packaging()
                self._repair_ddl_from_orm()
                self._repair_handler_fk_aliases()
                self._repair_psycopg_dsn()
                # RESILIENCE (stuck-loop breaker): record the post-heal signature so
                # the heal-gate (line above) only re-heals when the *integrated source*
                # changed — but DO NOT reset the validation budget on that delta. The
                # heal/skeleton/DDL regeneration is the orchestrator's OWN output and is
                # not byte-stable across cycles (subprocess ORM introspection ordering,
                # write churn), so a post-heal-signature reset re-granted a fresh fast
                # budget EVERY cycle → the FAST cap never tripped → the SAME failing
                # validation cycle (merge → regen → run_validation → fail) spun every
                # ~60s forever with zero agent activity (observed: 36 identical cycles).
                # The fast budget is now reset ONLY on genuine LANE progress: a rising
                # implemented-endpoint count (below) or a CHANGED failure set (after the
                # validation result is known) — never on self-induced signature churn.
                self._fwval_healed_sig = self._compute_app_source_signature()
            # FIX #26: fire when the contract is implemented by registryhub registration
            # OR by route code present in the integrated source (registration lags
            # the actual code). api_smoke is the real arbiter downstream.
            if not (all_business_endpoints_implemented(registryhub.get_endpoints())
                    or self._all_business_endpoints_have_route_code()):
                return
            session_ts = getattr(self, "_session_start_ts", 0.0) or 0.0
            runhub = getattr(self.hubs, "runhub", None)
            if runhub is not None and hasattr(runhub, "last_successful_run_since"):
                if runhub.last_successful_run_since(session_ts):
                    return  # already have a gate-passing run
            # FIX #31: reset the attempt cap on real progress. The 6-attempt
            # cap (anti-docker-churn) was exhausting in a ~5-min window WHILE the
            # app was still implementing/merging (instagram-core: all 6 attempts
            # 05:13-05:19 reported "app may still be booting/merging", then
            # endpoints kept landing until 05:37 — by which point the now-ready,
            # all-22-implemented app could NEVER be re-validated → no delivery).
            # Reset the counter whenever the implemented-endpoint count rises, so
            # validation keeps retrying as the app converges; the cap only bites
            # once the app is STABLE and still failing. Same self-reset shape as
            # FIX #28's ask_cap.
            try:
                from .runtime.lifecycle import business_endpoints
                _cur_impl = sum(
                    1 for e in business_endpoints(registryhub.get_endpoints() or {})
                    if isinstance(e, dict) and e.get("status") == "implemented"
                )
            except Exception:
                _cur_impl = 0
            if _cur_impl > getattr(self, "_fwval_last_impl_count", -1):
                self._fwval_last_impl_count = _cur_impl
                self._framework_validation_attempts = 0
            # PIPE-C2: cap the FAST (every-tick) retries to stop docker churn, but
            # past the cap DOWNSHIFT to a slow retry instead of hard-stopping — a
            # sig-stable app failing on transient docker contention must still
            # eventually record the gate-required RunHub run (else: silent budget
            # death, 0 release). _fwval_should_attempt gates the slow phase by a
            # wall-clock interval; attempts stays pinned at the cap (logs read 6/6).
            _attempts = getattr(self, "_framework_validation_attempts", 0)
            _now = time.time()
            if not _fwval_should_attempt(
                    _attempts, getattr(self, "_fwval_last_attempt_ts", 0.0), _now):
                return  # capped + within the slow-retry interval — wait, don't churn
            self._fwval_last_attempt_ts = _now
            if _attempts < FWVAL_FAST_CAP:
                self._framework_validation_attempts = _attempts + 1
            from tools.validation_tools import RunValidationTool
            tool = RunValidationTool(workspace=None)
            tool._hubs = self.hubs
            tool._agent_id = "orchestrator"
            res = await tool.execute()
            # ── Verifier self-trigger (Design A — PROPOSAL #2, reviewed_version:2 PASS) ──
            # The deterministic driver (NOT the orchestrator LLM) wakes the verifier to run its
            # validation pass whenever api_smoke is ATTEMPTED on a bootable impl (we reach here
            # only past the route-code floor at :2751-2753), independent of the canonical
            # `validation_ready` signal — which needs ALL endpoints `implemented` and did NOT
            # fire in run #15 (validation_ready count=0), leaving the verifier idle
            # `awaiting ['frontend']` forever because the frontend finished notify=[] (Defect C).
            # Re-armable, keyed to the impl epoch (`_fwval_last_impl_count`, updated at :2777-78):
            # one guarded message per epoch (no storm); re-fires after the impl lanes implement
            # MORE endpoints — i.e. after they fix the bugs the verifier filed. Placed AFTER
            # tool.execute() so the verifier validates a SETTLED docker stack (no contention with
            # the framework's own api_smoke boot), but fired UNCONDITIONALLY (not gated on the
            # api_smoke result). Do NOT move this above the passing-run early-return at :2756-58:
            # once a clean run exists this function returns first and the canonical
            # `validation_ready` (all-implemented) path owns the verifier — this driver trigger is
            # the failing/pre-pass regime only. DEPENDS ON a3aea89: task_ready must wake an IDLE
            # resident lane (allow_resident_wakeup → allow_task_ready); if reverted this silently
            # no-ops (guarded by tests/test_verifier_validation_trigger.py).
            try:
                _epoch = getattr(self, "_fwval_last_impl_count", -1)
                if self._verifier_trigger_due(
                        _epoch, getattr(self, "_verifier_triggered_impl_count", -1)):
                    from tools.communication_tools import _create_message
                    _vmsg = _create_message(
                        source_agent_id="orchestrator", target_agent_id="verifier",
                        content=(
                            "Implementation is bootable and api_smoke is being validated — run "
                            "your validation pass now: docker_up -> the 5 check categories "
                            "(build:docker / build:frontend / validation:api_smoke / "
                            "validation:ui_smoke / validation:ui_flow:<name>) -> bug_create per "
                            "failure -> route summary -> finish."
                        ),
                        msg_type="task_ready", priority="urgent", persist=True,
                    )
                    # _create_message has NO metadata kwarg; inject the explicit-trigger key
                    # post-construction. validation_phase=True alone satisfies
                    # VerifierValidationTriggerPolicy.explicit_trigger (workflow_policies.py:327),
                    # with zero dependence on env-configured accepted_tags/phases/keywords.
                    _vmsg.metadata["validation_phase"] = True
                    await self.message_bus.send(_vmsg)
                    self._verifier_triggered_impl_count = _epoch
                    self._logger.info(
                        "Orchestrator triggered verifier validation pass (impl epoch=%s; "
                        "validation_ready not required).", _epoch,
                    )
            except Exception as _vte:
                self._logger.debug("verifier validation trigger skipped: %s", _vte)
            data = getattr(res, "data", None) if res is not None else None
            # CHAINS-BLOCKED early-exit (round 39 deadlock): RunValidationTool
            # refuses to run until chains are registered, returning a fail with
            # data=None. The framework validation shares that tool — so a
            # missing-chains block looks like "no checks returned" AND #53's
            # data.checks scan finds nothing. Detect the block via the error
            # string and SYNTHESIZE a business_chain-fail check so the #53
            # dispatch path below fires (verifier gets the P0 task).
            _err = getattr(res, "error_message", "") or "" if res is not None else ""
            if (not data) and "no verification chains" in _err.lower():
                data = {"summary": "blocked: no verification chains registered",
                        "checks": [{"name": "business_chain", "status": "fail",
                                    "detail": _err}]}
            if data and data.get("runhub_run_id"):
                self._logger.warning(
                    "Framework validation: api_smoke PASSED → recorded RunHub run %s "
                    "(%s endpoints) — delivery-gate run requirement satisfied.",
                    data.get("runhub_run_id"), data.get("endpoints_tested"),
                )
                await self._maybe_run_visual_fidelity()
            else:
                # FIX #36: log WHY the in-run validation failed (summary + failed
                # check names). The bare "not yet passing" hid the real cause for
                # a whole 2-hour run — the app passes api_smoke when booted by
                # hand, so the in-run failures are environmental (docker
                # contention / build-under-load) and we need the detail to fix it.
                _summ = (data or {}).get("summary", "?")
                _failed = [
                    f"{c.get('name')}:{(c.get('detail') or '')[:60]}"
                    for c in ((data or {}).get("checks") or [])
                    if c.get("status") == "fail"
                ]
                self._logger.warning(
                    "Framework validation attempt %s/6: api_smoke NOT passing — %s "
                    "| failed=%s",
                    self._framework_validation_attempts, str(_summ)[:200],
                    _failed or "(no checks returned)",
                )
                # RESILIENCE (stuck-loop breaker): track the FAILURE SET (the set of
                # failing check ids) across validations. A CHANGED failure set is
                # genuine lane-driven progress (a check now passes, or a new one
                # fails) → grant a fresh fast budget and reset the stuck counter, so a
                # converging app is never slowed. An UNCHANGING failure set means the
                # last fast-cap of validations achieved nothing — the lanes are idle
                # and the orchestrator is re-running the identical cycle (the 36-cycle
                # spin). The self-induced heal/skeleton churn no longer resets the
                # budget (above), so the fast cap now actually trips; once it does on a
                # stable failure set we ESCALATE rather than spin to wall-clock.
                _fset = _fwval_failure_set(data)
                _prev_fset = getattr(self, "_fwval_failure_set", None)
                if _prev_fset is None or _fset != _prev_fset:
                    # New/changed failure set → real progress (or first observation).
                    self._fwval_failure_set = _fset
                    self._fwval_stuck_count = 0
                    if _prev_fset is not None:
                        # An actual change (not the first sight) → fresh fast budget,
                        # exactly like a rising endpoint count (FIX #31).
                        self._framework_validation_attempts = 0
                        # Re-arm the per-milestone owner-dispatch guards so the
                        # next-failure feedback can fire afresh for the new failure set.
                        self._fwval_rearm_owner_dispatch()
                else:
                    # Same failure set as last validation → no functional progress.
                    self._fwval_stuck_count = getattr(self, "_fwval_stuck_count", 0) + 1
                    # Only escalate once the FAST budget is spent (the converging
                    # window is over); below the cap we are still in the normal
                    # fast-retry phase and must not interfere with a healthy run.
                    if _attempts >= FWVAL_FAST_CAP:
                        _stage = _fwval_stuck_decision(self._fwval_stuck_count)
                        if _stage == "redispatch":
                            # Re-wake the lane(s) that own the failing dimension: the
                            # existing per-milestone _dispatch_* guards have gone quiet
                            # (one dispatch per milestone), so re-arm them — the
                            # _dispatch_* calls below will then re-fire the owner task +
                            # urgent wake for this specific, persisting failure set.
                            self._fwval_rearm_owner_dispatch()
                            self._logger.warning(
                                "STUCK-LOOP ESCALATION: framework validation has failed "
                                "on the SAME failure set %s for %s post-cap cycles with no "
                                "lane progress — re-dispatching the owning lane(s).",
                                sorted(_fset) or "(none)", self._fwval_stuck_count,
                            )
                        elif _stage == "terminal":
                            # Re-dispatch did not break the stall → surface a clear,
                            # terminal "stuck on <blocker>" signal so the run stops
                            # churning to wall-clock and the UI/monitor shows the real
                            # blocker (instead of looking dead with idle lanes + a
                            # spinning orchestrator). We do NOT hard-kill here — the run
                            # budget cap is the terminator; this downshifts the cadence
                            # (attempts pinned at the cap → slow interval) and makes the
                            # blocker visible exactly once.
                            _blocker = ", ".join(sorted(_fset)) or (str(_summ)[:120] or "unknown")
                            if getattr(self, "_fwval_stuck_blocker", None) != _blocker:
                                self._fwval_stuck_blocker = _blocker
                                self._logger.error(
                                    "STUCK: framework validation is wedged on %s — the "
                                    "same failure set has persisted for %s post-cap "
                                    "cycles with no lane progress AND re-dispatch did not "
                                    "help. Downshifting to the slow re-validation "
                                    "interval; the run will end on its budget cap unless "
                                    "a lane makes progress. Real blocker: %s",
                                    _blocker, self._fwval_stuck_count, str(_summ)[:200],
                                )
                                try:
                                    self.progress.emit(
                                        EventType.PHASE_ERROR,
                                        "Framework Validation",
                                        {"error": f"stuck on {_blocker}",
                                         "failure_set": sorted(_fset),
                                         "cycles": self._fwval_stuck_count},
                                    )
                                except Exception:
                                    pass
                # GATE-C1 feedback loop: a business_endpoints_implemented FAIL
                # (registered-implemented endpoint answering 404/405) routes to
                # the backend lane — a hard gate with no exit deadlocks the run.
                await self._dispatch_unimplemented_routes(data)
                # frontend_navigable feedback loop: a blank-shell frontend (0
                # routes) otherwise pins validation red with no path back to the
                # lane that owns the UI.
                await self._dispatch_frontend_navigable(data)
                # Mechanism #53 (round 33 deadlock): business_chain failing
                # because the verifier never authored verification_chains.json
                # must CLOSE THE LOOP — the chain fallback was removed (user
                # decision: agent feedback over framework content), so the
                # framework must actually deliver that feedback: one P0 task +
                # urgent wake per milestone, carrying the authoring spec.
                # Match VERB-INDEPENDENTLY (the chain_executor wording moved
                # authored→registered when chains became registry-backed; the
                # old literal "authored" match silently broke #53 — found in
                # the 2026-06-12 scheduling audit). Key on the stable prefix.
                _chain_fail = next(
                    (c for c in ((data or {}).get("checks") or [])
                     if c.get("name") == "business_chain"
                     and c.get("status") == "fail"
                     and "no verification chains" in str(c.get("detail") or "")),
                    None)
                if _chain_fail and getattr(self, "_chain_task_dispatched", None) == \
                        getattr(self, "_current_milestone_version", ""):
                    # already dispatched but STILL failing → the verifier has
                    # not digested it (round 34: a 97-message inbox swallowed
                    # the first wake). Re-nudge, urgent, no duplicate task.
                    try:
                        from tools.communication_tools import _create_message
                        await self.message_bus.send(_create_message(
                            source_agent_id="orchestrator",
                            target_agent_id="verifier",
                            content=(
                                "STILL BLOCKED on business_chain: you have not "
                                "registered any verification chains. Drop "
                                "everything, claim your P0 chain task, and "
                                "register them via "
                                "registryhub_register_verification_chain, then "
                                "run_validation."),
                            msg_type="task_ready", priority="urgent",
                            persist=True, tags=["verification_chains", "renudge"],
                        ))
                        self._logger.warning(
                            "CHAIN-AUTHORING re-nudge sent to verifier.")
                    except Exception:
                        pass
                if _chain_fail and getattr(self, "_chain_task_dispatched", None) != \
                        getattr(self, "_current_milestone_version", ""):
                    self._chain_task_dispatched = getattr(
                        self, "_current_milestone_version", "")
                    try:
                        from .runtime.chain_executor import AUTHORING_INSTRUCTIONS
                        _ct = self.hubs.workhub.create_task(
                            title="Register verification chains (blocks delivery)",
                            description=(
                                "The business_chain delivery check FAILS until you "
                                "register chains. " + AUTHORING_INSTRUCTIONS +
                                " Derive the chains from THIS app's registered endpoints "
                                "(registryhub_list_endpoints) and the kickoff user_flows, "
                                "register each via registryhub_register_verification_chain, "
                                "then re-run run_validation."),
                            assignee="verifier",
                            agent="orchestrator",
                            priority="P0",
                        )
                        from tools.communication_tools import _create_message
                        await self.message_bus.send(_create_message(
                            source_agent_id="orchestrator",
                            target_agent_id="verifier",
                            content=(
                                "URGENT: delivery is blocked on business_chain — you have "
                                "registered no verification chains. Claim task "
                                f"{(_ct or {}).get('id')} and register them via "
                                "registryhub_register_verification_chain NOW, then "
                                "run_validation."),
                            msg_type="task_ready",
                            priority="urgent",
                            persist=True,
                            tags=["verification_chains", "remediation"],
                        ))
                        self._logger.warning(
                            "CHAIN-AUTHORING remediation dispatched to verifier "
                            "(task %s).", (_ct or {}).get("id"))
                    except Exception as _cd_exc:
                        self._logger.error(
                            "chain-authoring dispatch failed: %s", _cd_exc)
        except Exception as exc:  # never break the coordination loop
            self._logger.error("framework validation raised (non-fatal): %s", exc)

    def _fwval_rearm_owner_dispatch(self) -> None:
        """RESILIENCE: clear the per-milestone owner-dispatch guards so the existing
        ``_dispatch_*`` feedback helpers (business_endpoints → backend,
        frontend_navigable / unwired_ui_pages → frontend, business_chain → verifier)
        re-fire their P0 task + urgent wake for a failure set that has either CHANGED
        (genuine progress — the new gap deserves a fresh dispatch) or PERSISTED past
        the fast cap (stuck — re-wake the owner that's gone quiet). Reuses the
        existing dispatch machinery; invents no new control flow. Clearing the guard
        is safe — each ``_dispatch_*`` is idempotent within a milestone (it re-sets
        its own guard) and only acts when its specific check is still failing."""
        for _guard in (
            "_unimpl_routes_dispatched",
            "_frontend_navigable_dispatched",
            "_unwired_ui_pages_dispatched",
            "_chain_task_dispatched",
        ):
            try:
                setattr(self, _guard, None)
            except Exception:
                pass

    async def _dispatch_unimplemented_routes(self, data) -> None:
        """GATE-C1 feedback loop: a ``business_endpoints_implemented`` FAIL (an
        endpoint registered ``status=implemented`` answering 404/405) must reach
        the lane that can fix it — the verifier has no bug-write channel
        (TOOL-C1), so without this the hard gate just pins validation red until
        the budget dies. Mirrors the business_chain #53 dispatch: ONE P0 task +
        urgent wake to the BACKEND lane per milestone (validation retries every
        tick; re-dispatching would spam workhub). The fix is either real
        (implement the route) or registry hygiene (deprecate a junk
        registration via registryhub_deprecate_endpoint — it then leaves the
        business contract and the gate self-clears). Best-effort: never raises
        into the coordination loop."""
        try:
            check = next(
                (c for c in ((data or {}).get("checks") or [])
                 if c.get("name") == "business_endpoints_implemented"
                 and c.get("status") == "fail"),
                None)
            if not check:
                return
            milestone = getattr(self, "_current_milestone_version", "")
            if getattr(self, "_unimpl_routes_dispatched", None) == milestone:
                return
            detail = str(check.get("detail") or "")
            task = self.hubs.workhub.create_task(
                title="Registered-implemented endpoint(s) answer 404/405 (blocks delivery)",
                description=(
                    "api_smoke's business_endpoints_implemented gate FAILED: the "
                    "following endpoints are registered status=implemented but the "
                    "live app answers 404/405 — the route is not actually wired:\n"
                    f"{detail}\n"
                    "For each one, either IMPLEMENT the route in the backend, or — "
                    "if the registration is junk/obsolete — deprecate it via "
                    "registryhub_deprecate_endpoint so it leaves the business "
                    "contract. Delivery stays blocked until a validation pass shows "
                    "every registered-implemented endpoint serving its route."),
                assignee="backend",
                agent="orchestrator",
                priority="P0",
            )
            self._unimpl_routes_dispatched = milestone
            from tools.communication_tools import _create_message
            await self.message_bus.send(_create_message(
                source_agent_id="orchestrator",
                target_agent_id="backend",
                content=(
                    "URGENT: delivery is blocked on business_endpoints_implemented "
                    "— endpoint(s) registered as implemented answer 404/405. Claim "
                    f"task {(task or {}).get('id')} and implement the route(s) or "
                    "deprecate the junk registration(s) NOW."),
                msg_type="task_ready",
                priority="urgent",
                persist=True,
                tags=["unimplemented_routes", "remediation"],
            ))
            self._logger.warning(
                "UNIMPLEMENTED-ROUTE remediation dispatched to backend (task %s): %s",
                (task or {}).get("id"), detail[:200])
        except Exception as exc:
            self._logger.error("unimplemented-route dispatch failed: %s", exc)

    async def _dispatch_frontend_navigable(self, data) -> None:
        """frontend_navigable feedback loop: a blank-shell frontend (page
        components present but 0 routes wired, or 0 pages) FAILS the navigable
        gate, but the failure routed NOWHERE — the framework deliberately does
        not author UI (lane owns it, 2026-06-11), and the frontend lane has
        already finish()ed, so it never re-engages and the gate pins validation
        red until the budget dies (observed: gemini wrote 2 components, 0 routes,
        imported one into App.jsx, finished → "blank shell" forever). Close the
        loop the same way visual-fidelity and GATE-C1 do: ONE P0 task + urgent
        wake to the FRONTEND lane per milestone, with a concrete instruction to
        wire the router. Framework still authors no UI content — it only routes
        the failure back to the owner. Best-effort: never raises into the loop."""
        try:
            check = next(
                (c for c in ((data or {}).get("checks") or [])
                 if c.get("name") == "frontend_navigable"
                 and c.get("status") == "fail"),
                None)
            if not check:
                return
            milestone = getattr(self, "_current_milestone_version", "")
            if getattr(self, "_frontend_navigable_dispatched", None) == milestone:
                return
            detail = str(check.get("detail") or "")
            task = self.hubs.workhub.create_task(
                title="Frontend is a blank shell — wire routes + build the pages (blocks delivery)",
                description=(
                    "The frontend_navigable gate FAILED: " + detail + ".\n"
                    "The app renders blank because react-router routes are not "
                    "wired. Do ALL of the following, then finish:\n"
                    "1. In src/App.jsx set up react-router (BrowserRouter + Routes) "
                    "with a <Route> for EVERY screen in the reference spec "
                    "(design/reference_spec.json) — login, signup, feed/home, "
                    "explore/search, create, reels, messages, profile — each "
                    "pointing at its page component.\n"
                    "2. Author any page components that don't exist yet (one per "
                    "screen), reading data via src/services/api.js (data.items / "
                    "data.item).\n"
                    "3. A logged-out user lands on /login; an authed user lands on "
                    "the home feed.\n"
                    "frontend_navigable requires >=1 page AND >=1 route; delivery "
                    "stays blocked until a validation pass shows a navigable UI."),
                assignee="frontend",
                agent="orchestrator",
                priority="P0",
            )
            self._frontend_navigable_dispatched = milestone
            from tools.communication_tools import _create_message
            await self.message_bus.send(_create_message(
                source_agent_id="orchestrator",
                target_agent_id="frontend",
                content=(
                    "URGENT: delivery is blocked on frontend_navigable — the app is "
                    "a blank shell (routes not wired). Claim task "
                    f"{(task or {}).get('id')} and wire src/App.jsx react-router "
                    "Routes for every reference-spec screen (+ author the missing "
                    "page components) NOW, then finish."),
                msg_type="task_ready",
                priority="urgent",
                persist=True,
                tags=["frontend_navigable", "remediation"],
            ))
            self._logger.warning(
                "FRONTEND-NAVIGABLE remediation dispatched to frontend (task %s): %s",
                (task or {}).get("id"), detail[:200])
        except Exception as exc:
            self._logger.error("frontend-navigable dispatch failed: %s", exc)

    async def _dispatch_unwired_ui_pages(self, blockers) -> None:
        """ui_page-wiring feedback loop: declared ui_pages whose route is not
        wired in App.jsx (or whose component file is missing) HARD-block delivery
        (``deliverability_ui_page_unwired``) even on a functionally-validated app
        — but, unlike GATE-C1 / frontend_navigable / visual-fidelity, this blocker
        routed NOWHERE. ``frontend_navigable`` passes on >=1 route (a lone wired
        ``/login`` satisfies it), so ITS dispatch goes quiet while delivery still
        requires EVERY declared page wired — the frontend lane finish()es with one
        route wired and nothing ever tells it to wire the rest, so the run
        deadlocks (gemini instagram 2026-06-13: App.jsx wired only ``/login``; 12
        declared pages — home/explore/reels/messages/profile/… — sat unwired and
        delivery blocked for hours with no feedback). Close the loop the same way
        the others do: ONE P0 task + urgent wake to the FRONTEND lane per
        milestone, listing the specific unwired pages + their declared routes +
        components. The framework authors NO UI — it routes the gap (with registry
        truth) back to the owner. Best-effort: never raises into the loop."""
        try:
            if not blockers:
                return
            milestone = getattr(self, "_current_milestone_version", "")
            if getattr(self, "_unwired_ui_pages_dispatched", None) == milestone:
                return  # one dispatch per milestone — the gate recomputes every tick
            try:
                pages = self.hubs.registryhub.list_ui_pages() or {}
            except Exception:
                pages = {}
            # Build an actionable list: route → component, for the pages the
            # blockers name (audit emits ``ui_page `<name>` declared but unusable``).
            lines: List[str] = []
            for name, pg in (pages.items() if isinstance(pages, dict) else []):
                if not isinstance(pg, dict):
                    continue
                if any(("`%s`" % name) in str(b) for b in blockers):
                    route = pg.get("route") or pg.get("path") or "?"
                    comp = pg.get("component") or "?"
                    lines.append(f"  - {route}  →  <{comp} />")
            page_list = "\n".join(lines) or "\n".join("  - " + str(b) for b in blockers[:15])
            task = self.hubs.workhub.create_task(
                title="Wire the declared pages into App.jsx routes (blocks delivery)",
                description=(
                    f"Delivery is HARD-BLOCKED: {len(blockers)} declared ui_page(s) "
                    "are unwired — their declared route is not present in "
                    "src/App.jsx (or the page component file is missing). api_smoke "
                    "is green but the app is a near-blank shell — only the wired "
                    "route(s) render. Wire EVERY page below into src/App.jsx "
                    "react-router <Routes> (BrowserRouter + a <Route> per page, "
                    "each pointing at its component), then finish:\n"
                    f"{page_list}\n"
                    "Author any page component that doesn't exist yet (read data via "
                    "src/services/api.js → data.items / data.item). Delivery stays "
                    "blocked until a gate tick shows every declared route wired."),
                assignee="frontend",
                agent="orchestrator",
                priority="P0",
            )
            self._unwired_ui_pages_dispatched = milestone
            from tools.communication_tools import _create_message
            await self.message_bus.send(_create_message(
                source_agent_id="orchestrator",
                target_agent_id="frontend",
                content=(
                    f"URGENT: delivery is blocked — {len(blockers)} declared page(s) "
                    "are unwired in src/App.jsx (only a subset of routes render). "
                    f"Claim task {(task or {}).get('id')} and add a react-router "
                    "<Route> for EACH unwired page (home/explore/reels/messages/"
                    "profile/…) pointing at its component, then finish."),
                msg_type="task_ready",
                priority="urgent",
                persist=True,
                tags=["ui_page_unwired", "remediation"],
            ))
            self._logger.warning(
                "UI-PAGE-UNWIRED remediation dispatched to frontend (task %s): %s "
                "unwired page(s): %s",
                (task or {}).get("id"), len(blockers),
                "; ".join(str(b) for b in blockers)[:200])
        except Exception as exc:
            self._logger.error("ui-page-unwired dispatch failed: %s", exc)

    def _detect_misplaced_frontend_root(self) -> Optional[Dict[str, Any]]:
        """Detect a frontend the lane authored at the REPO ROOT (``./src``) while
        the canonical ``app/frontend/src`` the framework builds+gates is the blank
        baseline. Observed live (gemini instagram 2026-06-13): the lane built a
        full Vite app at ``./src`` (10 routes, 8 pages, own ``./package.json``) —
        but docker uses ``build: ../app/frontend`` and the gate audits
        ``app/frontend/src``, so the real app was invisible and delivery saw a
        blank shell. Returns a small count summary when the repo-root tree is
        materially richer than the canonical one (→ misplaced), else None.
        Deterministic, best-effort — never raises."""
        try:
            root_src = self.output_dir / "src"
            canon_src = self.output_dir / "app" / "frontend" / "src"
            if not root_src.is_dir():
                return None

            def _pages(p: Path) -> int:
                d = p / "pages"
                return len(list(d.glob("*.jsx")) + list(d.glob("*.tsx"))) if d.is_dir() else 0

            def _routes(p: Path) -> int:
                f = p / "App.jsx"
                if not f.is_file():
                    f = p / "App.tsx"
                try:
                    txt = f.read_text(encoding="utf-8", errors="ignore") if f.is_file() else ""
                except Exception:
                    txt = ""
                # count <Route …> elements but NOT the <Routes> wrapper (which
                # contains the substring "<Route") — match only when a delimiter
                # follows, so "<Routes>" is excluded.
                return len(re.findall(r"<Route[\s/>]", txt))

            rp, cp = _pages(root_src), _pages(canon_src)
            rr, cr = _routes(root_src), _routes(canon_src)
            # Misplaced when the repo-root tree is the real app and the canonical
            # one is (at most) the baseline shell — i.e. root is materially richer.
            if (rp >= 2 and rp > cp) or (rr >= 2 and rr > cr):
                return {"root_pages": rp, "canonical_pages": cp,
                        "root_routes": rr, "canonical_routes": cr}
            return None
        except Exception:
            return None

    async def _dispatch_misplaced_frontend_root(self, info) -> None:
        """The frontend lane authored a real app at the REPO ROOT (``./src`` +
        ``./package.json``) instead of under ``app/frontend/`` — so docker
        (``build: ../app/frontend``) and the delivery gate (``app/frontend/src``)
        never see it and report a blank shell despite a full app existing. The
        framework does NOT move the lane's files (the lane owns the UI); it routes
        the fix back to the owner: ONE P0 task + urgent wake per milestone to
        RELOCATE the app into ``app/frontend/``. This is the ROOT-cause remedy for
        the ``ui_page_unwired`` block when the pages exist but at the wrong root —
        preferred over the per-page wiring dispatch, which would give misleading
        'wire each route' advice when the whole app just needs moving.
        Best-effort: never raises into the loop."""
        try:
            if not info:
                return
            milestone = getattr(self, "_current_milestone_version", "")
            if getattr(self, "_misplaced_frontend_dispatched", None) == milestone:
                return
            task = self.hubs.workhub.create_task(
                title="Move the frontend into app/frontend/ — it was built at the repo root (blocks delivery)",
                description=(
                    f"Your frontend app is at the REPO ROOT (./src/App.jsx + ./src/pages/ "
                    f"= {info.get('root_routes')} route(s) / {info.get('root_pages')} page(s)), "
                    f"but the framework builds and gates ONLY `app/frontend/` (currently "
                    f"{info.get('canonical_routes')} route(s) / {info.get('canonical_pages')} "
                    "page(s) — a blank shell). docker-compose uses `build: ../app/frontend` "
                    "and the delivery gate audits `app/frontend/src`, so your real app is "
                    "INVISIBLE to delivery. MOVE the whole app under app/frontend/: "
                    "app/frontend/src/App.jsx, app/frontend/src/pages/*.jsx, "
                    "app/frontend/src/components/*.jsx, app/frontend/src/services/api.js, "
                    "app/frontend/package.json, app/frontend/index.html, "
                    "app/frontend/vite.config.js — then delete the repo-root ./src + "
                    "./package.json + ./index.html + ./vite.config.js duplicates, and "
                    "finish. EVERY file-tool path must start with `app/frontend/`."),
                assignee="frontend",
                agent="orchestrator",
                priority="P0",
            )
            self._misplaced_frontend_dispatched = milestone
            from tools.communication_tools import _create_message
            await self.message_bus.send(_create_message(
                source_agent_id="orchestrator",
                target_agent_id="frontend",
                content=(
                    f"URGENT: your frontend is at the repo ROOT (./src, "
                    f"{info.get('root_pages')} pages) but the framework only builds "
                    f"app/frontend/ — delivery sees a blank shell. Claim task "
                    f"{(task or {}).get('id')} and MOVE the app into app/frontend/ "
                    "(full app/frontend/src/... paths, delete the root duplicates), "
                    "then finish."),
                msg_type="task_ready",
                priority="urgent",
                persist=True,
                tags=["frontend_misplaced_root", "remediation"],
            ))
            self._logger.warning(
                "MISPLACED-FRONTEND-ROOT remediation dispatched to frontend (task %s): "
                "repo-root=%s routes/%s pages vs canonical app/frontend=%s routes/%s pages",
                (task or {}).get("id"), info.get("root_routes"), info.get("root_pages"),
                info.get("canonical_routes"), info.get("canonical_pages"))
        except Exception as exc:
            self._logger.error("misplaced-frontend-root dispatch failed: %s", exc)

    async def _compile_reference_materials(self, raw_req: str) -> str:
        """Classify reference materials, stage documents into the workspace,
        compile the REFERENCE SPEC with the run's selected model, persist it,
        derive deliverability gates from it, and return the requirements text
        extended with the spec summary. Best-effort: on any failure the run
        proceeds with the original requirements."""
        try:
            from .runtime.reference_materials import (
                classify_references, compile_reference_spec, gates_from_spec,
                merge_user_gates, spec_summary_for_requirements,
                stage_reference_docs)
            split = classify_references(getattr(self, "_reference_images", None) or [])
            self._reference_images = split["images"]
            self._reference_docs = split["docs"]
            if not split["images"] and not split["docs"]:
                return raw_req
            try:
                from .runtime.reference_materials import write_agent_notes
                write_agent_notes(self.output_dir)
            except Exception:
                pass
            # stage BOTH docs and reference images into design/references/ so the
            # env is self-contained (the Env Forge UI can serve/show the screenshots).
            staged = stage_reference_docs(split["docs"] + split["images"], self.output_dir)
            if staged:
                self._logger.info("Reference documents staged: %s", staged)
            spec = await compile_reference_spec(
                self.llm, split["images"], split["docs"], raw_req)
            if not spec or not any(spec.get(k) for k in
                                   ("screens", "endpoints", "entities", "mcp_tools")):
                self._logger.info("Reference spec compile produced nothing usable — continuing without.")
                return raw_req
            spec_path = Path(self.output_dir) / "design" / "reference_spec.json"
            spec_path.parent.mkdir(parents=True, exist_ok=True)
            spec_path.write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
            gates = gates_from_spec(spec)
            n = merge_user_gates(self.output_dir, gates) if gates else 0
            self._reference_spec = spec
            self._reference_spec_summary = spec_summary_for_requirements(spec)
            self._logger.warning(
                "REFERENCE SPEC compiled: %d screens, %d endpoints, %d entities, "
                "%d mcp tools → %d deliverability gates registered; spec at %s",
                len(spec.get("screens") or []), len(spec.get("endpoints") or []),
                len(spec.get("entities") or []), len(spec.get("mcp_tools") or []),
                n, spec_path)
            return raw_req + spec_summary_for_requirements(spec)
        except Exception as exc:
            self._logger.error("reference material compile failed (non-fatal): %s", exc)
            return raw_req

    async def _maybe_run_visual_fidelity(self) -> None:
        """VISUAL FIDELITY gate — runs after api_smoke passes. Screenshots the
        running frontend on the routes the reference images depict, has the
        vision model compare each pair, and on failure files an ACTIONABLE
        remediation task for the frontend lane (concrete per-screen deviations).
        Visual design stays the lane's job; this is the enforcement loop that
        makes the app converge to the references instead of to whatever the
        lane happened to ship. Bounded: 3 judged runs per app-source signature
        (each is N vision calls); a pass latches until the source changes.
        Best-effort — never raises into the coordination loop."""
        try:
            refs = list(getattr(self, "_reference_images", None) or [])
            if not refs:
                return
            sig = self._compute_app_source_signature()
            if sig != getattr(self, "_vf_sig", None):
                self._vf_sig = sig
                self._vf_attempts = 0   # fresh per-source judging budget (new pixels deserve a verdict)
                self._vf_passed = False
                # PIPE-C3: do NOT reset _vf_deferred_since here. The deferral
                # wall-clock is anchored to the milestone's FIRST defer (set in
                # _maybe_framework_deliver, zeroed only at milestone start) — a
                # frontend lane that churns files on every visual-fail must NOT be
                # able to keep rewinding the 900s escape clock (the livelock that
                # left delivery deferred until the run's budget died).
            if getattr(self, "_vf_passed", False):
                return
            if getattr(self, "_vf_attempts", 0) >= 3:
                return  # budget spent on this source state — wait for lane changes
            self._vf_attempts = getattr(self, "_vf_attempts", 0) + 1
            from .runtime.visual_fidelity import run_visual_fidelity, remediation_text
            if sig is not None and sig == getattr(self, "_vf_last_judged_sig", None):
                # JUDGE-ON-CHANGE: identical source ⇒ identical pixels — re-
                # judging burns 7 vision calls to learn nothing (round 30:
                # 3 attempts on one source, scores just noise-wiggled). The
                # attempt budget now counts DISTINCT source versions.
                return
            result = await run_visual_fidelity(self.output_dir, refs, self.llm)
            if result.get("capture_unavailable") or result.get("auth_unavailable"):
                # Not a judgment — the app wasn't reachable (mid-rebuild) or
                # the authed session was rejected wholesale (token mint failed
                # / every auth route bounced to /login — round 31 judged the
                # LOGIN PAGE against feed/profile references, 0.2s across the
                # board). Refund so the budget only counts REAL verdicts.
                self._vf_attempts = max(0, getattr(self, "_vf_attempts", 1) - 1)
                self._logger.warning(
                    "Visual fidelity: %s — attempt refunded, will retry next tick.",
                    result.get("summary") or "capture/auth unavailable")
                return
            screens = result.get("screens") or []
            self._vf_last_result = result
            self._vf_last_judged_sig = sig
            # PIPE-C3: per-milestone real-judgment counter (NOT reset on sig
            # change — only at milestone start). A vision-cost backstop escape so a
            # churning lane that keeps flipping the source signature can't drive
            # unbounded judging even before the 900s wall-clock escape fires.
            self._vf_total_judgments = getattr(self, "_vf_total_judgments", 0) + 1
            if result.get("passed"):
                self._vf_passed = True
                self._logger.warning(
                    "Visual fidelity PASSED (%s): %s",
                    ", ".join(f"{s['name']}={s['similarity']:.2f}" for s in screens),
                    result.get("summary"))
                return
            self._logger.warning(
                "Visual fidelity attempt %s/3 FAILED — %s",
                self._vf_attempts, result.get("summary"))
            try:
                _vt = self.hubs.workhub.create_task(
                    title=f"UI does not match reference designs (visual gate, attempt {self._vf_attempts})",
                    description=remediation_text(result),
                    assignee="frontend",
                    agent="orchestrator",
                    priority="P1",
                )
                # Wake the frontend NOW — milestone work is done at this
                # point and the lane otherwise idles through the deferral.
                try:
                    from tools.communication_tools import _create_message
                    _msg = _create_message(
                        source_agent_id="orchestrator",
                        target_agent_id="frontend",
                        content=(
                            "Visual-fidelity remediation task assigned "
                            f"(task_id={(_vt or {}).get('id')}). Claim it and "
                            "fix the listed per-screen deviations NOW — the "
                            "milestone release is DEFERRED until the UI "
                            "matches the references (or attempts exhaust)."),
                        msg_type="task_ready",
                        priority="urgent",
                        persist=True,
                        tags=["visual_fidelity", "remediation"],
                    )
                    await self.message_bus.send(_msg)
                except Exception:
                    pass
            except Exception as exc:
                self._logger.error("visual-fidelity task creation failed: %s", exc)
        except Exception as exc:
            self._logger.error("visual fidelity gate raised (non-fatal): %s", exc)

    def _all_business_endpoints_have_route_code(self) -> bool:
        """Code-reality complement to ``all_business_endpoints_implemented``
        (which reads the lanes' lagging registryhub *status*). True iff the INTEGRATED
        source (self.output_dir) has a route handler for every business endpoint's
        resource token. FIX #26: lanes write+commit routes but can't finish (gated
        on unclaimed workhub tasks) so they never register all endpoints
        'implemented' — leaving the validation/delivery gate shut on a contract
        that IS implemented in code. Triggering on code presence is safe because
        the downstream api_smoke probe is the real arbiter (a missing/broken route
        404/500s → validation fails → no delivery). Best-effort; False on error.
        """
        try:
            from .runtime.lifecycle import business_endpoints
            from .agents.runtime.preconditions import (
                _collect_source_route_tokens,
                _endpoint_resource_token,
            )
            from pathlib import Path as _P
            registryhub = getattr(self.hubs, "registryhub", None)
            if registryhub is None:
                return False
            biz = business_endpoints(registryhub.get_endpoints() or {})
            if not biz:
                return False
            root = getattr(self, "output_dir", None)
            if root is None:
                return False
            tokens = _collect_source_route_tokens(_P(root))
            for ep in biz:
                tok = _endpoint_resource_token(
                    ep.get("path") if isinstance(ep, dict) else None)
                if not tok or tok not in tokens:
                    return False
            return True
        except Exception:
            return False

    def _compute_app_source_signature(self):
        """OPTIMIZATION: a stable CONTENT hash of the integrated app source the
        heal-repairs care about (backend *.py, frontend src + tooling configs, the
        DDL). Idempotent repairs leave it unchanged, so re-ticks are no-ops; a real
        lane change flips it → re-heal + re-validate. None on error (caller heals)."""
        try:
            import hashlib
            out_dir = getattr(self, "output_dir", None)
            if not out_dir:
                return None
            from pathlib import Path as _P
            base = _P(out_dir) / "app"
            exts = {".py", ".js", ".jsx", ".ts", ".tsx", ".json", ".sql", ".cjs", ".mjs"}
            h = hashlib.sha256()
            for sub in ("backend", "frontend/src", "frontend", "database/init"):
                d = base / sub
                if not d.exists():
                    continue
                top_only = sub == "frontend"  # avoid node_modules; only top-level configs
                it = d.glob("*") if top_only else d.rglob("*")
                for f in sorted(it, key=lambda p: str(p)):
                    if f.is_file() and f.suffix in exts:
                        try:
                            h.update(str(f.relative_to(base)).encode() + b"\0")
                            h.update(f.read_bytes())
                        except Exception:
                            continue
            return h.hexdigest()
        except Exception:
            return None

    def _scaffold_design_readme(self) -> None:
        """The delivery gate requires ``design/README.md`` (a design artifact the
        kickoff coordinator is meant to author). When no lane writes it, the run
        cuts a release via api_smoke but the FINAL delivery gate fails on the
        missing file → Status FAILED on an otherwise-working app. Framework-scaffold
        a project README from the registered contract (write-if-missing, idempotent,
        best-effort)."""
        try:
            out_dir = getattr(self, "output_dir", None)
            if not out_dir:
                return
            readme = out_dir / "design" / "README.md"
            if readme.exists() and readme.read_text(encoding="utf-8", errors="ignore").strip():
                return
            name = out_dir.name or "app"
            lines = [
                f"# {name}", "",
                "Generated full-stack application — FastAPI backend, React/Vite "
                "frontend, PostgreSQL, embedded OAuth2 (RS256 JWT).", "",
            ]
            eps = []
            registryhub = getattr(getattr(self, "hubs", None), "registryhub", None)
            if registryhub is not None:
                try:
                    from .runtime.lifecycle import business_endpoints
                    for e in business_endpoints(registryhub.get_endpoints() or {}):
                        if isinstance(e, dict) and e.get("method") and e.get("path"):
                            eps.append((str(e["method"]).upper(), str(e["path"]),
                                        str(e.get("summary") or "")))
                except Exception:
                    pass
            if eps:
                lines += ["## API", ""]
                for m, p, s in sorted(set(eps)):
                    lines.append(f"- `{m} {p}`" + (f" — {s}" if s else ""))
                lines.append("")
            lines += ["## Run", "", "```bash",
                      "cd docker && docker compose up -d --build", "```", ""]
            readme.parent.mkdir(parents=True, exist_ok=True)
            readme.write_text("\n".join(lines), encoding="utf-8")
            _log = getattr(self, "_logger", None)
            if _log is not None:
                _log.warning(
                    "Scaffolded design/README.md (delivery-gate required artifact)")
        except Exception:
            pass  # best-effort; logger may be absent in minimal/test contexts

    def _repair_backend_auth(self) -> None:
        """FIX #45: the handlers gate on ``Depends(get_current_user)`` but the lane
        writes a placeholder that IGNORES the token (returns the first DB user) —
        the lane itself says "the full auth dependency is provided elsewhere in the
        complete scaffold". So the framework provides it: a real JWT-verifying
        ``auth_dependency.py`` + rewrite each route file's placeholder to import it.
        Best-effort."""
        try:
            out_dir = getattr(self, "output_dir", None)
            if not out_dir:
                return
            from pathlib import Path as _P
            from .runtime.backend_scaffold import (
                repair_backend_auth_dependency, repair_inline_token_auth,
                repair_auth_enforcement_middleware)
            be_dir = _P(out_dir) / "app" / "backend"
            rep = repair_backend_auth_dependency(be_dir)
            if rep.get("repaired"):
                self._logger.warning(
                    "Backend auth dependency installed (FIX #45, real JWT auth): "
                    "rewrote %s", rep.get("rewritten"))
            # FIX #46 (run #12): handlers that fake-parse a ``user:<id>`` token INLINE
            # (no shared get_current_user to rewrite) → rewrite the fake split to decode
            # the real RS256 JWT, so authed endpoints stop 401'ing 'invalid token'.
            inline = repair_inline_token_auth(be_dir)
            if inline.get("fixed"):
                self._logger.warning(
                    "Backend inline token auth repaired (FIX #46): %s fake "
                    "'user:<id>' parse site(s) now decode the real JWT.",
                    inline.get("fixed"))
            # FIX #47 (run #16): some lanes write NO auth (handlers fetch the first DB
            # user) → 200 with no token → auth_enforced_401 stalls the milestone. Enforce
            # a valid bearer JWT on every /api/ business route via middleware.
            mw = repair_auth_enforcement_middleware(be_dir)
            if mw.get("injected"):
                self._logger.warning(
                    "Backend auth-enforcement middleware injected (FIX #47): /api/ "
                    "business routes now require a valid bearer JWT.")
        except Exception as exc:
            self._logger.debug("backend auth repair skipped: %s", exc)

    def _repair_backend_packaging(self) -> None:
        """Ensure the backend is pip-installable in docker. The lane writes a
        hatchling pyproject with a FLAT layout, so the Dockerfile's
        ``uv pip install .`` can't build a wheel → the whole docker build dies →
        docker_up TIMES OUT → no delivery (instagram MM, 2026-06-08: M5 was blocked
        here for 12 min, never delivered, so its declared endpoints — incl. POST
        follow — were never projected). bypass-selection makes the deps install +
        the build succeed. Best-effort."""
        try:
            out_dir = getattr(self, "output_dir", None)
            if not out_dir:
                return
            from pathlib import Path as _P
            from .runtime.backend_scaffold import repair_backend_packaging
            rep = repair_backend_packaging(_P(out_dir) / "app" / "backend")
            if rep.get("repaired"):
                self._logger.warning(
                    "Backend packaging made build-safe (hatchling flat-layout → "
                    "wheel bypass-selection so `pip install .` installs deps without "
                    "failing package detection): %s", rep.get("pyproject"))
        except Exception as exc:
            self._logger.debug("backend packaging repair skipped: %s", exc)

    def _repair_ddl_from_orm(self) -> None:
        """FIX #43 (#2 guaranteed): regenerate the DDL FROM the app's SQLAlchemy
        models so it can never drift from the handlers. The LLM's model+handler
        agree with each other (e.g. ``posts.user_id``) but may diverge from the
        description-derived DDL (``posts.author_id``) → runtime UndefinedColumn.
        The model is the runtime truth, so project the DDL from it. Best-effort:
        leaves the existing spec-DDL in place if models.py can't be introspected."""
        try:
            out_dir = getattr(self, "output_dir", None)
            if not out_dir:
                return
            from pathlib import Path as _P
            from .runtime.database_scaffold import (
                introspect_orm_schema, render_schema_sql)
            be = _P(out_dir) / "app" / "backend"
            tables = introspect_orm_schema(be)
            if not tables:
                return
            ddl_sql = render_schema_sql(tables)
            # Write the spine-correct DDL to the framework's canonical path AND to
            # EVERY path the docker-compose actually MOUNTS as a Postgres init
            # script. The backend routinely authors its OWN app/backend/01_init.sql
            # (its users table carries username/full_name but NOT the spine `name`
            # column the embedded OAuth2 AS register inserts) and points the
            # compose at THAT file — so writing only to app/database/init/ leaves
            # the LIVE DB with the wrong schema (auth_register_login 500: column
            # "name" does not exist, which silently burned a full M1 run on 36
            # validation retries before this fix).
            targets = [_P(out_dir) / "app" / "database" / "init" / "01_init.sql"]
            try:
                import yaml as _yaml
                compose = _P(out_dir) / "docker" / "docker-compose.yml"
                if compose.exists():
                    data = _yaml.safe_load(compose.read_text(encoding="utf-8")) or {}
                    for svc in (data.get("services") or {}).values():
                        if not isinstance(svc, dict):
                            continue
                        for vol in (svc.get("volumes") or []):
                            if not isinstance(vol, str) or "initdb.d" not in vol:
                                continue
                            host = vol.split(":")[0].strip()
                            if not host:
                                continue
                            p = (compose.parent / host).resolve()
                            targets.append(p if host.endswith(".sql") else p / "01_init.sql")
            except Exception:
                pass
            written: List[str] = []
            for t in list(dict.fromkeys(targets)):  # dedup, keep order
                try:
                    t.parent.mkdir(parents=True, exist_ok=True)
                    t.write_text(ddl_sql, encoding="utf-8")
                    written.append(str(t))
                except Exception:
                    continue
            self._logger.warning(
                "DDL regenerated from the app's ORM models + written to all "
                "compose-mounted init paths (FIX #43 + mount-path fix): tables=%s "
                "targets=%s", sorted(tables), written)
        except Exception as exc:
            self._logger.debug("ORM-DDL repair skipped: %s", exc)

    def _project_missing_routes(self) -> None:
        """ROOT FIX (instagram MM, 2026-06-08): a backend lane DECLARES endpoints in
        RegistryHub but runs out of its loop budget before writing route code for all of
        them — the milestone then delivers HOLLOW (declared endpoints that 404, e.g.
        7/28 on instagram). Trusting RegistryHub status is the trap; the contract surface
        must be PROJECTED from the declared contract, exactly as _repair_ddl_from_orm
        projects the DDL from the ORM rather than trusting LLM-written SQL. For every
        business endpoint RegistryHub declares that has no route in main.py, project a
        working handler from the ORM (the lane's real handlers are untouched; this
        only fills the gaps). Idempotent; best-effort."""
        try:
            out_dir = getattr(self, "output_dir", None)
            if not out_dir:
                return
            registryhub = getattr(self.hubs, "registryhub", None)
            if registryhub is None:
                return
            from pathlib import Path as _P
            from .runtime.lifecycle import business_endpoints
            from .runtime.route_projector import project_missing_routes
            declared = business_endpoints(registryhub.get_endpoints())
            if not declared:
                return
            res = project_missing_routes(_P(out_dir) / "app" / "backend", declared)
            projected = res.get("projected") or []
            if projected:
                self._logger.warning(
                    "By-construction route projection: the lane DECLARED %s "
                    "endpoint(s) it never coded — projected working handlers from "
                    "the ORM so the contract is complete (no 404 on declared "
                    "routes): %s", len(projected), projected)
        except Exception as exc:
            self._logger.debug("route projection skipped: %s", exc)

    def _repair_handler_fk_aliases(self) -> None:
        """ROOT FIX (instagram MM run #9, 2026-06-09): the backend lane authored a
        handler querying ``Post.user_id`` while the Post model's owner FK is
        ``author_id`` → ``AttributeError`` 500 on /api/users/me → api_smoke
        ``business_endpoints_reachable`` stalled out the whole milestone. Like
        _repair_ddl_from_orm, repair the handler↔model surface deterministically:
        rewrite ``<Model>.<owner_alias>`` references to the model's real owner FK when
        the alias is not a column (a guaranteed AttributeError) — never touching a valid
        query. Best-effort; idempotent."""
        try:
            out_dir = getattr(self, "output_dir", None)
            if not out_dir:
                return
            from pathlib import Path as _P
            from .runtime.handler_fk_repair import repair_handler_fk_aliases
            res = repair_handler_fk_aliases(_P(out_dir) / "app" / "backend")
            fixed = res.get("fixed") or []
            if fixed:
                self._logger.warning(
                    "By-construction handler FK-alias repair: rewrote %s handler "
                    "reference(s) to a non-existent owner FK to the model's real one "
                    "(prevents AttributeError 500s): %s", len(fixed), fixed)
        except Exception as exc:
            self._logger.debug("handler FK-alias repair skipped: %s", exc)

    def _repair_psycopg_dsn(self) -> None:
        """ROOT FIX (instagram MM run #10, 2026-06-09): the backend lane opened RAW
        psycopg connections with the SQLAlchemy URL ``postgresql+psycopg://…`` (the env
        ``DATABASE_URL``), which ``psycopg.connect`` rejects (``missing "=" …``) → 500 on
        every such endpoint (/api/users/suggested, /api/feed, /api/explore, … 14+ sites)
        → api_smoke stall. The SQLAlchemy engine needs the +driver form, so only the raw
        call sites are normalised: wrap each ``psycopg.connect(arg)`` with a
        ``_psycopg_dsn(arg)`` helper that strips the dialect. Best-effort; idempotent."""
        try:
            out_dir = getattr(self, "output_dir", None)
            if not out_dir:
                return
            from pathlib import Path as _P
            from .runtime.psycopg_dsn_repair import repair_psycopg_dsn
            res = repair_psycopg_dsn(_P(out_dir) / "app" / "backend")
            wrapped = res.get("wrapped") or 0
            if wrapped:
                self._logger.warning(
                    "By-construction psycopg DSN repair: wrapped %s raw "
                    "psycopg.connect() site(s) to strip the SQLAlchemy dialect from the "
                    "DSN (prevents 'missing \"=\"' 500s).", wrapped)
        except Exception as exc:
            self._logger.debug("psycopg DSN repair skipped: %s", exc)

    # _project_missing_pages REMOVED (user decision 2026-06-11): the framework
    # no longer authors UI content — gates + lane feedback replace projection.

    def _run_test_user_validation(self, version: str) -> None:
        """Post-milestone TEST-USER phase (2026-06-09, user-asked): once a release is
        cut, simulate a real user's journey across the API (register → post → feed →
        view-my-posts → follow → comment → like → message) and check the MCP surface is
        complete, writing a feedback report — the automated form of the hand-verification
        that exposed the route_projector bugs (null owner on create, 500 on
        /users/{username}/posts). Blocking (HTTP + subprocess); the caller runs it in a
        thread. Health-pre-checks the app and SKIPS (no false negatives) if it is not
        up — never boots (to avoid racing the next milestone's api_smoke) and never
        raises into delivery. Web screenshots are produced by the orchestrating layer
        (Playwright is not a gen-runtime dependency)."""
        try:
            out_dir = getattr(self, "output_dir", None)
            registryhub = getattr(self.hubs, "registryhub", None)
            if not out_dir or registryhub is None:
                return
            from pathlib import Path as _P
            from .runtime.lifecycle import business_endpoints
            from .runtime.validation_runner import _backend_host_port, _http
            from .runtime.test_user_validation import run_test_user_validation
            proj = _P(out_dir)
            compose = proj / "docker" / "docker-compose.yml"
            port = _backend_host_port(compose, compose.parent) if compose.exists() else None
            base = f"http://localhost:{port}" if port else None
            # Health pre-check: only run the journey against a live app.
            healthy = False
            if base:
                for _ in range(3):
                    if _http("GET", f"{base}/health", timeout=5).get("status") == 200:
                        healthy = True
                        break
            if not healthy:
                self._logger.warning(
                    "TEST-USER validation (v%s): SKIPPED — app not reachable at "
                    "delivery time (no false-negative report).", version)
                return
            eps = business_endpoints(registryhub.get_endpoints())
            report = run_test_user_validation(
                proj, eps, version=version, base_url=base, compose_file=compose,
                llm=getattr(self, "llm", None))
            summ = report.get("summary", {})
            if summ.get("verdict") == "PASS":
                self._logger.warning(
                    "TEST-USER validation (v%s): PASS — %s/%s API journey steps OK + "
                    "MCP surface complete.", version,
                    summ.get("api_passed"), summ.get("api_steps"))
            else:
                self._logger.warning(
                    "TEST-USER validation (v%s): %s — %s/%s journey steps passed; "
                    "BROKEN: %s", version, summ.get("verdict"),
                    summ.get("api_passed"), summ.get("api_steps"), summ.get("broken"))
        except Exception as exc:
            self._logger.debug("test-user validation skipped: %s", exc)

    def _scaffold_frontend_baseline(self) -> None:
        """FIX #40: gap-fill a minimal buildable frontend (infra + login/feed UI)
        for any standard file the frontend lane left missing/empty. The frontend
        lane variably produces NOTHING (empty app/frontend/ → no Dockerfile →
        docker build can't start → docker_up FAIL → no delivery). Best-effort;
        never clobbers files the lane wrote."""
        try:
            out_dir = getattr(self, "output_dir", None)
            if not out_dir:
                return
            from .runtime.frontend_scaffold import (
                scaffold_frontend_baseline, pin_frontend_build_tooling)
            from pathlib import Path as _P
            fe = _P(out_dir) / "app" / "frontend"
            rep = scaffold_frontend_baseline(fe)
            if rep.get("scaffolded"):
                self._logger.warning(
                    "Frontend baseline scaffolded (lane left it incomplete): %s",
                    rep.get("written"))
            # FIX #44: force the build tooling to known-good pinned versions so the
            # image always builds (the lane writes "latest" everywhere → tailwind v4
            # vs v3 postcss config → npm build dies).
            pin = pin_frontend_build_tooling(fe)
            if pin.get("pinned"):
                self._logger.warning(
                    "Frontend build tooling pinned to known-good: %s", pin.get("changed"))
        except Exception as exc:
            self._logger.debug("frontend baseline scaffold skipped: %s", exc)

    def _scaffold_frontend_pages(self) -> None:
        """Project a page-component STUB per registered ui_page + wire React-Router
        routes — the frontend analogue of the deterministic backend skeleton
        (_generate_database / backend models from the contract).

        Closes the build-asymmetry root cause (youtube run #13): the backend is
        framework-scaffolded so it completes reliably; the frontend had to
        hand-author every page + routing from scratch → built 1 page, left the
        rest in_progress, declared a hallucinated done (blank shell). Run once
        after finalize: the lane then FILLS page bodies (write/edit) instead of
        authoring from nothing, and the app is navigable-by-construction. Stubs
        are written only-if-missing; App.jsx only (re)written while it carries the
        @framework-managed-routes marker (the lane deletes it to take over). Also
        replaces the social-shaped baseline App.jsx (login/feed) with a generic
        router → domain-agnostic. Best-effort; never raises."""
        try:
            out_dir = getattr(self, "output_dir", None)
            if not out_dir:
                return
            ui_pages = []
            registryhub = getattr(self.hubs, "registryhub", None)
            if registryhub is not None and hasattr(registryhub, "list_ui_pages"):
                ui_pages = list((registryhub.list_ui_pages() or {}).values())
            if not ui_pages:
                return
            from .runtime.frontend_scaffold import scaffold_pages_from_contract
            from pathlib import Path as _P
            fe = _P(out_dir) / "app" / "frontend"
            rep = scaffold_pages_from_contract(fe, ui_pages)
            if rep.get("scaffolded") or rep.get("app_wired"):
                self._logger.info(
                    "Frontend pages projected from contract: %d stub(s), "
                    "%d route(s) wired (app_wired=%s)",
                    len(rep.get("scaffolded") or []), rep.get("routes", 0),
                    rep.get("app_wired"))
        except Exception as exc:
            self._logger.debug("frontend page projection skipped: %s", exc)

    def _repair_frontend_api(self) -> None:
        """FIX #37: reconcile frontend api.js exports with component imports on the
        integrated tree, so naming drift can't break ``npm run build`` (and thus
        the api_smoke docker_up gate). Deterministic + best-effort."""
        try:
            out_dir = getattr(self, "output_dir", None)
            if not out_dir:
                return
            from .runtime.frontend_scaffold import (
                repair_frontend_api_exports, scaffold_missing_local_pages)
            from pathlib import Path as _P
            fe = _P(out_dir) / "app" / "frontend"
            rep = repair_frontend_api_exports(fe)
            if rep.get("repaired"):
                self._logger.warning(
                    "Frontend api.js reconciled: aliased=%s stubbed=%s",
                    rep.get("aliased"), rep.get("stubbed"),
                )
            # Build-integrity: the frontend lane routinely imports a page it never
            # created (e.g. ./pages/MessagesInboxPage) → ``npm run build`` fails →
            # frontend container can't boot. Scaffold a valid stub for any dangling
            # local component import so the app always builds.
            pages = scaffold_missing_local_pages(fe)
            if pages.get("scaffolded"):
                self._logger.warning(
                    "Frontend dangling imports resolved by stub pages (lane "
                    "imported components it never created): %s",
                    pages.get("scaffolded"),
                )
        except Exception as exc:
            self._logger.debug("frontend api repair skipped: %s", exc)

    def _repair_backend_as_wiring(self) -> None:
        """FIX #39: ensure main.py wires the framework OAuth2 AS router, which now
        owns /oauth/*, /.well-known/*, AND the standard /auth/register +
        /auth/login. The backend lane variably forgets to include it (this run:
        no /oauth/* and no /auth/register at all → auth_register_login 404).
        Inject the include_router right after ``app = FastAPI(...)`` (so its routes
        take precedence over any inline /auth/* the backend wrote). Idempotent +
        best-effort."""
        try:
            out_dir = getattr(self, "output_dir", None)
            if not out_dir:
                return
            from pathlib import Path as _P
            be = _P(out_dir) / "app" / "backend"
            main_py = be / "main.py"
            if not main_py.exists() or not (be / "oauth_routes.py").exists():
                return
            src = main_py.read_text(encoding="utf-8")
            if "build_router" in src:
                return  # AS already wired (and the template now includes /auth/*)
            import re as _re
            lines = src.splitlines()
            idx = None
            for i, ln in enumerate(lines):
                if _re.match(r"\s*app\s*=\s*FastAPI\b", ln):
                    depth, j = 0, i
                    while j < len(lines):
                        depth += lines[j].count("(") - lines[j].count(")")
                        if depth <= 0:
                            break
                        j += 1
                    idx = j
                    break
            if idx is None:
                return
            wiring = [
                "",
                "# FIX #39: wire the framework OAuth2 AS (provides /oauth/*,",
                "# /.well-known/*, and the standard /auth/register + /auth/login).",
                "try:",
                "    from oauth_store import OAuthStore as _ASStore",
                "    from jwt_manager import JWTManager as _ASJwt",
                "    from oauth_routes import build_router as _as_build_router",
                "    app.include_router(_as_build_router(_ASStore(), _ASJwt()))",
                "except Exception as _as_exc:  # pragma: no cover",
                "    import logging as _l",
                "    _l.getLogger('uvicorn').warning('AS wiring skipped: %s', _as_exc)",
            ]
            lines[idx + 1:idx + 1] = wiring
            main_py.write_text("\n".join(lines) + "\n", encoding="utf-8")
            self._logger.warning(
                "Backend main.py: wired the framework OAuth2 AS router "
                "(was missing → /auth/register + /oauth/* absent).")
        except Exception as exc:
            self._logger.debug("backend AS wiring repair skipped: %s", exc)

    def _repair_backend_entrypoint(self) -> None:
        """FIX #38: ensure the backend main.py actually STARTS the server. The
        Dockerfile CMD is ``python main.py``, but the lane sometimes omits the
        ``if __name__ == '__main__': uvicorn.run(...)`` block → the container
        imports main.py and exits(0) without serving → backend_health FAIL → no
        delivery of an otherwise-working app. Append a standard uvicorn entrypoint
        (reading API_PORT, which the compose sets) when missing. Deterministic +
        best-effort."""
        try:
            out_dir = getattr(self, "output_dir", None)
            if not out_dir:
                return
            from pathlib import Path as _P
            main_py = _P(out_dir) / "app" / "backend" / "main.py"
            if not main_py.exists():
                return
            src = main_py.read_text(encoding="utf-8")
            if "uvicorn.run" in src or "__main__" in src:
                return  # already starts the server / has a main guard
            import re as _re
            if not _re.search(r"^\s*app\s*=", src, _re.M):
                return  # no module-level `app` to serve
            entry = (
                "\n\n# FIX #38: ensure `python main.py` actually serves (the lane "
                "omitted the\n# entrypoint, so the container exited(0) without "
                "starting uvicorn).\n"
                'if __name__ == "__main__":\n'
                "    import os\n"
                "    import uvicorn\n"
                "    uvicorn.run(app, host=\"0.0.0.0\", "
                "port=int(os.environ.get(\"API_PORT\", \"8081\")))\n"
            )
            main_py.write_text(src.rstrip() + entry, encoding="utf-8")
            self._logger.warning(
                "Backend main.py entrypoint appended (was missing uvicorn.run "
                "→ container would exit(0) without serving).")
        except Exception as exc:
            self._logger.debug("backend entrypoint repair skipped: %s", exc)

    def _merge_committed_agent_work(self) -> None:
        """Merge each lane's COMMITTED agent-branch work into integration so the
        framework validation/delivery runs against the latest code even when the
        authoring lane hasn't 'finished' (its workhub-task bookkeeping can lag the
        code it already wrote+committed). Best-effort, idempotent
        ("nothing to merge" when already integrated), conflict-safe
        (merge_agent_branch_to_main aborts on conflict). Never raises into the loop.
        """
        try:
            from .agents.runtime.auto_commit import merge_agent_branch_to_main, flush_worktree
        except Exception:
            return
        repo = getattr(self, "output_dir", None)
        if repo is None:
            return
        from pathlib import Path as _P
        for lane in ("backend", "database", "frontend"):
            # FLUSH FIRST: commit any uncommitted/untracked app work in the lane's
            # worktree so it's part of agent/<lane> before we merge. Without this,
            # files the lane WROTE but never finish-committed (e.g. the frontend's
            # pages authored after its last commit) are invisible to the squash
            # merge → integration ships a blank shell (frontend_navigable: 0) and
            # the run idle-wedges. This is the root fix for that recurring stall.
            try:
                _wt = _P(repo) / "worktrees" / lane
                if _wt.exists():
                    fok, finfo = flush_worktree(worktree_dir=_wt, branch=f"agent/{lane}", author=lane)
                    if fok and all(s not in str(finfo) for s in ("nothing to commit", "no deliverable", "not a git")):
                        self._logger.warning("🧹 flushed uncommitted %s worktree before merge → %s", lane, finfo)
            except Exception:
                pass
            try:
                ok, info = merge_agent_branch_to_main(
                    repo_root=repo,
                    agent_branch=f"agent/{lane}",
                    main_branch="integration",
                    agent_id=lane,
                )
            except Exception:
                continue
            if ok and info and "nothing to merge" not in str(info):
                self._logger.warning(
                    "🔀 Pre-validation merge agent/%s → integration: %s "
                    "(surfaced committed code the lane had not finish-merged).",
                    lane, info,
                )

    def _commit_framework_delivery(self) -> None:
        """Commit the framework's delivery-time writes (backend skeleton, frontend
        infra pin, projected routes/pages) on integration BEFORE the release branch
        is cut. ``create_release`` snapshots the COMMITTED head — without this
        commit every framework write stayed working-tree-only, so each release
        shipped the lane's last committed (broken) state: v1.0.0's snapshot carried
        the lane's mismatched start.sh and NO vite.config.js even though the pin
        had fixed both on disk. Best-effort; "nothing to commit" is fine."""
        try:
            from pathlib import Path as _P
            from .agents.runtime.auto_commit import _run_git
            repo = getattr(self, "output_dir", None)
            if not repo:
                return
            repo = _P(repo)
            staged_any = False
            for sub in ("app", "mcp_server", "docker"):
                if not (repo / sub).exists():
                    continue
                rc, _o, _e = _run_git(
                    ["add", "-A", "--", sub,
                     ":(exclude)**/__pycache__/**", ":(exclude)**/*.py[cod]"],
                    cwd=repo)
                staged_any = staged_any or (rc == 0)
            if not staged_any:
                return
            rc, out, err = _run_git(
                ["commit", "-m",
                 "framework delivery: backend skeleton + frontend infra + projections"],
                cwd=repo)
            if rc == 0:
                self._logger.warning(
                    "Framework delivery writes COMMITTED to integration so the "
                    "release snapshot ships them (skeleton/infra/projections).")
            # rc != 0 → nothing to commit (already clean) — silent.
        except Exception as exc:
            self._logger.debug("framework delivery commit skipped: %s", exc)

    async def _maybe_framework_deliver(self) -> None:
        """Deterministically DELIVER when the delivery gate is fully clear.

        The orchestrator LLM drifts: it calls deliverability_check over and over
        without ever firing deliver_project, even when the gate is fully clear
        (smoke #19: 30x deliverability_check, 0 deliver_project). deliver_project
        itself just sets ``_project_delivered_event`` — it does not cut a release.
        So once ``_validate_delivery_gate`` reports NO failed checks (which, with
        the functionally-validated relaxations, means: code present + a passing
        in-session api_smoke RunHub run + contract/build proven at runtime), cut
        the release and signal delivery HERE — the run completes regardless of LLM
        behaviour. Idempotent; best-effort (never breaks the loop)."""
        try:
            if getattr(self, "_project_delivered", False):
                return
            from .runtime.lifecycle import all_business_endpoints_implemented
            registryhub = getattr(self.hubs, "registryhub", None)
            if registryhub is None or not (
                all_business_endpoints_implemented(registryhub.get_endpoints())
                or self._all_business_endpoints_have_route_code()  # FIX #26
            ):
                return  # nothing to deliver yet
            gate = self._validate_delivery_gate()
            if gate.get("failed_checks"):
                # FEEDBACK LOOP (2026-06-13): an unwired-ui-pages block (declared
                # pages whose routes aren't in App.jsx) HARD-blocks delivery but,
                # unlike GATE-C1 / frontend_navigable / visual, routed NOWHERE —
                # frontend_navigable passes on >=1 route so its dispatch goes quiet
                # while delivery needs ALL declared pages wired. Route the specific
                # unwired pages back to the frontend lane (it owns the UI) so the
                # run can't deadlock with one route wired (gemini: 12 unwired,
                # delivery stuck for hours with no path back to the owner).
                if any("ui_page_unwired" in str(c) for c in gate.get("failed_checks") or []):
                    try:
                        # ROOT-CAUSE FIRST: if the pages exist but the lane built the
                        # whole app at the repo root (./src) instead of app/frontend/,
                        # tell it to RELOCATE — per-page 'wire the route' advice would
                        # be misleading. Otherwise route the genuinely-unwired pages.
                        _misplaced = self._detect_misplaced_frontend_root()
                        if _misplaced:
                            await self._dispatch_misplaced_frontend_root(_misplaced)
                        else:
                            from .runtime.deliverability import _ui_page_wiring_blockers
                            _app_root = self.output_dir / "app"
                            if not _app_root.exists():
                                _app_root = self.output_dir
                            await self._dispatch_unwired_ui_pages(
                                _ui_page_wiring_blockers(self.hubs, _app_root))
                    except Exception as _exc:
                        self._logger.error("unwired/misplaced frontend dispatch failed: %s", _exc)
                return  # not deliverable yet
            # VISUAL-FIDELITY BLOCKING (2026-06-11, user goal: UI must be
            # near-indistinguishable from the references). Releases used to cut
            # the moment the functional gate cleared, so the lane NEVER paused
            # to digest its visual-remediation P1 tasks (score flat at 0.20
            # across a full 5/5). When reference images exist: a milestone may
            # not release while the visual gate is failing AND attempts remain
            # — the lane fixes (source changes reset the per-signature
            # budget, re-judging happens in the validation flow). Exhausted
            # attempts release anyway (no deadlock), loudly. Disable via
            # ENVGEN_VISUAL_BLOCKING=0.
            if (getattr(self, "_reference_images", None)
                    and getattr(self, "_is_final_milestone", True)
                    and os.environ.get("ENVGEN_VISUAL_BLOCKING", "1").lower()
                        not in ("0", "false", "no", "off")
                    and not getattr(self, "_vf_passed", False)):
                if getattr(self, "_vf_deferred_since", None) is None:
                    self._vf_deferred_since = time.time()  # anchor: milestone's FIRST defer
                _now = time.time()
                _vf_decision = _visual_release_decision(
                    self._vf_deferred_since,
                    getattr(self, "_vf_attempts", 0),
                    getattr(self, "_vf_total_judgments", 0),
                    _now,
                )
                if _vf_decision == "defer":
                    self._logger.warning(
                        "DELIVERY DEFERRED: visual fidelity not passed (attempt "
                        "%s/3 on current source, %ss deferred, %s judged) — re-"
                        "judging now; waiting for the frontend to digest the "
                        "remediation task before cutting this milestone's release.",
                        getattr(self, "_vf_attempts", 0),
                        int(_now - self._vf_deferred_since),
                        getattr(self, "_vf_total_judgments", 0))
                    # DRIVE the re-judge from here (the validation-success branch
                    # SKIPS once a gate-passing run exists). _maybe_run_visual_fidelity
                    # self-guards (pass latch + per-source attempt cap); the deferral
                    # now ALWAYS terminates via _visual_release_decision's escapes —
                    # the 900s wall-clock ANCHORED to the first defer (no longer reset
                    # by lane churn — PIPE-C3), the per-source attempt cap, or the
                    # per-milestone total-judgment cap.
                    await self._maybe_run_visual_fidelity()
                    return
                # release: an escape fired — deliver anyway, loudly, below-threshold.
                self._logger.warning(
                    "Visual fidelity deferral RELEASED (escape after %ss deferred / "
                    "%s attempts / %s total judged) — delivering anyway "
                    "(recorded as below-threshold).",
                    int(_now - self._vf_deferred_since),
                    getattr(self, "_vf_attempts", 0),
                    getattr(self, "_vf_total_judgments", 0))
            # Flush any committed-but-unmerged lane work into integration BEFORE
            # snapshotting the release. Observed (instagram MM, 2026-06-08): the
            # backend committed the final milestone's routes to agent/backend 11s
            # AFTER the gate cleared and delivery fired; the periodic
            # pre-validation merge had already run, so those commits never reached
            # integration and the release (1.4.0) was hollow — 3 implemented M5
            # endpoints stranded. Merging here (idempotent, conflict-safe — aborts
            # on real conflict) guarantees create_release() snapshots every commit
            # the lanes have landed, closing the deliver↔merge race.
            self._merge_committed_agent_work()
            # SKELETON根治: regenerate the deterministic backend from the contract on the
            # merged tree right before the release snapshot, so the released milestone
            # ships the by-construction backend (the route projector below then no-ops).
            self._generate_backend_skeleton()
            # Frontend INFRA parity: re-force the known-good build/serve tooling on the
            # merged tree too, so the RELEASE SNAPSHOT ships working infra (the merge
            # re-imports the lane's broken Dockerfile/nginx/start.sh/vite config that
            # the heal-time pin had fixed — v1.0.0 shipped exactly that breakage).
            self._scaffold_frontend_baseline()
            # …and reconcile api.js exports with what pages import (the merge
            # re-imports the lane's api.js; projected pages need apiGet/apiPost).
            self._repair_frontend_api()
            # Fill any declared-but-uncoded endpoints AFTER the merge, on the merged
            # tree, right before the snapshot. Projecting post-merge (not per heal
            # tick) is what stops the re-projection waste: the per-tick merge
            # stashes+drops an uncommitted projection, so projecting before a merge
            # is destroyed and re-added every tick. Here nothing follows to drop it.
            self._project_missing_routes()
            # (frontend projection removed 2026-06-11 — the lane owns the UI;
            # frontend_navigable / dead-controls / visual gates enforce it.)
            # COMMIT the framework writes above — the release branch is cut from the
            # COMMITTED head, so uncommitted skeleton/infra/projection writes would
            # otherwise be excluded from the snapshot the user boots.
            self._commit_framework_delivery()
            # Gate fully clear → cut the release from the integration branch.
            # Multi-milestone: the release tag is the CURRENT milestone version
            # (1.0.0/1.1.0/1.2.0/…) so releases accumulate in
            # codehub_releases.json (the store is keyed by tag). Defaults to
            # "1.0.0" for the single-milestone path (byte-identical to today).
            release_tag = getattr(self, "_current_milestone_version", "1.0.0")
            try:
                ch = getattr(self.hubs, "codehub", None)
                if ch is not None and hasattr(ch, "create_release"):
                    ch.create_release(
                        tag=release_tag, source="integration",
                        notes=("Framework delivery: api_smoke validated (RunHub run "
                               "passed) and the delivery gate is fully clear."),
                        agent="orchestrator",
                    )
            except Exception as _rel_err:  # release is best-effort observability
                self._logger.warning("framework delivery: create_release failed: %s", _rel_err)
            # Post-milestone TEST-USER phase: simulate a real user's journey across the
            # API + check the MCP surface, writing a feedback report so a milestone never
            # ships a broken contract silently. Offloaded to a thread (blocking HTTP +
            # subprocess); best-effort, never blocks/raises into delivery.
            try:
                import asyncio as _asyncio
                await _asyncio.to_thread(self._run_test_user_validation, release_tag)
            except Exception as _tu_err:
                self._logger.debug("test-user phase dispatch failed: %s", _tu_err)
            self._project_delivered = True
            ev = getattr(self, "_project_delivered_event", None)
            if ev is not None:
                try:
                    ev.set()
                except Exception:
                    pass
            self._logger.warning(
                "🚀 FRAMEWORK DELIVERY: delivery gate fully clear (no failed "
                "checks) → cut release v%s + signalled delivery "
                "(orchestrator LLM drifted on deliver_project).",
                release_tag,
            )
        except Exception as exc:  # never break the coordination loop
            self._logger.error("framework delivery raised (non-fatal): %s", exc)

    def _incomplete_required_tasks(self) -> List[Dict[str, Any]]:
        """GATE-C2/C3: kickoff-synthesized STRUCTURAL tasks that are still
        pending/in_progress AND not satisfied by registry evidence.

        The delivery gate is an "evidence exists" model — it never checked
        whether the assigned work is DONE, so dozens of per-endpoint
        ``validate_api_smoke`` tasks (and any ``implement_*`` task) could linger
        pending while a release cut anyway (the user's "task not finished, why
        release" root cause).

        This is COVERAGE-AWARE, not status-naive — verified on the released
        generated/instagram round47: 24 ``validate_api_smoke`` tasks sat pending
        only because the verifier ran one ``run_validation()`` covering every
        endpoint instead of closing each per-endpoint task. Blocking on raw
        pending status would falsely block that good release. So a pending task
        blocks ONLY when its registry evidence is missing:

          * ``implement_endpoint``  → endpoint not registered implemented/tested
          * ``implement_table``     → table not registered implemented/tested
          * ``validate_api_smoke``  → endpoint has no passing contract-test record

        Ad-hoc ``task_*`` (visual / breaking-change / merge-conflict / chain-
        authoring remediation) are NOT structural kickoff kinds — they are
        governed by their own gates (visual deferral, deliverability) and are
        deliberately excluded here so this gate never double-blocks them.
        """
        wh = getattr(self.hubs, "workhub", None)
        if wh is None or not hasattr(wh, "list_tasks"):
            return []
        rh = getattr(self.hubs, "registryhub", None)
        sh = getattr(self.hubs, "schema_hub", None)
        try:
            tasks = wh.list_tasks() or []
        except Exception:
            return []

        def _norm(s: Any) -> str:
            return re.sub(r"[^a-z0-9]", "", str(s or "").lower())

        # Registry endpoint identity → (clean_id, implemented?) keyed by the
        # normalized form so a task's metadata.endpoint OR its munged id both map.
        endpoints: Dict[str, Any] = {}
        try:
            endpoints = (rh.get_endpoints() if rh is not None else {}) or {}
        except Exception:
            endpoints = {}
        reg_clean: Dict[str, str] = {}
        impl_ep: set = set()
        for k, v in endpoints.items():
            if k == "_meta" or not isinstance(v, dict):
                continue
            clean = (
                f"{(v.get('method') or '').upper()} {v.get('path') or ''}".strip()
                if v.get("method") else str(k)
            )
            nk = _norm(clean)
            reg_clean[nk] = clean
            if v.get("status") in {"implemented", "tested"}:
                impl_ep.add(nk)

        tables: Dict[str, Any] = {}
        try:
            tables = (sh.list_tables() if sh is not None else {}) or {}
        except Exception:
            tables = {}
        impl_tbl: set = {
            _norm(v.get("name") or k)
            for k, v in tables.items()
            if k != "_meta" and isinstance(v, dict)
            and v.get("status") in {"implemented", "tested"}
        }

        _METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}

        def _endpoint_norm(t: Dict[str, Any]) -> str:
            ep = (t.get("metadata") or {}).get("endpoint") or t.get("endpoint")
            if isinstance(ep, dict) and ep.get("path"):
                return _norm(f"{(ep.get('method') or '').upper()} {ep['path']}")
            parts = str(t.get("id") or "").split(".")
            for i, p in enumerate(parts):
                if p.lower() in _METHODS and i + 1 < len(parts):
                    return _norm(p + " " + ".".join(parts[i + 1:]))
            return _norm(t.get("id"))

        def _table_norm(t: Dict[str, Any]) -> str:
            name = (t.get("metadata") or {}).get("table") or t.get("table")
            if name:
                return _norm(name)
            tid = str(t.get("id") or "")
            return _norm(tid[len("impl.table."):] if tid.startswith("impl.table.") else tid)

        def _endpoint_validated(nk: str) -> bool:
            if rh is None:
                return False
            clean = reg_clean.get(nk)
            if not clean:  # endpoint not even registered → cannot be validated
                return False
            try:
                recs = rh.get_contract_test_results(clean) or []
            except Exception:
                return False
            return any(
                isinstance(r, dict)
                and ((r.get("result") or {}).get("passed") is True
                     or (r.get("result") or {}).get("verdict") == "pass")
                for r in recs
            )

        incomplete: List[Dict[str, Any]] = []
        for t in tasks:
            if not isinstance(t, dict):
                continue
            if t.get("status") not in {"pending", "in_progress"}:
                continue
            kind = (t.get("metadata") or {}).get("kind") or t.get("kind")
            if kind == "implement_endpoint":
                if _endpoint_norm(t) in impl_ep:
                    continue
                reason = "endpoint not implemented in registry"
            elif kind == "implement_table":
                if _table_norm(t) in impl_tbl:
                    continue
                reason = "table not implemented in registry"
            elif kind == "validate_api_smoke":
                if _endpoint_validated(_endpoint_norm(t)):
                    continue
                reason = "endpoint has no passing contract-test record"
            else:
                continue  # not a structural kickoff task — governed elsewhere
            incomplete.append({
                "id": t.get("id"),
                "kind": kind,
                "status": t.get("status"),
                "assignee": t.get("assignee"),
                "reason": reason,
            })
        return incomplete

    def _noncanonical_business_response_keys(self) -> List[Dict[str, Any]]:
        """PROMPT-C1 (response_key by-construction): a route_projector-projected
        business endpoint MUST declare a response_key inside the canonical envelope
        the projector actually emits — ``items`` (collection) or ``item`` (single).
        The projector hardcodes that envelope and IGNORES any other key, so a
        registered ``response_key='games'`` leaves the frontend reading
        ``data.games`` against a ``{"items": [...]}`` body → the single biggest
        blank-page source. Flag the non-canonical key at build time instead.

        Only the KEY VOCABULARY is enforced ({items, item}); WHICH of the two an
        endpoint should use (single vs collection) is the runtime
        ``business_endpoints_correct_shape`` gate's job — and is deliberately NOT
        re-derived here, because the method/path heuristic mis-classifies legit
        single-object GETs that don't end in ``/me`` or ``/{id}`` (round47's
        ``GET /api/.../insights`` / ``/limit`` / ``/business_discovery`` correctly
        return ``item``; demanding ``items`` for them would be a false positive).

        Scope = projector-owned BUSINESS endpoints only. Control-plane / infra /
        auth / oauth / spine endpoints carry a ``metadata.kind`` and ship their own
        handlers (e.g. ``{"message": ...}``) — NOT projected, frontend already skips
        them, exempt (round47's 3 ``message`` keys are all ``kind=infra``).
        custom_routes are hand-authored, exempt. An ABSENT response_key is a
        separate "lane forgot to set it" concern, not a wrong-key blank page, so it
        is not flagged here."""
        rh = getattr(self.hubs, "registryhub", None)
        if rh is None:
            return []
        try:
            endpoints = rh.get_endpoints() or {}
        except Exception:
            return []
        _CANONICAL = {"items", "item"}
        _EXEMPT_KINDS = {"auth", "oauth", "infra", "spine", "control_plane", "custom"}
        bad: List[Dict[str, Any]] = []
        for k, v in endpoints.items():
            if k == "_meta" or not isinstance(v, dict):
                continue
            md = v.get("metadata") or {}
            if str(md.get("kind") or "").strip().lower() in _EXEMPT_KINDS:
                continue  # not projector-owned (orchestrator/spine/custom handlers)
            if md.get("custom") or md.get("custom_route"):
                continue  # custom_routes are hand-authored, not projected
            rk = md.get("response_key") or (v.get("schema") or {}).get("response_key")
            if rk is None or rk in _CANONICAL:
                continue
            bad.append({
                "endpoint": k,
                "response_key": rk,
                "reason": (
                    f"projected business endpoint declares non-canonical "
                    f"response_key={rk!r} — the projector emits {{items/item}}, so the "
                    f"frontend reading data.{rk} renders blank. Use 'items' or 'item'."
                ),
            })
        return bad

    def _validate_delivery_gate(self) -> Dict[str, Any]:
        """
        Validate objective delivery readiness.

        Gate design:
        1) Required artifacts must exist (compose + README).
        2) Generated code footprint must exist for backend/frontend/database.
        3) RegistryHub / SchemaHub / WorkHub must contain registered contract entries.
        4) Contract alignment: registered endpoints/tables match implemented code.
        5) If build checklist has recorded results, it must be ready_for_delivery.
        """
        # Guarantee the required design doc exists before checking (also scaffolded
        # each heal tick; this covers the resumed-complete checkpoint path).
        self._scaffold_design_readme()
        required_files = [
            "docker/docker-compose.yml",
            "design/README.md",
        ]
        required_dirs = [
            "app/backend",
            "app/frontend",
            "app/database",
        ]

        missing_files: List[str] = []
        invalid_json: List[str] = []
        missing_dirs: List[str] = []
        failed_checks: List[str] = []

        for rel in required_files:
            p = self.output_dir / rel
            if not p.exists():
                missing_files.append(rel)

        for rel in required_dirs:
            p = self.output_dir / rel
            if not p.exists() or not p.is_dir():
                missing_dirs.append(rel)

        # Basic code footprint checks
        backend_has_code = any((self.output_dir / "app/backend").glob("**/*.*"))
        frontend_has_code = any((self.output_dir / "app/frontend").glob("**/*.*"))
        database_has_sql = any((self.output_dir / "app/database").glob("**/*.sql"))
        if not backend_has_code:
            failed_checks.append("backend_code_missing")
        if not frontend_has_code:
            failed_checks.append("frontend_code_missing")
        if not database_has_sql:
            failed_checks.append("database_sql_missing")

        # A deterministically functionally-validated app — a successful in-session
        # RunHub run (the framework's api_smoke: clean docker boot that BUILT the
        # frontend+backend, then probed every endpoint) — has already PROVEN both
        # contract alignment and the frontend build at runtime. So the static
        # contract-alignment check and the frontend_build RECORD (verifier
        # bookkeeping the LLM drifts on) become warnings, not hard delivery
        # blockers. They still block when the app is NOT functionally validated.
        _session_ts = getattr(self, "_session_start_ts", 0.0) or 0.0
        _runhub = getattr(self.hubs, "runhub", None)
        functionally_validated = bool(
            _runhub is not None
            and hasattr(_runhub, "last_successful_run_since")
            and _runhub.last_successful_run_since(_session_ts)
        )

        contract_report = self._validate_contract_alignment()
        if contract_report.get("errors") and not functionally_validated:
            failed_checks.append("contract_alignment_failed")

        build_report = self._validate_build_evidence()
        if (build_report.get("frontend_package")
                and not build_report.get("frontend_build_recorded")
                and not functionally_validated):
            failed_checks.append("frontend_build_not_recorded")

        # hub topology checks
        endpoints = self.hubs.registryhub.get_endpoints() or {}
        tables = self.hubs.schema_hub.list_tables() or {}
        pages = self.hubs.registryhub.list_ui_pages() or {}
        projection_errors = {}  # file-coordination CRDT removed in Cutover 4 (replaced by git worktree)
        semantic_drift = {"errors": [], "warnings": []}  # vestigial — specs no longer exist as independent source.

        if not endpoints:
            failed_checks.append("no_endpoints_in_hub")
        if not tables:
            failed_checks.append("no_tables_in_hub")
        if not pages:
            failed_checks.append("no_pages_in_hub")
        if semantic_drift.get("errors"):
            failed_checks.append("semantic_hub_drift")
        if projection_errors:
            failed_checks.append("semantic_projection_errors")

        implemented_endpoints = sum(
            1 for v in endpoints.values()
            if isinstance(v, dict) and v.get("status") in {"implemented", "tested"}
        )
        implemented_tables = sum(
            1 for v in tables.values()
            if isinstance(v, dict) and v.get("status") in {"implemented", "tested"}
        )
        if implemented_endpoints == 0:
            failed_checks.append("no_implemented_endpoints")
        if implemented_tables == 0:
            failed_checks.append("no_implemented_tables")

        # Build verification checklist from CodeHub.checks directly (hubs.get_verification_checklist removed)
        try:
            build_checks = [
                c for c in self.hubs.codehub.list_checks()
                if c.get("name", "").startswith("build:")
            ]
            by_component: dict = {}
            for c in build_checks:
                comp = c.get("name", "").removeprefix("build:")
                prev = by_component.get(comp)
                if prev is None or c.get("updated_at", 0) > prev.get("updated_at", 0):
                    by_component[comp] = c.get("status", "pending")
            checklist_statuses_map = {
                "sql_syntax": by_component.get("database", "pending"),
                "docker_build": by_component.get("docker", "pending"),
                "npm_install": by_component.get("frontend", "pending"),
                "backend_start": by_component.get("backend", "pending"),
            }
            all_passing = all(s == "success" for s in checklist_statuses_map.values())
            checklist = {
                "checklist": {k: {"status": v} for k, v in checklist_statuses_map.items()},
                "all_required_passing": all_passing,
                "ready_for_delivery": all_passing,
            }
        except Exception:
            checklist = {"checklist": {}, "all_required_passing": False, "ready_for_delivery": False}
        checklist_items = checklist.get("checklist", {})
        statuses = [
            item.get("status", "pending")
            for item in checklist_items.values()
            if isinstance(item, dict)
        ]
        any_recorded = any(s != "pending" for s in statuses)
        if any_recorded and not checklist.get("ready_for_delivery", False):
            failed_checks.append("verification_checklist_not_ready")

        # Runtime validation matrix (if task suite exists):
        # require at least one API smoke pass and one UI smoke pass.
        task_suite_exists = (self.output_dir / "tasks" / "tasks.yaml").exists()
        validation_summary = self._get_validation_summary() or {}
        validation_results = self._get_validation_results(limit=200) or []
        retry_pending_count = int(validation_summary.get("retry_pending_count", 0) or 0)
        api_smoke_pass = any(
            isinstance(r, dict)
            and r.get("status") == "passed"
            and r.get("metadata", {}).get("check") in {"api_smoke", "api_health"}
            for r in validation_results
        )
        ui_smoke_pass = any(
            isinstance(r, dict)
            and r.get("status") == "passed"
            and r.get("metadata", {}).get("check") in {"ui_smoke", "ui_page_reachable"}
            for r in validation_results
        )
        failed_validation_top = [
            {
                "task_id": r.get("task_id"),
                "status": r.get("status"),
                "summary": r.get("summary", ""),
                "domain_hint": (
                    (r.get("metadata", {}) or {}).get("domain")
                    or (r.get("evidence", {}) or {}).get("domain")
                    or "any"
                ),
                "execution_mode": r.get("execution_mode", "auto"),
            }
            for r in validation_results
            if isinstance(r, dict) and r.get("status") in {"failed", "error"}
        ][:5]
        if task_suite_exists:
            if retry_pending_count > 0:
                # Soft-fail: auto-retry loop is still in progress.
                failed_checks.append("validation_retry_pending")
            else:
                if not api_smoke_pass:
                    failed_checks.append("validation_api_smoke_missing")
                if not ui_smoke_pass:
                    failed_checks.append("validation_ui_smoke_missing")

        # PR 6 review (2026-05-30) follow-up: fold the
        # deliverability aggregator into the autonomous hard gate.
        # ``compute_deliverability`` was previously only consumed by
        # the UI-driven deliver path (``deliver_project_call`` in
        # live_monitor_server). The autonomous / LLM-driven deliver
        # path enforced retro (via ``RetroBeforeDeliverPolicy``) and
        # the topology/build checks above, but NOT visual-critical
        # approval, seed data, RunHub-successful-run-since-session,
        # or coverage dead-artifact detection. The original in-tool
        # gates in ``DeliverProjectTool.execute`` intended to enforce
        # those four — but were dead-wired (``self.agent.hub_registry``
        # vs the real ``self.agent._hubs``); the 2026-05-30 cleanup
        # commit deleted them. Folding here closes the
        # autonomous-vs-UI enforcement asymmetry by reusing the SAME
        # aggregator both paths now share. Single enforcement point,
        # consistent with the architectural pattern from the
        # two-pass dispatcher and GateRegistry extraction.
        deliverability_failed_checks: List[str] = []
        try:
            from .runtime.deliverability import compute_deliverability
            session_start_ts = getattr(self, "_session_start_ts", 0.0) or 0.0
            app_root = self.output_dir / "app"
            if not app_root.exists():
                app_root = self.output_dir
            deliverability_report = compute_deliverability(
                self.hubs, app_root, session_start_ts=session_start_ts,
            )
            for blocker in (deliverability_report.blockers or []):
                # Canonicalize: blocker strings are human prose; map
                # them onto stable check tokens the test surface
                # can assert against. Each token names the failed
                # dimension; the full prose remains in
                # ``deliverability_report`` returned below for the
                # operator-facing log.
                low = blocker.lower()
                if "no successful runhub run" in low:
                    deliverability_failed_checks.append("deliverability_no_successful_run")
                elif "failed endpoint probe" in low:
                    deliverability_failed_checks.append("deliverability_failed_endpoint_probes")
                elif "failed mcp probe" in low:
                    deliverability_failed_checks.append("deliverability_failed_mcp_probes")
                elif "dead artifact" in low:
                    deliverability_failed_checks.append("deliverability_dead_artifacts")
                elif "missing seed" in low:
                    deliverability_failed_checks.append("deliverability_missing_seed")
                elif "low row count" in low or "placeholder seed" in low:
                    deliverability_failed_checks.append("deliverability_seed_quality")
                elif "critical visual review" in low and "pending" in low:
                    deliverability_failed_checks.append("deliverability_critical_visuals_pending")
                elif "critical visual review" in low and "need revision" in low:
                    deliverability_failed_checks.append("deliverability_critical_visuals_needs_revision")
                elif "critical_flows" in low and "unparseable" in low:
                    deliverability_failed_checks.append("deliverability_critical_flows_invalid")
                elif "ui flow(s) failed" in low:
                    # Anchor on the FULL prefix emitted by
                    # ``_flow_coverage_summary`` (``"N critical UI
                    # flow(s) failed:"``) so a flow whose NAME
                    # contains the substring "missing" (e.g.
                    # ``recover_missing_password``) doesn't collide
                    # with the missing-branch elif. Check failed
                    # FIRST: ``ui flow(s) failed`` doesn't appear in
                    # the missing-branch prose; ``missing`` can
                    # appear in the failed-branch prose if a flow
                    # name has it.
                    deliverability_failed_checks.append("deliverability_ui_flow_failed")
                elif "ui flow(s) missing" in low:
                    deliverability_failed_checks.append("deliverability_ui_flow_missing")
                elif "declared but unusable" in low:
                    # B1: a declared ui_page whose route isn't wired in App.jsx
                    # or whose component file is absent (round 44 blank-screen
                    # class). Deterministic, NOT relaxed on functionally_validated.
                    deliverability_failed_checks.append("deliverability_ui_page_unwired")
                else:
                    # Unmapped blocker — surface verbatim under a
                    # catch-all so the operator sees it instead of
                    # silently dropping; future canonicalization
                    # work can move it into a named token.
                    deliverability_failed_checks.append(
                        f"deliverability_other:{blocker[:80]}"
                    )
        except Exception as deliv_err:
            # Defense in depth: a malformed aggregator call must
            # never crash the gate. Surface the exception as its
            # own failure so the gap stays visible.
            try:
                self._logger.warning(
                    f"compute_deliverability raised inside delivery gate: {deliv_err}"
                )
            except Exception:
                pass
            deliverability_failed_checks.append("deliverability_compute_failed")
            deliverability_report = None

        failed_checks.extend(deliverability_failed_checks)

        # GATE-C2/C3 (2026-06-12): task-completeness HARD check. The gate above
        # proves "evidence exists"; this proves "the assigned structural work is
        # DONE". Coverage-aware (see _incomplete_required_tasks) so it never
        # blocks a run_validation-covered endpoint whose per-endpoint task was
        # left open. NOT relaxed by functionally_validated — an un-evidenced
        # implement_*/validate task is genuine incomplete work, not bookkeeping.
        incomplete_required_tasks = self._incomplete_required_tasks()
        if incomplete_required_tasks:
            failed_checks.append("incomplete_required_tasks")

        # PROMPT-C1 (2026-06-12): response_key by-construction. A projected
        # business endpoint whose declared response_key isn't the canonical
        # items/item envelope the projector emits is a latent blank page —
        # catch it at the gate instead of at the user's screen.
        noncanonical_response_keys = self._noncanonical_business_response_keys()
        if noncanonical_response_keys:
            failed_checks.append("business_response_key_noncanonical")

        ok = not (missing_files or missing_dirs or invalid_json or failed_checks)
        soft_fail_only = (
            bool(failed_checks)
            and set(failed_checks).issubset({"validation_retry_pending"})
            and not (missing_files or missing_dirs or invalid_json)
        )
        gate_state = "ok" if ok else ("waiting_for_retry" if soft_fail_only else "failed")
        return {
            "ok": ok,
            "state": gate_state,
            "soft_fail_only": soft_fail_only,
            "missing_files": missing_files,
            "missing_dirs": missing_dirs,
            "invalid_json": invalid_json,
            "failed_checks": failed_checks,
            "incomplete_required_tasks": incomplete_required_tasks,
            "noncanonical_response_keys": noncanonical_response_keys,
            "hub_counts": {
                "endpoints": len(endpoints),
                "tables": len(tables),
                "pages": len(pages),
                "implemented_endpoints": implemented_endpoints,
                "implemented_tables": implemented_tables,
            },
            "verification": checklist,
            "contract_alignment": contract_report,
            "semantic_hub_drift": semantic_drift,
            "projection_errors": projection_errors,
            "build_evidence": build_report,
            "deliverability": (
                deliverability_report.to_dict()
                if deliverability_report is not None else None
            ),
            "validation_runtime": {
                "task_suite_exists": task_suite_exists,
                "total_results": validation_summary.get("total", 0),
                "all_passed": validation_summary.get("all_passed", False),
                "api_smoke_pass": api_smoke_pass,
                "ui_smoke_pass": ui_smoke_pass,
                "retries_used_total": validation_summary.get("retries_used_total", 0),
                "retry_pending_count": validation_summary.get("retry_pending_count", 0),
                "retry_exhausted_count": validation_summary.get("retry_exhausted_count", 0),
                "failed_top": failed_validation_top,
            },
        }

    def _validate_contract_alignment(self) -> Dict[str, Any]:
        """Run lightweight static checks for design/DB/backend/API drift."""
        errors: List[str] = []
        warnings: List[str] = []

        # Sources of truth: RegistryHub for endpoints, SchemaHub for tables.
        hub_endpoints = self.hubs.registryhub.get_endpoints() or {}
        hub_tables = self.hubs.schema_hub.list_tables() or {}
        api_spec = {
            "endpoints": [
                {"method": ep.get("method"), "path": ep.get("path")}
                for ep in hub_endpoints.values()
                if isinstance(ep, dict) and ep.get("status") != "deprecated"
            ],
        }
        db_spec = {"tables": list(hub_tables.values())}

        expected_tables = self._extract_spec_tables(db_spec)
        sql_tables = self._extract_sql_tables(self.output_dir / "app/database")
        backend_sql_refs = self._extract_backend_sql_refs(self.output_dir / "app/backend")

        from .runtime.database_scaffold import _SPINE_OWNED_TABLES
        for table, expected_columns in sorted(expected_tables.items()):
            if str(table).lower() in _SPINE_OWNED_TABLES:
                # tenants/users/oauth_* are owned deterministically by the
                # tenancy spine (database_scaffold), not the contract — skip
                # column alignment so a contract-declared users table (which
                # the spine intentionally replaces) doesn't false-error.
                continue
            if not expected_columns:
                # Hub knows of the table but hasn't registered columns
                # yet (early/minimal state). Skip column-level alignment.
                continue
            actual_columns = sql_tables.get(table)
            if actual_columns is None:
                errors.append(f"SQL schema missing registered table: {table}")
                continue
            missing_columns = sorted(expected_columns - actual_columns)
            if missing_columns:
                errors.append(f"SQL table `{table}` missing registered columns: {', '.join(missing_columns[:8])}")

        for table, referenced_columns in sorted(backend_sql_refs.items()):
            actual_columns = sql_tables.get(table)
            if not actual_columns:
                warnings.append(f"Backend references table `{table}` but SQL schema did not define it.")
                continue
            missing_columns = sorted(referenced_columns - actual_columns)
            if missing_columns:
                errors.append(f"Backend references missing SQL columns on `{table}`: {', '.join(missing_columns[:8])}")

        declared_endpoints = self._extract_api_endpoints(api_spec)
        implemented_endpoints = self._extract_backend_routes(self.output_dir / "app/backend")
        # Param-agnostic match so {id}/:id/${id} + stack differences don't false-flag.
        declared_keys = {_contract.param_agnostic(e): e for e in declared_endpoints}
        impl_keys = {_contract.param_agnostic(r) for r in implemented_endpoints}
        if declared_endpoints and implemented_endpoints:
            missing_endpoints = sorted(e for k, e in declared_keys.items() if k not in impl_keys)
            if missing_endpoints:
                warnings.append(
                    "Backend route coverage missing declared endpoints: "
                    + ", ".join(missing_endpoints[:10])
                )

        # Code-derived consumer gate (P0, contract_enforcement_and_lifecycle_design §A2):
        # every BUSINESS API call in the generated frontend MUST hit a registered
        # endpoint. Phase 3b.6: the auth/oauth surface (oauth_scaffold), the spine
        # tables (database_scaffold) and the tenant/health control plane
        # (control_plane) are now REGISTERED in RegistryHub by _register_contract_surface
        # — so a frontend call to /auth/login or /api/v1/reset matches a real
        # declared endpoint and needs no hardcoded path exemption (consistency-by-
        # construction replaces the old _INFRA prefix list). The only residual
        # exemption is the EXTERNAL central IdP (/idp) used by the google-idp env
        # variant — it is a foreign service, never an endpoint of THIS env.
        frontend_calls = self._extract_frontend_calls(self.output_dir / "app/frontend")
        _EXTERNAL = ("/idp",)
        # Match on PATH (param-agnostic), METHOD-tolerant. A static scan can't
        # reliably tell a fetch's method from a React-Router route path (a `/auth/
        # login` *page* route looks like `GET /auth/login`), so requiring a
        # method-exact match false-flags registered endpoints as "unregistered".
        # The api_smoke gate (authoritative — it boots the app and probes every
        # registered endpoint with its real method) already validated the surface,
        # so here flag only a call whose PATH has NO registered endpoint at all —
        # that is the genuine frontend↔contract drift this gate exists to catch.
        def _pa_path(mp: str) -> str:
            pa = _contract.param_agnostic(mp)
            return pa.split(" ", 1)[1] if " " in pa else pa
        declared_path_keys = {_pa_path(e) for e in declared_endpoints}
        unregistered_calls = []
        for call in sorted(frontend_calls):
            path = call.split(" ", 1)[1] if " " in call else call
            if any(path == pre or path.startswith(pre + "/") for pre in _EXTERNAL):
                continue
            if declared_path_keys and _pa_path(call) not in declared_path_keys:
                unregistered_calls.append(call)
        if unregistered_calls:
            errors.append(
                "Frontend calls unregistered endpoint(s) (register in RegistryHub): "
                + ", ".join(unregistered_calls[:10])
            )

        return {
            "errors": errors[:20],
            "warnings": warnings[:20],
            "expected_tables": len(expected_tables),
            "sql_tables": len(sql_tables),
            "declared_endpoints": len(declared_endpoints),
            "implemented_endpoints": len(implemented_endpoints),
            "frontend_calls": len(frontend_calls),
            "frontend_call_unregistered": len(unregistered_calls),
        }

    def _validate_build_evidence(self) -> Dict[str, Any]:
        """Check whether generated projects have recorded build validation."""
        frontend_package = self.output_dir / "app/frontend/package.json"
        validation_results = self._get_validation_results(limit=200) or []
        frontend_build_recorded = any(
            isinstance(r, dict)
            and r.get("status") == "passed"
            and (
                r.get("metadata", {}).get("check") == "frontend_build"
                or "npm run build" in str(r.get("summary", "")).lower()
            )
            for r in validation_results
        )
        return {
            "frontend_package": frontend_package.exists(),
            "frontend_build_recorded": frontend_build_recorded,
        }

    def _read_json_file(self, path: Path) -> Dict[str, Any]:
        try:
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}
        return {}

    def _extract_spec_tables(self, spec: Dict[str, Any]) -> Dict[str, set]:
        tables = spec.get("tables", {})
        out: Dict[str, set] = {}
        if isinstance(tables, dict):
            iterable = tables.items()
        elif isinstance(tables, list):
            iterable = ((t.get("name"), t) for t in tables if isinstance(t, dict))
        else:
            iterable = []
        for raw_name, table in iterable:
            name = str(raw_name or "").strip()
            if not name or not isinstance(table, dict):
                continue
            columns = table.get("columns", {})
            if isinstance(columns, dict):
                out[name] = {str(c) for c in columns.keys()}
            elif isinstance(columns, list):
                out[name] = {
                    str(c.get("name"))
                    for c in columns
                    if isinstance(c, dict) and c.get("name")
                }
        return out

    # Contract extraction lives in multi_agent/delivery/contract_extract.py. It is
    # now STACK-PLUGGABLE (FastAPI + Express auto-detected) — see that module.
    def _extract_sql_tables(self, db_dir: Path) -> Dict[str, set]:
        return _contract.extract_sql_tables(db_dir)

    def _extract_frontend_calls(self, frontend_dir: Path) -> set:
        return _contract.extract_frontend_calls(frontend_dir)

    def _extract_backend_sql_refs(self, backend_dir: Path) -> Dict[str, set]:
        return _contract.extract_backend_sql_refs(backend_dir)

    def _extract_api_endpoints(self, spec: Dict[str, Any]) -> set:
        return _contract.extract_api_endpoints(spec)

    def _extract_spec_pages(self, spec: Dict[str, Any]) -> set:
        return _contract.extract_spec_pages(spec)

    def _extract_backend_routes(self, backend_dir: Path) -> set:
        return _contract.extract_backend_routes(backend_dir)

    # ---- Run budget (surfaced in the UI) ----------------------------------
    def _run_budget_path(self) -> Path:
        return self.output_dir / "run_budget.json"

    def _load_run_budget_caps(self, env_defaults: Dict[str, Any]) -> Dict[str, Any]:
        """Caps from run_budget.json if present (UI can raise them live), else env."""
        try:
            data = json.loads(self._run_budget_path().read_text(encoding="utf-8"))
            caps = data.get("caps") or {}
            return {
                "max_wall_sec": float(caps.get("max_wall_sec", env_defaults["max_wall_sec"])),
                "max_ticks": int(caps.get("max_ticks", env_defaults["max_ticks"])),
                "unlimited": bool(caps.get("unlimited", env_defaults.get("unlimited", False))),
            }
        except Exception:
            return dict(env_defaults)

    def _write_run_budget(self, caps: Dict[str, Any], started_at: float,
                          elapsed: float, ticks: int, status: str) -> None:
        """Persist caps + usage so the live monitor can show budget progress."""
        try:
            payload = {
                "caps": {"max_wall_sec": float(caps["max_wall_sec"]), "max_ticks": int(caps["max_ticks"]),
                         "unlimited": bool(caps.get("unlimited", False))},
                "usage": {
                    "started_at": started_at,
                    "elapsed_sec": round(float(elapsed), 1),
                    "ticks": int(ticks),
                    "status": status,
                    "updated_at": time.time(),
                },
            }
            path = self._run_budget_path()
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            os.replace(tmp, path)
        except Exception as e:
            self._logger.debug("run_budget write failed: %s", e)
    
    def _format_delivery_gate_report(self, gate: Dict[str, Any]) -> str:
        """Format delivery gate result as a readable report."""
        if gate.get("ok", False):
            counts = gate.get("hub_counts", {})
            return (
                "Delivery gate passed.\n"
                f"- Endpoints: {counts.get('endpoints', 0)} "
                f"(implemented/tested: {counts.get('implemented_endpoints', 0)})\n"
                f"- Tables: {counts.get('tables', 0)} "
                f"(implemented/tested: {counts.get('implemented_tables', 0)})\n"
                f"- Pages: {counts.get('pages', 0)}"
            )

        state = gate.get("state", "failed")
        if state == "waiting_for_retry":
            lines = ["Delivery gate waiting for automatic retries:"]
        else:
            lines = ["Delivery gate failed:"]
        
        missing_files = gate.get("missing_files", [])
        if missing_files:
            lines.append(f"- Missing files: {', '.join(missing_files)}")
        
        missing_dirs = gate.get("missing_dirs", [])
        if missing_dirs:
            lines.append(f"- Missing directories: {', '.join(missing_dirs)}")
        
        invalid_json = gate.get("invalid_json", [])
        if invalid_json:
            lines.append(f"- Invalid JSON specs: {', '.join(invalid_json)}")
        
        failed_checks = gate.get("failed_checks", [])
        if failed_checks:
            lines.append(f"- Failed checks: {', '.join(failed_checks)}")

        contract_alignment = gate.get("contract_alignment", {})
        if contract_alignment:
            lines.append(
                "- Contract alignment: "
                f"expected_tables={contract_alignment.get('expected_tables', 0)}, "
                f"sql_tables={contract_alignment.get('sql_tables', 0)}, "
                f"declared_endpoints={contract_alignment.get('declared_endpoints', 0)}, "
                f"implemented_endpoints={contract_alignment.get('implemented_endpoints', 0)}"
            )
            for item in contract_alignment.get("errors", [])[:5]:
                lines.append(f"  • ERROR: {item}")
            for item in contract_alignment.get("warnings", [])[:5]:
                lines.append(f"  • WARN: {item}")

        semantic_drift = gate.get("semantic_hub_drift", {})
        if semantic_drift:
            lines.append(
                "- Semantic hub drift: "
                f"spec_endpoints={semantic_drift.get('spec_endpoints', 0)}, "
                f"hub_endpoints={semantic_drift.get('hub_endpoints', 0)}, "
                f"spec_tables={semantic_drift.get('spec_tables', 0)}, "
                f"hub_tables={semantic_drift.get('hub_tables', 0)}, "
                f"spec_pages={semantic_drift.get('spec_pages', 0)}, "
                f"hub_pages={semantic_drift.get('hub_pages', 0)}"
            )
            for item in semantic_drift.get("errors", [])[:5]:
                lines.append(f"  • ERROR: {item}")
            for item in semantic_drift.get("warnings", [])[:5]:
                lines.append(f"  • WARN: {item}")

        projection_errors = gate.get("projection_errors", {})
        if projection_errors:
            lines.append(f"- Projection errors: {len(projection_errors)}")
            for path, item in list(projection_errors.items())[:5]:
                lines.append(f"  • {path}: {item.get('error') if isinstance(item, dict) else item}")

        build_evidence = gate.get("build_evidence", {})
        if build_evidence:
            lines.append(
                "- Build evidence: "
                f"frontend_package={build_evidence.get('frontend_package', False)}, "
                f"frontend_build_recorded={build_evidence.get('frontend_build_recorded', False)}"
            )
        
        counts = gate.get("hub_counts", {})
        lines.append(
            "- hub counts: "
            f"endpoints={counts.get('endpoints', 0)} "
            f"(implemented={counts.get('implemented_endpoints', 0)}), "
            f"tables={counts.get('tables', 0)} "
            f"(implemented={counts.get('implemented_tables', 0)}), "
            f"pages={counts.get('pages', 0)}"
        )
        
        verification = gate.get("verification", {})
        checklist = verification.get("checklist", {}) if isinstance(verification, dict) else {}
        if checklist:
            status_pairs = []
            for key, item in checklist.items():
                status = item.get("status", "pending") if isinstance(item, dict) else "pending"
                status_pairs.append(f"{key}={status}")
            lines.append(f"- Verification checklist: {', '.join(status_pairs)}")

        runtime_validation = gate.get("validation_runtime", {})
        if runtime_validation:
            lines.append(
                "- Runtime validation: "
                f"task_suite={runtime_validation.get('task_suite_exists', False)}, "
                f"total_results={runtime_validation.get('total_results', 0)}, "
                f"api_smoke_pass={runtime_validation.get('api_smoke_pass', False)}, "
                f"ui_smoke_pass={runtime_validation.get('ui_smoke_pass', False)}, "
                f"retries_used_total={runtime_validation.get('retries_used_total', 0)}, "
                f"retry_pending={runtime_validation.get('retry_pending_count', 0)}, "
                f"retry_exhausted={runtime_validation.get('retry_exhausted_count', 0)}"
            )
            failed_top = runtime_validation.get("failed_top", [])
            if failed_top:
                lines.append("- Failed validation tasks (top):")
                for item in failed_top:
                    lines.append(
                        "  • "
                        f"{item.get('task_id')} [{item.get('status')}] "
                        f"(domain_hint={item.get('domain_hint')}, mode={item.get('execution_mode')}) "
                        f"- {item.get('summary') or 'no summary'}"
                    )
        
        suggestions = self._delivery_gate_suggestions(gate)
        if suggestions:
            lines.append("- Suggested fixes:")
            for s in suggestions:
                lines.append(f"  • {s}")
        
        return "\n".join(lines)

    def _delivery_gate_suggestions(self, gate: Dict[str, Any]) -> List[str]:
        """Map gate failures to concrete remediation suggestions."""
        suggestions: List[str] = []

        missing_files = set(gate.get("missing_files", []))
        missing_dirs = set(gate.get("missing_dirs", []))
        invalid_json = set(gate.get("invalid_json", []))
        failed_checks = set(gate.get("failed_checks", []))

        if "docker/docker-compose.yml" in missing_files:
            suggestions.append("Regenerate `docker/docker-compose.yml` and verify service ports/paths.")
        if "design/README.md" in missing_files:
            suggestions.append("Recreate `design/README.md` (kickoff-coordinator-authored).")

        if "app/backend" in missing_dirs or "backend_code_missing" in failed_checks:
            suggestions.append("Generate backend implementation files under `app/backend` before delivery.")
        if "app/frontend" in missing_dirs or "frontend_code_missing" in failed_checks:
            suggestions.append("Generate frontend implementation files under `app/frontend` before delivery.")
        if "app/database" in missing_dirs or "database_sql_missing" in failed_checks:
            suggestions.append("Create database SQL artifacts under `app/database` (e.g., schema/seed SQL).")

        if "no_endpoints_in_hub" in failed_checks:
            suggestions.append("Register API endpoints in hub using `update_endpoint(...)`.")
        if "no_tables_in_hub" in failed_checks:
            suggestions.append("Register DB tables in hub using `update_table(...)`.")
        if "no_pages_in_hub" in failed_checks:
            suggestions.append("Register UI pages via `workhub.update_ui_page(...)`.")
        if "no_implemented_endpoints" in failed_checks:
            suggestions.append("Mark at least one endpoint as implemented via `update_endpoint(key=..., status='implemented')`.")
        if "no_implemented_tables" in failed_checks:
            suggestions.append("Mark at least one table as implemented via `update_table(name=..., status='implemented')`.")
        if "verification_checklist_not_ready" in failed_checks:
            suggestions.append("Run and record verification/build checks until checklist is ready for delivery.")
        if "validation_retry_pending" in failed_checks:
            suggestions.append(
                "Automatic smoke retry is still pending. Wait for retry completion and rerun delivery gate."
            )
        if "validation_api_smoke_missing" in failed_checks:
            suggestions.append(
                "Record at least one passed API smoke check via `record_validation_result(..., metadata={'check': 'api_smoke'})`."
            )
        if "validation_ui_smoke_missing" in failed_checks:
            suggestions.append(
                "Record at least one passed UI smoke check via `record_validation_result(..., metadata={'check': 'ui_smoke'})`."
            )
        if "contract_alignment_failed" in failed_checks:
            suggestions.append(
                "Resolve hub/code drift: align RegistryHub-registered endpoints + SchemaHub-registered tables with SQL schema and backend route definitions before delivery."
            )
        if "semantic_projection_errors" in failed_checks:
            suggestions.append(
                "Fix semantic projection errors recorded in hub, usually invalid or unsupported design/task spec structure."
            )
        if "frontend_build_not_recorded" in failed_checks:
            suggestions.append(
                "Run frontend build (`npm install && npm run build` in `app/frontend`) and record a passed `frontend_build` validation result."
            )
        if "deliverability_ui_flow_missing" in failed_checks:
            suggestions.append(
                "Each critical UI flow in WorkHub (explicit `critical_flows[]` "
                "or `pages` with `critical: true`) needs a passing `validation:ui_flow` "
                "record. Spawn a UI-flow tester worker (config_profile='verifier'); have "
                "it drive `browser_navigate` + at least one mutating step "
                "(`browser_click`/`browser_fill`) + `browser_screenshot`, then call "
                "`record_validation_result(task_id='ui_flow_<name>', status='passed', "
                "metadata={'check': 'ui_flow', 'flow': '<name>'})`."
            )
        if "deliverability_ui_flow_failed" in failed_checks:
            suggestions.append(
                "One or more critical UI flow tests failed. Inspect the failure evidence "
                "(`browser_console`, `browser_network_errors`, screenshot), file a bug "
                "via `bug_create(...)`, route to the owning agent, and re-run the flow "
                "test once fixed."
            )
        if "deliverability_critical_flows_invalid" in failed_checks:
            suggestions.append(
                "WorkHub `critical_flows[]` is present but every entry is "
                "unparseable (each entry must be either a `{\"name\": \"<slug>\", ...}` "
                "dict or a bare slug string). Fix the entries via frontend's "
                "kickoff section re-emit."
            )

        # Deduplicate while preserving order
        deduped: List[str] = []
        seen = set()
        for s in suggestions:
            if s not in seen:
                deduped.append(s)
                seen.add(s)
        return deduped
    
    
    def get_status(self) -> Dict:
        """Get current status."""
        return {
            "name": self.context.name,
            "ports": {"api": self.context.api_port, "ui": self.context.ui_port, "db": self.context.db_port},
            "issues_found": self._issues_found,
            "issues_fixed": self._issues_fixed,
        }
