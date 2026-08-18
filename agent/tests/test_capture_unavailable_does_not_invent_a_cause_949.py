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
    b = _branch()
    assert "_cap_err935" in b and "the capture raised" in b


def test_it_marks_the_guess_as_a_guess():
    """★ When no exception was recorded the app IS the likely cause — but likely is not known,
    and the word has to appear or the sentence is the old assertion with softer grammar."""
    assert "unverified" in _branch()


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
