"""FIX #129 — STICKY per-screen visual pass across re-judge rounds within a milestone.

The vision judge (Gemini) self-compresses scores toward the center and noise-wiggles
the SAME unchanged pixels by ±0.2-0.4 between calls (run-47 autopsy). Requiring every
blocking screen to clear min_similarity on the SAME re-judge is a joint-probability
wall: with N center-clustered noisy screens the gate essentially never passes and every
milestone ships via the below-threshold escape. _apply_sticky_pass latches each blocking
screen the first round it clears the bar, so the gate is satisfied once each has cleared
AT LEAST ONCE this milestone. Advisory (overlay) screens (#128) are excluded.

ENV-AGNOSTIC + LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.visual_fidelity import (  # noqa: E402
    _apply_sticky_pass, remediation_text)


def _s(name, passed, advisory=False):
    return {"name": name, "passed": passed, "advisory": advisory}


def test_all_pass_same_round_passes():
    latch = set()
    ok = _apply_sticky_pass(latch, [_s("login", True), _s("feed", True)])
    assert ok and latch == {"login", "feed"}


def test_never_all_same_round_but_each_passes_once_across_rounds_passes():
    # THE core bug: noisy judge never clears all screens on ONE re-judge, but each
    # clears on SOME round. Sticky latch must let the milestone converge.
    latch = set()
    # round 1: login passes, feed fails (noise)
    assert not _apply_sticky_pass(latch, [_s("login", True), _s("feed", False)])
    assert latch == {"login"}
    # round 2 (new source): login now fails (noise), feed passes
    ok = _apply_sticky_pass(latch, [_s("login", False), _s("feed", True)])
    assert ok, "gate must pass once EVERY blocking screen cleared at least once"
    assert latch == {"login", "feed"}


def test_a_screen_that_never_passes_keeps_gate_blocked():
    latch = set()
    for _ in range(5):
        ok = _apply_sticky_pass(latch, [_s("login", True), _s("explore", False)])
        assert not ok
    assert latch == {"login"}  # explore never latched → gate stays blocked forever


def test_advisory_screens_excluded_from_criterion():
    # an overlay reference (#128) that never passes must NOT block a gate whose
    # real blocking screens have all cleared.
    latch = set()
    ok = _apply_sticky_pass(
        latch, [_s("feed", True), _s("search_flyout", False, advisory=True)])
    assert ok and latch == {"feed"}


def test_all_advisory_is_not_a_pass():
    # no blocking screens at all → not a positive pass (bool(blocking) guard); the
    # upstream "vacuous gate" path owns the no-real-screen case, not this latch.
    latch = set()
    ok = _apply_sticky_pass(latch, [_s("modal", False, advisory=True)])
    assert not ok


def test_latch_reset_between_milestones_reblocks():
    latch = set()
    _apply_sticky_pass(latch, [_s("login", True)])
    assert "login" in latch
    latch.clear()  # reset_for_milestone does this
    ok = _apply_sticky_pass(latch, [_s("login", False), _s("feed", False)])
    assert not ok and latch == set()


def _screen_result(name, similarity, passed):
    return {"name": name, "route": "/" + name, "similarity": similarity,
            "passed": passed, "dimensions": {}, "deviations": [f"{name} differs"],
            "fixes": [f"fix {name}"]}


def test_remediation_excludes_latched_screen_scored_low_this_round():
    # gate still open (explore never latched), but login latched a prior round and
    # the noisy judge scored it 0.30 THIS round — remediation must NOT re-list login
    # (re-working a good screen risks regressing it), only explore.
    result = {"screens": [_screen_result("login", 0.30, False),
                          _screen_result("explore", 0.20, False)]}
    body = remediation_text(result, None, latched={"login"})
    assert "## explore" in body
    assert "## login" not in body, "latched screen must be excluded from the fix list"


def test_remediation_without_latch_lists_all_failing():
    result = {"screens": [_screen_result("login", 0.30, False),
                          _screen_result("explore", 0.20, False)]}
    body = remediation_text(result, None)
    assert "## login" in body and "## explore" in body
