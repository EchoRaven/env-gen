"""#1202fw -- warn at RESUME when the run has already spent its no-convergence budget.

The abort needs BOTH a lane time over FWVAL_NO_DELIVER_ABORT_S and a DECLINED delivery, so
such a resume is not hopeless — it has exactly one attempt. Nothing said so, and the money
goes before anyone finds out: tiktok-r96 was resumed twice past the line (102 then 113 min
of lane time), aborted at tick 1 both times having done no useful work, ~$20 each.

A warning, not a refusal: the one-shot path is real, and an operator may be resuming
precisely because a fix should make that first evaluation green.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "env_generator" / "llm_generator"))

from multi_agent import orchestrator as O  # noqa: E402


class _Log:
    def __init__(self):
        self.warnings = []

    def warning(self, msg, *a):
        self.warnings.append(msg % a if a else msg)


class _Orc:
    """Bound to the real method — the behaviour under test is the method, not a copy."""
    _warn_spent_lane_time_1202fw = O.Orchestrator._warn_spent_lane_time_1202fw

    def __init__(self, decline_ts, spent):
        self._fwdeliver_first_decline_ts = decline_ts
        self._logger = _Log()
        self._spent = spent

    def _lane_time_1202fk(self, raw):
        return self._spent


def _over():
    return float(O.FWVAL_NO_DELIVER_ABORT_S) + 600.0


def _under():
    """Spent little enough that AMPLE budget remains — relative to the gate threshold.

    #1202hz: this was `- 600.0`, i.e. ten minutes left, which read as "budget remains"
    only because the threshold was then the p50 of time-to-first-gate (9 min). Ten
    minutes is not ample: tiktok-r106's third resume had 9.45 and took 21 minutes to
    reach the evaluation it never survived. Expressing the margin against the constant
    keeps this test asserting its INTENT rather than a number that was true once.
    """
    return float(O.FWVAL_NO_DELIVER_ABORT_S) - (
        float(O._TIME_TO_FIRST_GATE_S_1202GO) + 600.0)


def test_warns_when_the_budget_is_already_spent():
    o = _Orc(time.time() - 99999, _over())
    o._warn_spent_lane_time_1202fw()
    assert any("#1202fw" in w for w in o._logger.warnings), "resume gave no cost warning"


def test_the_warning_says_it_is_one_attempt():
    o = _Orc(time.time() - 99999, _over())
    o._warn_spent_lane_time_1202fw()
    w = " ".join(o._logger.warnings).lower()
    assert "one attempt" in w, "does not say what the operator actually gets"
    assert "fresh run" in w, "does not name the cheaper alternative"


def test_silent_when_budget_remains():
    o = _Orc(time.time() - 60, _under())
    o._warn_spent_lane_time_1202fw()
    assert o._logger.warnings == []


def test_silent_when_delivery_was_never_declined():
    """An untouched budget must not look spent."""
    for ts in (0, None, -1):
        o = _Orc(ts, _over())
        o._warn_spent_lane_time_1202fw()
        assert o._logger.warnings == [], f"warned on decline_ts={ts!r}"


def test_it_warns_but_does_not_refuse():
    """The one-shot path is legitimate; this must never raise or stop the resume."""
    o = _Orc(time.time() - 99999, _over())
    assert o._warn_spent_lane_time_1202fw() is None


def test_it_uses_the_bounded_lane_time_not_the_wall_clock():
    """#1202fk bounds lane time by the seconds a process existed to spend it; a resume
    the next day must not read its downtime as spent budget."""
    seen = {}

    class _O(_Orc):
        def _lane_time_1202fk(self, raw):
            seen["raw"] = raw
            return _under()

    o = _O(time.time() - 86400, None)
    o._warn_spent_lane_time_1202fw()
    assert seen["raw"] > 80000, "did not consult the raw wall gap"
    assert o._logger.warnings == [], "a whole day of downtime read as spent lane time"


def test_a_hiccup_is_announced_not_swallowed():
    import inspect
    assert "warn_once_1201" in inspect.getsource(O.Orchestrator._warn_spent_lane_time_1202fw)
