"""#1202ny: a converging grace holds the no-convergence abort for its full length FROM NOW.

tiktok-r126 ab2 resumed at 127min of a 120min lane budget. #228's grace moved the decline stamp
900s later (`_fwdeliver_first_decline_ts += grace`), which only helps a clock sitting AT the
budget: at 15:48:46 the clock read ~160min, grace #1 left it at ~145, grace #2 fired 147s later
and the run aborted at 15:53:06 — 113s after "extending the deadline by 900s" — one chain away
from a gate that had been green ten minutes earlier.
"""
import ast
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.orchestrator import Orchestrator  # noqa: E402
from multi_agent.runtime.delivery_gate import convergence_grace  # noqa: E402

BUDGET = 7200.0


def _simulate(start_clock_s, ticks, window_mode):
    """Replay the abort check every `tick` seconds; returns the second the abort fires."""
    o = SimpleNamespace(_fwdeliver_grace_until_1202ny=0.0, grace_count=0, decline=0.0)
    for now in ticks:
        lane = start_clock_s + now - o.decline
        open_ = (window_mode and Orchestrator._grace_window_open_1202ny(o, now))
        if lane > BUDGET and not open_:
            g = convergence_grace(failed_count=1, last_shrink_age_s=60, grace_used=o.grace_count)
            if g > 0:
                o.grace_count += 1
                if window_mode:
                    o._fwdeliver_grace_until_1202ny = now + g
                else:
                    o.decline += g
            else:
                return now
    return None


def test_r126_ab2_an_overdue_clock_still_gets_both_windows():
    ticks = list(range(0, 4000, 30))
    overdue = 9600.0                       # ~160min when the first grace was granted
    old = _simulate(overdue, ticks, window_mode=False)
    new = _simulate(overdue, ticks, window_mode=True)
    assert old is not None and old <= 60   # the old shift did nothing useful
    assert new is not None and new >= 1800  # two full 900s windows


def test_a_clock_at_the_budget_behaves_as_before():
    ticks = list(range(0, 4000, 30))
    at_budget = BUDGET - 10
    old = _simulate(at_budget, ticks, window_mode=False)
    new = _simulate(at_budget, ticks, window_mode=True)
    assert abs(old - new) <= 60 and new >= 1800


def test_the_window_is_closed_by_default_and_on_bad_values():
    assert Orchestrator._grace_window_open_1202ny(SimpleNamespace(), 10.0) is False
    assert Orchestrator._grace_window_open_1202ny(
        SimpleNamespace(_fwdeliver_grace_until_1202ny=None), 10.0) is False
    assert Orchestrator._grace_window_open_1202ny(
        SimpleNamespace(_fwdeliver_grace_until_1202ny="x"), 10.0) is False
    assert Orchestrator._grace_window_open_1202ny(
        SimpleNamespace(_fwdeliver_grace_until_1202ny=20.0), 10.0) is True


def test_the_abort_honours_the_window_and_no_longer_shifts_the_stamp():
    src = (LLM / "multi_agent" / "orchestrator.py").read_text()
    assert "self._fwdeliver_first_decline_ts += _grace" not in src
    i = src.index("DELIVERY-GATE NO-CONVERGENCE ABORT: %s")
    cond = src.rindex("if (_lane1202fk > FWVAL_NO_DELIVER_ABORT_S", 0, i)
    guard = src[cond:src.index("from .runtime.delivery_gate import convergence_grace", cond)]
    assert "self._grace_window_open_1202ny(_now2)" in guard
    grant = src[src.index("if _grace > 0:", cond):i]
    assert "self._fwdeliver_grace_until_1202ny = _now2 + float(_grace)" in grant
    lines = src.splitlines()
    reset = next(n for n, ln in enumerate(lines)
                 if ln.strip() == "self._fwdeliver_first_decline_ts = 0.0")
    assert lines[reset + 1].strip().startswith("self._fwdeliver_grace_until_1202ny = 0.0")
