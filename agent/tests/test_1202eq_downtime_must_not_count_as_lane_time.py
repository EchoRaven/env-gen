r"""#1202eq: the "lane time" fail-fast counts hours in which no lane existed.

    (now - self._fwdeliver_first_decline_ts - live_credit) > FWVAL_NO_DELIVER_ABORT_S

`_fwdeliver_first_decline_ts` is a wall-clock stamp, it is PERSISTED across resumes, and
nothing subtracts the time a run spends stopped.

googlemaps-r16: its first gate decline was stamped 09:45. Resumed at 17:03 — after roughly
thirty minutes of actual work spread across the day — it aborted at once with "delivery
never SUCCEEDED in 437min of lane time since the contract built". The wall clock between
those two points is 438 minutes. The default ceiling is 5400s, so any run picked up more
than ninety minutes later is dead on arrival however little of that time it was alive.

That is the direct opposite of "resume from a good checkpoint to save money": the strategy
stops working the moment you take a break.

#1133 already exists for this shape of correction — "give back the time the FRAMEWORK
spent deferring delivery" — and downtime is the same claim: the lanes did not have it.
"""
import json
import sys
import time
from pathlib import Path

import pytest

THIS_DIR = Path(__file__).resolve().parent
ORCH_SRC = (THIS_DIR.parent / "env_generator" / "llm_generator" / "multi_agent"
            / "orchestrator.py").read_text(encoding="utf-8")


class _Orch:
    """Just enough orchestrator to exercise the credit.

    `_prev_alive_1202eq` mirrors what the real __init__ captures BEFORE #1170's early
    run_budget write can refresh the file — reading it later returns ~0s, which is exactly
    the bug this attribute exists to avoid.
    """
    def __init__(self, tmp, prev_alive=None):
        self.output_dir = str(tmp)
        self.credited = []
        self._logger = _Log()
        self._prev_alive_1202eq = prev_alive
        # #1202fi: the stamp the credit now shifts directly. A real run has one the
        # moment the delivery gate first declines.
        self._fwdeliver_first_decline_ts = 1000000.0

    def _credit_framework_deferral_1133(self, deferred_s, source):
        self.credited.append((deferred_s, source))


class _Log:
    def warning(self, *a, **k): pass
    def error(self, *a, **k): pass


def _method():
    from multi_agent.orchestrator import Orchestrator  # noqa: E402
    return Orchestrator._credit_downtime_1202eq


def _budget(tmp, updated_at):
    (tmp / "run_budget.json").write_text(
        json.dumps({"usage": {"updated_at": updated_at}}), encoding="utf-8")


sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))


def test_a_long_gap_is_credited_back(tmp_path):
    """r16's case: stopped for hours, resumed, must not be billed for the gap."""
    _budget(tmp_path, time.time())          # the file is already refreshed — as in a real run
    o = _Orch(tmp_path, prev_alive=time.time() - 7 * 3600)
    _method()(o)
    # The credit MEASURES the gap and hands it on; the shift itself runs after #1202ce
    # restores the clocks (#1202fd/#1202fi ordering) and is tested there. Asserting the
    # stamp here is what hid the AttributeError that swallowed the whole credit on
    # tiktok-r96's second resume: the stamp does not exist yet at this point.
    _gap = getattr(o, "_downtime_gap_1202fd", None)
    assert _gap is not None, "the downtime was not measured at all"
    assert 6.5 * 3600 < _gap < 7.5 * 3600, "wrong gap measured: %ss" % _gap


def test_a_fast_relaunch_is_not_downtime(tmp_path):
    """Restarting within a minute is continuity, not a break."""
    _budget(tmp_path, time.time())
    o = _Orch(tmp_path, prev_alive=time.time() - 5)
    _method()(o)
    assert not o.credited


def test_no_captured_stamp_is_not_an_error(tmp_path):
    o = _Orch(tmp_path, prev_alive=None)
    _method()(o)          # must not raise
    assert not o.credited


def test_a_malformed_stamp_is_ignored(tmp_path):
    o = _Orch(tmp_path, prev_alive="not-a-number")
    _method()(o)
    assert not o.credited


def test_it_runs_where_a_resume_is_first_known(tmp_path):
    """PLACEMENT IS THE MECHANISM. My first version credited inside the milestone loop,
    and neither measured resume ever reached it: one died in kickoff
    (`Kickoff timed out (missing=['backend','frontend','verifier'])`), the other delivered
    at tick=0 through the final-gate path. It now runs where the resume is detected —
    before kickoff, before any of that."""
    i = ORCH_SRC.index("self.checkpoint.resume_generation()")
    seg = ORCH_SRC[i:ORCH_SRC.index("else:", i)]
    assert "_credit_downtime_1202eq()" in seg


def test_it_is_credited_once_per_resume():
    """Two call sites would bill the same gap twice."""
    assert ORCH_SRC.count("self._credit_downtime_1202eq()") == 1


def test_a_fresh_run_never_credits():
    """`start_generation` is the fresh branch; it has no clock to correct."""
    # bounded by the landmark that follows, never by a byte count (#943 — my fifth
    # offence today; the ratchet caught every one)
    i = ORCH_SRC.index("self.checkpoint.start_generation(")
    seg = ORCH_SRC[i:ORCH_SRC.index("try:", i)]
    assert "_credit_downtime_1202eq()" not in seg


def test_downtime_does_not_go_through_the_capped_channel(tmp_path):
    """#1202fi. This test used to assert the OPPOSITE -- that downtime routed through
    #1133 -- and that routing is what made the credit useless. #1133 caps its total at
    FWVAL_NO_DELIVER_ABORT_S because the FRAMEWORK must not defer past the ceiling; a
    stopped process is a different claim, and every overnight resume exceeds that cap by
    construction. tiktok-r96: stopped 23.5h, credited 90min, aborted at 1474min."""
    i = ORCH_SRC.index("def _credit_downtime_1202eq")
    seg = ORCH_SRC[i:ORCH_SRC.index("\n    def ", i + 10)]
    assert "_credit_framework_deferral_1133(_gap" not in seg
    assert "self._downtime_gap_1202fd = _gap" in seg


def test_the_stamp_is_captured_before_any_write(tmp_path):
    """THE BUG THAT MADE THIS A NO-OP. #1170 writes run_budget.json near the top of run(),
    long before the resume block, so a fresh read there measured ~33s of "downtime" against
    a run that had been idle for 28 minutes. The stamp is now read once at construction."""
    src = (THIS_DIR.parent / "env_generator" / "llm_generator" / "multi_agent"
           / "orchestrator.py").read_text(encoding="utf-8")
    i = src.index("self._budget = RunBudget(")
    seg = src[i:src.index("def ", i)]
    assert "_prev_alive_1202eq" in seg, "the stamp must be captured where RunBudget is built"
    # Asserted on BEHAVIOUR, not on whether a word appears: the docstring legitimately
    # explains where the stamp originates. What must not happen is a fresh read.
    j = src.index("def _credit_downtime_1202eq")
    body = src[j:src.index("def _credit_framework_deferral_1133", j)]
    assert "read_text" not in body, "it must not re-read the ledger #1170 already refreshed"
    assert "_prev_alive_1202eq" in body, "it must use the stamp captured at construction"
