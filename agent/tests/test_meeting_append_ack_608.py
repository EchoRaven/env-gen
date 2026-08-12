r"""#608: an APPEND returned the whole page it had just grown.

Fifth finding on the cost axis (after #604 check_inbox, #605 terminal task ack, #606 document
listing, #607 asset listing). `workhub_add_meeting_decision` handed back the entire meeting page
— including `metadata['decisions']`, which the call had just appended to — so the Nth append
re-serialises all N decisions and the cost grows with the square of the meeting's length.

Over the arc's 58 meeting pages the median ends at **72,879 chars with 62 decisions**
(max 103 / 102,405). Measured from the run logs the tool returned **4.80M tokens over 350 calls**
(avg 13.7k) — for an append whose useful answer is "stored, that's now N".

`workhub_close_meeting` echoed the same accumulated page and gets the same trim.
`workhub_create_meeting` is deliberately left alone: it returns a page the caller does not have
yet, and a fresh page has no decisions to elide.
"""
import inspect
import json

import pytest

from env_generator.llm_generator.tools import hub_tools as ht


def _page(n_decisions, dec_chars=2000):
    return {"id": "doc_m1", "kind": "meeting", "title": "M1 kickoff", "status": "open",
            "attendees": ["backend", "frontend"],
            "metadata": {"decisions": [{"content": "x" * dec_chars} for _ in range(n_decisions)]}}


# --- the hint -------------------------------------------------------------------------------

def test_the_hint_reports_the_running_count_and_where_to_read():
    h = ht._meeting_hint_608(_page(62), "m1")
    assert "62 decisions" in h
    assert "workhub_get_document(document_id='doc_m1')" in h


def test_the_hint_falls_back_to_the_meeting_id_when_the_page_has_none():
    assert "document_id='m1'" in ht._meeting_hint_608({"metadata": {}}, "m1")


def test_the_hint_survives_a_junk_page():
    for p in (None, {}, {"metadata": None}, {"metadata": {"decisions": None}}):
        assert "0 decisions" in ht._meeting_hint_608(p, "m1")


# --- the trim -----------------------------------------------------------------------------------

def test_the_accumulated_decisions_are_elided():
    out = ht._elide_large_fields(_page(62), ht._meeting_hint_608(_page(62), "m1"))
    assert "chars omitted" in out["metadata"]
    assert "62 decisions" in out["metadata"]


def test_every_small_field_of_the_page_is_byte_identical():
    p = _page(62)
    out = ht._elide_large_fields(p, "h")
    for f in ("id", "kind", "title", "status", "attendees"):
        assert out[f] == p[f], f


def test_a_meeting_with_one_short_decision_is_untouched():
    p = {"id": "doc_m1", "metadata": {"decisions": [{"content": "ok"}]}}
    assert ht._elide_large_fields(p, "h") == p


def test_the_growth_it_removes_is_real():
    """The Nth append used to carry all N decisions; now it carries none of them."""
    before = len(json.dumps(_page(62)))
    after = len(json.dumps(ht._elide_large_fields(_page(62), ht._meeting_hint_608(_page(62), "m1"))))
    assert before > 100_000 and after < 1_000


# --- where it is applied, and where it must NOT be ------------------------------------------------

def _tool_src(name):
    cls = next(c for _, c in vars(ht).items()
               if inspect.isclass(c) and getattr(c, "NAME", "") == name)
    return inspect.getsource(cls)


def test_the_append_uses_it():
    src = _tool_src("workhub_add_meeting_decision")
    assert "_elide_large_fields(page, _meeting_hint_608(page, meeting_id))" in src


def test_closing_uses_it_too():
    src = _tool_src("workhub_close_meeting")
    assert "_elide_large_fields(page, _meeting_hint_608(page, meeting_id))" in src


def test_CREATING_a_meeting_still_returns_the_page_whole():
    """A fresh page is what the caller asked for and has no decisions to elide."""
    src = _tool_src("workhub_create_meeting")
    assert "return ToolResult.ok(data=page)" in src
    assert "_elide_large_fields" not in src


def test_an_error_page_still_fails_the_call():
    for name in ("workhub_add_meeting_decision", "workhub_close_meeting"):
        src = _tool_src(name)
        i = src.index("_elide_large_fields")
        assert 'return ToolResult.fail(page["error"])' in src[:i], name


def test_the_measurement_that_justifies_it_is_recorded():
    src = _tool_src("workhub_add_meeting_decision")
    assert "4.80M tokens over 350 calls" in src and "72,879" in src


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
