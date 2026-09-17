r"""#696: a 500 rendered as "Titles you add will appear here", and nothing anywhere could tell.

Found by auditing what r146 SHIPPED, on the frontend this time. Every projected page fetch ends:

    .then((r) => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
    .then(setData)
    .catch((e) => setError(/\bHTTP\b/.test(String(e)) ? '' : String(e)));

It throws `HTTP <status>` and then discards exactly that error. The suppression is deliberate and
documented — "HTTP-status failure suppresses to the graceful empty/loading catalog state (a
genuine network/parse error still shows). Generalizable." — and it is not changed here. It was
added for a measured reason (r104 new_and_popular) and a raw fetch error painted across a page is
worse than an empty state.

The unintended half is that it makes a server failure indistinguishable from an empty dataset,
in both directions that matter:

    the USER       is told "Titles you add will appear here." while /api/my-list is 500ing
    the FRAMEWORK  judges a screenshot of a clean, plausible, well-scoring page

That second one is the #566x shape: the harm is invisible precisely BECAUSE nothing looks broken.
A visual gate cannot flag a page that looks fine, and this page looks fine.

The fix costs nothing visually — not one pixel — and reuses a detector that is already running:
`browser_navigate` returns `console_errors`, filtered to `type == "error"`. So the suppressed
branch now writes one. The error text still never reaches the DOM.
"""
import inspect
import re

import pytest

from env_generator.llm_generator.multi_agent.runtime import frontend_scaffold as fs


SRC = inspect.getsource(fs)
_CATCH = re.compile(r"\.catch\(\(e\) => \{[^\n]*?\}\)")


def _catches():
    return _CATCH.findall(SRC)


# --- every projected catch reports, and there are no stragglers ---------------------------------

def test_all_three_projected_catches_were_updated():
    assert len(_catches()) == 3


def test_no_silent_catch_survives():
    """The old one-liner discarded the error with no trace at all."""
    assert ".catch((e) => setError(/\\\\bHTTP\\\\b/.test(String(e)) ? '' : String(e)))" not in SRC


@pytest.mark.parametrize("i", [0, 1, 2])
def test_each_catch_logs_the_suppressed_failure(i):
    assert "console.error(" in _catches()[i]


@pytest.mark.parametrize("i", [0, 1, 2])
def test_each_catch_shows_the_http_failure(i):
    """#1202qm reversed #536's suppression: an HTTP failure reaches the page as a readable
    sentence instead of passing for an empty dataset."""
    assert "setError('')" not in _catches()[i]
    assert "setError('Could not load this data (' + String(e) + ')')" in _catches()[i]


@pytest.mark.parametrize("i", [0, 1, 2])
def test_a_genuine_error_still_reaches_the_ui(i):
    """Network/parse errors were always shown and must stay shown."""
    assert "setError(String(e))" in _catches()[i]


@pytest.mark.parametrize("i", [0, 1, 2])
def test_the_status_test_is_unchanged(i):
    assert "/\\\\bHTTP\\\\b/.test(String(e))" in _catches()[i]


# --- the emitted JS is well-formed ---------------------------------------------------------------

def test_the_branches_are_balanced():
    for c in _catches():
        assert c.count("{") == c.count("}")
        assert c.count("(") == c.count(")")


def test_the_log_line_is_identifiable_in_a_console_dump():
    """A browser-lane console_errors entry has to be attributable to this projection."""
    for c in _catches():
        assert "[projected] data load failed:" in c


def test_the_log_carries_the_error_itself():
    for c in _catches():
        assert "+ String(e)" in c


def test_exactly_one_catch_omits_the_trailing_semicolon():
    """Two sites end a statement, one is mid-chain before .finally — keep that split."""
    semis = [c for c in re.findall(r"\.catch\(\(e\) => \{[^\n]*?\}\);", SRC)]
    assert len(semis) == 2


# --- the empty state that made it invisible ------------------------------------------------------

def test_the_graceful_empty_state_is_untouched():
    assert "Titles you add will appear here." in SRC


def test_the_loading_state_is_untouched():
    # raw: the Python source emits `…` to JS, so the source text carries TWO backslashes.
    assert r"loading ? 'Loading\\u2026'" in SRC


# --- provenance -----------------------------------------------------------------------------------

def _doc() -> str:
    return fs._owned_list_shell_src_535.__doc__ or ""


def test_the_deliberate_half_is_recorded_as_deliberate():
    d = _doc()
    assert "DELIBERATE and unchanged" in d
    assert "r104's" in d


def test_the_unintended_half_is_recorded():
    d = " ".join(_doc().split())
    assert "indistinguishable from an empty dataset" in d
    assert "Titles you add will appear here" in d


def test_it_names_the_class_of_bug():
    assert "#566x shape" in _doc()
    assert "invisible BECAUSE nothing looks broken" in " ".join(_doc().split())


def test_it_records_why_console_error_is_the_right_channel():
    d = " ".join(_doc().split())
    assert "browser_navigate` returns `console_errors`" in d
    assert "Not one pixel changes" in d


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
