r"""#657: a screen stuck on the profile picker was reported as "the SPA never hydrated".

Two different causes append to the same `blank_screens` list:

    the profile picker was still up after every reselect retry      (the SPA hydrated fine)
    the DOM was a bare <div id=root> shell after a ~5s re-poll      (the SPA never hydrated)

and the deviation built from that list names only the second one, ending "fix the page's
mount/data load, not its styling". For a picker-stuck screen every clause of that is wrong: the
page mounted, the data loaded, and what actually happened is that the app rendered the
who's-watching chooser instead of the route. The lane is sent after a bug that does not exist.

This one carries no frequency measurement, and the reason is the defect itself: the two causes
are indistinguishable in every artifact the run leaves behind — same list, same message, no log
line on the picker path. The conflation is what makes it unmeasurable, and #657 is what makes it
measurable from here on. (Same reasoning #650 recorded for its own undecidable question.)

Same family as #634/#635/#636/#642/#650: an error whose text does not match the condition costs
the lane a whole round.
"""
import inspect

import pytest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf


# --- the two causes are separated at the source ----------------------------------------------

def test_the_capture_accepts_a_picker_list():
    assert "picker_screens" in inspect.signature(vf.capture_route_screenshots).parameters


def test_the_picker_list_is_optional():
    """Callers that predate #657 must keep working."""
    assert inspect.signature(vf.capture_route_screenshots).parameters["picker_screens"].default is None


def test_the_picker_branch_records_both_lists():
    """It must STAY in blank_screens: the refund and the #542a exclusion both key off it."""
    src = inspect.getsource(vf.capture_route_screenshots)
    i = src.index("if _still_picker:")
    branch = src[i:src.index("continue", i)]
    assert "picker_screens.append" in branch
    assert "blank_screens.append" in branch


def test_the_shell_branch_does_not_claim_the_picker():
    src = inspect.getsource(vf.capture_route_screenshots)
    i = src.index("_CAPTURE_BLANK_PROBE")
    shell = src[i:src.index("if _scheme:", i)]
    assert "blank_screens.append" in shell
    assert "picker_screens.append" not in shell


# --- the message now matches the condition -------------------------------------------------------

def _dev_branch():
    src = inspect.getsource(vf.run_visual_fidelity)
    i = src.index('if screen["name"] in _picker_screens:')
    return src[i:src.index("results.append(", i)]


def test_the_picker_gets_its_own_deviation():
    body = _dev_branch()
    assert "PROFILE PICKER" in body
    assert "who's-watching" in body


def test_it_no_longer_claims_the_spa_failed_to_hydrate():
    body = _dev_branch()
    picker = body[:body.index('elif screen["name"] in _blank_screens:')]
    assert "never hydrated" not in picker
    assert "mount/data load, not its styling" not in picker


def test_it_says_what_is_actually_fine():
    """The #634 lesson: a message that only says 'broken' costs a round of guessing."""
    body = _dev_branch()
    assert "mount and data load are fine" in body


def test_it_names_the_real_ask():
    body = _dev_branch()
    assert "make profile selection persist" in body


def test_the_route_is_still_named():
    assert "route {screen['route']}" in _dev_branch()


def test_the_shell_message_is_unchanged_for_real_shells():
    src = inspect.getsource(vf.run_visual_fidelity)
    i = src.index('elif screen["name"] in _blank_screens:')
    shell = src[i:src.index('else:', i)]
    assert "rendered BLANK" in shell
    assert "never hydrated" in shell
    assert "fix the page's mount/data load, not its styling" in shell


# --- ordering and bookkeeping --------------------------------------------------------------------

def test_the_picker_branch_is_checked_first():
    """Every picker screen is also a blank screen, so the specific case must win."""
    src = inspect.getsource(vf.run_visual_fidelity)
    assert src.index('in _picker_screens:') < src.index('in _blank_screens:')


def test_the_remint_retry_clears_both_lists():
    """#105 re-captures after a re-mint; a stale picker name would mislabel a good screen."""
    src = inspect.getsource(vf.run_visual_fidelity)
    assert "_blank_screens.clear()\n            _picker_screens.clear()" in src


def test_the_no_playwright_path_defines_it_too():
    """The else-branch must define the name or the deviation lookup raises."""
    src = inspect.getsource(vf.run_visual_fidelity)
    assert src.count("_picker_screens = []") >= 1
    assert src.count("_picker_screens: List[str] = []") == 1


def test_why_there_is_no_frequency_number_is_recorded():
    """This codebase expects a measurement; the absence of one has to be justified in place."""
    src = inspect.getsource(vf.capture_route_screenshots)
    i = src.index("if _still_picker:")
    flat = " ".join(src[i:src.index("continue", i)].replace("#", " ").split())
    assert "the SPA never hydrated" in flat
    assert "works fine" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
