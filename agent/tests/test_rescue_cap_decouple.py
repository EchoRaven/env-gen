"""PIPE-C2 / PIPE-C3 — decouple "stop churning" from "stop trying".

The deterministic-rescue loops are attempt-capped to stop docker/vision churn,
but the caps used to HARD-STOP and reset on "did the source change":

  * PIPE-C2: a sig-stable app failing on a transient ENVIRONMENTAL hiccup (docker
    contention / build-under-load) hit the 6-attempt cap and never recorded the
    RunHub run the delivery gate requires → silent budget death, 0 release.
  * PIPE-C3: a frontend lane churning files on each visual-fail flipped the source
    signature, which reset the 900s deferral clock AND the attempt budget every
    tick → neither escape was ever reached → delivery deferred until the run's
    budget died (livelock).

Fix = decouple: cap the FAST retries (anti-churn) but DOWNSHIFT to a slow retry
instead of hard-stopping (PIPE-C2), and ANCHOR the visual deferral wall-clock to
the milestone's first defer so lane churn can't rewind it, with a per-milestone
total-judgment backstop (PIPE-C3). The decisions are pure predicates so the state
machine is tested without the docker/vision machinery.
"""

from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.orchestrator import (  # noqa: E402
    Orchestrator, _fwval_should_attempt, _visual_release_decision,
    _fwval_failure_set, _fwval_stuck_decision,
    FWVAL_FAST_CAP, FWVAL_SLOW_INTERVAL_S, FWVAL_STUCK_REDISPATCH_AFTER,
    FWVAL_STUCK_TERMINAL_AFTER, VISUAL_DEFERRAL_ESCAPE_S,
    VISUAL_TOTAL_JUDGMENTS_CAP)


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        asyncio.set_event_loop(None)
        loop.close()


# ── PIPE-C2: _fwval_should_attempt (fast cap → slow retry, never hard-stop) ───

def test_fast_phase_runs_every_tick_below_cap():
    for a in range(FWVAL_FAST_CAP):
        assert _fwval_should_attempt(a, last_attempt_ts=0.0, now=10_000) is True


def test_capped_within_slow_interval_skips():
    # at the cap, just attempted → don't churn docker this tick
    assert _fwval_should_attempt(FWVAL_FAST_CAP, last_attempt_ts=10_000,
                                 now=10_000 + FWVAL_SLOW_INTERVAL_S - 1) is False


def test_capped_after_slow_interval_retries_not_dead():
    # THE PIPE-C2 FIX: past the cap it is NOT a permanent stop — after the slow
    # interval one retry fires, so a transient env failure eventually records the run.
    assert _fwval_should_attempt(FWVAL_FAST_CAP, last_attempt_ts=10_000,
                                 now=10_000 + FWVAL_SLOW_INTERVAL_S) is True
    # and it keeps slow-retrying indefinitely (never silently dies)
    assert _fwval_should_attempt(99, last_attempt_ts=10_000,
                                 now=10_000 + 5 * FWVAL_SLOW_INTERVAL_S) is True


def test_missing_last_ts_treated_as_zero():
    assert _fwval_should_attempt(FWVAL_FAST_CAP, last_attempt_ts=None, now=10_000) is True


# ── PIPE-C3: _visual_release_decision (deferral always terminates) ────────────

def test_defer_while_within_clock_and_budget():
    assert _visual_release_decision(deferred_since=1_000, attempts=1,
                                    total_judgments=2, now=1_000 + 100) == "defer"


def test_none_deferred_since_defers():
    # first call sets the anchor in the caller; here it must not release
    assert _visual_release_decision(deferred_since=None, attempts=0,
                                    total_judgments=0, now=1_000) == "defer"


def test_wallclock_escape_releases():
    assert _visual_release_decision(deferred_since=1_000, attempts=1, total_judgments=1,
                                    now=1_000 + VISUAL_DEFERRAL_ESCAPE_S + 1) == "release"


def test_attempt_budget_escape_releases():
    assert _visual_release_decision(deferred_since=1_000, attempts=3, total_judgments=1,
                                    now=1_000 + 10) == "release"


def test_total_judgment_backstop_releases():
    # even with a fresh-ish clock and low per-source attempts, the per-milestone
    # total-judgment cap is the churn backstop
    assert _visual_release_decision(deferred_since=1_000, attempts=1,
                                    total_judgments=VISUAL_TOTAL_JUDGMENTS_CAP,
                                    now=1_000 + 10) == "release"


# ── PIPE-C3 wiring: _maybe_run_visual_fidelity ANCHORS the deferral clock ─────

def _vf_stub():
    stub = types.SimpleNamespace(
        _reference_images=["ref.png"],
        _vf_sig="OLD_SIG",
        _vf_attempts=2,
        _vf_passed=False,
        _vf_deferred_since=5_000.0,   # a prior defer already anchored this milestone
        _vf_total_judgments=1,
        _vf_last_judged_sig="SOME_OTHER_SIG",
        output_dir=Path("/tmp"),
        llm=object(),
        _logger=MagicMock(),
        hubs=types.SimpleNamespace(
            workhub=types.SimpleNamespace(create_task=lambda **k: {"id": "t1"})),
    )

    async def _send(msg):
        return None
    stub.message_bus = types.SimpleNamespace(send=_send)
    stub._compute_app_source_signature = lambda: "NEW_SIG"  # source changed (lane churn)
    return stub


def test_visual_fidelity_does_not_reset_deferral_clock_on_sig_change(monkeypatch):
    """THE PIPE-C3 FIX: a source-signature change (frontend lane churn) resets the
    per-source attempt budget but must NOT rewind the anchored 900s deferral
    clock — otherwise the lane livelocks delivery forever."""
    import multi_agent.runtime.visual_fidelity as vf

    async def _fake_run(*a, **k):
        return {"passed": False, "screens": [], "summary": "mismatch"}

    monkeypatch.setattr(vf, "run_visual_fidelity", _fake_run)
    monkeypatch.setattr(vf, "remediation_text", lambda r: "fix the header")

    stub = _vf_stub()
    _run(Orchestrator._maybe_run_visual_fidelity(stub))

    # deferral clock PRESERVED across the sig change (the bug was resetting it to None)
    assert stub._vf_deferred_since == 5_000.0
    # per-source attempt budget WAS reset by the sig change, then this judgment counted
    assert stub._vf_attempts == 1
    assert stub._vf_sig == "NEW_SIG"
    # per-milestone total-judgment backstop advanced (NOT reset on sig change)
    assert stub._vf_total_judgments == 2


def test_visual_fidelity_pass_latches(monkeypatch):
    import multi_agent.runtime.visual_fidelity as vf

    async def _fake_pass(*a, **k):
        return {"passed": True, "screens": [{"name": "feed", "similarity": 0.95}],
                "summary": "ok"}

    monkeypatch.setattr(vf, "run_visual_fidelity", _fake_pass)
    stub = _vf_stub()
    stub._vf_last_judged_sig = "SOME_OTHER_SIG"  # force a real judge
    _run(Orchestrator._maybe_run_visual_fidelity(stub))
    assert stub._vf_passed is True


# ── RESILIENCE: framework-validation STUCK-LOOP breaker ───────────────────────
# The orchestrator's own heal/skeleton/DDL regeneration churns the app-source
# signature every cycle, so the OLD reset (post-heal-sig delta → fresh fast budget)
# fired every tick → the FAST cap never tripped → the SAME failing validation
# cycle spun every ~60s indefinitely (observed: 36 identical cycles, 0 agent
# activity). The fix tracks the FAILURE SET (not the file signature): reset the
# budget only on a CHANGED failure set (real lane progress); once the cap is spent
# on an unchanging failure set, escalate (re-dispatch the owner, then surface a
# terminal "stuck" signal) instead of churning to wall-clock.

def test_failure_set_keys_on_failing_check_names_only():
    data = {"checks": [
        {"name": "business_endpoints_implemented", "status": "fail", "detail": "404 boot noise"},
        {"name": "frontend_navigable", "status": "pass"},
        {"name": "business_chain", "status": "fail", "detail": "no verification chains"},
    ]}
    # only the FAILING names, detail (transient docker/boot noise) ignored
    assert _fwval_failure_set(data) == frozenset(
        {"business_endpoints_implemented", "business_chain"})
    # detail churn on the SAME failing names → SAME set (no spurious "progress")
    data2 = {"checks": [
        {"name": "business_endpoints_implemented", "status": "fail", "detail": "405 different noise"},
        {"name": "frontend_navigable", "status": "pass"},
        {"name": "business_chain", "status": "fail", "detail": "still none"},
    ]}
    assert _fwval_failure_set(data2) == _fwval_failure_set(data)
    assert _fwval_failure_set(None) == frozenset()
    assert _fwval_failure_set({}) == frozenset()


def test_stuck_decision_ladder():
    # below the re-dispatch threshold: keep iterating (don't interfere)
    for n in range(FWVAL_STUCK_REDISPATCH_AFTER):
        assert _fwval_stuck_decision(n) == "wait"
    # at the re-dispatch threshold: re-wake the owning lane
    assert _fwval_stuck_decision(FWVAL_STUCK_REDISPATCH_AFTER) == "redispatch"
    assert _fwval_stuck_decision(FWVAL_STUCK_TERMINAL_AFTER - 1) == "redispatch"
    # at the terminal threshold: re-dispatch didn't help → surface "stuck"
    assert _fwval_stuck_decision(FWVAL_STUCK_TERMINAL_AFTER) == "terminal"
    assert _fwval_stuck_decision(FWVAL_STUCK_TERMINAL_AFTER + 5) == "terminal"
    # ordering is sane: terminal threshold strictly past re-dispatch
    assert FWVAL_STUCK_TERMINAL_AFTER > FWVAL_STUCK_REDISPATCH_AFTER


def _fwval_stub(*, run_data, attempts=0, healed_sig="SIG_A", impl_count=2):
    """A faithful-enough stub to drive _maybe_run_framework_validation's FAILURE
    branch without docker/git/LLM. The pre-validation heal helpers are no-ops; the
    source signature CHURNS every call (NEW_SIG_<n>) to reproduce the self-induced
    signature churn that used to reset the budget. RunValidationTool is patched by
    the test to return ``run_data``."""
    calls = {"sig": 0}

    def _churning_sig():
        calls["sig"] += 1
        return f"NEW_SIG_{calls['sig']}"  # never byte-stable (heal churn)

    endpoints = {f"e{i}": {"status": "implemented", "method": "GET",
                           "path": f"/e{i}", "business": True}
                 for i in range(impl_count)}

    stub = types.SimpleNamespace(
        _logger=MagicMock(),
        progress=MagicMock(),
        _framework_validation_attempts=attempts,
        _fwval_last_attempt_ts=0.0,
        _fwval_healed_sig=healed_sig,
        _fwval_last_impl_count=impl_count,   # no endpoint-count progress
        _fwval_failure_set=None,
        _fwval_stuck_count=0,
        _fwval_stuck_blocker=None,
        _session_start_ts=0.0,
        _current_milestone_version="1.0.0",
        # per-milestone owner-dispatch guards (already "spent" this milestone)
        _unimpl_routes_dispatched="1.0.0",
        _frontend_navigable_dispatched="1.0.0",
        _unwired_ui_pages_dispatched="1.0.0",
        _chain_task_dispatched="1.0.0",
        hubs=types.SimpleNamespace(
            registryhub=types.SimpleNamespace(get_endpoints=lambda: endpoints),
            runhub=types.SimpleNamespace(last_successful_run_since=lambda ts: False),
        ),
    )
    # heal/scaffold/merge helpers — all no-ops for the test
    for _m in ("_merge_committed_agent_work", "_scaffold_design_readme",
               "_generate_backend_skeleton", "_scaffold_frontend_baseline",
               "_repair_frontend_api", "_repair_backend_entrypoint",
               "_repair_backend_as_wiring", "_repair_backend_auth",
               "_repair_backend_packaging", "_repair_ddl_from_orm",
               "_repair_handler_fk_aliases", "_repair_psycopg_dsn"):
        setattr(stub, _m, lambda *a, **k: None)
    stub._compute_app_source_signature = _churning_sig
    stub._all_business_endpoints_have_route_code = lambda: True
    # bind the real methods under test
    stub._fwval_rearm_owner_dispatch = lambda: Orchestrator._fwval_rearm_owner_dispatch(stub)

    async def _noop_dispatch(*a, **k):
        return None
    stub._dispatch_unimplemented_routes = _noop_dispatch
    stub._dispatch_frontend_navigable = _noop_dispatch
    stub._maybe_run_visual_fidelity = _noop_dispatch
    return stub


def _patch_run_validation(monkeypatch, run_data):
    import tools.validation_tools as vt

    class _FakeTool:
        def __init__(self, *a, **k):
            pass

        async def execute(self):
            return types.SimpleNamespace(data=run_data, error_message="")
    monkeypatch.setattr(vt, "RunValidationTool", _FakeTool)


_FAIL = {"summary": "boot failed", "checks": [
    {"name": "business_endpoints_implemented", "status": "fail", "detail": "x"}]}


def test_self_induced_sig_churn_does_NOT_reset_budget(monkeypatch):
    """THE CORE BUG: the orchestrator's own heal churns the source signature every
    cycle. The fast budget must NOT reset on that churn — otherwise the cap never
    trips and the same failing cycle spins forever."""
    _patch_run_validation(monkeypatch, _FAIL)
    stub = _fwval_stub(run_data=_FAIL, attempts=3)
    _run(Orchestrator._maybe_run_framework_validation(stub))
    # attempts ADVANCED (3→4), it did NOT reset to 0 despite the churning signature
    assert stub._framework_validation_attempts == 4
    assert stub._fwval_failure_set == frozenset({"business_endpoints_implemented"})


def test_changed_failure_set_resets_budget_and_stuck(monkeypatch):
    """A CHANGED failure set is genuine lane progress → fresh fast budget + reset
    stuck counter (a converging app is never slowed)."""
    _patch_run_validation(monkeypatch, _FAIL)
    stub = _fwval_stub(run_data=_FAIL, attempts=FWVAL_FAST_CAP)
    # a prior, DIFFERENT failure set was recorded; we were 3 cycles into a stall
    stub._fwval_failure_set = frozenset({"frontend_navigable"})
    stub._fwval_stuck_count = 3
    _run(Orchestrator._maybe_run_framework_validation(stub))
    assert stub._framework_validation_attempts == 0   # fresh budget on real progress
    assert stub._fwval_stuck_count == 0
    assert stub._fwval_failure_set == frozenset({"business_endpoints_implemented"})


def test_unchanging_failure_set_past_cap_escalates_to_redispatch(monkeypatch):
    """Same failure set, fast budget spent → increment stuck counter and, at the
    re-dispatch threshold, RE-ARM the owner-dispatch guards (re-wake the owner)."""
    _patch_run_validation(monkeypatch, _FAIL)
    stub = _fwval_stub(run_data=_FAIL, attempts=FWVAL_FAST_CAP)
    stub._fwval_failure_set = frozenset({"business_endpoints_implemented"})
    stub._fwval_stuck_count = FWVAL_STUCK_REDISPATCH_AFTER - 1  # this call tips it over
    _run(Orchestrator._maybe_run_framework_validation(stub))
    assert stub._fwval_stuck_count == FWVAL_STUCK_REDISPATCH_AFTER
    # past the cap, attempts stay pinned (no fresh budget on a stable failure set)
    assert stub._framework_validation_attempts == FWVAL_FAST_CAP
    # owner-dispatch guards re-armed so the _dispatch_* helpers re-fire the owner task
    assert stub._unimpl_routes_dispatched is None
    assert stub._frontend_navigable_dispatched is None
    assert stub._chain_task_dispatched is None


def test_unchanging_failure_set_past_cap_surfaces_terminal_stuck(monkeypatch):
    """When re-dispatch did not break the stall, surface a clear terminal 'stuck on
    <blocker>' signal (PHASE_ERROR) so the UI shows the real blocker — but do NOT
    hard-kill (the run budget cap is the terminator)."""
    _patch_run_validation(monkeypatch, _FAIL)
    stub = _fwval_stub(run_data=_FAIL, attempts=FWVAL_FAST_CAP)
    stub._fwval_failure_set = frozenset({"business_endpoints_implemented"})
    stub._fwval_stuck_count = FWVAL_STUCK_TERMINAL_AFTER - 1  # tips into terminal
    _run(Orchestrator._maybe_run_framework_validation(stub))
    assert stub._fwval_stuck_count == FWVAL_STUCK_TERMINAL_AFTER
    assert stub._fwval_stuck_blocker == "business_endpoints_implemented"
    # surfaced the blocker exactly once via the progress channel
    assert stub.progress.emit.called
    _evt = stub.progress.emit.call_args[0]
    assert "stuck on business_endpoints_implemented" in str(_evt)


def test_below_cap_unchanging_failure_set_does_not_escalate(monkeypatch):
    """BEHAVIOR-PRESERVING: while still inside the fast budget (app converging),
    an unchanging failure set must NOT trigger escalation — only the stuck counter
    advances; guards stay set and no terminal signal fires."""
    _patch_run_validation(monkeypatch, _FAIL)
    stub = _fwval_stub(run_data=_FAIL, attempts=1)  # well below the cap
    stub._fwval_failure_set = frozenset({"business_endpoints_implemented"})
    stub._fwval_stuck_count = 1
    _run(Orchestrator._maybe_run_framework_validation(stub))
    assert stub._framework_validation_attempts == 2   # normal fast advance
    assert stub._fwval_stuck_blocker is None           # no terminal signal
    assert stub._unimpl_routes_dispatched == "1.0.0"   # guards untouched
    assert not stub.progress.emit.called
