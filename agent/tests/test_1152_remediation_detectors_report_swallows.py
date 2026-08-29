"""#1152: a remediation detector that could not run must say so.

`delivery_gate._swallowed_790` has existed since r148 and is used 9 times --
all of them inside that one file.  `remediation_dispatcher` is where the
framework decides WHAT TO TELL A LANE, and four of its detectors answered a
raised exception with `[]`: the same value they return when the codebase is
clean.  A broken detector and "nothing to remediate" were the same observation,
and either way the lane heard nothing.  That is the shape of r4/r7/r9/r10 --
a run ends 1-3 checks short with no remediation ever filed for them.
"""
import re
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime import delivery_gate as dg
from env_generator.llm_generator.multi_agent.runtime import remediation_dispatcher as rd

SRC = Path(rd.__file__).read_text(encoding="utf-8")
FOUR = ("_chain_broken_detail_798", "_ui_flow_missing_names",
        "_ui_evidence_failed_pages", "_ui_flow_failed_names")


def _body(fn):
    """Anchor on the def and stop at the next top-level def (#943: never a
    fixed byte window)."""
    i = SRC.index("def %s(" % fn)
    j = SRC.index("\ndef ", i + 1)
    return SRC[i:j]


def test_the_reporter_reaches_the_gates_own_channel():
    before = len(dg.check_errors_790())
    rd._swallowed_1152("unit_test_probe", RuntimeError("boom"), "[] = nothing")
    after = dg.check_errors_790()
    assert len(after) == before + 1
    assert any("unit_test_probe" in n and "RuntimeError" in n for n in after), after


def test_the_reporter_never_raises():
    class Nasty(BaseException):
        def __str__(self):  # a reporter must survive a hostile exception
            raise ValueError("nope")
    rd._swallowed_1152("probe2", Nasty(), "[]")   # must not propagate


def test_each_detector_reports_before_returning_empty():
    for fn in FOUR:
        b = _body(fn)
        assert "_swallowed_1152(" in b, "%s still swallows silently" % fn
        assert "except Exception as _exc_1152:" in b, fn


def test_no_bare_silent_empty_return_left_in_those_four():
    """The exact shape that made the defect invisible."""
    bare = re.compile(r"except Exception:\s*\n\s*return \[\]")
    for fn in FOUR:
        assert not bare.search(_body(fn)), "%s: bare silent `return []`" % fn


def test_the_gate_reporter_is_reused_not_reinvented():
    """A second channel would leave the two halves of one question in two
    places; #790's list is where a release's unverified axes are read."""
    i = SRC.index("def _swallowed_1152(")
    body = SRC[i:SRC.index("\ndef ", i + 1)]
    assert "from .delivery_gate import _swallowed_790" in body
    assert "#1152" in body
