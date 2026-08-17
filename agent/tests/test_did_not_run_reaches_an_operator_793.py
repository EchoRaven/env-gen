r"""#793: the three "did not run" reporters had no consumer — I committed #779/#786's defect
three times in a row, immediately after writing the rule down.

#786's finding, from this same session: `copy` was added to the design-prep schema, wired through
both projections, tested — the whole WRITE path — and **nothing read it**. The lesson recorded
there was: *"a field is not done when it is produced and tested; it is done when something
CONSUMES it. The write path is the easy half AND the half that has tests, which is why it feels
finished."*

Then #790, #791 and #792 each added a reporter:

    checks_errored_790   readers: delivery_gate.py   (its own definition + the result key)
    scan_errors_791()    readers: frontend_audit.py  (its own definition)
    gates_absent_792()   readers: NONE ANYWHERE

Three for three. The tests referenced them, which is what made it feel finished — a test is not a
consumer. `checks_errored_790` was even placed in the gate's returned dict, and **no caller reads
that key**, so it travelled exactly as far as a log line would have.

The consumer is `_validate_delivery_gate` in the orchestrator: the single funnel all six gate call
sites pass through. Merging there reaches every gate tick, puts all three facts in the returned
dict under `did_not_run_793`, and emits one operator-visible line at the tick where a release may
be cut.

★ Self-application is the only reliable check here. The rule was fresh, written by me, in this
session, about this exact mistake — and it still did not fire while I was making it three more
times. What caught it was going back and *running the rule as a query* against my own diff, not
remembering it.
"""
import inspect
import logging

import pytest

from env_generator.llm_generator.multi_agent import orchestrator as orch
from env_generator.llm_generator.multi_agent.runtime import delivery_gate as dg
from env_generator.llm_generator.multi_agent.runtime import deliverability as dv
from env_generator.llm_generator.multi_agent.runtime import frontend_audit as fa


_SRC = inspect.getsource(orch.MultiAgentOrchestrator._validate_delivery_gate) \
    if hasattr(orch, "MultiAgentOrchestrator") else None


def _funnel_src():
    for name in dir(orch):
        obj = getattr(orch, name)
        if inspect.isclass(obj) and hasattr(obj, "_validate_delivery_gate"):
            return inspect.getsource(obj._validate_delivery_gate)
    raise AssertionError("the gate funnel moved")


def test_all_three_reporters_are_consumed():
    src = _funnel_src()
    for sym in ("checks_errored_790", "scan_errors_791", "gates_absent_792"):
        assert sym in src, f"{sym} is still a writer with no reader"


def test_the_facts_travel_in_the_returned_dict():
    """A log line is not enough — #788's lesson is that nobody reads for an absence, and
    `checks_errored_790` proved it by sitting in a dict key no caller opened."""
    src = _funnel_src()
    assert '_gate793["did_not_run_793"] = _did_not_run' in src
    assert "return _gate793" in src


def test_the_operator_line_says_the_verdict_is_unverified():
    src = _funnel_src()
    assert "HAVE NOT RUN at some point this run" in src
    assert "UNVERIFIED on these axes, whatever the gate says" in src


def test_the_line_does_not_claim_the_failure_just_happened():
    """#801: it said "this tick". The three reporters are RUN-lifetime records, so one failure
    made this line repeat every tick for the rest of the run, each time claiming the failure had
    just occurred. Cumulative is the right semantics at a release cut — the question there is
    "was this axis ever unverified" — so only the label was wrong. A signal that overstates is
    how a reader learns to skip it."""
    src = _funnel_src()
    assert "this tick" not in src.split("#793")[1].split("return _gate793")[0] \
        or "not necessarily this tick" in src
    assert "cumulative" in src


def test_it_is_silent_when_everything_ran():
    """Non-vacuity in the other direction: a line that fires on healthy runs gets filtered out,
    which is how a signal becomes decoration."""
    src = _funnel_src()
    i = src.index("if _did_not_run:")
    assert src.index("warning", i) > i, "the log must be inside the non-empty branch"


def test_the_merge_cannot_break_the_gate():
    """It runs on the release path and imports two other modules to do it."""
    src = _funnel_src()
    assert "except Exception:" in src
    assert "a reporter must never break the gate it reports on" in src


def test_a_reporter_failure_still_yields_the_790_facts():
    """The fallback keeps the one source that needs no import."""
    src = _funnel_src()
    tail = src[src.index("except Exception:"):]
    assert 'checks_errored_790' in tail


# --- the reporters themselves still work (non-vacuity for the whole chain) ------------------------

def test_the_three_sources_are_live():
    dg.reset_check_errors_790()
    fa.reset_scan_errors_791()
    dv.reset_said_700()
    assert dg.check_errors_790() == []
    assert fa.scan_errors_791() == []
    assert dv.gates_absent_792() == []

    dg._swallowed_790("f", RuntimeError("a"), "d")
    fa._scan_truncated_791("g", RuntimeError("b"), 1)
    dv._gate_absent_792("h", RuntimeError("c"), "run")
    try:
        assert len(dg.check_errors_790()) == 1
        assert len(fa.scan_errors_791()) == 1
        assert len(dv.gates_absent_792()) == 1
    finally:
        dg.reset_check_errors_790()
        fa.reset_scan_errors_791()
        dv.reset_said_700()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
