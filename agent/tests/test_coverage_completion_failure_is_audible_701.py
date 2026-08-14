r"""#701: the fix for the #1 recurring stuck-blocker could fail silently and leave the blocker.

Third sweep of the "computed but never consumed" family, and the first to look at SWALLOWS rather
than at unread values: every `except ...: pass` in the runtime whose guarded body calls something
detector-shaped (audit/check/detect/validate/verify/blocker/coverage/probe/scan/assert). Ten sites;
most are the documented and correct "a hiccup must never wedge the gate" pattern. One is not just
that.

`delivery_gate` wraps `complete_coverage_chain(hubs)`, and the comment two lines above it says what
that call is for:

    "COVERAGE-BY-CONSTRUCTION (2026-07-01): once the verifier authored real chains, let the
     framework complete the mechanical api-coverage gap (the #1 recurring stuck-blocker —
     run-12/run-19 wedged 78min here)."

When it raises, no `kind="coverage"` chain is registered, the api-coverage check immediately below
finds the mechanical gap this call exists to close, and the run wedges on precisely the blocker the
call prevents. Nothing said the prevention had failed, so the wedge reads as a verifier failure.

The swallow is kept — a coverage-completion hiccup genuinely must not crash the gate, and the check
below still runs correctly. What was wrong is that "completed" and "crashed, so the next 78 minutes
are for nothing" were indistinguishable. Same disposition as #691, #696, #698 and #700: keep the
behaviour, end the silence.
"""
import inspect
import logging

import pytest

from env_generator.llm_generator.multi_agent.runtime import delivery_gate as dg


def _block() -> str:
    src = inspect.getsource(dg)
    # The INDENTED call, not the def: `def complete_coverage_chain(hubs)` contains the same
    # substring, and anchoring on it silently returned the whole function body instead.
    i = src.index("\n        complete_coverage_chain(hubs)")
    j = src.index("chains = rh.get_verification_chains()", i)
    return src[i:src.rfind("\n", i, j) + 1]


# --- the failure is now audible ---------------------------------------------------------------

def test_the_handler_no_longer_only_passes():
    b = _block()
    assert "except Exception as _e:" in b
    assert "_LOG_701.warning(" in b


def test_the_exception_is_named_in_the_message():
    b = _block()
    assert "type(_e).__name__" in b
    assert "_e)" in b


def test_it_says_what_the_consequence_will_be():
    b = " ".join(_block().split())
    assert "the api-coverage check below will report the mechanical gap" in b


def test_it_tells_the_reader_not_to_blame_the_verifier():
    """The whole cost of the silence was mis-attributing the wedge."""
    b = " ".join(_block().split())
    assert "SYMPTOM of it, not a verifier failure" in b


def test_the_logging_itself_cannot_raise():
    """A warning about a swallowed error must not become an unswallowed one."""
    b = _block()
    inner = b[b.index("_LOG_701.warning("):]
    assert "except Exception:" in inner and "pass" in inner


# --- the behaviour is unchanged -----------------------------------------------------------------

def test_the_call_is_still_guarded():
    b = _block()
    assert "try:" in b
    assert "complete_coverage_chain(hubs)" in b


def test_it_does_not_re_raise():
    b = _block()
    code = "\n".join(l for l in b.split("\n")
                     if l.strip() and not l.strip().startswith("#"))
    assert "raise" not in code


def test_it_does_not_return_early():
    b = _block()
    code = "\n".join(l for l in b.split("\n")
                     if l.strip() and not l.strip().startswith("#"))
    assert "return" not in code


def test_the_coverage_check_still_follows():
    src = inspect.getsource(dg)
    # The INDENTED call, not the def: `def complete_coverage_chain(hubs)` contains the same
    # substring, and anchoring on it silently returned the whole function body instead.
    i = src.index("\n        complete_coverage_chain(hubs)")
    assert "chains = rh.get_verification_chains()" in src[i:]


def test_the_module_logger_exists():
    assert isinstance(dg._LOG_701, logging.Logger)


# --- provenance -----------------------------------------------------------------------------------

def test_the_stakes_are_recorded():
    b = " ".join(_block().replace("#", " ").split())
    assert "the 1 recurring stuck-blocker" in b
    assert "78min" in b


def test_why_the_swallow_is_kept_is_recorded():
    b = " ".join(_block().replace("#", " ").split())
    assert "must never crash the gate" in b
    assert "the check below still runs" in b


def test_it_names_the_sibling_findings():
    b = " ".join(_block().replace("#", " ").split())
    for n in ("691", "696", "698", "700"):
        assert n in b


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
