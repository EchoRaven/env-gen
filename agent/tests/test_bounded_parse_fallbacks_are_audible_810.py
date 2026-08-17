r"""#810: three bounded-slice fallbacks in the audit parsed a fragment and said nothing.

#802b/#809 established that a guard's own coverage is a claim needing checking. Running that over
the fixed-width-source-window guard: its scope is right (flat `tests/test_*.py`, and the tests dir
IS flat), but it only polices TEST assertions. The framework has fixed windows too:

    _tag_span             a 400-char forward slice from the tag start   unbalanced <Route ...>
    _tag_span             a 200-char BACKWARD slice from the match       no `<Route` before it
    _balanced_call_span   a 600-char forward slice from the open paren   unbalanced parens

(Described in words on purpose: the fixed-width-window guard greps test files for slice
expressions, so quoting these verbatim made it flag this very file — documentation matching the
thing it documents, the tenth self-match of the session.)

★ These are **legitimate**, and that is the interesting part. Unlike the nine window errors I made
in tests — where a window stood in *place of* an anchor — each of these is a bounded fallback
*after* a proper balanced scan, taken only when the source is genuinely malformed. The alternative
is reading to end-of-file. The defect was not the window; it was the **silence**.

`_balanced_call_span` feeds `bare_authed_fetch_blockers` (#791) — the release-BLOCKING path. A
truncated span there means the audit judged a call site it only half saw, and the error runs in
both directions: a missed blocker, or an invented one.

Reuses #791's say-once list rather than a fourth reporting mechanism (#792's lesson), so the fact
already reaches the delivery gate through #793's merge without any new wiring.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime import frontend_audit as fa


@pytest.fixture(autouse=True)
def _clean():
    fa.reset_scan_errors_791()
    yield
    fa.reset_scan_errors_791()


# --- silence on well-formed input (the overwhelmingly common case) --------------------------------

def test_a_balanced_call_reports_nothing():
    """Non-vacuity: the helper really does parse this, and quietly."""
    assert fa._balanced_call_span("fetch('/api/x')", 5) == "('/api/x')"
    assert fa.scan_errors_791() == []


def test_a_balanced_route_tag_reports_nothing():
    span = fa._tag_span("<Route path='/a' element={<A/>} />", 8)
    assert span.startswith("<Route")
    assert fa.scan_errors_791() == []


# --- each fallback is audible ---------------------------------------------------------------------

def test_an_unbalanced_call_says_it_parsed_a_fragment():
    fa._balanced_call_span("fetch('/api/x'" + "y" * 900, 5)
    errs = fa.scan_errors_791()
    assert errs and "_balanced_call_span" in errs[0]
    assert "600-char fragment" in errs[0]


def test_an_unterminated_route_tag_says_so():
    fa._tag_span("<Route path='/a' element={<A/>", 8)
    assert any("_tag_span" in e and "400" in e for e in fa.scan_errors_791())


def test_a_missing_route_prefix_says_so():
    """The third window, a BACKWARD one, which the first read of this file missed entirely."""
    fa._tag_span("path='/a'>", 0)
    assert any("no-<Route>-before" in e for e in fa.scan_errors_791())


def test_the_warning_says_the_verdict_is_unconfirmed(caplog):
    import logging
    with caplog.at_level(logging.WARNING):
        fa._balanced_call_span("fetch('(" + "y" * 900, 5)
    msg = " ".join(r.getMessage() for r in caplog.records)
    assert "AUDIT PARSED A FRAGMENT" in msg
    assert "or the absence of one, as unconfirmed" in msg, \
        "a missed blocker and an invented one are both possible; the note must say both"


def test_it_is_said_once():
    for _ in range(4):
        fa._balanced_call_span("fetch('/api/x'" + "y" * 900, 5)
    assert len(fa.scan_errors_791()) == 1


def test_the_reporter_cannot_break_the_parse():
    """It runs inside a parser on the release path."""
    fa._span_truncated_810("x", 1)          # must not raise
    assert fa.scan_errors_791()


# --- it reaches the operator through the existing pipeline ------------------------------------------

def test_it_reuses_791s_list_rather_than_adding_a_fourth_mechanism():
    """#792's lesson. It also means #793's merge already surfaces this at the delivery gate, with
    no new wiring — and #762's reset already clears it between tests."""
    import inspect
    src = inspect.getsource(fa._span_truncated_810)
    assert "_SCAN_ERRORS_791" in src
    fa._span_truncated_810("probe", 7)
    assert fa.scan_errors_791(), "the existing accessor must see it"


def test_all_three_fallbacks_are_wired():
    import inspect
    src = inspect.getsource(fa)
    assert src.count("_span_truncated_810(") >= 4, "3 call sites + the definition"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
