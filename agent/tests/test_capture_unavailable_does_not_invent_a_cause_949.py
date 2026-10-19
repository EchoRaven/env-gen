r"""#949: "app not reachable" was asserted for every zero-capture round, verified for none.

`heal_missing_browser` re-raises when the playwright binary is missing and cannot be installed, so
a browser-infra failure reaches this branch and is reported as an app failure. That is a
mis-attribution, and mis-attribution is worse than silence: it sends the reader to the app. This
session lost a long detour to exactly that shape — #934's stale PNG, which said "working page"
about a screen that had not been photographed in ninety minutes.

#935's `_cap_err935` is already in scope here and holds the real exception per screen.
"""
import ast
import inspect

import pytest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf


def _branch():
    src = inspect.getsource(vf.run_visual_fidelity)
    i = src.index("#949: say what is KNOWN")
    return src[i:src.index("min_similarity\": min_similarity}", i)]


def test_it_no_longer_asserts_an_unverified_cause():
    src = inspect.getsource(vf.run_visual_fidelity)
    assert "capture unavailable — app not reachable" not in src


def test_it_says_how_many_screens_were_attempted():
    """A count is a fact. It was not there, and it is the first thing a reader needs."""
    assert "len(judged_screens)" in _branch()


def test_it_names_the_real_exception_when_one_was_recorded():
    """RE-AIMED at #1203pg's owner: the sentence moved into
    `_capture_unavailable_summary_1203pg`, and the branch now passes it `_cap_err935`. Driven
    below as well, which is what the source form could never do."""
    assert "_cap_err935" in _branch()
    assert "the capture raised" in inspect.getsource(vf._capture_unavailable_summary_1203pg)


def test_it_marks_the_guess_as_a_guess():
    """★ When no exception was recorded the app IS the likely cause — but likely is not known,
    and the word has to appear or the sentence is the old assertion with softer grammar.

    RE-AIMED at the owner (#1203pg), and driven in `TheSentenceItself` below."""
    assert "unverified" in inspect.getsource(vf._capture_unavailable_summary_1203pg)


def test_the_errors_travel_as_data_not_only_as_prose():
    """A caller should not have to parse a sentence to learn what raised (#947's rule)."""
    assert '"capture_errors": dict(_cap_err935)' in _branch()


def test_the_branch_still_reports_capture_unavailable():
    """The flag other code keys on must not move (#5272 reads it to refund the attempt)."""
    assert '"capture_unavailable": True' in _branch()


def test_the_summary_is_one_expression_not_a_silent_fallthrough():
    """AST: the summary must be a single conditional expression, so neither arm can be dropped."""
    src = inspect.getsource(vf.run_visual_fidelity)
    i = src.index("#949: say what is KNOWN")
    tree = ast.parse(inspect.getsource(vf))
    ifexps = [n for n in ast.walk(tree) if isinstance(n, ast.IfExp)
              and "the capture raised" in ast.dump(n)]
    assert len(ifexps) == 1, "one conditional, both arms present"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))


# --- #1203pg: both arms, DRIVEN ------------------------------------------------------------------
#
# All seven assertions above read the SOURCE, and three mutations walked through untouched:
#
#   * INVERTING the conditional -- so the sentence names a raised exception when none was
#     recorded, and says "no capture exception was recorded ... (unverified)" when one was.
#     That is mis-attribution, the exact thing #949 exists to stop.
#   * `len(judged_screens)` -> `len(judged_screens) - 1`, understating what was attempted.
#   * capping the error list at ZERO, so "the capture raised" is followed by only a cut note.
#
# None of them was reachable from a test before: `_cap_err935` is filled by the default
# `capture_route_screenshots` path, so a test that injects `capture_fn` always sees it empty and
# can only ever reach ONE arm. The sentence is now a pure function of (attempted, errors).

_SUM = vf._capture_unavailable_summary_1203pg


def test_with_an_exception_recorded_it_names_that_exception():
    s = _SUM(12, {"browse_home": "TimeoutError: nav exceeded 30000ms"})
    assert "the capture raised" in s
    assert "browse_home" in s and "TimeoutError" in s
    assert "unverified" not in s, "a KNOWN cause was reported as a guess"
    assert "most likely" not in s


def test_with_no_exception_recorded_it_marks_the_guess_as_a_guess():
    s = _SUM(12, {})
    assert "no capture exception was recorded" in s
    assert "unverified" in s, "the guess was stated as fact"
    assert "the capture raised" not in s, "it named an exception nobody recorded"


def test_a_missing_dict_is_the_same_as_an_empty_one_not_a_crash():
    assert "unverified" in _SUM(3, None)


def test_the_count_is_what_was_attempted():
    assert "0 of 12 screen(s) photographed" in _SUM(12, {})
    assert "0 of 1 screen(s) photographed" in _SUM(1, {})


def test_several_exceptions_are_listed_and_the_cut_is_declared():
    """#1034: a capped list must say it was capped, or the reader thinks three is all there was."""
    errs = {"s%d" % i: "TimeoutError: t" for i in range(7)}
    s = _SUM(7, errs)
    assert "the capture raised" in s
    assert "more" in s, "seven exceptions were cut to three with no note of the cut: %s" % s


def test_the_branch_passes_the_real_count_and_the_real_dict():
    """#1032: one owner only helps if the call site hands it the true inputs."""
    b = _branch()
    assert "_capture_unavailable_summary_1203pg(" in b
    assert "len(judged_screens)" in b and "_cap_err935" in b
