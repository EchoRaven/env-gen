"""#521 (netflix r91/r92, 2026-08-06) — the visual-gate deferral escape must be STICKY.

GROUND TRUTH: r92's visual deferral RELEASED via the plateau escape (8 judged) and the
orchestrator narrated deliver_project — but then it RE-DEFERRED and looped (88 deliver_project
narrations, 12 deferrals, no release persisted for ~17 min). Root cause: the orchestrator
re-evaluates _visual_release_decision on EVERY delivery poll, and the release path's final
re-judge can register a >0.02 per-screen improvement → plateau_rounds resets to 0 → the next
poll's decision flips back to "defer". The escape was not latched, so delivery only finalized
at the 3600s wall-clock (r91 was killed ~82s short of that; both had ~75min deliver-tails).
FIX #521: VisualFidelityGate gains a per-milestone `released` latch; the orchestrator sets it
when the escape fires and SKIPS the whole visual-defer block while it is set — so an earned
below-threshold release stays released (delivery finalizes promptly, no re-defer loop).

These tests lock: the `released` field default + settability + per-milestone reset; and the
sticky invariant the orchestrator condition encodes (defer only while NOT passed AND NOT
released)."""
from env_generator.llm_generator.multi_agent.runtime.visual_fidelity import (
    VisualFidelityGate)


def _gate():
    return VisualFidelityGate(None)   # __init__ only stores orch; fields are what we test


def test_released_defaults_false():
    g = _gate()
    assert g.released is False


def test_released_is_settable_and_cleared_per_milestone():
    g = _gate()
    g.released = True
    assert g.released is True
    g.reset_for_milestone()             # a NEW milestone re-arms the gate
    assert g.released is False


def test_reset_clears_released_alongside_the_other_per_milestone_state():
    g = _gate()
    g.released = True
    g.plateau_rounds = 9
    g.deferred_since = 123.0
    g.total_judgments = 8
    g.reset_for_milestone()
    assert g.released is False and g.plateau_rounds == 0
    assert g.deferred_since is None and g.total_judgments == 0


def test_sticky_defer_invariant():
    # mirrors the orchestrator's visual-defer gate condition (orchestrator.py ~2886):
    # enter the defer/re-judge block only while NOT passed AND NOT released.
    def _should_enter_defer_block(gate):
        return (not gate.passed) and (not getattr(gate, "released", False))
    g = _gate()
    assert _should_enter_defer_block(g) is True          # fresh: block runs (may defer)
    g.released = True
    assert _should_enter_defer_block(g) is False          # escaped: block SKIPPED (no re-defer)
    g.released = False
    g.passed = True
    assert _should_enter_defer_block(g) is False          # passed: block skipped too


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
