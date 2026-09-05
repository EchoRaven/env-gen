r"""#1202dq: the tool-io rollup was emitted once, from the orchestrator's `finally`.

`tool_io_rollup()` is the authoritative answer to "which tool grows the prompt" — the
accounting #257 added and #679 aimed at (check_inbox: 187.3M chars, 46.7% of 401M, mean
24,044 over 7788 calls). It was printed exactly once per run, from a `finally` block.

A SIGKILL does not run `finally`. Measured over the netflix corpus, 4 of 12 run logs carry
zero `[tool-io] TOTAL` lines — r41, r43b, r44, r44-resume — and r44 is the case that shows
why it matters: it died on `insufficient_quota` (37 retries, 13:08:57) and left no table.
The runs that end badly are the ones worth diagnosing, and they were exactly the ones that
lost the diagnosis.

So the rollup now also rides the #1175 budget ticker, which fires every 30s regardless of
lane state, self-gated to ENVGEN_TOOLIO_ROLLUP_MIN (default 15 min). A killed run keeps its
last table. The header string is deliberately unchanged so existing corpus greps for
`[tool-io] TOTAL` still match both the periodic and the final emission.
"""
import pathlib

import pytest

from env_generator.llm_generator.multi_agent.agents.runtime import tooling as T


class _Log:
    def __init__(self):
        self.lines = []

    def info(self, fmt, *args):
        self.lines.append(fmt % args if args else fmt)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """Each test gets its own counters and cadence clock."""
    monkeypatch.setattr(T, "_TOOL_IO_TOTALS", {}, raising=True)
    monkeypatch.setattr(T, "_TOOL_IO_ROLLUP_LAST_AT", 0.0, raising=True)
    monkeypatch.delenv("ENVGEN_TOOLIO_ROLLUP_MIN", raising=False)
    yield


def _seed(name="check_inbox", calls=7788, total=187_300_000, mx=1_515_342):
    T._TOOL_IO_TOTALS[name] = [calls, total, mx]


# --- the cadence gate ---------------------------------------------------------------------

def test_the_first_periodic_call_emits():
    _seed()
    log = _Log()
    assert T.maybe_tool_io_rollup(log) is True
    assert len(log.lines) == 1


def test_a_second_call_inside_the_window_does_not_emit():
    _seed()
    log = _Log()
    assert T.maybe_tool_io_rollup(log) is True
    assert T.maybe_tool_io_rollup(log) is False
    assert len(log.lines) == 1, "the cadence gate must not spam the log every 30s tick"


def test_a_call_after_the_window_emits_again(monkeypatch):
    _seed()
    log = _Log()
    assert T.maybe_tool_io_rollup(log) is True
    # advance past the default 15-minute window
    monkeypatch.setattr(T, "_TOOL_IO_ROLLUP_LAST_AT", T._TOOL_IO_ROLLUP_LAST_AT - 16 * 60)
    assert T.maybe_tool_io_rollup(log) is True
    assert len(log.lines) == 2


def test_the_window_is_configurable(monkeypatch):
    _seed()
    monkeypatch.setenv("ENVGEN_TOOLIO_ROLLUP_MIN", "0.0001")  # ~6ms
    log = _Log()
    assert T.maybe_tool_io_rollup(log) is True
    monkeypatch.setattr(T, "_TOOL_IO_ROLLUP_LAST_AT", T._TOOL_IO_ROLLUP_LAST_AT - 1.0)
    assert T.maybe_tool_io_rollup(log) is True


def test_a_zero_window_disables_periodic_emission(monkeypatch):
    _seed()
    monkeypatch.setenv("ENVGEN_TOOLIO_ROLLUP_MIN", "0")
    log = _Log()
    assert T.maybe_tool_io_rollup(log) is False
    assert log.lines == []


def test_a_junk_window_falls_back_to_the_default(monkeypatch):
    _seed()
    monkeypatch.setenv("ENVGEN_TOOLIO_ROLLUP_MIN", "not-a-number")
    log = _Log()
    assert T.maybe_tool_io_rollup(log) is True


# --- force, for the run-exit path ---------------------------------------------------------

def test_force_ignores_the_cadence_gate():
    _seed()
    log = _Log()
    assert T.maybe_tool_io_rollup(log) is True
    assert T.maybe_tool_io_rollup(log, force=True) is True, \
        "the final emission at run exit must never be suppressed by the cadence gate"
    assert len(log.lines) == 2


def test_force_still_declines_when_nothing_was_recorded():
    log = _Log()
    assert T.maybe_tool_io_rollup(log, force=True) is False
    assert log.lines == [], "an empty table is noise, not accounting"


# --- it must never be able to disturb a run -----------------------------------------------

def test_a_none_logger_is_survivable():
    _seed()
    assert T.maybe_tool_io_rollup(None) is False


def test_a_raising_logger_is_swallowed():
    _seed()

    class _Boom:
        def info(self, *a, **k):
            raise RuntimeError("log sink is gone")

    assert T.maybe_tool_io_rollup(_Boom()) is False, \
        "accounting must never propagate an exception into the run"


# --- the corpus contract: existing greps keep matching -------------------------------------

def test_the_header_string_is_unchanged_so_corpus_greps_still_match():
    _seed()
    log = _Log()
    T.maybe_tool_io_rollup(log)
    assert log.lines[0].startswith("[tool-io] TOTAL chars returned per tool"), \
        "corpus tooling greps for this literal; changing it silently orphans every past log"
    assert "check_inbox" in log.lines[0]


# --- wiring: a mechanism nobody calls is a dead mechanism ----------------------------------

def _orchestrator_src() -> str:
    here = pathlib.Path(T.__file__).resolve()
    root = here.parents[2]          # .../multi_agent/
    return (root / "orchestrator.py").read_text()


def test_the_budget_ticker_calls_it():
    """Landmark-anchored, not a byte window: the call must sit inside _budget_ticker_1175."""
    src = _orchestrator_src()
    start = src.index("async def _budget_ticker_1175()")
    end = src.index("self._budget_ticker_1175 = asyncio.create_task", start)
    body = src[start:end]
    assert "maybe_tool_io_rollup" in body, \
        "the periodic rollup must ride the ticker that runs regardless of lane state"


def test_the_run_exit_path_forces_an_emission():
    src = _orchestrator_src()
    assert "maybe_tool_io_rollup(self._logger, force=True)" in src
    assert "self._logger.info(\"%s\", tool_io_rollup())" not in src, \
        "the exit path should route through the helper so the cadence clock stays coherent"
