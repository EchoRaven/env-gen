r"""#736: #711's divergence warning compared a 2-screen mean against a 12-screen one.

#711 warns when #500's best-ever-per-screen gating average has "left the app behind" — when it
exceeds the live average of THIS capture. Its only condition was a >=0.05 gap between the two
numbers. It never checked that the two averages cover the SAME screens, and often they do not.

Both averages correctly drop `blank is True` screens. That means a blank capture shrinks the
LIVE denominator while the gating average keeps every screen's best-ever score, so a near-total
blackout leaves a two-screen mean facing a twelve-screen mean. The difference is COMPOSITION.

r148 round 4 is the worked example, and the run log states every part of it:

    #711 ... blocking_average 0.6190 vs blocking_average_live 0.4250 (gap 0.1940)
    Visual fidelity: ... (blocking avg 0.42) [blank capture: browse_by_languages, browse_home,
    games, genre_category, movies, my_list, new_and_popular, player, shows, title_detail]
      — blank capture, attempt refunded (transient 1/3).

Ten of twelve screens blanked. The surviving two are landing(0.45) and login(0.40), whose mean
is 0.425 exactly — the "live" number. The framework had already classified the round as transient
and refunded the attempt; #711 then reported it as the app degrading, twice.

Measured across every log in the corpus: #711 has fired **2 times, and 2 of 2 were this
artefact** — a 100% false-positive rate over its whole firing history.

The fix needs no tuned constant (same disposition as #656's "the rule needs no tuned constant"):
restrict the gating mean to the screens this capture actually scored, then compare. A real
divergence is untouched, because the routes in #713's r147 case fall THROUGH to the landing page
rather than blanking — they are captured, scored, and stay in both populations.
"""
import inspect
import json
import logging
import pathlib
import tempfile

import pytest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf


_LOGGER = "multi_agent.runtime.visual_fidelity"
_TWELVE = ["browse_by_languages", "browse_home", "games", "genre_category", "landing",
           "login", "movies", "my_list", "new_and_popular", "player", "shows", "title_detail"]
# r148 round 1, from rounds.jsonl.
_ROUND1 = {"browse_by_languages": 0.55, "browse_home": 0.80, "games": 0.62,
           "genre_category": 0.60, "landing": 0.45, "login": 0.40, "movies": 0.70,
           "my_list": 0.70, "new_and_popular": 0.75, "player": 0.55, "shows": 0.55,
           "title_detail": 0.60}


def _row(name, sim, *, blank=False):
    return {"name": name, "route": "/" + name, "similarity": sim, "passed": sim >= 0.65,
            "dimensions": {}, "deviations": [], "blank": blank, "advisory": False,
            "screenshot": None if blank else f"{name}.png", "reference": f"ref/{name}.png"}


def _persist(project_dir, results):
    vf._persist_verdict(project_dir, passed=False, min_similarity=0.65,
                        summary="t", coverage=None, results=results)


def _fires(caplog):
    return [r for r in caplog.records if "#711 the gating average" in r.getMessage()]


@pytest.fixture
def project():
    with tempfile.TemporaryDirectory() as td:
        yield pathlib.Path(td)


# --- the false positive is gone ------------------------------------------------------------

def test_r148_round_4_no_longer_warns(project, caplog):
    """The exact capture that produced both of #711's firings."""
    _persist(project, [_row(n, _ROUND1[n]) for n in _TWELVE])
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        _persist(project, [_row(n, 0.0, blank=True) if n not in ("landing", "login")
                           else _row(n, _ROUND1[n]) for n in _TWELVE])
    assert not _fires(caplog), [r.getMessage() for r in _fires(caplog)]


def test_the_run_wide_gap_that_used_to_trigger_it_is_still_there(project, caplog):
    """Non-vacuity: the fix must not work by making the old inputs disappear. The two
    run-wide numbers still differ by ~0.19 — the comparison changed, not the data."""
    _persist(project, [_row(n, _ROUND1[n]) for n in _TWELVE])
    _persist(project, [_row(n, 0.0, blank=True) if n not in ("landing", "login")
                       else _row(n, _ROUND1[n]) for n in _TWELVE])
    v = json.loads((project / "design" / "visual_gate" / "verdict.json").read_text())
    g, l = v["blocking_average"], v["blocking_average_live"]
    assert g - l >= 0.05, f"the old condition must still hold on the raw numbers: {g} vs {l}"
    assert abs(l - 0.425) < 0.01, l


def test_a_single_blank_screen_does_not_warn_either(project, caplog):
    """The smallest version of the same artefact."""
    _persist(project, [_row(n, 0.80) for n in _TWELVE])
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        _persist(project, [_row(n, 0.0, blank=True) if n == "player" else _row(n, 0.80)
                           for n in _TWELVE])
    assert not _fires(caplog)


# --- a real divergence must still fire (the negative control) ---------------------------------

def test_a_real_regression_still_warns(project, caplog):
    """#713's r147 shape: routes fall THROUGH to the landing page. They are captured and
    scored, so they stay in both populations and the warning is still correct."""
    _persist(project, [_row(n, _ROUND1[n]) for n in _TWELVE])
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        _persist(project, [_row(n, 0.05) if n in ("browse_by_languages", "genre_category",
                                                  "new_and_popular", "player")
                           else _row(n, _ROUND1[n]) for n in _TWELVE])
    assert _fires(caplog), "a real fall-through regression must not be silenced"


def test_a_regression_confined_to_the_captured_screens_warns(project, caplog):
    """The hard case: MOST screens blanked, and the few that captured really did get worse.
    Restricting to the captured population must still see it."""
    _persist(project, [_row(n, _ROUND1[n]) for n in _TWELVE])
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        _persist(project, [_row(n, 0.0, blank=True) if n not in ("landing", "login")
                           else _row(n, 0.05) for n in _TWELVE])
    assert _fires(caplog), "a genuine drop on the surviving screens must survive the fix"


def test_the_warning_reports_the_population_it_compared(project, caplog):
    _persist(project, [_row(n, _ROUND1[n]) for n in _TWELVE])
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        _persist(project, [_row(n, 0.05) for n in _TWELVE])
    msg = _fires(caplog)[0].getMessage()
    assert "over the 12 screen(s) THIS capture scored" in msg
    assert "run-wide the two are" in msg


# --- the mechanism is the restriction, not a threshold ------------------------------------------

def _block() -> str:
    src = inspect.getsource(vf._persist_verdict)
    i = src.index("#736: COMPARE LIKE WITH LIKE")
    return src[i:src.index("except Exception:", i)]


def test_the_gating_mean_is_restricted_to_the_live_population():
    b = _block()
    assert "_names736 = {s.get(\"name\") for s in _live_blocking}" in b
    assert "for s in _blocking_merged if s.get(\"name\") in _names736" in b


def test_no_new_tuned_constant_was_introduced():
    """#656's rule. The only number in the condition is #711's original 0.05."""
    b = _block()
    cond = [l for l in b.split("\n") if "_g736 - _l711 >=" in l]
    assert cond and "0.05" in cond[0], cond
    assert "_TRANSIENT_REFUND_CAP" not in b
    assert "len(_cmp736) >" not in b and "len(_cmp736) <" not in b


def test_the_comparison_is_on_the_restricted_number():
    """The bug would come straight back if the condition still read _g711."""
    b = _block()
    assert "_g711 - _l711 >=" not in b


# --- provenance ---------------------------------------------------------------------------------

def test_the_false_positive_rate_is_recorded():
    b = " ".join(_block().replace("#", " ").split())
    assert "fired 2 times and BOTH are this artefact" in b
    assert "100% false-positive firing history" in b


def test_the_worked_example_is_recorded():
    b = " ".join(_block().replace("#", " ").split())
    assert "r148 round 4" in b
    assert "0.6190 over 12" in b and "0.4250 over the only two that captured" in b
    assert "attempt refunded" in b


def test_it_records_why_a_real_divergence_survives():
    b = " ".join(_block().replace("#", " ").split())
    assert "713's r147 case is four routes falling THROUGH to the landing page" in b


def test_the_original_711_finding_is_not_overwritten():
    """#711's underlying observation — the gating number never falls — is still true and
    still stated. #736 narrows WHEN it is reported, not whether it is real."""
    b = _block()
    assert "best-ever-per-screen and never falls" in b
    assert "the RECORD on disk overstates the app" in b


def test_the_withdrawn_consequence_is_not_emitted_to_the_log():
    """The message used to end with the claim that a release authorised on the gating number
    ships the live one. That sentence is WRONG — #711r measured it: the release path reads the
    RETURNED dict (the current capture), not the persisted high-water number this warning is
    about. It stayed in the emitted text for two fixes after the retraction, so every reader of
    a real run log was told it. This is the same trap as #726's — an assertion that a withdrawn
    sentence is PRESENT certifies it — and the first version of this very test file had one."""
    b = _block()
    assert "authorised on the former ships the latter" not in b
    assert "NOT what authorises a release" in b
    assert "measured false" in b


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
