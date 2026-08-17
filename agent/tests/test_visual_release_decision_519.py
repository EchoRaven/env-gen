"""#519 (netflix r91, 2026-08-06) — the visual-gate deferral escape must be robust to
frontend SOURCE CHURN.

GROUND TRUTH: r91 delivery deferred 1418s and looped (deliver_project narrated 44x, no
release). Root cause: _visual_release_decision's only FAST escape is the per-source attempt
cap (attempts>=3), but `attempts` resets to 0 on every frontend source-signature change
(visual_fidelity.py); a lane that edits pages on each visual-fail keeps attempts at 0-1, so
that escape never fires. The soft plateau/idle escapes are gated behind a 1500s floor, so
under churn the ONLY releases left are the 20-judgment cap and the 3600s wall-clock — both
slow. FIX #519: a CHURN-ROBUST hard-plateau escape with NO time floor — plateau_rounds is
per-milestone and NOT reset by source churn (it counts real judgments where no blocking
screen beat its best-so-far), so plateau_rounds >= 2*plateau_cap is conclusive regardless of
how fast the lane flips the source. Additive: every prior escape is untouched, so delivery
still ALWAYS eventually fires; 2x the soft cap means noise can't trip it early.

These tests lock: the new hard-plateau escape fires with NO time floor; it needs 2x the soft
cap (noise-safe); the exact r91 churn state defers below the hard cap and releases at it; and
every pre-existing escape (wall-clock, total-judgments, attempts, floored soft-plateau,
floored idle) still behaves as before."""
from env_generator.llm_generator.multi_agent.orchestrator import (
    _visual_release_decision, VISUAL_PLATEAU_HARD_ROUNDS, VISUAL_PLATEAU_ROUNDS,
    VISUAL_PLATEAU_MIN_S, VISUAL_DEFERRAL_ESCAPE_S, VISUAL_TOTAL_JUDGMENTS_CAP)

NOW = 1_000_000.0


def _decide(**kw):
    """Call with r91-like 'all quiet' baseline; override per case."""
    base = dict(deferred_since=NOW - 100.0, attempts=0, total_judgments=0, now=NOW,
                plateau_rounds=0, last_judgment_at=None)
    base.update(kw)
    return _visual_release_decision(**base)


def test_hard_plateau_default_is_2x_soft():
    assert VISUAL_PLATEAU_HARD_ROUNDS == 2 * VISUAL_PLATEAU_ROUNDS   # e.g. 8 vs 4


def test_hard_plateau_escapes_with_NO_time_floor():
    # the #519 core: churn keeps attempts=1, deferral is BELOW the 1500s soft floor,
    # judgments below the 20 cap — yet a hard plateau releases immediately.
    d = _decide(attempts=1, total_judgments=9,
                deferred_since=NOW - 200.0,               # 200s << 1500 floor << 3600
                plateau_rounds=VISUAL_PLATEAU_HARD_ROUNDS)
    assert d == "release", d


def test_below_hard_cap_still_defers_under_churn():
    # exact r91 wedge state one short of the hard cap → correctly still deferring
    # (no early release; the lane still gets its budget).
    d = _decide(attempts=1, total_judgments=9, deferred_since=NOW - 1418.0,
                plateau_rounds=VISUAL_PLATEAU_HARD_ROUNDS - 1)
    assert d == "defer", d
    # and at the hard cap → the fix releases:
    d2 = _decide(attempts=1, total_judgments=9, deferred_since=NOW - 1418.0,
                 plateau_rounds=VISUAL_PLATEAU_HARD_ROUNDS)
    assert d2 == "release", d2


def test_soft_plateau_still_needs_the_time_floor():
    # soft plateau (4) below the floor must NOT release (unchanged behavior)...
    d = _decide(plateau_rounds=VISUAL_PLATEAU_ROUNDS,
                deferred_since=NOW - (VISUAL_PLATEAU_MIN_S - 50.0))
    assert d == "defer", d
    # ...and above the floor it does:
    d2 = _decide(plateau_rounds=VISUAL_PLATEAU_ROUNDS,
                 deferred_since=NOW - (VISUAL_PLATEAU_MIN_S + 50.0))
    assert d2 == "release", d2


def test_preexisting_escapes_unregressed():
    assert _decide(attempts=3) == "release"                              # per-source cap
    assert _decide(total_judgments=VISUAL_TOTAL_JUDGMENTS_CAP) == "release"  # judgment cap
    assert _decide(deferred_since=NOW - (VISUAL_DEFERRAL_ESCAPE_S + 1)) == "release"  # wall-clock
    # idle escape: last judgment long ago + past the floor
    assert _decide(last_judgment_at=NOW - 900.0,
                   deferred_since=NOW - (VISUAL_PLATEAU_MIN_S + 50.0)) == "release"


def test_all_quiet_defers():
    # nothing tripped → keep deferring (the lane iterates)
    assert _decide() == "defer"


def test_hard_plateau_disabled_when_zero():
    # env override to 0 disables the hard escape (falls through to prior behavior)
    d = _visual_release_decision(deferred_since=NOW - 200.0, attempts=1, total_judgments=9,
                                 now=NOW, plateau_rounds=99, plateau_hard=0,
                                 plateau_min_s=VISUAL_PLATEAU_MIN_S)
    # plateau_rounds=99 but below the 1500s floor and hard disabled → still defers
    assert d == "defer", d


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
