"""#1196 — the ledger's elapsed and the wall-clock cap measured from different origins.

The cap compares `time.time() - loop_start` (line 2426). The #1175 ticker was writing
`time.time() - start_time.timestamp()`, which starts at PROCESS launch and therefore
includes design-prep, kickoff and skeleton generation. One field, two meanings, whichever
writer touched it last.

netflix-r26 showed both at once: the ledger read "wall-clock remaining -31 min" — 31 minutes
past a 300-minute ceiling, still running — while the loop saw 25 minutes of room, because the
phases before the loop had taken about an hour. I read the ledger and concluded the
wall-clock cap "never binds and is a dead safety net". That was wrong. It binds fine, against
a clock I was not reading.

Same shape as #1192: my own instrumentation destroying the signal someone later relies on,
and me being that someone.
"""
import inspect
import re

from env_generator.llm_generator.multi_agent import orchestrator as orc

_SRC = inspect.getsource(orc)


def _ticker():
    i = _SRC.index("async def _budget_ticker_1175(")
    return _SRC[i:_SRC.index("self._budget_ticker_1175 = asyncio.create_task", i)]


def test_the_ticker_measures_from_the_loop_origin():
    body = _ticker()
    assert "_loop_start_1196" in body
    assert body.count("_loop_start_1196") >= 2, "both the start stamp and the elapsed"


def test_it_falls_back_to_process_start_before_the_loop_exists():
    """There is no loop origin during design-prep; process start is the honest answer then."""
    body = _ticker()
    assert 'getattr(self, "_loop_start_1196", None)' in body
    assert "or start_time.timestamp()" in body


def test_the_loop_publishes_its_origin():
    # Same landmark rule as its sibling — no byte windows.
    i = _SRC.index("self._loop_start_1196 = loop_start")
    between = _SRC[i:_SRC.index("self._write_run_budget(", i)]
    assert "\n\n" not in between, "publish must sit in the same block as the ledger write"


def test_the_cap_still_compares_the_loop_clock():
    """The fix aligns the REPORT with the check; it must not move the check."""
    assert 'elapsed > caps["max_wall_sec"]' in _SRC
    i = _SRC.index('elapsed > caps["max_wall_sec"]')
    window = _SRC[_SRC.rindex("elapsed = time.time()", 0, i):i]
    assert "loop_start" in window, "the cap is measured from loop_start and stays that way"


def test_ledger_and_cap_now_share_one_origin():
    """★ The property that was violated: whoever writes the field, it means the same thing."""
    loop_write = _SRC[_SRC.index("self._loop_start_1196 = loop_start"):]
    loop_write = loop_write[:loop_write.index("\n", loop_write.index("_write_run_budget("))]
    assert "elapsed" in loop_write
    assert "_loop_start_1196" in _ticker()
