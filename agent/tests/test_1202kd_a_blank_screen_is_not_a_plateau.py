"""#1202kd: #737's sentence, applied one level down.

#737 already says it for a WHOLESALE blackout -- "the capture produced no rendered page, so
its 0.00s are not evidence the app has flatlined" -- and holds the plateau counter for that
round. In a PARTIALLY blank round `capture_transient` is False, so each blank screen still
entered `_best_by_screen` at 0.00 and contributed "no improvement", which is exactly the signal
the #138 plateau escape releases on.

That is r148's mechanism, and `maybe_run`'s own comment describes it: ten of twelve screens
blank for eight rounds, plateau climbed to five, release cut while a P0 titled "SPA crashes on
ALL routes" was open -- "the blackout was the truest signal in the run, and it was consumed as
evidence of stability."

Measured: 14 of the 29 recent final verdicts are partially blank, so the wholesale exemption
misses about half of them.

WHAT IS VERIFIED here: the plateau reading skips blank screens, does not seed them as a 0.00
baseline, and holds rather than climbs when nothing was photographed at all; and a real screen
still drives both improvement and no-improvement.

WHAT IS NOT: that this changes any run's verdict. The blank keeps its 0.00 in the gate itself
-- it still blocks and still drags the #542a average -- so this removes a false accelerant, it
does not make anything easier to ship.
"""
import sys
import pathlib

_AGENT = pathlib.Path(__file__).resolve().parents[1]
if str(_AGENT) not in sys.path:
    sys.path.insert(0, str(_AGENT))

import ast                                                             # noqa: E402
import inspect                                                        # noqa: E402

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as VF  # noqa: E402

read = VF._plateau_reading_1202kd


def _scr(name, sim, **kw):
    d = {"name": name, "similarity": sim}
    d.update(kw)
    return d


def test_a_real_screen_that_climbs_is_an_improvement():
    """Non-regression floor: the ordinary path must still work."""
    best = {"feed": 0.40}
    improved, scored = read([_scr("feed", 0.70)], best)
    assert improved is True and scored == 1
    assert best["feed"] == 0.70


def test_a_real_screen_that_does_not_climb_is_no_improvement():
    """The other floor: without this the fix could pass by never reporting a plateau."""
    best = {"feed": 0.70}
    improved, scored = read([_scr("feed", 0.71)], best)   # inside the 0.02 epsilon
    assert improved is False and scored == 1


def test_a_blank_screen_is_not_counted_as_scored():
    """★ The fix. r148's shape: one screen improving, one blank."""
    best = {"feed": 0.40, "profile": 0.55}
    improved, scored = read(
        [_scr("feed", 0.70), _scr("profile", 0.0, blank=True)], best)
    assert scored == 1, "the blank screen must not count as a round that tested the plateau"
    assert improved is True


def test_the_live_spelling_counts_too():
    """#931/#500: `blank` describes the RECORDED capture, `blank_live` THIS one. A screen that
    just blanked but whose merged high-water record is not blank is the exact case #500's
    best-of merge hides -- and the one r148 was."""
    best = {}
    _, scored = read([_scr("profile", 0.0, blank=False, blank_live=True)], best)
    assert scored == 0
    assert best == {}, "a blank must not be seeded as a 0.00 baseline either"


def test_an_all_blank_round_holds_rather_than_climbs():
    """★ The residual hole the skip alone would leave: skip every screen and `improved` is
    False by construction, which is the SAME false 'no improvement' in a new costume. The
    caller must read `scored == 0` and hold."""
    best = {}
    improved, scored = read(
        [_scr("a", 0.0, blank=True), _scr("b", 0.0, blank_live=True)], best)
    assert scored == 0 and improved is False


def test_the_caller_holds_the_counter_when_nothing_was_scored():
    """★ Reachability (#1202 'prove reachability, not presence'): the helper returning 0 is
    worthless unless `maybe_run` branches on it. Anchored on landmarks, not a byte window
    (#943)."""
    src = inspect.getsource(VF)
    i = src.index("_improved, _scored_1202kd = _plateau_reading_1202kd(")
    j = src.index("#1202cz", i)
    body = src[i:j]
    assert "if not _scored_1202kd:" in body
    assert "plateau HELD" in body
    # and the climb must live in the else, never unconditionally after the hold
    assert body.index("if not _scored_1202kd:") < body.index(
        "self.plateau_rounds = 0 if _improved else self.plateau_rounds + 1")
    assert "                else:\n" in body


def test_advisory_screens_are_still_excluded():
    """Non-regression: #128's advisory exclusion predates this and must survive the extraction."""
    best = {}
    _, scored = read([_scr("banner", 0.9, advisory=True)], best)
    assert scored == 0


def test_the_gate_verdict_did_not_learn_about_blank_from_here():
    """★ Scope. The helper decides ONE thing. If it grew a say in pass/fail, the blank screen
    would stop blocking -- the opposite of what this is for."""
    tree = ast.parse(inspect.getsource(VF._plateau_reading_1202kd))
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert not (names & {"passed", "self", "orch", "result"}), (
        f"the plateau reading must not reach the verdict: {sorted(names)}")
