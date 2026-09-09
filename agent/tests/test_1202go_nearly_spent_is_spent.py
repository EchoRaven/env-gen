"""#1202go — a resume that starts with minutes of budget left is already doomed.

#1202fw only spoke once the no-convergence budget was GONE. tiktok-r98's second resume began
with about 7 minutes of it left, said nothing, cost $62.61, and hit the 90-minute abort 22
minutes in — the exact waste #1202fw exists to prevent, skipped because the budget was not
QUITE spent.

The threshold is measured, not picked. Across 39 runs on this machine the gap from run start
to the FIRST delivery-gate evaluation is p50 8.6 min, p75 19.6, p90 28.9, max 52.6. A resume
holding less than the median cannot reach the one evaluation it needs, so it arrives over
budget before it is ever asked to deliver. (#647: a tuned constant needs measured rationale.)

Both warnings REPORT; neither refuses. The one-shot path stays legitimate — an operator may
be resuming precisely because a fix should make that first evaluation green.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "env_generator" / "llm_generator"))

from multi_agent import orchestrator as O  # noqa: E402

THRESH = float(O.FWVAL_NO_DELIVER_ABORT_S)


class _Log:
    def __init__(self):
        self.warnings = []

    def warning(self, msg, *a):
        self.warnings.append(msg % a if a else msg)


class _Orc:
    """Bound to the real method, and carrying the attribute the real Orchestrator defines
    (`_logger`, not `logger` — #1202gh)."""
    _warn_spent_lane_time_1202fw = O.Orchestrator._warn_spent_lane_time_1202fw

    def __init__(self, spent):
        self._fwdeliver_first_decline_ts = time.time() - 99999
        self._logger = _Log()
        self._spent = spent

    def _lane_time_1202fk(self, raw):
        return self._spent


def _warn(spent):
    o = _Orc(spent)
    o._warn_spent_lane_time_1202fw()
    return " ".join(o._logger.warnings)


def test_a_nearly_spent_budget_warns():
    """r98's second resume: ~7 minutes left."""
    w = _warn(THRESH - 7 * 60)
    assert "#1202go" in w, w
    assert "7 min" in w


def test_it_says_what_the_median_run_needs():
    w = _warn(THRESH - 7 * 60)
    assert "median" in w and "delivery-gate evaluation" in w, w
    assert "fresh run" in w, "does not name the cheaper alternative"


def test_a_healthy_budget_stays_silent():
    assert _warn(30 * 60) == ""


def test_the_boundary_is_the_measured_median():
    assert _warn(THRESH - O._TIME_TO_FIRST_GATE_S_1202GO - 60) == ""
    assert "#1202go" in _warn(THRESH - O._TIME_TO_FIRST_GATE_S_1202GO + 60)


def test_a_spent_budget_still_gets_the_original_warning():
    """#1202fw's own case must not be swallowed by the new branch."""
    w = _warn(THRESH + 20 * 60)
    assert "#1202fw" in w and "#1202go" not in w, w


def test_neither_warning_refuses():
    o = _Orc(THRESH - 7 * 60)
    assert o._warn_spent_lane_time_1202fw() is None


def test_an_untouched_budget_is_silent():
    """No declined delivery yet — nothing has been spent."""
    o = _Orc(THRESH - 7 * 60)
    o._fwdeliver_first_decline_ts = 0
    o._warn_spent_lane_time_1202fw()
    assert o._logger.warnings == []


def test_the_constant_records_its_measurement():
    import inspect
    src = inspect.getsource(O)
    i = src.index("_TIME_TO_FIRST_GATE_S_1202GO = ")
    head = src[src.rindex("\n\n", 0, i):i]
    assert "39 runs" in head and "p50" in head, "the constant has no measured rationale (#647)"
