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
    FWVAL_FAST_CAP, FWVAL_SLOW_INTERVAL_S, VISUAL_DEFERRAL_ESCAPE_S,
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
