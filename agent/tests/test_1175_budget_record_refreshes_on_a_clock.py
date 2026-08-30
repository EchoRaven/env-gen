"""#1175: the live spend record went stale by 3.4x.

The per-tick write sits after the delivery loop's `wait_for(..., timeout=60)`,
which reads like a 60-second cadence and is not one: the loop BODY runs a whole
coordination cycle, so one iteration can take many minutes.

Measured on r17 while it was running: `run_budget.json` said 372 calls / $25.35
with `ticks: 0`, sixteen minutes after it was written, while the log showed
1,251 calls / $86.23. A spend record that lags like that is worse than none --
it gets read as current, and it is the number the cost question is answered
from.

A small task on its own clock fixes the axis the loop cannot. It only reads
counters #1163 already keeps, so it costs nothing and cannot disturb the run.
"""
import re
from pathlib import Path

from env_generator.llm_generator.multi_agent import orchestrator as orch

SRC = Path(orch.__file__).read_text(encoding="utf-8")


def _ticker():
    i = SRC.index("async def _budget_ticker_1175")
    return SRC[i:SRC.index("self._budget_ticker_1175 = asyncio.create_task", i)]


def test_the_refresher_runs_on_its_own_clock():
    b = _ticker()
    assert "await _a1175.sleep(" in b
    assert "ENVGEN_BUDGET_REFRESH_S" in b


def test_it_is_started_before_design_prep():
    """The phase the loop never covers is exactly where r16 spent $128 unseen."""
    start = SRC.index("self._budget_ticker_1175 = asyncio.create_task")
    assert start < SRC.index("await run_design_prep(")


def test_a_zero_interval_disables_it():
    assert "if _iv <= 0:" in _ticker()


def test_cancellation_is_not_swallowed():
    """A bare `except Exception` around an await would trap CancelledError on
    modern Python and leave the task un-killable."""
    b = _ticker()
    assert "except _a1175.CancelledError" in b
    assert b.index("CancelledError") < b.index("except Exception")


def test_a_write_failure_never_kills_the_run():
    b = _ticker()
    assert "except Exception" in b and "pass" in b


def test_the_ticker_is_stopped_and_a_final_reading_taken():
    """Otherwise the record on disk trails the summary printed beside it."""
    i = SRC.index("#1175: stop the refresher")
    seg = SRC[i:SRC.index("return GenerationResult(", i)]
    assert ".cancel()" in seg
    assert '"finished"' in seg


def test_the_final_state_is_distinct_from_running():
    """`running` on a finished run reads as a live process."""
    i = SRC.index("#1175: stop the refresher")
    seg = SRC[i:SRC.index("return GenerationResult(", i)]
    assert '"running"' not in seg
