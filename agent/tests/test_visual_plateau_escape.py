"""FIX #138 — plateau-based early escape of the final visual-fidelity window.

Log-mining runs 50-62: the final visual window averaged 65m31s = ~40% of a run's
TOTAL wall-clock, and in 7/7 delivered runs it ended via the 3600s escape timer —
never a pass. When several consecutive REAL judgments show no blocking screen
beating its best-so-far, further waiting buys nothing: escape after a deferral
floor. Any genuine per-screen improvement re-arms the counter (conservative).

ENV-AGNOSTIC + LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.orchestrator import _visual_release_decision  # noqa: E402
from multi_agent.runtime.visual_fidelity import VisualFidelityGate  # noqa: E402


# ── decision function ────────────────────────────────────────────────────────

def test_plateau_escape_after_floor():
    # 4 no-improvement rounds + past the 1500s floor -> release (before 3600s wall)
    assert _visual_release_decision(
        deferred_since=0.0, attempts=1, total_judgments=6, now=1600.0,
        plateau_rounds=4) == "release"


def test_plateau_needs_the_floor():
    # plateaued but only 800s deferred -> still defer (frontend deserves the floor)
    #
    # plateau_rounds must stay BELOW the hard threshold. #519 added a second,
    # churn-proof plateau escape at 2x the soft cap that deliberately has NO time
    # floor ("a HARD plateau count is conclusive churn-proof evidence the scores
    # are final"), so the original 9 stopped testing the floor and started testing
    # the hard escape — which correctly releases. 5 is past the soft cap (4) and
    # short of the hard one (8), so the floor is what decides.
    assert _visual_release_decision(
        deferred_since=0.0, attempts=1, total_judgments=6, now=800.0,
        plateau_rounds=5) == "defer"


def test_no_plateau_keeps_deferring_until_wall():
    assert _visual_release_decision(
        deferred_since=0.0, attempts=1, total_judgments=6, now=1600.0,
        plateau_rounds=1) == "defer"
    # the anchored wall-clock escape is untouched
    assert _visual_release_decision(
        deferred_since=0.0, attempts=1, total_judgments=6, now=3700.0,
        plateau_rounds=0) == "release"


def test_plateau_disabled_via_zero_cap():
    # Both plateau paths off: plateau_cap=0 disables the soft escape and
    # plateau_hard=0 the #519 one. In production a single env var does both —
    # VISUAL_PLATEAU_HARD_ROUNDS is derived as 2 * VISUAL_PLATEAU_ROUNDS — but the
    # kwargs are independent, so "disabled" has to say so twice here.
    assert _visual_release_decision(
        deferred_since=0.0, attempts=1, total_judgments=6, now=1600.0,
        plateau_rounds=99, plateau_cap=0, plateau_hard=0) == "defer"


# ── gate-side counter ────────────────────────────────────────────────────────

def _gate():
    g = VisualFidelityGate.__new__(VisualFidelityGate)
    g._best_by_screen = {}
    g.plateau_rounds = 0
    return g


def _feed(g, scores):
    """Mimic the maybe_run plateau-tracking block for one real judgment."""
    improved = False
    for name, sim in scores.items():
        if sim > g._best_by_screen.get(name, 0.0) + 0.02:
            g._best_by_screen[name] = sim
            improved = True
        elif name not in g._best_by_screen:
            g._best_by_screen[name] = sim
    g.plateau_rounds = 0 if improved else g.plateau_rounds + 1


def test_counter_increments_on_flat_scores_and_rearms_on_improvement():
    g = _gate()
    _feed(g, {"login": 0.2, "explore": 0.4})   # first round: everything is a new best
    assert g.plateau_rounds == 0
    _feed(g, {"login": 0.2, "explore": 0.35})  # noise wiggle below best -> no improve
    assert g.plateau_rounds == 1
    _feed(g, {"login": 0.21, "explore": 0.4})  # +0.01 is inside the noise epsilon
    assert g.plateau_rounds == 2
    _feed(g, {"login": 0.45, "explore": 0.3})  # REAL improvement -> re-arm
    assert g.plateau_rounds == 0


def test_reset_for_milestone_clears_plateau_state():
    g = VisualFidelityGate.__new__(VisualFidelityGate)
    g._best_by_screen = {"login": 0.4}
    g.plateau_rounds = 5
    g.deferred_since = 1.0
    g.total_judgments = 9
    g.transient_refunds = 1
    g._passed_screens = {"x"}
    g._seed_reminder_sent = True
    g.reset_for_milestone()
    assert g.plateau_rounds == 0 and g._best_by_screen == {}


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
