r"""#1202dp: the final gate raised five seconds after filing the fix that would clear it.

netflix r44, live:

    15:41:41  GATE-CHECK remediation dispatched to backend (task_c448404c80):
              business_response_key_noncanonical
    15:41:42  Project phase: implement -> test (run delivery gate checks)
    15:41:44  Final delivery gate failed on FIRST evaluation
              (['validation_ui_evidence_failed', 'business_response_key_noncanonical'])
    15:41:46  [E] Generation failed: Delivery gate failed.
    15:44:04  [main-exit] main() returned 1

It died with 53 of 180 wall-clock minutes and 144 of 200 ticks unspent, $320.50 in, and
visual fidelity still IMPROVING (median 0.465 -> 0.610, 3 -> 4 screens over 0.65). Both
blockers were OWNED and in flight: business_response_key_noncanonical -> backend, filed 5s
earlier; validation_ui_evidence_failed -> verifier, task_d117dab4a9 in_progress.

The three existing hatches each cover a narrower class -- readiness race, #139 registry
drift, #553 re-runnable chains -- and none covers "owned, dispatched, budget remains".

The grace CANNOT cause a bad delivery: it never sets gate["ok"], never touches an escape
path, and delivery still requires the gate to pass on its own. It only defers the raise.
"""
from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

import pytest

AGENT = Path(__file__).resolve().parents[1]

SRC = (AGENT / "env_generator" / "llm_generator" / "multi_agent" / "orchestrator.py").read_text()


def _grace_block() -> str:
    """The extracted method body, landmark-anchored (no byte windows)."""
    start = SRC.index("    async def _final_gate_grace_1202dp(")
    return SRC[start:SRC.index("    def _final_gate_grace_budget_1202dp(", start)]


# --- the budget helper is real code; exercise it directly ---------------------------

class _Orch:
    """Just enough object to call the unbound helper."""

    def __init__(self, origin_offset=0.0):
        import time as _t
        self._loop_start_1196 = _t.time() - origin_offset


def _helper():
    from env_generator.llm_generator.multi_agent.orchestrator import Orchestrator as O
    return O._final_gate_grace_budget_1202dp


def test_grace_is_allowed_early_in_a_run(monkeypatch):
    monkeypatch.setenv("ENVGEN_MAX_WALLCLOCK_SEC", "7200")
    assert _helper()(_Orch(origin_offset=100), 120) is True


def test_grace_is_refused_near_the_wall_clock(monkeypatch):
    """It must never be the thing that pushes a run past its own ceiling."""
    monkeypatch.setenv("ENVGEN_MAX_WALLCLOCK_SEC", "7200")
    assert _helper()(_Orch(origin_offset=7100), 120) is False


def test_the_refusal_leaves_a_tail(monkeypatch):
    """Fits the round but not the 60s tail -> refuse."""
    monkeypatch.setenv("ENVGEN_MAX_WALLCLOCK_SEC", "1000")
    assert _helper()(_Orch(origin_offset=860), 120) is False   # 860+120+60 > 1000
    assert _helper()(_Orch(origin_offset=700), 120) is True    # 700+120+60 < 1000


def test_a_missing_origin_refuses_rather_than_waiting_forever(monkeypatch):
    monkeypatch.setenv("ENVGEN_MAX_WALLCLOCK_SEC", "7200")
    o = _Orch()
    o._loop_start_1196 = None
    assert _helper()(o, 120) is False


def test_unlimited_budget_always_grants(monkeypatch):
    monkeypatch.setenv("ENVGEN_BUDGET_UNLIMITED", "1")
    assert _helper()(_Orch(origin_offset=999999), 120) is True


def test_a_junk_cap_refuses(monkeypatch):
    monkeypatch.delenv("ENVGEN_BUDGET_UNLIMITED", raising=False)
    monkeypatch.setenv("ENVGEN_MAX_WALLCLOCK_SEC", "not-a-number")
    assert _helper()(_Orch(origin_offset=10), 120) is False


# --- the loop, actually executed ----------------------------------------------------

class _Orch2:
    """Minimal orchestrator surface the grace loop touches. Real method, fake collaborators."""

    def __init__(self, verdicts, *, wedged=0, origin_offset=0.0):
        import time as _t
        from types import SimpleNamespace
        self._verdicts = list(verdicts)          # gates returned by successive re-evaluations
        self._gatecheck_wedged_ticks_1040 = wedged
        self._loop_start_1196 = _t.time() - origin_offset
        self.slept = []
        self.warnings = []
        _w = lambda fmt, *a: self.warnings.append(fmt % a if a else fmt)
        self._logger = SimpleNamespace(warning=_w, info=_w, error=_w, debug=_w)

    def _validate_delivery_gate(self):
        return self._verdicts.pop(0) if self._verdicts else {"ok": False, "failed_checks": ["x"]}


def _bind():
    from env_generator.llm_generator.multi_agent.orchestrator import Orchestrator
    return Orchestrator._final_gate_grace_1202dp, Orchestrator._final_gate_grace_budget_1202dp


def _run(orch, gate, monkeypatch, *, sleep_ok=True):
    """Drive the real coroutine with asyncio.sleep stubbed so the test is instant."""
    import asyncio as _a
    from env_generator.llm_generator.multi_agent import orchestrator as _mod
    grace, budget = _bind()
    orch._final_gate_grace_budget_1202dp = budget.__get__(orch)

    async def _sleep(sec):
        orch.slept.append(sec)
    monkeypatch.setattr(_mod.asyncio, "sleep", _sleep)
    return _a.run(grace(orch, gate))


BAD = {"ok": False, "failed_checks": ["validation_ui_evidence_failed",
                                      "business_response_key_noncanonical"]}
GOOD = {"ok": True, "failed_checks": []}


def test_the_grace_waits_and_the_gate_clears(monkeypatch):
    """r44's shape: remediation is in flight, and the next evaluation is green."""
    monkeypatch.setenv("ENVGEN_MAX_WALLCLOCK_SEC", "7200")
    o = _Orch2([GOOD], wedged=0, origin_offset=100)
    out = _run(o, dict(BAD), monkeypatch)
    assert out["ok"] is True
    assert o.slept == [120.0], "exactly one round should have been needed"
    assert any("GRACE 1/3" in w for w in o.warnings)
    assert any("CLEARED" in w for w in o.warnings)


def test_it_gives_up_after_the_round_cap(monkeypatch):
    monkeypatch.setenv("ENVGEN_MAX_WALLCLOCK_SEC", "7200")
    o = _Orch2([dict(BAD), dict(BAD), dict(BAD)], wedged=0, origin_offset=100)
    out = _run(o, dict(BAD), monkeypatch)
    assert out["ok"] is False
    assert len(o.slept) == 3, "the round cap must bound the wait"
    assert not any("CLEARED" in w for w in o.warnings)


def test_a_wedged_gate_never_waits(monkeypatch):
    """No failing check has an owner -- the r174 dead end. Waiting buys nothing."""
    monkeypatch.setenv("ENVGEN_MAX_WALLCLOCK_SEC", "7200")
    o = _Orch2([GOOD], wedged=2, origin_offset=100)
    out = _run(o, dict(BAD), monkeypatch)
    assert out["ok"] is False
    assert o.slept == [], "a wedged gate must raise immediately, exactly as before"


def test_it_stops_when_the_gate_becomes_wedged_mid_grace(monkeypatch):
    """Round one waits; the dispatcher then reports nothing owned, so round two must not."""
    monkeypatch.setenv("ENVGEN_MAX_WALLCLOCK_SEC", "7200")
    o = _Orch2([dict(BAD), dict(BAD)], wedged=0, origin_offset=100)
    real = o._validate_delivery_gate

    def _flip():
        o._gatecheck_wedged_ticks_1040 = 1     # becomes unowned after the first wait
        return real()
    o._validate_delivery_gate = _flip
    _run(o, dict(BAD), monkeypatch)
    assert len(o.slept) == 1


def test_no_grace_when_the_wall_clock_is_nearly_spent(monkeypatch):
    monkeypatch.setenv("ENVGEN_MAX_WALLCLOCK_SEC", "7200")
    o = _Orch2([GOOD], wedged=0, origin_offset=7150)
    out = _run(o, dict(BAD), monkeypatch)
    assert out["ok"] is False and o.slept == []


def test_zero_grace_seconds_disables_it(monkeypatch):
    monkeypatch.setenv("ENVGEN_MAX_WALLCLOCK_SEC", "7200")
    monkeypatch.setenv("ENVGEN_FINAL_GATE_GRACE_S", "0")
    o = _Orch2([GOOD], wedged=0, origin_offset=100)
    assert _run(o, dict(BAD), monkeypatch)["ok"] is False
    assert o.slept == []


def test_an_already_passing_gate_is_returned_untouched(monkeypatch):
    monkeypatch.setenv("ENVGEN_MAX_WALLCLOCK_SEC", "7200")
    o = _Orch2([], wedged=0, origin_offset=100)
    out = _run(o, dict(GOOD), monkeypatch)
    assert out["ok"] is True and o.slept == [] and o.warnings == []


def test_cancellation_propagates(monkeypatch):
    """A cancelled run must die, not absorb the cancellation and keep waiting."""
    import asyncio as _a
    from env_generator.llm_generator.multi_agent import orchestrator as _mod
    monkeypatch.setenv("ENVGEN_MAX_WALLCLOCK_SEC", "7200")
    o = _Orch2([GOOD], wedged=0, origin_offset=100)
    grace, budget = _bind()
    o._final_gate_grace_budget_1202dp = budget.__get__(o)

    async def _boom(sec):
        raise _a.CancelledError()
    monkeypatch.setattr(_mod.asyncio, "sleep", _boom)
    with pytest.raises(_a.CancelledError):
        _a.run(grace(o, dict(BAD)))


# --- the safety property that makes this change reviewable ---------------------------

def test_the_grace_never_forces_the_gate_open():
    """#139 and #553 may set gate["ok"]; this must NOT -- it only defers the raise."""
    b = _grace_block()
    assert not re.search(r'gate\s*\[\s*["\']ok["\']\s*\]\s*=', b), \
        "the grace must never assign gate['ok'] -- delivery stays conditional on a real pass"


def test_the_raise_still_follows_the_grace():
    """The terminal behaviour is preserved: exhausting the grace raises exactly as before."""
    start = SRC.index("#1202dp — FINAL-GATE GRACE WHILE REMEDIATION IS IN FLIGHT")
    # Landmark-anchored, NOT `SRC[start:start+6000]` -- #943's ratchet forbids fixed byte
    # windows precisely because a growing COMMENT silently moves what the window covers,
    # and the first draft of this test broke that ratchet (57 -> 58) with that exact line.
    end = SRC.index('self._enter_project_phase("done", reason="delivery gate passed")', start)
    assert 'raise RuntimeError(f"Delivery gate failed.' in SRC[start:end]


def test_env_knobs_are_documented_in_the_block():
    b = _grace_block()
    for knob in ("ENVGEN_FINAL_GATE_GRACE_ROUNDS", "ENVGEN_FINAL_GATE_GRACE_S"):
        assert knob in b
