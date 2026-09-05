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
    modern Python and leave the task un-killable.

    Asserted structurally (#1202dq). This used to compare byte offsets --
    `b.index("CancelledError") < b.index("except Exception")` -- which says
    "the first except-Exception in the whole ticker comes after the cancel
    handler". That is not the invariant: it also fails for any unrelated
    *synchronous* try/except added earlier in the loop body, which is exactly
    what #1202dq's rollup call is. The real rule is per-try and about awaits,
    so walk the AST and check only the handlers that actually guard one.
    """
    import ast
    import textwrap

    b = _ticker()
    assert "except _a1175.CancelledError" in b
    fn = ast.parse(textwrap.dedent(b).rstrip().rstrip("try:").rstrip()).body[0]

    def _guards_an_await(node):
        return any(isinstance(n, ast.Await) for n in ast.walk(node))

    def _name(handler):
        t = handler.type
        if t is None:
            return "bare"
        return ast.unparse(t)

    checked = 0
    for node in ast.walk(fn):
        if not isinstance(node, ast.Try):
            continue
        if not any(_guards_an_await(stmt) for stmt in node.body):
            continue          # a sync try cannot trap a cancellation
        checked += 1
        names = [_name(h) for h in node.handlers]
        broad = [i for i, n in enumerate(names) if n in ("Exception", "bare")]
        cancels = [i for i, n in enumerate(names) if "CancelledError" in n]
        assert cancels, f"a try around an await must re-raise CancelledError; got {names}"
        if broad:
            assert min(cancels) < min(broad), (
                f"CancelledError must be handled before the broad handler; got {names}")
    assert checked, "no try/except around an await was found -- the guard moved"


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
