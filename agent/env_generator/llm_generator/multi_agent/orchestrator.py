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


# NOTE: the base backend entrypoint + reset.sh templates (_BASE_MAIN_PY /
# _BASE_RESET_SH) moved to runtime/scaffolder.py with Scaffolder.seed_base_scaffold
# (PROPOSAL #8 — Scaffolder extraction).


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
FWVAL_STUCK_ABORT_AFTER = 7        # …then FAIL FAST: redispatch+terminal didn't help on an
#   unchanged failure set with no lane progress → abort early with the root surfaced, instead
#   of limping to the wall-clock cap (PROPOSAL #5). ~1 slow-retry interval past the cap (~11 min)
#   vs the 2h budget. Paced by the post-cap slow interval, not the 60s tick — tune against
#   FWVAL_SLOW_INTERVAL_S, not the tick.
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
                          terminal_after: int = FWVAL_STUCK_TERMINAL_AFTER,
                          abort_after: int = FWVAL_STUCK_ABORT_AFTER) -> str:
    """Escalation stage for a failure set that has persisted (with NO lane
    progress) across ``stuck_count`` post-cap validations. Returns:
      * ``"wait"``      — still inside the fast budget / early; keep iterating.
      * ``"redispatch"``— re-wake the lane that owns the failing dimension.
      * ``"terminal"``  — re-dispatch did not help; surface a clear "stuck" signal
                          (so the run stops churning to wall-clock and the UI shows
                          the real blocker) instead of spinning the same cycle.
      * ``"abort"``     — terminal-surface ALSO did not help; FAIL FAST — abort the
                          run with the root surfaced, instead of limping to the
                          wall-clock cap (PROPOSAL #5: the unrecoverable
                          framework-generation-bug case the in-run agents can't fix).
    Pure + side-effect-free so the escalation ladder is unit-tested without the
    docker/dispatch machinery."""
    if stuck_count >= abort_after:
        return "abort"
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

        # PROPOSAL #8 Tier-1b: run_budget.json ownership lives in RunBudget; the
        # _run_budget_path/_load_run_budget_caps/_write_run_budget methods below are
        # thin shims delegating here (callers in run() stay unchanged).
        from .runtime.run_budget import RunBudget
        self._budget = RunBudget(self.output_dir, self._logger)

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
                    self._vf_gate.reset_for_milestone()
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
                    # Coordination-tick dispatch (Defect B + PROPOSAL #17 fix). The
                    # resident orchestrator lane is a SERIAL queue-consumer: a tick
                    # dispatched while a prior one is still in flight cannot be
                    # consumed, so the lane's message queue floods and the dispatch
                    # send_task BLOCKS — the observed repeated 900s hangs (youtube run
                    # 2026-06-18). Defect B's wall-clock "re-dispatch a fresh tick when
                    # the done-event is stuck" was the very thing piling ticks onto the
                    # wedged lane. PROPOSAL #17: dispatch ONLY when the lane is FREE
                    # (done-event set → one tick in flight) and bound the dispatch await
                    # to a tunable timeout (was a hard-coded 900s, 3x this stuck cadence).
                    # While a tick is in flight or wedged, the deterministic drivers above
                    # (_maybe_run_framework_validation / _maybe_framework_deliver, every
                    # ~60s) carry the run — they, not a re-dispatched LLM tick, are the
                    # reliable recovery from a stuck orchestrator lane.
                    last_coordination_tick_at = 0.0
                    coordination_tick_stuck_sec = float(
                        os.environ.get("ENVGEN_COORD_TICK_STUCK_SEC", "300")
                    )
                    coordination_tick_dispatch_timeout_s = float(
                        os.environ.get("ENVGEN_COORD_TICK_DISPATCH_TIMEOUT_S", "180")
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
                    # PROPOSAL #5: a STUCK abort is kept SEPARATE from budget_exceeded so its
                    # raise surfaces the real root (framework-gen bug) instead of the
                    # budget-flavored "Adjust ENVGEN_MAX_*" message (which is the opposite of
                    # the action needed). Set from self._fwval_abort_reason after validation.
                    stuck_abort_reason: Optional[str] = None
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
                        # PROPOSAL #5 — FAIL FAST on an unrecoverable stuck: the validation
                        # above sets _fwval_abort_reason once its stuck ladder reaches `abort`
                        # (same failure set, no lane progress, redispatch+terminal didn't help).
                        # Break out HERE with a SEPARATE reason (not budget_exceeded) so the
                        # post-loop raise surfaces the real root instead of "raise the budget".
                        _abort = getattr(self, "_fwval_abort_reason", None)
                        if _abort and not getattr(self, "_project_delivered", False):
                            stuck_abort_reason = _abort
                            self._logger.error(
                                "FAIL-FAST: aborting the run early — %s", _abort)
                            self._write_run_budget(
                                caps, loop_start, time.time() - loop_start, tick_count,
                                "stuck_abort")
                            break
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
                        # PROPOSAL #17 busy-guard: dispatch a coordination tick ONLY
                        # when the lane is FREE (its prior tick completed → done-event
                        # set). Never pile a tick onto a busy/wedged serial-consumer
                        # lane — that floods its queue and blocks send_task (the 900s
                        # hang). While a tick is in flight the deterministic drivers
                        # above carry the run.
                        _lane_free = orchestrator_task_done_event.is_set()
                        if _lane_free and self._coordination_tick_due(
                            event_set=_lane_free,
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
                                }), timeout=coordination_tick_dispatch_timeout_s)
                            except asyncio.TimeoutError:
                                self._logger.error(
                                    "coordination-tick dispatch timed out (%.0fs) — "
                                    "lane busy/wedged; looping to re-check delivered/budget "
                                    "(deterministic drivers continue).",
                                    coordination_tick_dispatch_timeout_s)
                                continue
                    if orchestrator_lane._project_delivered_event.is_set():
                        self._write_run_budget(caps, loop_start, time.time() - loop_start, tick_count, "delivered")
                    # PROPOSAL #5 — a STUCK abort raises its OWN root-surfacing message
                    # (NOT the budget message, which would misleadingly tell the dev to raise
                    # ENVGEN_MAX_* — the opposite of fixing the regenerated-every-cycle root).
                    if stuck_abort_reason and not orchestrator_lane._project_delivered_event.is_set():
                        raise RuntimeError(
                            f"STUCK — generation aborted without delivery after {tick_count} "
                            f"coordination ticks: {stuck_abort_reason} This is very likely an "
                            f"UNRECOVERABLE framework-generation bug that the in-run agents "
                            f"cannot self-heal (the framework regenerates the same artifact "
                            f"every cycle), so raising ENVGEN_MAX_* will NOT help — fix the "
                            f"root shown above, then re-run."
                        )
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
                # …and missing UI pages (frontend analog, PROPOSAL #19 — now wired;
                # this was a dead comment): a declared ui_page the lane omitted from
                # its App.jsx gets a stub component + its route additively injected,
                # so the booted/shipped app is navigable to every declared page. Runs
                # HERE (final merge) + committed below, so the release snapshot carries
                # it (the per-tick heal write is stashed/dropped by this merge).
                self._scaffold_frontend_pages()
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

    # ── Kickoff driver (PROPOSAL #8/#16 — KickoffDriver) ──
    # The facilitator-led kickoff meeting loop + finalize/author/dispatch moved to
    # runtime/kickoff_driver.py. STATELESS (no orch state; calls only its own siblings),
    # so each shim constructs a fresh KickoffDriver(self) per call — call sites + tests
    # unchanged. (The interleaved _coordination_tick_due / _should_attempt_silent_lane_nudge
    # / _nudge_silent_resident_lanes stay here — they are NOT kickoff methods.)
    def _finalize_kickoff_and_author(self, *args, **kwargs):
        from .runtime.kickoff_driver import KickoffDriver
        return KickoffDriver(self)._finalize_kickoff_and_author(*args, **kwargs)

    async def _drive_kickoff_to_completion(self, *args, **kwargs):
        from .runtime.kickoff_driver import KickoffDriver
        return await KickoffDriver(self)._drive_kickoff_to_completion(*args, **kwargs)

    def _attempt_reconciled_finalize(self, *args, **kwargs):
        from .runtime.kickoff_driver import KickoffDriver
        return KickoffDriver(self)._attempt_reconciled_finalize(*args, **kwargs)

    def _kickoff_fallback_or_reconcile(self, *args, **kwargs):
        from .runtime.kickoff_driver import KickoffDriver
        return KickoffDriver(self)._kickoff_fallback_or_reconcile(*args, **kwargs)

    @staticmethod
    def _coordination_tick_due(*, event_set, now, last_tick_at, loop_start, stuck_sec):
        from .runtime.coordination import coordination_tick_due
        return coordination_tick_due(
            event_set=event_set, now=now, last_tick_at=last_tick_at,
            loop_start=loop_start, stuck_sec=stuck_sec)

    @staticmethod
    def _should_attempt_silent_lane_nudge(now, kickoff_finalized_at, last_nudge_attempt_at, grace_sec, interval_sec):
        from .runtime.coordination import should_attempt_silent_lane_nudge
        return should_attempt_silent_lane_nudge(
            now, kickoff_finalized_at, last_nudge_attempt_at, grace_sec, interval_sec)

    async def _dispatch_implementation_phase(self, *args, **kwargs):
        from .runtime.kickoff_driver import KickoffDriver
        return await KickoffDriver(self)._dispatch_implementation_phase(*args, **kwargs)

    # ── Coordination (PROPOSAL #8 — Coordination, final slice) ──
    # Resident-lane cadence predicates + stall-nudge moved to runtime/coordination.py
    # (the 2 pures are module fns; the stateful nudge is Coordination(orch).
    # _silent_lane_nudges stays here on the orch, init/reset by run()). The run()
    # coordination-tick BLOCK stays in the spine.
    async def _nudge_silent_resident_lanes(self, *args, **kwargs):
        from .runtime.coordination import Coordination
        return await Coordination(self).nudge_silent_resident_lanes(*args, **kwargs)

    def _author_kickoff_docs(self, *args, **kwargs):
        from .runtime.kickoff_driver import KickoffDriver
        return KickoffDriver(self)._author_kickoff_docs(*args, **kwargs)

    @property
    def _scaffolder(self):
        """Lazily-created project Scaffolder (PROPOSAL #8 — Scaffolder). Owns the
        deterministic scaffolding over runtime/*; created on first access (cached
        in __dict__) so partially-constructed orchestrators stay cheap."""
        s = self.__dict__.get("_scaffolder_instance")
        if s is None:
            from .runtime.scaffolder import Scaffolder
            s = Scaffolder(self)
            self.__dict__["_scaffolder_instance"] = s
        return s

    async def _generate_docker(self):
        await self._scaffolder.generate_docker()

    async def _generate_database(self):
        await self._scaffolder.generate_database()

    def _generate_backend_skeleton(self) -> None:
        self._scaffolder.generate_backend_skeleton()

    async def _seed_base_scaffold(self):
        await self._scaffolder.seed_base_scaffold()

    def _register_contract_surface(self):
        self._scaffolder.register_contract_surface()

    async def _generate_mcp(self):
        await self._scaffolder.generate_mcp()

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
        from .runtime.framework_validation import FrameworkValidation
        await FrameworkValidation(self).maybe_run()

    def _fwval_rearm_owner_dispatch(self) -> None:
        from .runtime.framework_validation import FrameworkValidation
        FrameworkValidation(self).rearm_owner_dispatch()

    # ── Remediation dispatch (PROPOSAL #8 — RemediationDispatcher) ──────────────
    # The 5 failed-gate→owner-lane dispatch helpers moved to
    # runtime/remediation_dispatcher.py. They are STATELESS (the per-milestone
    # ``_*_dispatched`` guards live here on the orchestrator, reset by
    # _fwval_rearm_owner_dispatch), so the shims construct a fresh dispatcher
    # bound to ``self`` per call — call sites + tests are unchanged.
    async def _dispatch_unimplemented_routes(self, data) -> None:
        from .runtime.remediation_dispatcher import RemediationDispatcher
        await RemediationDispatcher(self).dispatch_unimplemented_routes(data)

    async def _dispatch_frontend_navigable(self, data) -> None:
        from .runtime.remediation_dispatcher import RemediationDispatcher
        await RemediationDispatcher(self).dispatch_frontend_navigable(data)

    async def _dispatch_failing_checks(self, data) -> None:
        # PROPOSAL #21: re-dispatch the UNCOVERED lane-actionable failing checks
        # (dead_controls/reachable→frontend, endpoints_reachable/correct_shape/
        # auth_enforced_401/writes_persist→backend) — guard dict _check_owner_dispatched
        # reset by _fwval_rearm_owner_dispatch.
        from .runtime.remediation_dispatcher import RemediationDispatcher
        await RemediationDispatcher(self).dispatch_failing_checks(data)

    async def _dispatch_unwired_ui_pages(self, blockers) -> None:
        from .runtime.remediation_dispatcher import RemediationDispatcher
        await RemediationDispatcher(self).dispatch_unwired_ui_pages(blockers)

    def _detect_misplaced_frontend_root(self) -> Optional[Dict[str, Any]]:
        from .runtime.remediation_dispatcher import RemediationDispatcher
        return RemediationDispatcher(self).detect_misplaced_frontend_root()

    async def _dispatch_misplaced_frontend_root(self, info) -> None:
        from .runtime.remediation_dispatcher import RemediationDispatcher
        await RemediationDispatcher(self).dispatch_misplaced_frontend_root(info)

    async def _compile_reference_materials(self, raw_req: str) -> str:
        """Compile reference materials into a spec + deliverability gates and
        return the spec-extended requirements (delegates to
        ``runtime.reference_materials.compile_reference_materials``). Records the
        reference image/doc/spec state only for what this run actually produced,
        so a best-effort failure leaves prior state untouched."""
        from .runtime.reference_materials import compile_reference_materials
        res = await compile_reference_materials(
            raw_req,
            output_dir=self.output_dir,
            llm=self.llm,
            logger=self._logger,
            reference_images=getattr(self, "_reference_images", None),
        )
        if res.classified:
            self._reference_images = res.images
            self._reference_docs = res.docs
        if res.spec is not None:
            self._reference_spec = res.spec
            self._reference_spec_summary = res.spec_summary
        return res.requirements

    @property
    def _vf_gate(self):
        """Lazily-created visual-fidelity gate (PROPOSAL #8 — VisualFidelity
        slice B). Owns the per-source judging budget + the per-milestone
        deferral counters that used to live as inline ``_vf_*`` attrs; created
        on first access so partially-constructed orchestrators stay cheap."""
        g = self.__dict__.get("_vf_gate_instance")
        if g is None:
            from .runtime.visual_fidelity import VisualFidelityGate
            g = VisualFidelityGate(self)
            self.__dict__["_vf_gate_instance"] = g
        return g

    async def _maybe_run_visual_fidelity(self) -> None:
        """Run the bounded visual-fidelity judge-and-remediate loop (delegates to
        the extracted VisualFidelityGate)."""
        await self._vf_gate.maybe_run()

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
        self._scaffolder.scaffold_design_readme()

    # ── Delivery-time heal pipeline (PROPOSAL #8 — HealPipeline) ────────────────
    # The 12 repair/merge/commit steps moved to runtime/heal_pipeline.py. They are
    # STATELESS, idempotent wrappers; the load-bearing CALL ORDER lives in the
    # callers below (merge → skeleton → projection → audit, …), unchanged. Each
    # shim constructs a fresh HealPipeline(self) per call.
    def _repair_backend_auth(self) -> None:
        from .runtime.heal_pipeline import HealPipeline
        HealPipeline(self).repair_backend_auth()

    def _repair_backend_packaging(self) -> None:
        from .runtime.heal_pipeline import HealPipeline
        HealPipeline(self).repair_backend_packaging()

    def _repair_ddl_from_orm(self) -> None:
        from .runtime.heal_pipeline import HealPipeline
        HealPipeline(self).repair_ddl_from_orm()

    def _project_missing_routes(self) -> None:
        from .runtime.heal_pipeline import HealPipeline
        HealPipeline(self).project_missing_routes()

    def _repair_handler_fk_aliases(self) -> None:
        from .runtime.heal_pipeline import HealPipeline
        HealPipeline(self).repair_handler_fk_aliases()

    def _repair_psycopg_dsn(self) -> None:
        from .runtime.heal_pipeline import HealPipeline
        HealPipeline(self).repair_psycopg_dsn()

    # _project_missing_pages REMOVED (user decision 2026-06-11): the framework
    # no longer authors UI content — gates + lane feedback replace projection.

    def _run_test_user_validation(self, version: str) -> None:
        from .runtime.heal_pipeline import HealPipeline
        HealPipeline(self).run_test_user_validation(version)

    def _scaffold_frontend_baseline(self) -> None:
        self._scaffolder.scaffold_frontend_baseline()

    def _scaffold_frontend_pages(self) -> None:
        self._scaffolder.scaffold_frontend_pages()

    def _repair_frontend_api(self) -> None:
        from .runtime.heal_pipeline import HealPipeline
        HealPipeline(self).repair_frontend_api()

    def _repair_backend_as_wiring(self) -> None:
        from .runtime.heal_pipeline import HealPipeline
        HealPipeline(self).repair_backend_as_wiring()

    def _repair_backend_entrypoint(self) -> None:
        from .runtime.heal_pipeline import HealPipeline
        HealPipeline(self).repair_backend_entrypoint()

    def _merge_committed_agent_work(self) -> None:
        from .runtime.heal_pipeline import HealPipeline
        HealPipeline(self).merge_committed_agent_work()

    def _commit_framework_delivery(self) -> None:
        from .runtime.heal_pipeline import HealPipeline
        HealPipeline(self).commit_framework_delivery()

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
                    and not self._vf_gate.passed):
                if self._vf_gate.deferred_since is None:
                    self._vf_gate.deferred_since = time.time()  # anchor: milestone's FIRST defer
                _now = time.time()
                _vf_decision = _visual_release_decision(
                    self._vf_gate.deferred_since,
                    self._vf_gate.attempts,
                    self._vf_gate.total_judgments,
                    _now,
                )
                if _vf_decision == "defer":
                    self._logger.warning(
                        "DELIVERY DEFERRED: visual fidelity not passed (attempt "
                        "%s/3 on current source, %ss deferred, %s judged) — re-"
                        "judging now; waiting for the frontend to digest the "
                        "remediation task before cutting this milestone's release.",
                        self._vf_gate.attempts,
                        int(_now - self._vf_gate.deferred_since),
                        self._vf_gate.total_judgments)
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
                    int(_now - self._vf_gate.deferred_since),
                    self._vf_gate.attempts,
                    self._vf_gate.total_judgments)
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
            # Frontend analog (PROPOSAL #19 — RE-INSTATED; "removed 2026-06-11" was
            # the regression: a lane that drops the @framework-managed-routes marker
            # can omit a declared route entirely, and frontend_navigable/visual do NOT
            # catch a single genuinely-missing declared page → permanent ui_page-unwired
            # block, no delivery). ADDITIVELY inject any declared route the lane omitted
            # (+ a stub component if missing) on the merged tree, right before the
            # snapshot, so the release ships navigable-to-every-declared-page. Never
            # clobbers lane routes/bodies; idempotent.
            self._scaffold_frontend_pages()
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
        from .runtime.delivery_gate import incomplete_required_tasks
        return incomplete_required_tasks(self.hubs)
    def _noncanonical_business_response_keys(self) -> List[Dict[str, Any]]:
        from .runtime.delivery_gate import noncanonical_business_response_keys
        return noncanonical_business_response_keys(self.hubs)
    def _validate_delivery_gate(self) -> Dict[str, Any]:
        from .runtime.delivery_gate import validate_delivery_gate
        import logging as _lg
        return validate_delivery_gate(
            self.output_dir, self.hubs,
            getattr(self, "_session_start_ts", 0.0),
            getattr(self, "_logger", None) or _lg.getLogger("DeliveryGate"),
            scaffold_design_readme=self._scaffold_design_readme,
            get_validation_results=self._get_validation_results,
            get_validation_summary=self._get_validation_summary)
    def _validate_contract_alignment(self) -> Dict[str, Any]:
        from .runtime.delivery_gate import validate_contract_alignment
        return validate_contract_alignment(self.output_dir, self.hubs)
    def _validate_build_evidence(self) -> Dict[str, Any]:
        from .runtime.delivery_gate import validate_build_evidence
        return validate_build_evidence(self.output_dir, self._get_validation_results)
    def _read_json_file(self, path: Path) -> Dict[str, Any]:
        try:
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}
        return {}

    def _extract_spec_tables(self, spec: Dict[str, Any]) -> Dict[str, set]:
        from .runtime.delivery_gate import extract_spec_tables
        return extract_spec_tables(spec)
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
    # PROPOSAL #8 Tier-1b: extracted to runtime/run_budget.py (RunBudget). These
    # thin shims preserve the in-file call surface (run() calls them ~6×) byte-for-byte.
    def _run_budget_path(self) -> Path:
        return self._budget.path()

    def _load_run_budget_caps(self, env_defaults: Dict[str, Any]) -> Dict[str, Any]:
        return self._budget.load_caps(env_defaults)

    def _write_run_budget(self, caps: Dict[str, Any], started_at: float,
                          elapsed: float, ticks: int, status: str) -> None:
        self._budget.write(caps, started_at, elapsed, ticks, status)

    def _format_delivery_gate_report(self, gate: Dict[str, Any]) -> str:
        # PROPOSAL #8 Tier-1a: pure report formatters extracted to runtime/delivery_gate.py.
        from .runtime.delivery_gate import format_delivery_gate_report
        return format_delivery_gate_report(gate)

    def _delivery_gate_suggestions(self, gate: Dict[str, Any]) -> List[str]:
        from .runtime.delivery_gate import delivery_gate_suggestions
        return delivery_gate_suggestions(gate)


    def get_status(self) -> Dict:
        """Get current status."""
        return {
            "name": self.context.name,
            "ports": {"api": self.context.api_port, "ui": self.context.ui_port, "db": self.context.db_port},
            "issues_found": self._issues_found,
            "issues_fixed": self._issues_fixed,
        }
