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
from utils.llm import terminal_llm_error as _terminal_llm_error  # #326

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
    """Find an available port that hasn't been allocated yet.

    Bind-tests on 0.0.0.0 (NOT localhost): docker publishes host ports on 0.0.0.0, so a
    port free on 127.0.0.1 but already bound on 0.0.0.0 by another service would pass a
    localhost check yet make `docker compose up` fail to bind it (the docker_up wedge seen
    on busy shared hosts). Binding 0.0.0.0 here only hands out ports docker can actually use.
    """
    global _allocated_ports
    preferred = preferred or []
    
    for port in preferred:
        if port in _allocated_ports:
            continue
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('0.0.0.0', port))
                _allocated_ports.add(port)
                return port
        except OSError:
            pass
    
    for port in range(range_start, range_end):
        if port in _allocated_ports:
            continue
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('0.0.0.0', port))
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
FWVAL_NO_DELIVER_ABORT_S = int(os.environ.get("ENVGEN_NO_DELIVER_ABORT_S", "4500"))  # 75min
#   convergence backstop: the exact-stuck FWVAL ladder resets on ANY churn (file/chain
#   changes), so a run that stays active but OSCILLATES among delivery-gate checks without
#   ever clearing them (run v18: ~76min cycling business_chain_failing ↔ api_coverage ↔
#   verification_checklist) never fail-fasts and livelocks toward the 6h wall. If delivery
#   has not succeeded within this window AFTER the contract is built (first gate decline),
#   abort — generous (3-5× the observed clear time), well under the 6h wallclock backstop.
# CHAIN-AUTHORING PROGRESS (#71, outlook run-60): the exact-stuck ladder keys on the
# CHECK-level failure set ({"business_chain"}), which stays constant while the VERIFIER
# is actively RE-AUTHORING a broken verification chain toward correct — the verifier IS
# making progress the check set can't see, yet the 7-cycle abort fires mid-convergence
# (run-60: the chain went green ONE cycle after the abort). When business_chain is the
# only blocker AND the chains' authored content signature CHANGED since the last
# validation (a re-authoring), reset the stuck counter — but count the churn, BOUNDED by
# this cap so a verifier that oscillates FOREVER (never converging) still aborts (no
# livelock). Env-gated. ~this-many re-authorings of room before giving up on the verifier.
FWVAL_CHAIN_CHURN_CAP = max(2, int(os.environ.get("ENVGEN_CHAIN_CHURN_CAP") or "8"))
# FIX #186 (tiktok-r2): the api_smoke stuck ladder keyed only on (failure_set,
# chain_sig) — blind to APP-SOURCE edits, so it STUCK-ABORTed ~20s before the
# backend lane landed its /auth/login fix. (The delivery-gate ladder already
# counts source edits via _deliver_progress_sig; this closes the same gap here.)
# A changed app-source signature grants a BOUNDED stuck-counter reset — capped by
# this budget so an r3-style forever-thrash (edits every cycle, failure set never
# clears) still aborts. ~this-many edit-graces of room before giving up.
FWVAL_SOURCE_CHURN_CAP = max(2, int(os.environ.get("ENVGEN_SOURCE_CHURN_CAP") or "8"))
FWVAL_STUCK_ABORT_AFTER = max(3, int(os.environ.get("ENVGEN_DELIVERY_STUCK_ABORT_AFTER") or "7"))  # env-gated (default 7); …then FAIL FAST: redispatch+terminal didn't help on an
#   unchanged failure set with no lane progress → abort early with the root surfaced, instead
#   of limping to the wall-clock cap (PROPOSAL #5). ~1 slow-retry interval past the cap (~11 min)
#   vs the 2h budget. Paced by the post-cap slow interval, not the 60s tick — tune against
#   FWVAL_SLOW_INTERVAL_S, not the tick.
# ABORT-GRACE (smoke-notes exp11): the delivery stuck-abort latches at the deliver-check
# but is CONSUMED at the run-loop top of the NEXT iteration — so an in-flight remediation
# that lands BETWEEN (e.g. the verifier registers a chain that just needs one run_validation)
# is killed before it can run. Defer a latched deliver-stuck abort for up to this many cycles
# WHEN forward progress (source/contract/chain change) occurred since the latch. Capped so a
# genuinely wedged run still fails fast; FWVAL_NO_DELIVER_ABORT_S bounds the total regardless.
FWVAL_ABORT_GRACE_MAX = max(0, int(os.environ.get("ENVGEN_DELIVERY_ABORT_GRACE_MAX") or "3"))
# FIX #112 (runs 24+26 autopsy): remediation rounds take 3-10 min and scores DO rise
# +0.1-0.4/round, but the old 900s window fit only 1-3 rounds — the gate released
# below threshold mid-convergence (run-29 M4: dm_inbox 0.00→0.40→0.60 still climbing
# at the escape). #110 gives the lane eyes; this gives it time. #112b: user directive
# 2026-07-08 ("900s还是太短...可以长一点") → a full hour (~6-15 rounds); the judgment
# cap scales with it so it can't become the new binding constraint. Env-tunable; the
# per-source attempt cap (3) still releases early when the lane stops iterating.
VISUAL_DEFERRAL_ESCAPE_S = float(os.environ.get(
    "ENVGEN_VISUAL_ESCAPE_S") or "3600")   # max wall-clock a milestone may defer on visuals
VISUAL_TOTAL_JUDGMENTS_CAP = int(os.environ.get(
    "ENVGEN_VISUAL_JUDGMENTS_CAP") or "20")  # per-milestone hard cap on real visual judgments
# FIX #138 (log-mining runs 50-62): the final visual window averaged 65m31s = ~40% of a
# run's TOTAL wall-clock, and in 7/7 delivered runs it ended via the 3600s escape — never
# a pass. When the judged scores show NO improvement for several consecutive real
# judgments (no blocking screen beats its best-so-far), the remaining wait buys nothing:
# escape early. Conservative: any real per-screen improvement re-arms the counter.
VISUAL_PLATEAU_ROUNDS = int(os.environ.get(
    "ENVGEN_VISUAL_PLATEAU_ROUNDS") or "4")   # consecutive no-improvement judgments
VISUAL_PLATEAU_MIN_S = float(os.environ.get(
    "ENVGEN_VISUAL_PLATEAU_MIN_S") or "1500")  # never plateau-escape before this deferral floor
VISUAL_IDLE_S = float(os.environ.get(
    "ENVGEN_VISUAL_IDLE_S") or "600")  # FIX #145: idle-source escape (0 disables)
# FIX #519 (netflix r91): a frontend lane that edits the source on every visual-fail keeps
# resetting the ONLY fast escape — the per-source attempt cap (reset to 0 on each source-
# signature change) — so under sustained churn the attempts>=3 escape never fires and the
# soft plateau/idle escapes are floored at 1500s; delivery deferred 1418s+ and only the
# 3600s wall-clock (or the 20-judgment cap) would release. plateau_rounds, by contrast, is
# per-milestone and is NOT reset by source churn (it counts real judgments with no blocking
# screen beating its best-so-far, _best_by_screen accumulating across sources), so a HARD
# plateau count is conclusive churn-proof evidence the scores are final — escape with NO
# time floor. Set to 2x the soft plateau: needs 2x as many no-improvement judgments as the
# floored escape, so it never fires early on noise, but it CANNOT be outrun by fast churn.
VISUAL_PLATEAU_HARD_ROUNDS = int(os.environ.get(
    "ENVGEN_VISUAL_PLATEAU_HARD") or str(2 * VISUAL_PLATEAU_ROUNDS))  # churn-proof, no floor
# FIX #558 (netflix r95/r103/r107, 2026-08-07): AVG FAST-RELEASE. The visual gate's clean
# pass requires EVERY blocking screen ≥ the 0.65 bar (all-pass). But a run whose gating
# blocking_average (#542, BLOCKING screens only) is comfortably ≥ the bar (r107 = 0.7258)
# while a couple of screens lag (~0.50-0.60) is NOT a clean pass — so it DEFERS, and because
# the per-source attempt counter resets on frontend source-churn the fast escapes never fire;
# it grinds to the 3600s wall-clock escape (~40 wasted re-judgements, ~40-60 min), then
# RELEASES the SAME app anyway. The wall-clock escape already delivers the avg-≥-bar outcome —
# just ~60 min and ~40 re-judgements too late. This adds a FAST path to that EXACT release: a
# run whose blocking_average has cleared the bar for N consecutive judged rounds (STABLE — a
# single lucky pass never fires it; post-#548 captures are deterministic) and whose blocking
# exam is complete (the same ≥1-blocking-judged coverage precondition #353's pass requires)
# releases promptly. It is PURELY a faster route to the release the escape already grants — the
# 0.65 bar, the all-pass clean-pass fast-path, and every escape backstop (wall-clock / plateau /
# idle) are all untouched, and it reuses the #521 sticky-release latch so it never re-defers.
# Default-ON; disable with ENVGEN_VISUAL_AVG_RELEASE=0. N = ENVGEN_VISUAL_AVG_RELEASE_ROUNDS
# (default 2 — needs the avg stable over ≥2 real judgments, so noise/one lucky pass can't trip it).
VISUAL_AVG_RELEASE = os.environ.get(
    "ENVGEN_VISUAL_AVG_RELEASE", "1").lower() not in ("0", "false", "no", "off")
VISUAL_AVG_RELEASE_ROUNDS = max(1, int(
    os.environ.get("ENVGEN_VISUAL_AVG_RELEASE_ROUNDS") or "2"))


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


# Delivery-gate blockers that a RE-RUN of framework validation can clear (as opposed to
# a structural failure — docker/contract/build/ui_* — that a re-run cannot). These are
# the checks whose verdict is (re-)recorded by RunValidationTool against the LIVE app:
#   * business_chain_failing        — re-executing every verification chain re-records
#                                     fresh per-chain status (a TRANSIENT step failure —
#                                     e.g. a login 500 right after a compose restart —
#                                     clears; a genuine bug re-fails and still blocks).
#   * verification_checklist_not_ready — re-records FRESH build:* CodeHub checks (#502).
# Shared by _fwval_can_early_return (keep the coordination loop running) and
# _final_gate_revalidation_warranted (bounded final-gate re-run before rc=1).
REVALIDATION_FIXABLE_CHECKS = frozenset({
    "business_chain_failing", "verification_checklist_not_ready"})


def _fwval_can_early_return(has_passing_run: bool, failed_checks) -> bool:
    """May ``_maybe_run_framework_validation`` EARLY-RETURN (a gate-passing api_smoke run
    already exists, nothing left for it to do)?

    Yes ONLY when a passing api_smoke RunHub run exists AND the delivery gate is NOT still
    blocked on ``business_chain_failing``. The business_chain exception keeps the framework
    validation RE-RUNNING after api_smoke passes: the verifier registers verification chains
    but its OWN run_validation can fail for a reason the framework can fix by re-running from
    the integration tree — e.g. the verifier validated in a worktree that lacked the
    framework-delivered Dockerfile (outlook-seed1, 2026-06-29: app green via the framework's
    own api_smoke, yet business_chain_failing wedged the milestone because the idle verifier
    never retried). Re-running RunValidationTool validates the chains from the integration
    tree (which always has the Dockerfile), decoupling milestone advance from the flaky/idle
    verifier. Other post-api_smoke blockers (e.g. ``ui_page_unwired``) are NOT fixable by
    re-validation, so they do NOT keep the loop running here. Pure + unit-tested."""
    if not has_passing_run:
        return False
    # #502 (netflix r80, 2026-08-05): verification_checklist_not_ready, like
    # business_chain_failing, IS fixable by RE-RUNNING framework validation — the shared
    # RunValidationTool re-records FRESH build:* checks (a stale build:* failure on a
    # provably-built app supersedes to success; a genuine build failure re-records honestly,
    # so this never masks a real break). maybe_refresh_stale_build_checklist (#120/#492)
    # resets the api_smoke attempt counter for exactly this blocker, but this early-return
    # short-circuited maybe_run BEFORE the re-run could happen → the reset was wasted and the
    # stale build:* never refreshed. r80 reached the deliver tail with the ONLY blocker =
    # verification_checklist_not_ready (all 4 build:* stale-failure though api_smoke PASSED,
    # 15 endpoints, 0 docker_up errors); #492 fired 3× but this early-return blocked the
    # re-validation → final gate failed → main() returned 1, no release. Keep the loop
    # running for BOTH re-validation-fixable blockers so #492's reset is actually used.
    return not (REVALIDATION_FIXABLE_CHECKS & set(failed_checks or []))


def _abort_grace_should_defer(is_deliver_stuck: bool, grace_used: int,
                              sig_at_latch, sig_now,
                              grace_max: int = FWVAL_ABORT_GRACE_MAX) -> bool:
    """Should a LATCHED delivery stuck-abort be DEFERRED one coordination cycle?

    The delivery stuck-abort latches inside the deliver-check but is consumed at the
    run-loop top of the NEXT iteration — so an in-flight remediation that lands in the
    gap (most importantly: the verifier (re-)registers a verification chain that only
    needs one ``run_validation`` to go green) is killed before it can run. Defer iff:
      * the abort came from the DELIVERY stuck-ladder (NOT framework-validation / Site A —
        those are a separate, already-terminal path that must not be touched here),
      * forward PROGRESS happened since the abort latched (``sig_now != sig_at_latch`` —
        the signature is app-source + contract + verification-chain versions, so it moves
        only when a lane edited code or (re-)registered a contract/chain), and
      * the grace cap is not yet exhausted (a genuinely wedged run still fails fast; the
        NO_DELIVER time backstop bounds it regardless).
    Keyed on the STABLE progress signature, NEVER the counter-bearing reason string (which
    increments every cycle and would defer forever → livelock). Pure + side-effect-free."""
    if not is_deliver_stuck or grace_used >= grace_max:
        return False
    if sig_at_latch is None or sig_now is None:
        return False
    return sig_now != sig_at_latch


def _visual_release_decision(deferred_since, attempts: int, total_judgments: int,
                             now: float, *, attempt_cap: int = 3,
                             escape_s: float = VISUAL_DEFERRAL_ESCAPE_S,
                             total_cap: int = VISUAL_TOTAL_JUDGMENTS_CAP,
                             plateau_rounds: int = 0,
                             plateau_cap: int = VISUAL_PLATEAU_ROUNDS,
                             plateau_min_s: float = VISUAL_PLATEAU_MIN_S,
                             plateau_hard: int = VISUAL_PLATEAU_HARD_ROUNDS,
                             last_judgment_at=None,
                             idle_s: float = VISUAL_IDLE_S,
                             blocking_average=None, avg_min=None,
                             avg_stable_rounds: int = 0,
                             avg_release_rounds: int = VISUAL_AVG_RELEASE_ROUNDS,
                             avg_release: bool = VISUAL_AVG_RELEASE,
                             coverage_ok: bool = False) -> str:
    """Decide the visual-blocked delivery path. Returns:
      * ``"defer"``       — keep blocking the release; the lane should iterate.
      * ``"release"``     — escape: deliver anyway (recorded below-threshold).
      * ``"fast_release"``— FIX #558: the gating blocking_average already clears the
        min bar STABLY, so release NOW instead of grinding to the escape (same
        outcome, ~40-60 min sooner). Distinct value so the caller logs the fast-
        release line; the caller treats it EXACTLY like ``"release"`` otherwise.
    Escapes (so the deferral ALWAYS terminates — PIPE-C3): the per-milestone
    wall-clock since the FIRST defer exceeds ``escape_s`` (anchored, NOT reset by
    lane churn), OR the per-source attempt budget is spent, OR the per-milestone
    total real-judgment cap is hit (vision-cost backstop), OR — FIX #138 — the
    judged scores have PLATEAUED (``plateau_rounds`` consecutive real judgments
    with no blocking screen beating its best-so-far) after at least
    ``plateau_min_s`` of deferral: further waiting buys nothing (log-mining runs
    50-62: the window averaged ~65min = ~40% of total wall-clock and 7/7 ended
    on the timer, never a pass).

    FIX #558 (AVG FAST-RELEASE): checked FIRST so it pre-empts the wall-clock grind.
    Fires ONLY when ALL hold — (1) the gating ``blocking_average`` (#542, over
    BLOCKING screens only) is ≥ ``avg_min`` (the operationalized 0.65 Part-A bar,
    NEVER lowered here), (2) it has been ≥ the bar for ``avg_release_rounds``
    consecutive REAL judgments (``avg_stable_rounds`` — reuses the same per-milestone
    round tracking as ``plateau_rounds`` so a single lucky pass can't trip it), and
    (3) ``coverage_ok`` — the blocking exam is complete (≥1 blocking screen judged,
    the same coverage precondition ``visual_gate_verdict``'s pass already requires).
    This is a strict SUBSET of the states the wall-clock escape would eventually
    release anyway, so it can NEVER ship an app the escape would not, only sooner. It
    is a pure additive path: with the defaults (``coverage_ok`` False, averages None)
    it never fires, so every other branch is byte-identical. Disable via
    ``avg_release`` (env ENVGEN_VISUAL_AVG_RELEASE)."""
    if (avg_release and coverage_ok and avg_release_rounds > 0
            and blocking_average is not None and avg_min is not None
            and blocking_average >= avg_min
            and avg_stable_rounds >= avg_release_rounds):
        return "fast_release"
    if deferred_since is not None and (now - deferred_since) > escape_s:
        return "release"
    if total_judgments >= total_cap:
        return "release"
    if attempts >= attempt_cap:
        return "release"
    if (plateau_cap > 0 and plateau_rounds >= plateau_cap
            and deferred_since is not None
            and (now - deferred_since) >= plateau_min_s):
        return "release"
    # FIX #519 (netflix r91): CHURN-ROBUST hard plateau — NO time floor. A lane that
    # edits the source on every visual-fail resets the per-source attempt cap (the only
    # fast escape) to 0 each time, so attempts>=3 never fires and the soft plateau/idle
    # escapes above are gated behind the 1500s floor — delivery deferred 1418s+ with only
    # the 3600s wall-clock (or 20-judgment cap) left to release. plateau_rounds is
    # per-milestone and is NOT reset by source churn (it counts real judgments where no
    # blocking screen beat its best-so-far, _best_by_screen accumulating across sources),
    # so a HARD plateau (2x the soft cap) is conclusive evidence the scores are final no
    # matter how fast the lane flips the source — release with no floor. Additive escape;
    # every existing escape (incl. the 3600s backstop) is untouched, so delivery still
    # ALWAYS eventually fires, and 2x the soft cap means noise alone can't trip it early.
    if plateau_hard > 0 and plateau_rounds >= plateau_hard:
        return "release"
    # FIX #145 (run-68 M4): the gate judges on SOURCE CHANGE — when the
    # frontend stops producing changes the plateau counter freezes below its
    # cap and only the 3600s anchor releases (run-68: last judgment 13:59,
    # anchor release 14:21 = 22min of zero new evidence). A frozen source is
    # the strongest plateau evidence there is: no change → no new judgments →
    # the scores are final. Same deferral floor as #138.
    if (idle_s > 0 and last_judgment_at is not None
            and deferred_since is not None
            and (now - deferred_since) >= plateau_min_s
            and (now - last_judgment_at) >= idle_s):
        return "release"
    return "defer"


def _visual_fast_release_args(gate) -> dict:
    """FIX #558: the AVG fast-release inputs extracted from a VisualFidelityGate's LAST judged
    result — the gating ``blocking_average`` (#542), the min bar (``min_similarity`` = the
    operationalized ENVGEN_VISUAL_MIN), the consecutive-stable-round count (``avg_pass_rounds``,
    reusing the per-milestone round tracking), and whether the blocking exam is COMPLETE
    (``coverage_ok`` iff ≥1 blocking screen was judged — the same coverage precondition
    ``visual_gate_verdict``'s pass requires; a partial capture records missing pages as 0.0 which
    drags the average, so this can't mask an incomplete exam). Kwargs for ``_visual_release_decision``.
    Pure + getattr-guarded: with no last_result (fast-release cannot fire) it returns safe defaults
    that leave every other release branch byte-identical."""
    res = getattr(gate, "last_result", None) or {}
    cov = res.get("coverage") or {}
    try:
        _blocking_judged = int(cov.get("blocking_judged") or 0)
    except Exception:
        _blocking_judged = 0
    return {
        "blocking_average": res.get("blocking_average"),
        "avg_min": res.get("min_similarity"),
        "avg_stable_rounds": getattr(gate, "avg_pass_rounds", 0),
        "coverage_ok": _blocking_judged >= 1,
    }


# FIX #139: registry-state check classes a lane can flip during the delivery tail —
# a FRESH milestone-gate verdict outranks a final-gate re-read that fails ONLY on
# these (ig run-61: a chain re-registered status='registered' 1s before the final
# evaluation; outlook run-28/31 were the live-probe flavor of the same drift). Same
# membership as REVALIDATION_FIXABLE_CHECKS — a re-validatable blocker is exactly one
# a stale milestone verdict can outrank OR a re-run can clear.
FINAL_GATE_DRIFT_CLASSES = REVALIDATION_FIXABLE_CHECKS


def _final_gate_drift_waiver(ms_cleared_at, failed_checks, now: float,
                             *, window_s: float = 900.0) -> bool:
    """True when a failed FINAL gate should be waived in favor of the milestone
    verdict: the milestone gate evaluated fully clear within ``window_s`` and the
    final failure set is non-empty and ONLY registry-state drift classes
    (structural failures — docker/contract/build — are never waived)."""
    if ms_cleared_at is None:
        return False
    if (now - ms_cleared_at) > window_s:
        return False
    failed = set(failed_checks or [])
    return bool(failed) and failed <= FINAL_GATE_DRIFT_CLASSES


def _final_gate_revalidation_warranted(failed_checks) -> bool:
    """True when a failed FINAL gate should trigger a BOUNDED re-run of framework
    validation (re-execute every verification chain against the LIVE backend and
    re-record fresh status) BEFORE raising rc=1, rather than failing immediately.

    Warranted iff the failure set is NON-EMPTY and consists ONLY of re-validatable
    checks (``REVALIDATION_FIXABLE_CHECKS``) — a STRUCTURAL failure
    (docker/contract/build/ui_*) is not re-runnable and MUST raise immediately, so
    any check outside that set disqualifies the whole set.

    WHY (netflix r105, 2026-08-06): on the visual-ESCAPE delivery path
    (deliver-anyway) the framework-deliver clear branch never runs, so
    ``_milestone_gate_cleared_at`` is never stamped and the #139 drift-waiver above
    cannot fire. The existing final-gate readiness retry only WAITS + RE-READS the
    (stale) chain registry — it never RE-EXECUTES the chains — so a TRANSIENT chain
    failure at the final gate (r105: ``auth_register_login_round_trip`` hit a single
    ``POST /auth/login → 500`` while two IDENTICAL login chains passed in the same
    pass) wedged an otherwise fully-green run (Part-A solved, delivered 6× before) to
    rc=1 with NO release. A clean-boot re-run clears the transient; a genuine failure
    (a create 500ing deterministically, a 2xx-expected step returning 4xx) re-fails
    and still raises — so this never ships a broken app. Pure + unit-tested."""
    failed = set(failed_checks or [])
    return bool(failed) and failed <= REVALIDATION_FIXABLE_CHECKS


class Orchestrator:
    """Multi-Agent Orchestrator."""
    
    def __init__(
        self,
        llm_config: LLMConfig,
        output_dir: Path,
        name: str = "generated_app",
        reference_images: List[str] = None,
        verbose: bool = False,
        design_input: str = None,
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

        self._design_input = design_input  # Design-Prep phase input dir (Task 5); None → off
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

    async def _await_prior_milestone_delivery_drained(
        self,
        milestone_index: int,
        *,
        timeout_s: float = 600.0,
        poll_s: float = 2.0,
    ) -> bool:
        """FIX #561 (serialize milestones): block until the PRIOR milestone's
        delivery is FULLY DRAINED before M(i>=2) advances into its kickoff.

        "Fully drained" = the orchestrator lane's ``_project_delivered_event`` is
        set AND the prior milestone's release was cut (``self._project_delivered``).
        The per-milestone delivery ``while`` loop normally blocks until this holds,
        but a delivery that set the LANE event via the LLM ``deliver_project`` tool
        without the framework release having been cut (``deliver_project`` only sets
        the event; ``_maybe_framework_deliver`` is the SOLE ``create_release``
        caller) — or any early loop break — could otherwise let M(i)'s kickoff +
        ``_respawn_core_lanes`` + state-reset RACE an unfinished prior delivery
        (observed: M2 kickoff running concurrently with unfinished M1 delivery).
        This guard closes that race deterministically, right before the reset.

        Idempotently cuts the prior milestone's release (``_maybe_framework_deliver``
        no-ops once ``self._project_delivered`` is True) so "event set but release
        not cut" converges to fully-drained. Bounded: returns True when drained,
        False on timeout (logged loudly; caller proceeds rather than hang, since the
        delivery loop already ran). NEVER invoked for M1, so the single-milestone
        path is byte-identical (the whole method is behind ``if _m_idx > 1``).
        """
        prev_lane = self._agents.get("orchestrator")
        if prev_lane is None:
            return True
        ev = getattr(prev_lane, "_project_delivered_event", None)
        if ev is None:
            return True
        deadline = time.time() + max(0.0, timeout_s)
        while True:
            # Idempotent: cut the prior milestone's release if the lane signalled
            # delivery but the framework release wasn't cut yet.
            if not getattr(self, "_project_delivered", False):
                try:
                    await self._maybe_framework_deliver()
                except Exception as _drain_err:
                    self._logger.warning(
                        "M%s drain: _maybe_framework_deliver raised (continuing): %s",
                        milestone_index, _drain_err)
            if getattr(self, "_project_delivered", False) and ev.is_set():
                return True
            if time.time() >= deadline:
                self._logger.warning(
                    "M%s: prior-milestone delivery drain wait exceeded %.0fs "
                    "(delivered=%s, event_set=%s) — proceeding to avoid a hang.",
                    milestone_index, timeout_s,
                    getattr(self, "_project_delivered", False), ev.is_set())
                return False
            await asyncio.sleep(poll_s)

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
        """Return validation records shaped for legacy orchestrator consumers.
        #193: same canonical status vocabulary + nested-metadata flatten as
        hub_registry.get_validation_results — the two readers must agree."""
        from .runtime.hub_registry import (
            _canon_validation_status, _flatten_validation_metadata)
        checks = self._get_validation_checks()
        records = []
        for c in checks:
            ev = c.get("evidence", {}) or {}
            records.append({
                "task_id": c.get("name", "").removeprefix("validation:"),
                "status": _canon_validation_status(c.get("status", "error")),
                "summary": ev.get("summary", ""),
                "execution_mode": ev.get("execution_mode", "auto"),
                "duration_seconds": ev.get("duration_seconds"),
                "artifacts": ev.get("artifacts", []),
                "evidence": ev,
                "metadata": _flatten_validation_metadata(ev),
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
                    s.bind(('0.0.0.0', port))
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
                phases_completed = ["requirements", "kickoff", "code", "docker", "testing"]
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
                # STABILITY (ENVGEN_SINGLE_MILESTONE, default-off): force the whole
                # app into ONE milestone instead of the agent-planned ≤6 split.
                # Multi-milestone is a major wedge surface — every milestone past M1
                # opens its OWN kickoff, and a THIN later slice (e.g. an M2 with no new
                # backend endpoints) leaves backend/verifier with nothing to declare:
                # they never record a section, the deterministic reconcile can't derive
                # one from an empty slice, and the 1200s kickoff timeout HARD-ABORTS the
                # whole run (instagram_v4: M1 nearly delivered, M2 kickoff timed out
                # Missing=['backend','verifier'] → abort). Worse, M2 kickoff ran
                # concurrently with unfinished M1 delivery. Collapsing to one milestone
                # (the existing single-milestone fallback path, whole requirements as the
                # slice) removes that surface entirely. GENERAL, not env-specific: any env
                # just builds in one kickoff/delivery; byte-identical when the flag is off.
                # Tolerant flag parse: os.environ.get returns a STRING, and
                # bool("0") is True in Python — so `bool(os.environ.get(...))`
                # can never be turned OFF (setting =0 still forced single-ms).
                # Match the rest of the codebase idiom: only real truthy tokens
                # enable it; unset/"0"/"false"/"no"/"off" leave the agent-planned
                # multi-milestone split active (framework default = multi).
                _force_single_ms = os.environ.get(
                    "ENVGEN_SINGLE_MILESTONE", "0").strip().lower() in (
                    "1", "true", "yes", "y", "on")
                if _force_single_ms:
                    self._logger.warning(
                        "MILESTONE PLAN: single-milestone mode (ENVGEN_SINGLE_MILESTONE) — "
                        "whole app in ONE kickoff+delivery; multi-milestone planning skipped.")
                if not _milestones_explicit and not _force_single_ms:
                    try:
                        from .runtime.reference_materials import plan_milestones
                        from .runtime.llm_overrides import get_component_llm as _gcl
                        _planned = await plan_milestones(
                            _gcl(self, "milestone_plan") or self.llm, raw_req,
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

                # MILESTONES AS FIRST-CLASS STATE (2026-06-24): seed the roadmap into
                # hubs.milestones so it is queryable/persistent and the orchestrator can
                # revise FUTURE phases + author each phase's milestone detail via the
                # milestone_* tools at kickoff. The store is the source of truth from here:
                # the loop marks active/delivered + re-syncs the remaining phases from it
                # (so an orchestrator add/remove of a future milestone takes effect).
                try:
                    self.hubs.milestones.set_roadmap(milestones, agent="orchestrator")
                except Exception as _ms_seed_err:
                    self._logger.warning("milestone store seed failed: %s", _ms_seed_err)

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
                    # §4: expose the current milestone dict (its acceptance[] + slice) so the
                    # delivery gate + the test-user squad can scope to THIS milestone.
                    self._current_milestone = _milestone if isinstance(_milestone, dict) else {}
                    # Stamp milestone-completeness onto the orchestrator AGENT so the
                    # deliver_project tool can reject a premature FINAL delivery during an
                    # earlier milestone (deliver_project ends the run; earlier milestones
                    # cut a per-milestone release + advance — they must NOT final-deliver).
                    self._stamp_milestone_flags_on_orch_agent(_m_idx, len(milestones))
                    _orch_agent_ms = self._agents.get("orchestrator")
                    # Per-milestone visual state: anchor the deferral clock and the
                    # total-judgment backstop to THIS milestone (PIPE-C3 — within a
                    # milestone neither is reset by lane churn).
                    self._vf_gate.reset_for_milestone()
                    # Per-milestone page-build deferral state (mirror of the visual
                    # gate): the deferral clock + attempt count anchor to THIS milestone.
                    self._pages_gate_deferred_since = None
                    self._pages_gate_attempts = 0
                    # Per-milestone TEST-USER SQUAD gate state (§3.5). Unlike the visual
                    # gate, this runs EVERY milestone (the verify->fix loop the user's flow
                    # diagram puts inside each milestone), bounded by squad_release_decision.
                    self._tu_squad_passed = False
                    self._tu_squad_deferred_since = None
                    self._tu_squad_attempts = 0
                    # #532: the squad now runs as a single-flight BACKGROUND task; a
                    # leftover handle from the prior milestone must not be consumed by
                    # this one. Cancel any in-flight squad and drop the handle so the
                    # first defer of THIS milestone re-launches a fresh single-flight run.
                    _prev_tu_task = getattr(self, "_tu_squad_task", None)
                    if _prev_tu_task is not None and not _prev_tu_task.done():
                        _prev_tu_task.cancel()
                    self._tu_squad_task = None
                    # This milestone's requirement slice → kickoff input. When
                    # milestones were NOT explicitly supplied, the single
                    # synthesized M1 MUST receive the exact legacy ``raw_req``
                    # (byte-for-byte transparency at N=1). For explicit
                    # milestones, use the slice, falling back to raw_req only if
                    # a slice is empty.
                    _slice = str(_milestone.get("description_slice") or "").strip()
                    if not _milestones_explicit and len(milestones) <= 1:
                        # Genuine SINGLE synthesized milestone (N=1): the exact
                        # legacy raw_req, byte-for-byte transparency.
                        _milestone_req = raw_req
                    else:
                        # MULTIPLE milestones (explicit OR auto-planned): this phase is
                        # scoped to its own slice/detail, never the full goal. The store
                        # (hubs.milestones) is the source of truth.
                        #
                        # PER-MILESTONE PLANNING (user 2026-06-24, P1/P2/P4): mark THIS
                        # phase active, then run the orchestrator's KICKOFF-DETAIL turn —
                        # the orchestrator AGENT (its full system prompt + hub context +
                        # the milestone_* tools) reviews the roadmap, MAY revise FUTURE
                        # phases (add/update/remove; delivered+active frozen), and authors
                        # THIS phase's DETAILED detail — BEFORE the lanes draft. Bounded +
                        # best-effort: on timeout/decline it falls back to the rough slice
                        # (never hangs the run).
                        try:
                            for _pm in self.hubs.milestones.list_milestones():
                                if int(_pm.get("index", 0)) < _m_idx and _pm.get("status") != "delivered":
                                    self.hubs.milestones.mark_status(_pm["index"], "delivered", agent="orchestrator")
                            self.hubs.milestones.mark_status(_m_idx, "active", agent="orchestrator")
                        except Exception:
                            pass
                        _detail = ""
                        try:
                            from .runtime.kickoff.run_kickoff import author_milestone_detail
                            _detail = await author_milestone_detail(
                                self.hubs, self._agents.get("orchestrator"),
                                _m_idx, raw_req=raw_req)
                        except Exception as _br_exc:
                            self._logger.warning("milestone-detail turn raised: %s", _br_exc)
                            _detail = ""
                        # P2: the orchestrator may have added/updated/removed FUTURE phases
                        # via the tools — re-sync the not-yet-started tail from the store so
                        # the running loop honors the revision (delivered+current frozen).
                        try:
                            _store_future = [m for m in self.hubs.milestones.list_milestones()
                                             if int(m.get("index", 0)) > _m_idx]
                            milestones[_m_idx:] = _store_future
                            # is_final may have changed if a phase was added/removed.
                            self._is_final_milestone = (_m_idx >= len(milestones))
                            if _orch_agent_ms is not None:
                                _orch_agent_ms._is_final_milestone = self._is_final_milestone
                                _orch_agent_ms._milestone_progress = (_m_idx, len(milestones))
                                # FIX #117: keep the deliver_project visual guard stamped
                                # through milestone-plan revisions too.
                                _orch_agent_ms._visual_defer_check = self._visual_delivery_defer_active
                        except Exception:
                            pass
                        # P1+P4: kickoff requirement = the detailed detail (phase TASK) +
                        # the overall goal as labeled CONTEXT. Detail LEADS so the meeting
                        # TITLE is the phase. Fall back to the rough slice if the detail turn
                        # produced nothing (bounded await timed out / orchestrator declined).
                        if _detail and _detail.strip():
                            self._logger.warning(
                                "M%s: orchestrator authored a detailed milestone detail "
                                "(%d chars) + overall-goal context.", _m_idx, len(_detail))
                        else:
                            # LOUD, not silent: an empty detail means the kickoff-detail turn
                            # produced nothing. We still fall back to the rough slice so the
                            # run never hard-crashes, but surface it for investigation.
                            self._logger.error(
                                "M%s: orchestrator authored NO milestone detail — falling "
                                "back to the rough slice; INVESTIGATE.", _m_idx)
                        _phase = _detail.strip() if (_detail and _detail.strip()) else (_slice or raw_req)
                        _milestone_req = (
                            _phase
                            + "\n\n## OVERALL PROJECT TARGET (context only — the full end "
                              "goal; build ONLY this milestone's scope above)\n" + raw_req)
                        # Spec backstop ONLY when there's neither a detail NOR a slice.
                        if not (_detail and _detail.strip()) and not _slice:
                            _spec_block = getattr(self, "_reference_spec_summary", "")
                            if _spec_block and _spec_block not in _milestone_req:
                                _milestone_req = _milestone_req + _spec_block

                    if _m_idx > 1:
                        # FIX #561 (serialize milestones): M(i) kickoff MUST NOT begin
                        # until M(i-1) delivery is FULLY DRAINED (prior
                        # _project_delivered_event set + its release cut). The delivery
                        # while-loop above normally guarantees this, but a lane-set
                        # delivery event without a cut release (or an early break) could
                        # let this milestone's reset/respawn/kickoff race the prior
                        # milestone's delivery tail (observed: M2 kickoff concurrent with
                        # unfinished M1 delivery). Confirm/await the drain BEFORE
                        # clearing the event + resetting per-milestone state below, so
                        # the reset never races the prior delivery. Bounded; no-op once
                        # already drained. Never runs for M1 (byte-identical single-MS).
                        await self._await_prior_milestone_delivery_drained(_m_idx)
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
                        # deliver-stuck + abort-grace state is per-milestone too: a fresh
                        # milestone's stall is independently eligible for the grace.
                        self._fwdeliver_stuck_count = 0
                        self._fwdeliver_stuck_key = None
                        self._fwdeliver_first_decline_ts = 0.0
                        # #230 (r21 M2): the #228 converging-grace bookkeeping is
                        # per-milestone too — M1 consumed both graces, so M2's
                        # converging stall aborted with zero grace available.
                        self._fwdeliver_grace_count = 0
                        self._fwdeliver_prev_failed = None
                        self._fwdeliver_last_shrink_ts = 0.0
                        self._fwval_abort_grace_used = 0
                        self._fwval_abort_deliver_reason = None
                        self._fwval_abort_progress_sig = None
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
                        # FIX #123: the respawn just created a FRESH orchestrator agent —
                        # re-stamp the milestone flags + the #117 visual-defer check on it.
                        self._stamp_milestone_flags_on_orch_agent(_m_idx, len(milestones))

                    # Charter §8: orchestrator wire is ONE call site — boot
                    # the kickoff coordinator. start_kickoff opens the
                    # meeting page on WorkHub + broadcasts kickoff_request
                    # via EventHub. Each resident lane wakes via its default
                    # ('orchestrator','kickoff_request','high') subscription
                    # and runs its kickoff_response prompt. The orchestrator
                    # lane wakes on workhub.meeting_decision_added events
                    # and runs its kickoff_facilitation_prompt — which finalizes
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
                        # FIX #95 (runs 4/10/13, live): Gemini MALFORMED storms are
                        # 20-50min BURSTS — a kickoff landing in one times out with
                        # ZERO drafts and the abort discards runs that had ALREADY
                        # delivered milestones (run-13: M1+M2). ONE bounded retry:
                        # re-broadcast the kickoff_request to the missing lanes and
                        # drive one more window; if the burst passed, the run lives.
                        self._logger.error(
                            "Kickoff timed out (missing=%s) — FIX #95: ONE retry "
                            "(re-broadcast + one more drive window) before aborting.",
                            kickoff_receipt.get("missing"))
                        try:
                            run_kickoff.rebroadcast_kickoff_request(
                                self.hubs, self._kickoff_handle,
                                only=list(kickoff_receipt.get("missing") or []) or None)
                        except Exception as _rb_err:
                            self._logger.warning("kickoff re-broadcast failed: %s", _rb_err)
                        # the driver times out on handle['started_at'] — without a reset
                        # the retry window would expire INSTANTLY.
                        self._kickoff_handle["started_at"] = time.time()
                        try:
                            kickoff_receipt = await asyncio.wait_for(
                                self._drive_kickoff_to_completion(self._kickoff_handle),
                                timeout=run_kickoff.KICKOFF_TIMEOUT_SEC + 600,
                            )
                        except asyncio.TimeoutError:
                            try:
                                _ls2 = run_kickoff.try_synthesize(
                                    self.hubs, self._kickoff_handle)
                            except Exception:
                                _ls2 = {"status": "unknown"}
                            kickoff_receipt = self._kickoff_fallback_or_reconcile(
                                self._kickoff_handle, _ls2, "driver_wedged")
                    if kickoff_receipt.get("phase") == "timeout_fallback":
                        raise RuntimeError(
                            "Kickoff timed out after "
                            f"{run_kickoff.KICKOFF_TIMEOUT_SEC:.0f}s without "
                            "a ready synthesis (incl. one FIX #95 retry). Missing="
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
                            # B1 (pre-launch audit): the event may have been set by the
                            # LLM's deliver_project, which only flags the LANE — it does
                            # NOT cut a release. _maybe_framework_deliver (the SOLE
                            # create_release caller) is below this break, so without this
                            # the run could exit "delivered" with NO release tag. Run it
                            # once before breaking — it's idempotent (guards on the
                            # ORCHESTRATOR's self._project_delivered, distinct from the
                            # lane flag the tool set), so it cuts the release exactly once.
                            await self._maybe_framework_deliver()
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
                        # #326: a TERMINAL LLM-provider error (spend/budget/quota exhausted, hard
                        # auth) latched by the client is unrecoverable — abort within one tick
                        # (~60s) instead of letting every lane spin thousands of rejected calls
                        # to the wall-clock cap (r93: ~4500 rejected attempts over ~2h). This is
                        # NOT a run-budget/tick overrun, so its message points at the real fix.
                        if not budget_exceeded:
                            _term = _terminal_llm_error()
                            if _term:
                                budget_exceeded = (
                                    "LLM provider budget/auth exhausted — get a budget increase "
                                    f"or a fresh key (raising ENVGEN_MAX_* will NOT help): {_term}")
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
                            # ABORT-GRACE (smoke-notes exp11): a DELIVER-stuck abort latches
                            # at the deliver-check but is consumed HERE the next iteration —
                            # so an in-flight remediation that landed in the gap (most often:
                            # the verifier just (re-)registered a verification chain that only
                            # needs one run_validation to pass) gets killed before it can run.
                            # If forward progress (source/contract/chain change) happened SINCE
                            # the abort latched, defer one cycle so it can run. Keyed on the
                            # stable progress signature, capped (FWVAL_ABORT_GRACE_MAX) so a
                            # genuine wedge still fails fast; only the deliver-stuck reason
                            # (identity-matched below) is eligible — Site A / no-converge
                            # aborts have a different reason string → never deferred.
                            # IS this the DELIVER-stuck abort (vs a framework-validation /
                            # Site A or no-converge abort)? Tie it to the EXACT reason the
                            # deliver-stuck latch stored — NOT a separate boolean that can go
                            # stale if Site A overwrites _fwval_abort_reason while the flag
                            # lingers True (review wjakad12l). Identity-match is staleness-proof:
                            # a Site A / no-converge reason never equals the stored deliver one.
                            _is_deliver_stuck = (
                                _abort is not None
                                and _abort == getattr(self, "_fwval_abort_deliver_reason", None))
                            if _abort_grace_should_defer(
                                    _is_deliver_stuck,
                                    getattr(self, "_fwval_abort_grace_used", 0),
                                    getattr(self, "_fwval_abort_progress_sig", None),
                                    self._deliver_progress_sig()):
                                self._fwval_abort_grace_used = getattr(
                                    self, "_fwval_abort_grace_used", 0) + 1
                                self._logger.warning(
                                    "ABORT-GRACE (%d/%d): forward progress since the "
                                    "delivery stuck-abort latched (a contract/chain change is "
                                    "landing) — deferring fail-fast one cycle so the in-flight "
                                    "remediation can run_validation.",
                                    self._fwval_abort_grace_used, FWVAL_ABORT_GRACE_MAX)
                                self._fwval_abort_reason = None
                                self._fwval_abort_deliver_reason = None
                                # Reset the deliver-stuck ladder so the deferred remediation
                                # gets a FULL window (not an immediate re-latch+thrash that
                                # burns the grace cap in 1-2 cycles — review wjakad12l).
                                self._fwdeliver_stuck_count = 0
                                self._fwdeliver_stuck_key = None
                            else:
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
                            f"coordination ticks: {stuck_abort_reason} The gate blocker did not "
                            f"clear after re-dispatch — either a RECOVERABLE lane-phase desync "
                            f"(an owning lane went idle/unreachable and the remediation wake did "
                            f"not land) or a framework artifact regenerated every cycle. Raising "
                            f"ENVGEN_MAX_* will NOT help — inspect the gate blocker + the owning "
                            f"lane shown above, then re-run."
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
                    # FINAL-GATE READINESS RETRY (outlook run-28 rc=1 + run-31 FAILED, live):
                    # this gate probes LIVE state (sql_tables introspection, business-chain
                    # runs) and the compose stack restarts between milestones — a mid-restart
                    # evaluation saw sql_tables=4-of-11 / failing chains on a HEALTHY app and
                    # killed an otherwise-delivered run. Wait (bounded) for the backend to
                    # serve, then re-evaluate ONCE; a genuinely failing gate still raises,
                    # just ≤90s later.
                    from .runtime.validation_runner import wait_backend_ready
                    self._logger.warning(
                        "Final delivery gate failed on first evaluation (%s) — waiting for "
                        "backend readiness (compose may be mid-restart) and re-evaluating once.",
                        gate.get("failed_checks"))
                    wait_backend_ready(self.output_dir)
                    gate = self._validate_delivery_gate()
                if not gate["ok"]:
                    # FIX #139 (ig run-61 + outlook run-28/31 — final-gate/milestone-gate
                    # state DRIFT): this gate re-reads MUTABLE hub state, and a lane that
                    # touches the chain registry during the multi-minute delivery tail
                    # (run-61: the verifier re-registered a chain — status='registered',
                    # NEVER RUN — 1 second before this evaluation) flips
                    # business_chain_failing on a run whose milestone gate evaluated
                    # fully CLEAR minutes earlier and cut every release. When the
                    # milestone verdict is FRESH and the failure set is ONLY the
                    # registry-state class (not structural: docker/contract/build),
                    # honor the milestone verdict — loudly.
                    _ms_clear = getattr(self, "_milestone_gate_cleared_at", None)
                    _failed = set(gate.get("failed_checks") or [])
                    if _final_gate_drift_waiver(_ms_clear, _failed, time.time()):
                        self._logger.warning(
                            "FINAL-GATE DRIFT WAIVER (#139): the milestone gate evaluated "
                            "fully CLEAR %ss ago and every release was cut; the final "
                            "re-evaluation failed only on %s — registry state a lane "
                            "mutated during the delivery tail (run-61 class), not a "
                            "regression of the delivered artifact. Honoring the "
                            "milestone verdict.",
                            int(time.time() - _ms_clear), sorted(_failed))
                        gate = dict(gate)
                        gate["ok"] = True
                if not gate["ok"] and not getattr(self, "_final_gate_revalidated", False):
                    # FINAL-GATE CONVERGENCE RE-RUN (#553, netflix r105, live): the readiness
                    # retry above only WAITS + RE-READS the chain registry — it never RE-EXECUTES
                    # the chains — and on the visual-ESCAPE delivery path the #139 drift-waiver is
                    # unavailable (_milestone_gate_cleared_at is never stamped when the visual gate
                    # ESCAPES rather than CLEARS). So a TRANSIENT chain failure at the final gate
                    # (r105: auth_register_login_round_trip hit ONE POST /auth/login → 500 while two
                    # IDENTICAL login chains passed in the same pass) killed an otherwise fully-green
                    # run (Part-A solved, delivered 6× before) to rc=1 with NO release. When the ONLY
                    # blockers are re-validatable (business_chain_failing / verification_checklist_not
                    # _ready — NOT structural docker/contract/build/ui_*), do ONE bounded re-run of
                    # framework validation (RunValidationTool: clean boot + re-execute every chain
                    # against the live backend + re-record fresh chain/build status), then re-evaluate
                    # ONCE. A transient failure clears; a GENUINE failure (a create 500ing
                    # deterministically, a 2xx-expected step returning 4xx) re-fails and still raises
                    # below — so this NEVER ships a broken app. Bounded via _final_gate_revalidated.
                    _failed = set(gate.get("failed_checks") or [])
                    if _final_gate_revalidation_warranted(_failed):
                        self._final_gate_revalidated = True  # at most ONE re-run per run()
                        self._logger.warning(
                            "FINAL-GATE CONVERGENCE RE-RUN (#553): the final gate failed ONLY on "
                            "re-validatable check(s) %s and the #139 drift-waiver did not apply "
                            "(visual-ESCAPE delivery path leaves _milestone_gate_cleared_at unset). "
                            "Re-EXECUTING framework validation (clean boot + re-run every "
                            "verification chain against the live backend, re-recording fresh "
                            "status) before deciding — a transient chain failure clears; a genuine "
                            "one re-fails and still raises.", sorted(_failed))
                        try:
                            from tools.validation_tools import RunValidationTool
                            _rv = RunValidationTool(workspace=None)
                            _rv._hubs = getattr(self, "hubs", None)
                            _rv._agent_id = "orchestrator"
                            await _rv.execute()
                        except Exception as _rv_err:
                            self._logger.error(
                                "FINAL-GATE CONVERGENCE RE-RUN raised (non-fatal — gate is "
                                "re-evaluated on whatever state exists): %s", _rv_err)
                        gate = self._validate_delivery_gate()
                        if gate["ok"]:
                            self._logger.warning(
                                "FINAL-GATE CONVERGENCE RE-RUN CLEARED the gate — the prior "
                                "failure was transient/re-runnable; delivering.")
                if not gate["ok"]:
                    report = self._format_delivery_gate_report(gate)
                    raise RuntimeError(f"Delivery gate failed.\n{report}")
            
                self._enter_project_phase("done", reason="delivery gate passed")
                # FINAL-MILESTONE RELEASE. create_release lives ONLY inside the
                # per-milestone _maybe_framework_deliver, which DEFERS on the final
                # milestone (visual gate) — so this post-loop success path would mark
                # the generation done without ever cutting the last milestone's
                # release (run #11: M1 cut v1.0.0 but M2's v1.1.0 was never cut, and
                # the resident-lane shutdown then hung). Now the objective gate is
                # fully clear, so cut it here, BEFORE shutdown — the snapshot only
                # needs the committed integration head, not stopped lanes. Idempotent:
                # skipped when the tag is already released (single-milestone path).
                try:
                    self._commit_framework_delivery()
                    _ch = getattr(self.hubs, "codehub", None)
                    _ver = getattr(self, "_current_milestone_version", "1.0.0")
                    _already = False
                    try:
                        _rs = getattr(getattr(_ch, "stores", None), "releases", None)
                        _already = bool(_rs and _ver in (_rs.value() or {}))
                    except Exception:
                        _already = False
                    if _ch is not None and hasattr(_ch, "create_release") and not _already:
                        _ch.create_release(
                            tag=_ver, source="integration",
                            notes="Final delivery: delivery gate fully clear.",
                            agent="orchestrator")
                        self._write_preview_config(_ver)
                        self._logger.warning(
                            "FINAL DELIVERY: gate clear → cut release v%s", _ver)
                except Exception as _fin_rel_err:  # best-effort observability
                    self._logger.warning("final-gate release cut failed: %s", _fin_rel_err)
                phases_completed = ["requirements", "kickoff", "code", "docker", "testing"]
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
            # #257: where the prompt tokens actually came from. r51 measured 456.7M
            # prompt vs 0.9M completion, with the uncached share ~0.8x the per-step
            # GROWTH — i.e. the cache is already near-optimal and the cost IS the new
            # text each step appends (35-51k tokens/step/lane), which is tool OUTPUT.
            # Print the per-tool rollup once at exit so the next reduction is aimed at
            # measured offenders instead of guesses.
            try:
                from .agents.runtime.tooling import tool_io_rollup
                self._logger.info("%s", tool_io_rollup())
            except Exception:
                pass
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
        
        for agent_id in ["backend", "frontend"]:
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

    def _stamp_milestone_flags_on_orch_agent(self, m_idx: int, total: int) -> None:
        """FIX #123 (run-42, live): stamp the milestone flags + the #117 visual-defer
        check onto the CURRENT orchestrator agent instance. The original stamp ran
        only at the top of the milestone iteration — but _respawn_core_lanes()
        (milestone 2+) creates FRESH agent instances, so every stamp was LOST for
        the rest of the milestone: the new orchestrator agent defaulted to
        _is_final_milestone=True with NO _visual_defer_check, and run-42's LLM
        deliver_project sailed through mid-visual-window (1397s/3600s, the exact
        bypass #117 was built to close). Call at the iteration top AND immediately
        after every respawn. Idempotent; never raises."""
        try:
            a = self._agents.get("orchestrator")
            if a is None:
                return
            a._is_final_milestone = bool(getattr(self, "_is_final_milestone", True))
            a._milestone_progress = (m_idx, total)
            a._visual_defer_check = self._visual_delivery_defer_active
        except Exception:
            pass

    def _visual_delivery_defer_active(self) -> bool:
        """FIX #117 (run-32 autopsy): True while the FINAL milestone's visual gate is
        actively deferring — deliver_project consults this (stamped onto the
        orchestrator agent as ``_visual_defer_check``) and rejects, keeping the
        coordination loop (and the lanes it drives) alive so the remediation window
        (#112/#112b) actually gets its time. run-32: the LLM called deliver_project at
        1406s into a 3600s window (its objective gate report is all-green — visuals
        are not one of its checks) → loop exited → lanes terminated → post-loop path
        cut the release mid-convergence. Returns False the moment the gate passes OR
        the bounded escape fires (nothing can deadlock); getattr-pure + never raises
        (a broken check must never block delivery)."""
        try:
            if not getattr(self, "_reference_images", None):
                return False
            if not getattr(self, "_is_final_milestone", True):
                return False
            if os.environ.get("ENVGEN_VISUAL_BLOCKING", "1").lower() in (
                    "0", "false", "no", "off"):
                return False
            gate = getattr(self, "_vf_gate", None)
            # #533: also honor the STICKY escape-release (consistent with #521). Once
            # the bounded-deferral escape has fired (gate.released is True — set only
            # AFTER the escape earned a below-threshold delivery), the visual gate is
            # no longer deferring, so deliver_project must not be blocked by GUARD 2c.
            # No false-delivery risk: released is never True before the escape fires.
            if (gate is None or getattr(gate, "passed", False)
                    or getattr(gate, "released", False)):
                return False
            _since = getattr(gate, "deferred_since", None)
            if _since is None:
                # final milestone reached but the deliver-check hasn't anchored the
                # deferral yet — the gate is still ahead, not cleared: defer.
                return True
            # #558: pass the avg fast-release inputs so this defer-check agrees with the
            # deliver-gate block — a fast-releasable state returns "fast_release" (≠ "defer"),
            # so deliver_project is not blocked while the deliver block cuts the release.
            return _visual_release_decision(
                _since, getattr(gate, "attempts", 0),
                getattr(gate, "total_judgments", 0), time.time(),
                plateau_rounds=getattr(gate, "plateau_rounds", 0),
                last_judgment_at=getattr(gate, "last_judgment_at", None),
                **_visual_fast_release_args(gate)) == "defer"
        except Exception:
            return False

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

    async def _dispatch_unbuilt_pages(self, components) -> None:
        from .runtime.remediation_dispatcher import RemediationDispatcher
        await RemediationDispatcher(self).dispatch_unbuilt_pages(components)

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
        from .runtime.llm_overrides import get_component_llm as _gcl_rc
        res = await compile_reference_materials(
            raw_req,
            output_dir=self.output_dir,
            llm=_gcl_rc(self, "reference_compile") or self.llm,
            logger=self._logger,
            reference_images=getattr(self, "_reference_images", None),
        )
        if res.classified:
            self._reference_images = res.images
            self._reference_docs = res.docs
        if res.spec is not None:
            self._reference_spec = res.spec
            self._reference_spec_summary = res.spec_summary
        # Design-Prep phase (opt-in via --design-input): now that component_specs are measured
        # on disk, write the SKELETON design_system.json (measured palette + component regions +
        # staged real assets), then have the dedicated design_analyst AGENT measure each component
        # (crop + eyedrop + geometry) and enrich the doc. If no spawn_service (or the agent can't
        # finish), fall back to the single-shot enrich. Best-effort — a failure leaves the run
        # references-only.
        if getattr(self, "_design_input", None):
            try:
                from .runtime.design_prep import (
                    resolve_design_input, write_skeleton_design_system, run_design_prep,
                    load_valid_design_system, complete_design_system,
                    design_system_is_enriched, design_system_summary_for_requirements)
                resolved = resolve_design_input(
                    self._design_input, None, getattr(self, "_reference_images", None))
                write_skeleton_design_system(resolved, self.output_dir)   # the agent's starting doc
                agent_done = await self._spawn_design_analyst(resolved)
                dsp = self.output_dir / "design" / "design_system.json"
                # Validate the agent's output: parseable AND a design doc. A spawned LLM that wrote
                # MALFORMED JSON must not discard the whole phase — rebuild via the single-shot
                # enrich (which re-lays a valid skeleton + doc) instead.
                ds = load_valid_design_system(dsp) if agent_done else None
                # FIX #85a: an agent doc that parses but was never ENRICHED (run-5/6 live:
                # build_notes 0/98, all scales empty — the analyst wrote a script it could
                # not execute and finished) must ALSO fall back to the single-shot enrich,
                # not ship hollow. Parseability alone is not success.
                if ds is not None and not design_system_is_enriched(ds):
                    self._logger.warning(
                        "design_analyst doc is UNENRICHED (no build_notes/typography, empty "
                        "scales) — running the single-shot enrich fallback over it")
                    ds = None
                used_agent = ds is not None
                if ds is None:
                    if agent_done:
                        self._logger.warning(
                            "design_analyst produced no valid design_system.json — single-shot fallback")
                    # Per-component MODEL config: the enrichment analyst call may run
                    # its own model (component_models.design_enrich /
                    # ENVGEN_MODEL_DESIGN_ENRICH).
                    try:
                        from .runtime.llm_overrides import get_component_llm
                        _enrich_llm = get_component_llm(self, "design_enrich") or self.llm
                    except Exception:
                        _enrich_llm = self.llm
                    await run_design_prep(
                        self._design_input, None,
                        getattr(self, "_reference_images", None),
                        self.output_dir, _enrich_llm)
                    ds = load_valid_design_system(dsp)
                if ds is not None:
                    # FIX #80: deterministic completion floor — an analyst that skipped the
                    # per-component crop/eyedrop/asset mapping (model variance) must not ship a
                    # hollow doc; the framework crops+measures+maps what's missing itself.
                    ds = complete_design_system(ds, resolved, self.output_dir)
                    self._design_system = ds
                    self._logger.info(
                        "Design-Prep: design_system.json ready (%d screens, %d real assets) [%s]",
                        len(ds.get("screens") or []), len(ds.get("assets") or []),
                        "agent" if used_agent else "single-shot fallback")
                    # Fold the measured design system into the requirements every lane reads, so
                    # it drives the build from turn 1 (non-voluntary), mirroring the reference-spec
                    # summary. Stored + appended to the returned requirements below.
                    self._design_system_req_suffix = design_system_summary_for_requirements(ds)
            except Exception as dp_err:
                self._logger.warning("Design-Prep phase failed (continuing): %s", dp_err)
        return res.requirements + getattr(self, "_design_system_req_suffix", "")

    async def _spawn_design_analyst(self, resolved) -> bool:
        """Spawn the one-shot design_analyst agent to MEASURE each component and enrich
        design/design_system.json. Returns True iff it finished. Best-effort: no spawn_service, a
        spawn error, or a timeout → False (the caller uses the single-shot fallback)."""
        # NR1 (2026-07-21, AMENDED #252): the analyst is the ONLY producer of per-component
        # MEASURED design facts — the whole design-prep phase exists for it, and every lane's
        # visual fidelity depends on it. NR1 proposed default-OFF from runs on one model
        # (GPT-5.6 via the compat gateway, whose tool-call translation is independently known
        # broken — see utils/llm.py #249). On the validated Gemini path it converges in EVERY
        # observed run (r35 420s, r50 354s, r51 1419s — 3/3 "design_analyst finished", 0 timeouts).
        # A model-specific non-convergence must NOT become the global default: that silently
        # downgrades visual fidelity for every env. Default ON; turn OFF per-model/per-run with
        # ENVGEN_DESIGN_ANALYST=0 (which is the right knob for the GPT-5.6 path).
        if os.environ.get("ENVGEN_DESIGN_ANALYST", "1").strip().lower() in ("0", "false", "no", "off"):
            self._logger.info(
                "design_analyst subagent disabled via ENVGEN_DESIGN_ANALYST — using "
                "deterministic single-shot design prep (skeleton + enrich + completion floor)")
            return False
        spawn_service = getattr(self, "spawn_service", None)
        if spawn_service is None:
            return False
        from .agent_spawn_service import AgentSpawnRequest
        from .runtime.design_prep import build_design_analyst_briefing
        agent_id = "design_analyst_1"
        spawned = False
        try:
            briefing = build_design_analyst_briefing(self.output_dir, resolved)
            res = await spawn_service.spawn(AgentSpawnRequest(
                agent_id=agent_id, agent_type="design_analyst", config_key="design_analyst",
                task="Measure a design system from the references -> design_system.json",
                parent_id="orchestrator", role="design_analyst", resident=False,
                metadata={"description": briefing}))
            spawned = True
            ev = getattr(res, "task_done_event", None)
            if ev is None:
                return False
            # F1 (2026-07-21, AMENDED #252): F1 tightened this to 600s to bound a NON-converging
            # analyst. Correct intent, unsafe number: on the validated Gemini path the analyst
            # CONVERGES at 354s / 420s / 1419s (r50 / r35 / r51) — 600s would have killed r51's
            # analyst at 42% of its real work and silently fallen back, degrading every lane's
            # visual input with no error anywhere. A backstop must sit above the observed
            # converging maximum, not inside it. Keep 1800s (validated); the GPT-5.6 path can
            # set ENVGEN_DESIGN_ANALYST_TIMEOUT=600 (or ENVGEN_DESIGN_ANALYST=0) for its model.
            timeout = float(os.environ.get("ENVGEN_DESIGN_ANALYST_TIMEOUT", "1800"))
            await asyncio.wait_for(ev.wait(), timeout=timeout)
            self._logger.info("design_analyst finished — design_system.json enriched")
            return True
        except Exception as exc:
            self._logger.warning(
                "design_analyst agent unavailable/incomplete (%s) — single-shot fallback", exc)
            return False
        finally:
            if spawned:
                try:
                    await spawn_service.terminate(agent_id, wait=False)
                except Exception:
                    pass

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

    def _deliver_progress_sig(self):
        """The forward-PROGRESS signature the delivery stuck-abort keys on: app source
        content + contract (endpoint/table) versions + verification-chain registry version.
        It moves ONLY when a lane edits code or (re-)registers a contract/chain — i.e. real
        progress. Used both to detect a stuck (unchanged across cycles) AND to grant the
        abort-grace (changed since the abort latched → an in-flight remediation is landing).
        None on error (caller treats as 'no progress signal')."""
        try:
            rh = getattr(getattr(self, "hubs", None), "registryhub", None)
            _vc = getattr(rh, "_verification_chains", None) if rh is not None else None
            return (
                self._compute_app_source_signature(),
                tuple(sorted((rh.get_versions() or {}).items()))
                if (rh is not None and hasattr(rh, "get_versions")) else None,
                _vc.get_version() if (_vc is not None and hasattr(_vc, "get_version")) else 0,
            )
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

    def _run_test_user_validation(self, version: str) -> "dict | None":
        from .runtime.heal_pipeline import HealPipeline
        # Returns the browser test-user report (auth_ok/blank_pages/…) so the delivery
        # flow can use it as a PRE-RELEASE gate; None when it could not run.
        return HealPipeline(self).run_test_user_validation(version)

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
                # OBSERVABILITY (PROPOSAL #45): the deterministic deliver declined
                # SILENTLY for every non-ui_page blocker, so a run that "never
                # delivered" left NO on-disk signal of WHICH gate check was red —
                # forcing fragile post-mortem reconstruction (and mis-diagnosis:
                # smoke-notes 2026-06-19 was blocked on incomplete_required_tasks, a
                # contract-test param-key mismatch, but nothing logged it). Log the
                # failed-check set, deduped to once-per-CHANGE so it never spams the
                # ≤60s loop.
                _failed = sorted(str(c) for c in (gate.get("failed_checks") or []))
                if _failed != getattr(self, "_fwdeliver_last_failed", None):
                    self._fwdeliver_last_failed = _failed
                    self._logger.warning(
                        "Framework deliver declined: delivery gate has %d failed check(s): %s",
                        len(_failed), _failed,
                    )
                # FIX #120 (run-38): a STALE build:* failure checklist (transient
                # run_validation fail mid visual-churn, never re-recorded) must not
                # ride the no-convergence watchdog to an abort — deterministically
                # re-arm the framework's own api_smoke (bounded per milestone) so
                # fresh build:* truth gets recorded without depending on the verifier.
                try:
                    from .runtime.framework_validation import (
                        maybe_refresh_stale_build_checklist)
                    maybe_refresh_stale_build_checklist(self, _failed)
                except Exception:
                    pass
                # #475: business_chain_failing blocked ONLY by NEVER-RUN chains (verifier
                # re-authored a chain that hasn't been executed yet) → re-run the chains
                # deterministically (reset the api_smoke attempt counter) so run_chains
                # records their real status, instead of the verifier re-authoring (which
                # adds more unrun chains → the r50 churn: 14 deliver_project / 0 release).
                # No-ops when any chain is genuinely BROKEN — that stays a verifier fix.
                try:
                    from .runtime.framework_validation import maybe_rerun_unrun_chains
                    # #70(b) (netflix r76, 2026-08-05): CAPTURE whether a deterministic chain
                    # re-run was armed THIS tick. When armed, the remediation dispatcher SUPPRESSES
                    # the business_chain_failing verifier RE-AUTHOR dispatch for this tick — else the
                    # verifier authors MORE never-run chains while #475 is still re-running the
                    # existing batch, so run_chains never catches up (r76: converged 17→2 then
                    # business_chain went green→REGRESSED→restored with 11 never-run chains piling
                    # up, 0 delivery). Bounded: #475 caps at 4/milestone, so once spent this flag
                    # stays False and normal verifier dispatch resumes (a genuinely-broken chain,
                    # where #475 no-ops, also leaves it False → verifier IS dispatched to fix it).
                    self._chain_rerun_armed = bool(maybe_rerun_unrun_chains(self, _failed))
                except Exception:
                    self._chain_rerun_armed = False
                # #489 (netflix r61, task#47): delivery blocked on
                # deliverability_ui_flow_missing while the app is FULLY functional
                # (api_smoke green, 15/15 endpoints, frontend navigable) — the verifier
                # keeps FAILING to author the validation:ui_flow records (r61: 6+
                # dispatches over 11min, never cleared; r68/r91-93 same). The framework's
                # own authenticated browser walk auto-authors those records (#240,
                # heal_pipeline), but it only runs AFTER the gate clears → chicken-and-egg.
                # Run it pre-gate so the records get authored from a REAL passing walk and
                # the gate clears deterministically. PASS-ONLY (can't unblock a broken
                # app); app-up-gated; bounded per milestone. Generalizes to every app.
                try:
                    from .runtime.framework_validation import (
                        maybe_author_ui_flow_evidence)
                    await maybe_author_ui_flow_evidence(self, _failed)
                except Exception:
                    pass
                # #74 (netflix r78): database_sql_missing while the DB is functional (api_smoke
                # passed) — the deterministic app/database/ scaffold ran once post-kickoff and its
                # .sql didn't survive to the audited tree (no deliver-tail re-emit). Re-emit it
                # deterministically from the registered SchemaHub tables so the file-existence gate
                # clears without the flaky LLM backend lane (r78 wedged 11min on this). Guarded +
                # idempotent + never raises; no-ops when a .sql already exists.
                try:
                    from .runtime.framework_validation import maybe_emit_schema_sql
                    maybe_emit_schema_sql(self, _failed)
                except Exception:
                    pass
                # FORWARD-PROGRESS GUARANTEE for POST-api_smoke gate blockers (audit #2).
                # The deterministic stuck-abort ladder lives in the api_smoke-FAILING branch
                # of _maybe_run_framework_validation, so once api_smoke passes, a delivery-gate
                # blocker that api_smoke doesn't cover (business_chain_failing, ui_page_unwired)
                # loops UNCHANGED to the 6h wall — there was NO deterministic escape (run v12).
                # Track a stuck signature = (failed-check set, app source signature, registry +
                # verification-chain versions). It advances ONLY when ALL are unchanged — i.e.
                # the gate is still red AND no lane has edited code or (re-)registered any
                # contract/chain — so an actively-progressing run NEVER trips it. After
                # FWVAL_STUCK_ABORT_AFTER such cycles, set the run loop's FAIL-FAST signal
                # (_fwval_abort_reason, consumed at run()-loop) so a genuine wedge fails fast.
                _progress = self._deliver_progress_sig()
                _stuck_key = (tuple(_failed), _progress)
                if _progress is not None and _stuck_key == getattr(self, "_fwdeliver_stuck_key", None):
                    self._fwdeliver_stuck_count = getattr(self, "_fwdeliver_stuck_count", 0) + 1
                else:
                    self._fwdeliver_stuck_key = _stuck_key
                    self._fwdeliver_stuck_count = 1
                # #566b LAST-CHANCE RECONCILE before the fail-fast latch: if we are about to
                # abort with deliverability_ui_page_unwired among the blockers, first surface
                # any lane-committed-but-unmerged frontend page onto integration. If that copies
                # a real page it is genuine progress (r113: the real 390-line TitleDetailPage sat
                # in the lane worktree while integration held the projector stub, and the abort
                # fired ~1s after it finally merged) → reset the stuck counter so the abort does
                # NOT latch this cycle. Best-effort; no-op when there is no unmerged real page.
                if (self._fwdeliver_stuck_count >= FWVAL_STUCK_ABORT_AFTER
                        and not getattr(self, "_fwval_abort_reason", None)
                        and "deliverability_ui_page_unwired" in _failed):
                    try:
                        from pathlib import Path as _P
                        from .runtime.heal_pipeline import reconcile_integration_frontend_pages
                        _rc = reconcile_integration_frontend_pages(
                            _P(getattr(self, "output_dir", "") or "."), self._logger)
                    except Exception:
                        _rc = {}
                    if _rc.get("count"):
                        self._logger.warning(
                            "DELIVERY-GATE STUCK-ABORT deferred: reconciled %d lane frontend "
                            "page(s) onto integration — committed lane work had not merged; "
                            "treating as progress, not a wedge.", _rc.get("count"))
                        self._fwdeliver_stuck_count = 1
                        self._fwdeliver_stuck_key = None
                if (self._fwdeliver_stuck_count >= FWVAL_STUCK_ABORT_AFTER
                        and not getattr(self, "_fwval_abort_reason", None)):
                    # Diagnostics accuracy: this branch can latch even when api_smoke
                    # NEVER passed (the deliver gate is entered on route-code presence, not
                    # on a passing smoke). Hardcoding "after api_smoke passed" sent a whole
                    # review chasing a coordination wedge when the real fault was api_smoke
                    # failing on backend-port resolution. Reflect the actual smoke state.
                    _smoke_failed = "deliverability_no_successful_run" in _failed
                    _smoke_note = (
                        "WITHOUT any passing api_smoke run (deliverability_no_successful_run "
                        "is red — the app never validated end-to-end; inspect the api_smoke / "
                        "backend_port / RunHub failure, NOT the lanes)"
                        if _smoke_failed else "after api_smoke passed")
                    self._fwval_abort_reason = (
                        f"delivery gate stuck on {_failed} for {self._fwdeliver_stuck_count} "
                        f"consecutive cycles with NO source/contract/chain change {_smoke_note} "
                        "— no lane is making progress; failing fast instead of spinning to "
                        "wall-clock.")
                    # ABORT-GRACE bookkeeping: tag this as a DELIVER-stuck abort (so the
                    # run-loop consumption can distinguish it from a framework-validation /
                    # Site A abort) and STAMP the progress signature at latch time, so a
                    # remediation landing before consumption (e.g. a just-registered chain)
                    # is detected as progress and granted one cycle to run_validation.
                    # The deliver-reason IDENTITY (not a stale boolean) is what the consume
                    # site grace-gates on, so a later Site A / no-converge abort that
                    # overwrites _fwval_abort_reason is never wrongly deferred.
                    self._fwval_abort_deliver_reason = self._fwval_abort_reason
                    self._fwval_abort_progress_sig = _progress
                    self._logger.error("DELIVERY-GATE STUCK-ABORT: %s", self._fwval_abort_reason)
                # CONVERGENCE backstop (run v18): the exact-stuck check above resets on ANY
                # churn, so an ACTIVE-but-oscillating run (gates cycle, agents keep editing,
                # nothing ever fully clears) never trips it and livelocks toward the 6h wall.
                # Stamp the first decline; if delivery hasn't succeeded within
                # FWVAL_NO_DELIVER_ABORT_S of it, fail fast — the contract is built but the
                # lanes are not converging on a clean gate.
                _now2 = time.time()
                if not getattr(self, "_fwdeliver_first_decline_ts", 0.0):
                    self._fwdeliver_first_decline_ts = _now2
                # #228: track when the failing set last SHRANK (a strict subset
                # of the previous tick's) — visible convergence, not livelock.
                _cur_failed_set = set(map(str, _failed or []))
                _prev_failed_set = getattr(self, "_fwdeliver_prev_failed", None)
                if (_prev_failed_set and _cur_failed_set
                        and _cur_failed_set < _prev_failed_set):
                    self._fwdeliver_last_shrink_ts = _now2
                if _cur_failed_set:
                    self._fwdeliver_prev_failed = _cur_failed_set
                if ((_now2 - self._fwdeliver_first_decline_ts) > FWVAL_NO_DELIVER_ABORT_S
                        and not getattr(self, "_fwval_abort_reason", None)):
                    # #228 (r20: the verifier cleared the LAST gate 36s after the
                    # abort fired): a small, recently-shrinking failing set gets a
                    # bounded grace extension instead of the axe.
                    from .runtime.delivery_gate import convergence_grace
                    _shrink_ts = getattr(self, "_fwdeliver_last_shrink_ts", 0.0)
                    _grace = convergence_grace(
                        failed_count=len(_cur_failed_set),
                        last_shrink_age_s=(_now2 - _shrink_ts) if _shrink_ts else 1e9,
                        grace_used=getattr(self, "_fwdeliver_grace_count", 0))
                    if _grace > 0:
                        self._fwdeliver_grace_count = getattr(
                            self, "_fwdeliver_grace_count", 0) + 1
                        self._fwdeliver_first_decline_ts += _grace
                        self._logger.warning(
                            "DELIVERY-GATE CONVERGING-GRACE #%d: failing set is small "
                            "and recently shrank (%s) — extending the no-convergence "
                            "deadline by %ds instead of aborting.",
                            self._fwdeliver_grace_count, sorted(_cur_failed_set),
                            int(_grace))
                    else:
                        self._fwval_abort_reason = (
                            f"delivery gate has not gone green in "
                            f"{int((_now2 - self._fwdeliver_first_decline_ts)/60)}min since the "
                            f"contract built (now failing {_failed}) — the lanes are active but "
                            "not converging on a clean gate; failing fast instead of livelocking "
                            "to wall-clock.")
                        self._logger.error("DELIVERY-GATE NO-CONVERGENCE ABORT: %s", self._fwval_abort_reason)
                # PROPOSAL #49 (user): route each lane-owned gate-level failed_check back
                # to its owner for repair (guarded per-milestone) — and log any uncovered
                # one — so a gate blocker never silently dead-ends. Complements the bespoke
                # ui_page_unwired dispatch below + the validation-run #21 dispatch.
                try:
                    from .runtime.remediation_dispatcher import RemediationDispatcher
                    await RemediationDispatcher(self).dispatch_gate_level_checks(
                        gate.get("failed_checks"))
                except Exception as _gc_exc:
                    self._logger.error("gate-level check dispatch failed: %s", _gc_exc)
                # FEEDBACK LOOP (2026-06-13): an unwired-ui-pages block (declared
                # pages whose routes aren't in App.jsx) HARD-blocks delivery but,
                # unlike GATE-C1 / frontend_navigable / visual, routed NOWHERE —
                # frontend_navigable passes on >=1 route so its dispatch goes quiet
                # while delivery needs ALL declared pages wired. Route the specific
                # unwired pages back to the frontend lane (it owns the UI) so the
                # run can't deadlock with one route wired (gemini: 12 unwired,
                # delivery stuck for hours with no path back to the owner).
                # PROPOSAL #51 (a): the unwired-pages dispatch is ONE-SHOT per milestone,
                # and the validation-tied rearm (rearm_owner_dispatch) STOPS once api_smoke
                # passes — but ui_page_unwired is a DELIVERY-gate check evaluated AFTER that,
                # so a frontend that finished with stubs is never re-engaged (smoke-notes
                # 2026-06-19: 1 dispatch, lane misread it + idled, stuck to cap). Periodically
                # re-arm so the (sharper, #51b) dispatch re-fires + re-wakes the idle lane
                # while the stubs persist. ~every 8 declines (≈8 min); the dispatch is
                # idempotent within each re-arm window.
                _uw = any("ui_page_unwired" in str(c) for c in gate.get("failed_checks") or [])
                if _uw:
                    _n = getattr(self, "_unwired_persist_count", 0) + 1
                    self._unwired_persist_count = _n
                    if _n % 8 == 0:
                        self._unwired_ui_pages_dispatched = None  # re-arm the one-shot guard
                else:
                    self._unwired_persist_count = 0
                if _uw:
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
            # PAGE-BUILD BLOCKING (2026-06-22, user goal: the UI must be the REAL
            # reference pages, not the framework fallback). A declared business
            # ui_page the lane never authored ships as the framework FALLBACK
            # (data-fallback marker) — it is wired + functional so it passes
            # ui_page_unwired / frontend_navigable / the whole delivery gate above,
            # but it is NOT the real page (outlook: the inbox/calendar shipped as the
            # generic placeholder list even though the lane viewed the references).
            # When attempts remain, DEFER the final milestone's release and
            # re-dispatch the frontend lane to BUILD the fallback pages (it now views
            # the references + has write in edit_code). Bounded: <=3 attempts / 900s
            # anchored to the FIRST defer, then ESCAPE and ship the (usable light-list)
            # fallback — bounded for non-referenced pages (mirrors the visual deferral), but
            # a REFERENCE-depicted page never escapes (pages_release_decision) per the user
            # requirement that every page resemble the real design. DEFAULT-ON now (the
            # pipeline delivers multi-milestone e2e — seed3); set ENVGEN_PAGES_BLOCKING=0 to
            # disable (e.g. a no-reference env where the card fallback is acceptable).
            if (os.environ.get("ENVGEN_PAGES_BLOCKING", "1").lower()
                    in ("1", "true", "yes", "on")
                    and getattr(self, "_is_final_milestone", True)):
                _unbuilt: List[str] = []
                _ref_unbuilt: List[str] = []
                try:
                    from .runtime.page_build_gate import (
                        frontend_unbuilt_pages, pages_release_decision,
                        referenced_unbuilt_pages)
                    _app_root = self.output_dir / "app"
                    if not _app_root.exists():
                        _app_root = self.output_dir
                    _rh = getattr(self.hubs, "registryhub", None)
                    _unbuilt = frontend_unbuilt_pages(_rh, _app_root)
                    # §2 gate-hardening: which unbuilt pages do the REFERENCE images depict?
                    # Those must ship as the REAL page, not the fallback — block harder on them.
                    if _unbuilt and getattr(self, "_reference_images", None):
                        try:
                            from .runtime.visual_fidelity import (
                                load_screen_classifications, map_reference_screens)
                            _known_routes = set()
                            for _pg in (_rh.list_ui_pages() or {}).values() if _rh else []:
                                if isinstance(_pg, dict) and _pg.get("route"):
                                    _known_routes.add(str(_pg["route"]))
                            _ref_routes = {str(s.get("route")) for s in map_reference_screens(
                                list(self._reference_images), _known_routes,
                                classifications=load_screen_classifications(self.output_dir),
                            ) if s.get("route")}  # FIX #132: authoritative mapping wins
                            _ref_unbuilt = referenced_unbuilt_pages(_rh, _app_root, _ref_routes)
                        except Exception as _ru_exc:
                            self._logger.debug("referenced-unbuilt detect skipped: %s", _ru_exc)
                except Exception as _pb_exc:
                    self._logger.error("page-build gate detect failed: %s", _pb_exc)
                    _unbuilt = []
                if _unbuilt:
                    if getattr(self, "_pages_gate_deferred_since", None) is None:
                        self._pages_gate_deferred_since = time.time()
                    _now = time.time()
                    _pb_decision = pages_release_decision(
                        self._pages_gate_deferred_since,
                        getattr(self, "_pages_gate_attempts", 0),
                        _now,
                        has_referenced_unbuilt=bool(_ref_unbuilt),
                    )
                    if _pb_decision == "defer":
                        self._pages_gate_attempts = getattr(
                            self, "_pages_gate_attempts", 0) + 1
                        self._logger.warning(
                            "DELIVERY DEFERRED: %d business page(s) are still the "
                            "framework fallback (attempt %s/3, %ss deferred) — "
                            "re-dispatching the frontend lane to BUILD them: %s",
                            len(_unbuilt), self._pages_gate_attempts,
                            int(_now - self._pages_gate_deferred_since),
                            ", ".join(_unbuilt))
                        try:
                            await self._dispatch_unbuilt_pages(_unbuilt)
                        except Exception as _pb_d_exc:
                            self._logger.error(
                                "unbuilt-pages dispatch failed: %s", _pb_d_exc)
                        return
                    # release: escape fired — deliver with the fallback, loudly.
                    self._logger.warning(
                        "Page-build deferral RELEASED (escape after %ss / %s attempts) "
                        "— delivering with the framework fallback for: %s",
                        int(_now - self._pages_gate_deferred_since),
                        getattr(self, "_pages_gate_attempts", 0), ", ".join(_unbuilt))
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
                    and not self._vf_gate.passed
                    # #521: STICKY escape — once the deferral has escaped (below-threshold
                    # delivery earned), do NOT re-enter the defer/re-judge block. Without
                    # this a post-escape >0.02 per-screen improvement resets plateau_rounds,
                    # so the next delivery poll re-defers and delivery only finalizes at the
                    # 3600s wall-clock (r91/r92: 44/88 deliver_project narrations, ~75min
                    # deliver-tail). The recorded below-threshold verdict already reflects
                    # the delivered source; keep it and let delivery proceed.
                    and not getattr(self._vf_gate, "released", False)):
                if self._vf_gate.deferred_since is None:
                    self._vf_gate.deferred_since = time.time()  # anchor: milestone's FIRST defer
                _now = time.time()
                _vf_decision = _visual_release_decision(
                    self._vf_gate.deferred_since,
                    self._vf_gate.attempts,
                    self._vf_gate.total_judgments,
                    _now,
                    plateau_rounds=getattr(self._vf_gate, "plateau_rounds", 0),
                    last_judgment_at=getattr(self._vf_gate, "last_judgment_at", None),
                    **_visual_fast_release_args(self._vf_gate),
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
                    # the escape_s wall-clock (2400s dflt, #112) ANCHORED to the first defer (no longer reset
                    # by lane churn — PIPE-C3), the per-source attempt cap, or the
                    # per-milestone total-judgment cap.
                    await self._maybe_run_visual_fidelity()
                    return
                if _vf_decision == "fast_release":
                    # FIX #558: the gating blocking_average has cleared the min bar for N
                    # consecutive judged rounds and the blocking exam is complete — cut the
                    # SAME below-threshold-per-screen release the wall-clock escape would
                    # grant, but ~40-60 min and ~40 re-judgements sooner. No final re-judge
                    # (the avg is already 2-round STABLE — post-#548 captures are
                    # deterministic, so another judge call buys nothing but tokens). Latch
                    # #521-sticky so subsequent delivery polls skip the defer block, then
                    # fall through to squad/deliver exactly like the escape path.
                    _fra = _visual_fast_release_args(self._vf_gate)
                    self._vf_gate.released = True  # #521: sticky release latch
                    self._logger.warning(
                        "VISUAL FAST-RELEASE: blocking_average %.2f ≥ min %.2f over %s "
                        "stable rounds — releasing without the wall-clock grind (#558; "
                        "%ss deferred, %s judged; #521 latched sticky).",
                        float(_fra["blocking_average"] or 0.0),
                        float(_fra["avg_min"] or 0.0),
                        _fra["avg_stable_rounds"],
                        int(_now - self._vf_gate.deferred_since),
                        self._vf_gate.total_judgments)
                else:
                    # FIX #102 (run-20, live): the escape often fires SECONDS after the lane
                    # lands its fix — run-20's release verdict came from a 23:45 capture of
                    # PRE-fix source (broken icon refs) while the delivered image serves all
                    # 47 icons with 200. Drive ONE final fresh capture+judge before releasing;
                    # _maybe_run_visual_fidelity self-guards (pass latch + per-source attempt
                    # cap), so this re-judges ONLY when the source actually changed since the
                    # stale verdict — the recorded score then reflects the DELIVERED source.
                    await self._maybe_run_visual_fidelity()
                    if self._vf_gate.passed:
                        self._logger.warning(
                            "Visual fidelity PASSED on the final pre-release re-judge "
                            "(fresh capture of the delivered source).")
                    else:
                        # release: an escape fired — deliver anyway, loudly, below-threshold.
                        _plat = getattr(self._vf_gate, "plateau_rounds", 0)
                        self._vf_gate.released = True  # #521: LATCH — this milestone's release
                        #                                is now sticky; subsequent delivery polls
                        #                                skip the defer block (no re-defer loop).
                        self._logger.warning(
                            "Visual fidelity deferral RELEASED (escape after %ss deferred / "
                            "%s attempts / %s total judged%s) — delivering anyway "
                            "(recorded as below-threshold; #521 latched sticky).",
                            int(_now - self._vf_gate.deferred_since),
                            self._vf_gate.attempts,
                            self._vf_gate.total_judgments,
                            (" / PLATEAU %s no-improvement rounds — #138 early escape"
                             % _plat) if _plat >= VISUAL_PLATEAU_ROUNDS else "")
            # TEST-USER SQUAD BLOCKING GATE (§3.5, 2026-06-22): the verify->fix loop the
            # user's flow diagram puts INSIDE each milestone. The app is up (api_smoke
            # booted it; the visual gate just shot it), so spawn the three modality
            # test-user agents (api/mcp/browser) to drive it as real users and file P0
            # defects via bug_create (-> debugger -> owning lane). While open P0s remain
            # and attempts/wall-clock are not exhausted, DEFER the release (return) so the
            # fixes land before this milestone ships; then escape (never deadlock), loudly.
            # #179: default-ON (validated live on gmrun13 — spawned 9 agents, filed real
            # defects); disable with ENVGEN_TESTUSER_SQUAD=0.
            from .runtime.test_user_squad import squad_gate_enabled
            if (squad_gate_enabled(os.environ)
                    and not getattr(self, "_tu_squad_passed", False)):
                from .runtime.test_user_squad import (
                    run_squad_for_delivery, squad_release_decision, squad_gate_outcome,
                    squad_gate_tick_action)
                _now = time.time()
                if getattr(self, "_tu_squad_deferred_since", None) is None:
                    self._tu_squad_deferred_since = _now
                _tu_decision = squad_release_decision(
                    self._tu_squad_deferred_since,
                    getattr(self, "_tu_squad_attempts", 0), _now)
                if _tu_decision == "defer":
                    # #532: run the squad in the BACKGROUND (single-flight) — NEVER inline.
                    # The squad is ~42min of work (12 browser agents in 3 sequential waves);
                    # awaiting it here wedged the whole coordination loop so create_release
                    # was never reached and the run never delivered (this was THE delivery
                    # blocker). Instead spawn ONE background task and defer this tick — the
                    # loop stays live (re-ticks every ~60s, keeps driving lanes) while the
                    # squad tests, and squad_release_decision's wall-clock (900s, evaluated
                    # ABOVE) still preempts to RELEASE even if the squad is still running.
                    # Decide launch-vs-defer-vs-consume from the single task handle:
                    _tu_task = getattr(self, "_tu_squad_task", None)
                    _tu_action = squad_gate_tick_action(
                        task_exists=_tu_task is not None,
                        task_done=bool(_tu_task is not None and _tu_task.done()))
                    if _tu_action == "launch":
                        # SINGLE-FLIGHT: exactly one background squad run, then defer.
                        self._tu_squad_task = asyncio.create_task(
                            run_squad_for_delivery(
                                self, getattr(self, "_current_milestone_version", "1.0.0")))
                        self._logger.warning(
                            "TEST-USER SQUAD launched in BACKGROUND (single-flight, %ss "
                            "deferred) — deferring this delivery tick; the coordination loop "
                            "keeps running while it tests.",
                            int(_now - self._tu_squad_deferred_since))
                        return  # defer this tick; do NOT await the squad inline
                    if _tu_action == "defer":
                        # A squad run is in flight but not finished → defer WITHOUT spawning a
                        # second (single-flight) and WITHOUT awaiting it inline; re-check
                        # task.done() next tick. The loop stays live meanwhile.
                        return
                    # 'consume': the background squad finished → read its result exactly ONCE,
                    # clear the handle (so it is never re-read and a later 'launch' re-arms it
                    # after the fix lands), then run the SAME pass/retry/defect handling as the
                    # original inline gate.
                    try:
                        _tu_result = self._tu_squad_task.result()
                    except Exception as _tu_exc:  # includes a cancelled/failed background task
                        self._logger.debug("test-user squad gate run failed: %s", _tu_exc)
                        _tu_result = {"ran": False}
                    finally:
                        self._tu_squad_task = None  # consumed — single-flight may re-arm
                    _p0 = int((_tu_result.get("bugs") or {}).get("p0", 0))
                    _tu_outcome = squad_gate_outcome(ran=bool(_tu_result.get("ran")), p0=_p0)
                    if _tu_outcome == "pass":
                        self._tu_squad_passed = True  # clean -> fall through to release
                    elif _tu_outcome == "retry":
                        # #179: the squad couldn't run yet (app ports not resolved / empty
                        # contract) — defer WITHOUT burning an attempt so flaky first-attempt
                        # port timing can't erode the escape budget; wall-clock is the backstop.
                        self._logger.info(
                            "test-user squad not ready (%s) — deferring without burning an "
                            "attempt", _tu_result.get("reason"))
                        return
                    else:  # 'defect' — squad ran and filed P0s: burn an attempt and defer
                        self._tu_squad_attempts = getattr(self, "_tu_squad_attempts", 0) + 1
                        self._logger.warning(
                            "DELIVERY DEFERRED: test-user squad found %d P0 defect(s) "
                            "(attempt %s, %ss deferred) — filed to the debugger/owning lane; "
                            "re-testing after the fix lands. modalities=%s", _p0,
                            self._tu_squad_attempts, int(_now - self._tu_squad_deferred_since),
                            _tu_result.get("modalities"))
                        return  # block this milestone's release until the defects clear
                else:
                    # squad_release_decision escape fired (wall-clock 900s / attempt cap) →
                    # RELEASE regardless of the background task's state. Cancel any in-flight
                    # squad (findings are advisory once we've decided to ship) and drop the
                    # handle so it can't be re-read; the release then proceeds this tick.
                    _tu_task = getattr(self, "_tu_squad_task", None)
                    if _tu_task is not None and not _tu_task.done():
                        _tu_task.cancel()
                    self._tu_squad_task = None
                    self._logger.warning(
                        "Test-user squad gate RELEASED (escape after %ss / %s attempts) — "
                        "delivering with possibly-open test-user defects.",
                        int(_now - self._tu_squad_deferred_since),
                        getattr(self, "_tu_squad_attempts", 0))
            # DETERMINISTIC BROWSER TEST-USER GATE (2026-06-30): a reliable, objective
            # complement to the LLM squad above. Drive a real browser through the RUNNING app
            # (booted by api_smoke) and HOLD the release when the app is objectively UNUSABLE:
            # login broken (auth_ok False), protected pages rendering BLANK, or bounced to a
            # login wall (auth_redirect/hollow). These are deterministic signals the advisory
            # post-release walk already computes; here they GATE the cut so a non-functional UI
            # never ships as "delivered" (the user's "test-user反馈问题 / 没有 mock frontend"
            # bar). Blocks ONLY on the objective unusable-app subset — visual mismatches and
            # console errors stay ADVISORY (still dispatched as P0 inside the walk, never
            # block). Mirrors the bounded-deferral pattern (defer→re-test→escape) so it can
            # NEVER deadlock: after the attempt cap / wall-clock anchored to the first defer,
            # deliver anyway, loudly. Env-gated (default-ON — the escape makes on-by-default
            # deadlock-proof; set ENVGEN_TESTUSER_BROWSER_GATE=0 to disable). Skips cleanly
            # (never blocks) if the walk could not run — app unreachable / Playwright absent /
            # a one-off flake auto-clears on the next cycle's re-test.
            if (os.environ.get("ENVGEN_TESTUSER_BROWSER_GATE", "1").strip().lower()
                    not in ("0", "false", "no", "off")):
                _bg_report = None
                try:
                    import asyncio as _bg_asyncio
                    _bg_report = await _bg_asyncio.to_thread(
                        self._run_test_user_validation,
                        getattr(self, "_current_milestone_version", "1.0.0"))
                except Exception as _bg_exc:
                    self._logger.debug("pre-release browser test-user gate skipped: %s", _bg_exc)
                # Block ONLY when the walk actually RAN and found an objective unusable-app
                # signal ("a real user cannot use this app"). A None/could-not-run report
                # falls through (infra never blocks delivery). Pure predicate — unit-tested.
                from .runtime.test_user_runner import browser_report_unusable
                _bg_unusable = browser_report_unusable(_bg_report)
                if _bg_unusable:
                    # Bounded deferral (same escape as the squad/visual gates — a generic
                    # attempt-cap + wall-clock decision, never deadlocks): keep deferring
                    # while the fix lands, then escape and ship loudly.
                    from .runtime.test_user_squad import squad_release_decision
                    from .runtime.test_user_runner import browser_gate_decision
                    _bg_now = time.time()
                    if getattr(self, "_tu_browser_deferred_since", None) is None:
                        self._tu_browser_deferred_since = _bg_now
                    _bg_decision = squad_release_decision(
                        self._tu_browser_deferred_since,
                        getattr(self, "_tu_browser_attempts", 0), _bg_now)
                    # FIX #152: a HARD-unusable app (login broken / login-wall hollow) NEVER
                    # escape-releases — the bounded escape only applies to SOFT defects. A
                    # release nobody can log into is worthless; hold to FAIL-FAST instead of
                    # shipping a dead app (run-4: 401'd every core page yet escaped after
                    # 7 attempts). ENVGEN_TESTUSER_HARD_GATE=0 disables.
                    _bg_decision = browser_gate_decision(_bg_report, _bg_decision)
                    self._tu_browser_attempts = getattr(self, "_tu_browser_attempts", 0) + 1
                    if _bg_decision == "defer":
                        self._logger.warning(
                            "DELIVERY DEFERRED: browser test-user found the app UNUSABLE "
                            "(auth_ok=%s blank=%s login_wall=%s hollow=%s no_real_data=%s "
                            "fake_map=%s) — P0 dispatched to the frontend; re-testing after the "
                            "fix lands (attempt %s, %ss deferred). Set "
                            "ENVGEN_TESTUSER_BROWSER_GATE=0 to disable.",
                            _bg_report.get("auth_ok"), _bg_report.get("blank_pages"),
                            _bg_report.get("auth_redirect_pages"), _bg_report.get("hollow_frontend"),
                            _bg_report.get("no_real_data"), _bg_report.get("fake_map_pages"),
                            self._tu_browser_attempts,
                            int(_bg_now - self._tu_browser_deferred_since))
                        return  # hold this milestone's release until the UI is usable
                    self._logger.warning(
                        "Browser test-user gate RELEASED (escape after %ss deferred / %s "
                        "attempts) — delivering with a possibly-unusable UI, loudly.",
                        int(_bg_now - self._tu_browser_deferred_since), self._tu_browser_attempts)
                elif isinstance(_bg_report, dict) and _bg_report.get("ran"):
                    # Walk ran and the app is USABLE → clear the per-episode deferral budget
                    # so a later milestone starts with a fresh attempt/wall-clock allowance.
                    self._tu_browser_deferred_since = None
                    self._tu_browser_attempts = 0
            # SOFT CONTRACT ROUTE-CONSISTENCY GATE (#180, 2026-07-16): run-13 aborted (80min
            # no-convergence) because the contract registered ONE endpoint at version-variant
            # duplicate paths (GET /api/directions + GET /api/v1/directions); the lane
            # implemented one and left the other a projected empty stub the frontend called,
            # and #173's "query the table" remediation can't fix a path mismatch. Detect the
            # duplication and route the CORRECT "consolidate to one path" remediation to the
            # backend lane. SOFT: bounded defer→escape (mirrors the browser gate) so it NEVER
            # hard-aborts — a residual duplicate escapes-with-warning, never deadlocks.
            # ENVGEN_ROUTE_CONSISTENCY_GATE=0 disables.
            if (os.environ.get("ENVGEN_ROUTE_CONSISTENCY_GATE", "1").strip().lower()
                    not in ("0", "false", "no", "off")):
                _rc_dups = []
                try:
                    from .runtime.contract_drift import version_variant_duplicate_routes
                    _rh = getattr(self.hubs, "registryhub", None)
                    if _rh is not None:
                        _rc_dups = version_variant_duplicate_routes(_rh.get_endpoints())
                except Exception as _rc_exc:
                    self._logger.debug("route-consistency gate skipped: %s", _rc_exc)
                if _rc_dups:
                    try:
                        from .runtime.remediation_dispatcher import RemediationDispatcher
                        await RemediationDispatcher(self).dispatch_route_consolidation(_rc_dups)
                    except Exception as _rc_dexc:
                        self._logger.debug("route-consolidation dispatch skipped: %s", _rc_dexc)
                    from .runtime.test_user_squad import squad_release_decision
                    _rc_now = time.time()
                    if getattr(self, "_rc_deferred_since", None) is None:
                        self._rc_deferred_since = _rc_now
                    _rc_decision = squad_release_decision(
                        self._rc_deferred_since, getattr(self, "_rc_attempts", 0), _rc_now)
                    self._rc_attempts = getattr(self, "_rc_attempts", 0) + 1
                    if _rc_decision == "defer":
                        self._logger.warning(
                            "DELIVERY DEFERRED: contract has %d version-variant DUPLICATE "
                            "route(s) %s — consolidate remediation dispatched to backend; "
                            "re-checking after the fix lands (attempt %s, %ss deferred). SOFT: "
                            "escapes after the cap. Set ENVGEN_ROUTE_CONSISTENCY_GATE=0 to "
                            "disable.", len(_rc_dups), [d.get("paths") for d in _rc_dups],
                            self._rc_attempts, int(_rc_now - self._rc_deferred_since))
                        return  # hold this milestone's release until the routes consolidate
                    self._logger.warning(
                        "Route-consistency gate RELEASED (escape after %ss deferred / %s "
                        "attempts) — delivering with version-variant duplicate route(s), loudly.",
                        int(_rc_now - self._rc_deferred_since), self._rc_attempts)
                else:
                    self._rc_deferred_since = None
                    self._rc_attempts = 0
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
            # FIX #155 (§6-2, gmrun3 cold-start-crash class): the merge above imports
            # any LATE lane commit into the release tree AFTER every gate check ran —
            # gmrun3's broken custom_routes middleware landed 2min before the cut and
            # shipped unvalidated (delivered archive 500s on every request). If the
            # committed backend differs from what the last passing api_smoke
            # validated, run ONE fresh smoke on the exact release tree and HOLD the
            # cut on failure (the recorded failing run drives remediation; a lane fix
            # re-arms). Best-effort inside the helper; ENVGEN_FRESH_SMOKE_GATE=0 off.
            try:
                from .runtime.framework_validation import ensure_fresh_smoke_before_cut
                if not await ensure_fresh_smoke_before_cut(self):
                    return  # held: post-smoke backend drift failed the fresh smoke
            except Exception as _fs_exc:
                self._logger.debug("fresh-smoke-before-cut skipped: %s", _fs_exc)
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
            # Framework-written preview pointer for the Env Forge UI (NOT an agent
            # artifact — see _write_preview_config). Deterministic, agent-invisible.
            self._write_preview_config(release_tag)
            # Post-milestone TEST-USER phase: simulate a real user's journey across the
            # API + check the MCP surface, writing a feedback report so a milestone never
            # ships a broken contract silently. Offloaded to a thread (blocking HTTP +
            # subprocess); best-effort, never blocks/raises into delivery.
            try:
                import asyncio as _asyncio
                await _asyncio.to_thread(self._run_test_user_validation, release_tag)
            except Exception as _tu_err:
                self._logger.debug("test-user phase dispatch failed: %s", _tu_err)
            # NOTE: the multi-agent TEST-USER SQUAD now runs as a BLOCKING PRE-RELEASE gate
            # ABOVE (before create_release), not here — its bug_create defects gate the
            # milestone that produced them (the verify->fix loop). The deterministic
            # _run_test_user_validation above stays as the post-release safety net.
            self._project_delivered = True
            # FIX #139: stamp the moment the milestone gate evaluated CLEAR — the
            # post-loop FINAL gate re-reads MUTABLE hub state and a lane touching the
            # chain registry during the delivery tail (run-61: a re-registered chain
            # is status='registered', never-run -> business_chain_failing) can kill a
            # fully-delivered run seconds after this verdict. The final gate honors
            # this stamp for registry-state-class failures within a short window.
            self._milestone_gate_cleared_at = time.time()
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

    def _write_preview_config(self, release_tag: str) -> None:
        """Write the Env Forge UI's preview pointer at ``<output_dir>/config.yaml``.

        This is FRAMEWORK metadata for the frontend preview panel only — NOT part of
        the generated app and NOT an agent surface. It is written via a raw
        ``Path.write_text`` at the integration root (outside every agent worktree),
        so no lane routes through it: agents cannot read, write, or clobber it. The
        UI reads it via ``app/hub_reader.py:_preview_url``. Best-effort: never raises
        into the delivery path. (The released app must be running at ``ui_port`` for
        the iframe to render — keeping the stack up is a separate concern.)"""
        try:
            ui_port = getattr(self.context, "ui_port", None)
            if not ui_port:
                return
            url = f"http://localhost:{ui_port}/"
            (self.output_dir / "config.yaml").write_text(
                "# AUTO-GENERATED by the framework for the Env Forge preview panel.\n"
                "# Not part of the generated app; not an agent-editable file.\n"
                f"preview_url: {url}\n"
                f"frontend:\n  preview_url: {url}\n  host_port: {ui_port}\n"
                f"release_tag: {release_tag}\n",
                encoding="utf-8",
            )
        except Exception as _cfg_err:
            self._logger.debug("preview config write failed (non-fatal): %s", _cfg_err)

    def _incomplete_required_tasks(self) -> List[Dict[str, Any]]:
        from .runtime.delivery_gate import incomplete_required_tasks
        return incomplete_required_tasks(self.hubs)
    def _noncanonical_business_response_keys(self) -> List[Dict[str, Any]]:
        from .runtime.delivery_gate import noncanonical_business_response_keys
        return noncanonical_business_response_keys(self.hubs)
    def _validate_delivery_gate(self) -> Dict[str, Any]:
        from .runtime.delivery_gate import validate_delivery_gate
        import logging as _lg
        # §4 (env-gated, default-off): on an INTERMEDIATE milestone, scope the structural-task
        # gate to THIS milestone's declared endpoints so it isn't blocked on later-milestone
        # surface. Default-off ⇒ milestone_scope=None ⇒ full-app gate (byte-identical). Empty
        # parsed scope also falls back to full-app (never gates on an empty set).
        _scope = None
        if (os.environ.get("ENVGEN_MILESTONE_SCOPED_GATE", "0").lower() in ("1", "true", "yes", "on")
                and not getattr(self, "_is_final_milestone", True)):
            _ms = getattr(self, "_current_milestone", None) or {}
            _slice = str(_ms.get("description_slice") or "")
            _paths = re.findall(r"(?:GET|POST|PUT|PATCH|DELETE)\s+(/\S+)", _slice) \
                or re.findall(r"(/api/[A-Za-z0-9_./{}:-]+)", _slice)
            if _paths:
                _scope = {"endpoint_paths": sorted(set(_paths))}
        return validate_delivery_gate(
            self.output_dir, self.hubs,
            getattr(self, "_session_start_ts", 0.0),
            getattr(self, "_logger", None) or _lg.getLogger("DeliveryGate"),
            scaffold_design_readme=self._scaffold_design_readme,
            get_validation_results=self._get_validation_results,
            get_validation_summary=self._get_validation_summary,
            milestone_scope=_scope)
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
