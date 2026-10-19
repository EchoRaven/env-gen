r"""#769: a screen that could not be photographed left no trace at all.

The per-screen capture body ended:

    except Exception:
        continue

So a navigation timeout, a closed page and a proxy refusal were indistinguishable from each
other and from nothing happening — and downstream the screen becomes a hard 0.00 that COUNTS
against the gate (#542's invariant, and #768r kept it deliberately).

r150 is what that costs. Its final round captured 3 of 12 screens and scored NINE zeros, and the
zeros track missing captures exactly, round by round:

    shots written   4    0    2    5    3
    zeros           0    7    4    6    9

The app was fine — captures from the earlier rounds are a complete Netflix clone with a working
title-detail modal and player. So the gate reported 0.1727 about the HARNESS, and nothing
anywhere said so.

Same shape as #748 one layer up: the reason existed, was caught, and was discarded at the
`except`. This is the third time this session that a swallowed cause turned out to be the whole
answer (#748 compose, #740 console, this).
"""
import inspect

import pytest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf


def _src() -> str:
    return inspect.getsource(vf.capture_route_screenshots)


# --- the bare continue is gone -------------------------------------------------------------------

def test_the_handler_no_longer_swallows_silently():
    s = _src()
    assert "except Exception as _cap769:" in s
    assert "#769 capture FAILED for screen" in s


def _cap769_handler():
    """The `except Exception as _cap769:` handler, from the parse tree.

    #1203pg: not a source span. The span version asserted `"continue" in blk`, and a mutation
    that DELETED this handler's own `continue` survived — fed by a different `continue`
    elsewhere in the same span. The statement has to be located, not spelled.
    """
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(vf))
    hits = [h for n in ast.walk(tree) if isinstance(n, ast.Try)
            for h in n.handlers if getattr(h, "name", None) == "_cap769"]
    assert len(hits) == 1, "the #769 handler moved or multiplied: %d" % len(hits)
    return hits[0]


def test_the_exception_is_still_caught():
    """It must not start raising — one screen failing must never abort the whole capture."""
    import ast
    h = _cap769_handler()
    body = ast.unparse(h)
    assert "raise" not in body, body[:200]
    assert isinstance(h.body[-1], ast.Continue), (
        "the handler no longer ENDS in `continue`, so a screen whose capture raised falls "
        "through into scoring with no shot: %s" % ast.unparse(h.body[-1])[:120])


def test_the_handler_records_before_it_skips():
    """Order matters: a `continue` placed above the recorder would keep every assertion in this
    file green while recording nothing."""
    import ast
    h = _cap769_handler()
    stmts = [ast.unparse(s) for s in h.body]
    rec = next(i for i, s in enumerate(stmts) if "_record_capture_error_1203pg" in s)
    cont = next(i for i, s in enumerate(stmts) if s.strip() == "continue")
    assert rec < cont, stmts


def test_it_names_the_screen_and_the_route():
    s = _src()
    assert 'screen.get("name"), screen.get("route")' in s


def test_it_names_the_exception_TYPE():
    """A navigation timeout, a closed page and a proxy refusal are three different problems."""
    s = _src()
    assert "type(_cap769).__name__" in s


def test_the_message_is_bounded():
    s = _src()
    assert "str(_cap769)[:200]" in s


def test_it_says_the_zero_is_about_the_capture():
    """The line has to pre-empt the misreading, because the 0.00 it produces looks like a
    verdict on the page and is not."""
    # Adjacent string literals are joined first — the message wraps mid-sentence, and a plain
    # `" ".join(split())` leaves the quote characters inside the phrase. Same trap as #711's.
    import re
    flat = re.sub(r'"\s*\n\s*"', "", _src())
    assert "that zero is about the capture, not the page" in flat


# --- provenance --------------------------------------------------------------------------------------

def _prov() -> str:
    s = _src()
    i = s.index("#769: SAY WHY THE CAPTURE FAILED")
    return " ".join(l.strip().lstrip("#").strip() for l in s[i:s.index("_LOG.warning(", i)].split("\n"))


def test_the_r150_correlation_is_recorded():
    p = _prov()
    assert "captured 3 of 12 screens and" in p and "NINE zeros" in p
    assert "4 shots -> 0 zeros; 0 shots -> 7 zeros" in p


def test_it_records_that_the_app_was_fine():
    p = _prov()
    assert "The app was fine" in p
    assert "reported 0.1727 about the HARNESS" in p


def test_it_credits_the_pattern():
    p = _prov()
    assert "Same shape as #748 one layer up" in p


def test_it_records_that_the_downstream_zero_is_deliberate():
    """#768r decided the zero must still count. This line must not read as a plan to stop it."""
    p = _prov()
    assert "542's invariant, deliberately" in p


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))


# --- #1203pg: the PERSISTED half, driven ---------------------------------------------------------
#
# Every assertion above reads the source of a handler that only runs inside a live browser
# capture, so nothing could reach it. Three mutations proved it: the dict was never populated
# (leaving the reason in a logger the run directory does not persist -- exactly the state #935
# added the out-parameter to end), the message was dropped so only the exception TYPE survived,
# and the `continue` was removed so a failed screen fell through into scoring. All three MISSED,
# including the one meant as a control.
#
# The recorder is now `_record_capture_error_1203pg`, which is a plain function.

_REC = vf._record_capture_error_1203pg


def test_the_reason_is_recorded_under_the_screen_name():
    errs = {}
    _REC(errs, {"name": "title_detail", "route": "/title/1"}, TimeoutError("nav exceeded 30000ms"))
    assert list(errs) == ["title_detail"], errs
    assert errs["title_detail"].startswith("TimeoutError: ")


def test_the_MESSAGE_survives_not_only_the_type():
    """r154's whole cost was not knowing WHY. "TimeoutError" alone does not distinguish a
    navigation timeout from a closed page from a proxy refusal."""
    errs = {}
    _REC(errs, {"name": "s"}, RuntimeError("Target page, context or browser has been closed"))
    assert "browser has been closed" in errs["s"], errs["s"]


def test_a_long_message_is_bounded():
    errs = {}
    _REC(errs, {"name": "s"}, RuntimeError("x" * 5000))
    assert len(errs["s"]) <= 240, len(errs["s"])
    assert errs["s"].startswith("RuntimeError: ")


def test_a_caller_that_collects_nothing_is_not_an_error():
    """`None` means "this caller does not collect them" — it must not raise into the capture
    loop, because losing the whole capture is worse than losing one reason."""
    _REC(None, {"name": "s"}, RuntimeError("boom"))


def test_each_failed_screen_gets_its_own_entry():
    errs = {}
    _REC(errs, {"name": "a"}, TimeoutError("t"))
    _REC(errs, {"name": "b"}, RuntimeError("r"))
    assert sorted(errs) == ["a", "b"]
    assert "TimeoutError" in errs["a"] and "RuntimeError" in errs["b"]


def test_the_handler_calls_the_owner():
    """#1032: if the assignment is inlined again the property loses its driver."""
    s = _src()
    assert "_record_capture_error_1203pg(capture_errors, screen, _cap769)" in s
    assert 'capture_errors[str(screen.get("name"))]' not in s, (
        "the recorder was inlined back into the handler, where nothing can reach it")


def test_what_949_reports_is_what_this_recorded():
    """The two halves joined: #949's sentence is built from exactly this dict (#947's rule —
    a finding has to reach a reader, and the reader here is the lane's ledger)."""
    errs = {}
    _REC(errs, {"name": "browse_home"}, TimeoutError("nav exceeded 30000ms"))
    sentence = vf._capture_unavailable_summary_1203pg(12, errs)
    assert "browse_home" in sentence and "TimeoutError" in sentence
