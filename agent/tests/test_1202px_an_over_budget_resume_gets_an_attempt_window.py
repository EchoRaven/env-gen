"""#1202px: a resume that starts over its no-convergence budget gets a real attempt window.

tiktok-r126-ab4 resumed at ~160min of lane time, dispatched the verifier's chain repair at
15:18 and was aborted at 15:25; ab3 the same at 20 minutes. #1202lu's six evaluations are one
gate cycle, not one repair cycle."""
import sys
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "env_generator" / "llm_generator"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent import orchestrator as O  # noqa: E402


class _Log:
    def warning(self, *a, **k):
        pass


class _Orc:
    _warn_spent_lane_time_1202fw = O.Orchestrator._warn_spent_lane_time_1202fw
    _resume_floor_open_1202px = O.Orchestrator._resume_floor_open_1202px

    def __init__(self, spent):
        self._fwdeliver_first_decline_ts = time.time() - 1.0
        self._logger = _Log()
        self._spent = spent

    def _lane_time_1202fk(self, raw):
        return self._spent


def test_an_over_budget_resume_opens_the_window():
    o = _Orc(float(O.FWVAL_NO_DELIVER_ABORT_S) + 3000.0)
    o._warn_spent_lane_time_1202fw()
    now = time.time()
    assert o._resume_floor_open_1202px(now + 60)
    assert o._resume_floor_open_1202px(now + O._RESUME_ATTEMPT_S_1202PX - 30)
    assert not o._resume_floor_open_1202px(now + O._RESUME_ATTEMPT_S_1202PX + 30)


def test_a_resume_with_budget_left_gets_no_window():
    o = _Orc(0.0)
    o._warn_spent_lane_time_1202fw()
    assert not o._resume_floor_open_1202px(time.time() + 60)


def test_closed_by_default_and_on_bad_values():
    f = O.Orchestrator._resume_floor_open_1202px
    assert f(SimpleNamespace(), 1.0) is False
    assert f(SimpleNamespace(_resume_floor_until_1202px="x"), 1.0) is False


def test_the_abort_condition_consults_the_window():
    src = (ROOT / "env_generator" / "llm_generator" / "multi_agent" / "orchestrator.py").read_text()
    cond = src.index("if (_lane1202fk > FWVAL_NO_DELIVER_ABORT_S")
    guard = src[cond:src.index("from .runtime.delivery_gate import convergence_grace", cond)]
    assert "self._resume_floor_open_1202px(_now2)" in guard
