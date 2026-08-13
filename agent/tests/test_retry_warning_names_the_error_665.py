r"""#665: the agent retry warning printed nothing, 3150 times.

    self._logger.warning(f"Retry {attempt + 1}/{max_tries} after error: {e}. ...")

`{e}` renders "" for any exception whose `str()` is empty — a bare `assert x`, and most
SDK/transport errors — so the log read:

    Retry 1/3 after error: . Waiting 1.0s

Measured over the 249 run logs: **3150 such lines against 60** that carried any text at all.
98% of every retry warning this agent emits was undiagnosable.

#582 already solved exactly this — in the OTHER retry loop. `utils/llm.py` logs
"[{error_type}] {error_msg}" and ships `_blank_error_origin(e)` to name the frame when the
message is empty ("2313 three-attempt failure groups across the netflix arc, none of them
diagnosable"). `utils/base_agent.py` is its twin and never got the treatment.

Now: always the type, and the #582 origin helper when the message is blank —
`[AssertionError] (no message) at utils/foo.py:88 in _probe: assert x`.
"""
import asyncio
import logging

import pytest

from utils.base_agent import BaseAgent


class _Host:
    """A minimal stand-in carrying only what the retry helper touches."""

    def __init__(self):
        self._logger = logging.getLogger("test.retry665")
        # mirrors BaseAgent.__init__'s shape, with the waits collapsed so the suite is fast
        self._retry_config = {"max_retries": 2, "min_wait": 0.001,
                              "max_wait": 0.001, "multiplier": 1.0}
        # `_metrics.total_retries += 1` — an object with attributes, not a mapping
        self._metrics = type("M", (), {"total_retries": 0})()


def _run(host, fn, tries=2):
    # the parameter is `max_retries`; anything else is forwarded into `fn` as a kwarg
    return asyncio.run(BaseAgent.call_with_retry(host, fn, max_retries=tries))


def _warnings(caplog):
    return [r.message for r in caplog.records if r.levelno == logging.WARNING]


# --- the defect ---------------------------------------------------------------------------------

def test_a_blank_exception_no_longer_logs_an_empty_reason(caplog):
    async def boom():
        # `raise` explicitly: a bare `assert False` inside a test file gets pytest's
        # assertion rewriting, which ATTACHES a message and destroys the premise.
        raise AssertionError()

    host = _Host()
    with caplog.at_level(logging.WARNING, logger="test.retry665"):
        with pytest.raises(AssertionError):
            _run(host, boom)
    warned = _warnings(caplog)
    assert warned, "the retry must still warn"
    assert "after error: . " not in warned[0]


def test_it_names_the_exception_type(caplog):
    async def boom():
        raise AssertionError()

    host = _Host()
    with caplog.at_level(logging.WARNING, logger="test.retry665"):
        with pytest.raises(AssertionError):
            _run(host, boom)
    assert "[AssertionError]" in _warnings(caplog)[0]


def test_it_falls_back_to_the_582_origin_helper(caplog):
    """The whole point: a blank message must still say WHERE it came from."""
    async def boom():
        raise AssertionError()

    host = _Host()
    with caplog.at_level(logging.WARNING, logger="test.retry665"):
        with pytest.raises(AssertionError):
            _run(host, boom)
    assert "(no message) at" in _warnings(caplog)[0]


# --- a real message is untouched ----------------------------------------------------------------

def test_an_exception_with_a_message_keeps_it(caplog):
    async def boom():
        raise ValueError("connection reset by peer")

    host = _Host()
    with caplog.at_level(logging.WARNING, logger="test.retry665"):
        with pytest.raises(ValueError):
            _run(host, boom)
    w = _warnings(caplog)[0]
    assert "connection reset by peer" in w
    assert "[ValueError]" in w
    assert "(no message)" not in w


def test_the_retry_counter_and_wait_are_still_reported(caplog):
    async def boom():
        raise ValueError("x")

    host = _Host()
    with caplog.at_level(logging.WARNING, logger="test.retry665"):
        with pytest.raises(ValueError):
            _run(host, boom, tries=3)
    w = _warnings(caplog)
    assert "Retry 1/3" in w[0] and "Retry 2/3" in w[1]
    assert "Waiting" in w[0]


def test_a_succeeding_call_never_warns(caplog):
    async def fine():
        return 42

    host = _Host()
    with caplog.at_level(logging.WARNING, logger="test.retry665"):
        assert _run(host, fine) == 42
    assert _warnings(caplog) == []


# --- it must never break the retry ---------------------------------------------------------------

def test_a_failing_origin_helper_degrades_to_a_marker(caplog, monkeypatch):
    """Building a log line on an already-failing path must not raise."""
    import utils.llm as L
    monkeypatch.setattr(L, "_blank_error_origin",
                        lambda e: (_ for _ in ()).throw(RuntimeError("nope")))

    async def boom():
        raise AssertionError()

    host = _Host()
    with caplog.at_level(logging.WARNING, logger="test.retry665"):
        with pytest.raises(AssertionError):
            _run(host, boom)
    assert "(no message)" in _warnings(caplog)[0]


def test_the_original_exception_still_propagates():
    async def boom():
        raise KeyError("the real one")

    with pytest.raises(KeyError):
        _run(_Host(), boom)


# --- provenance -------------------------------------------------------------------------------

def test_the_measurement_is_recorded():
    import inspect
    src = inspect.getsource(BaseAgent)
    flat = " ".join(src.replace("#", " ").split())
    assert "3150 such lines against 60" in flat


def test_the_already_fixed_twin_is_credited():
    """A reader must see this is #582 applied to the loop it missed, not a new idea."""
    import inspect
    flat = " ".join(inspect.getsource(BaseAgent).split())
    assert "utils/llm.py" in flat and "582" in flat


def test_the_twin_really_does_name_the_type():
    """Pins the comparison the fix rests on."""
    import inspect
    import utils.llm as L
    assert "_blank_error_origin" in dir(L)
    src = inspect.getsource(L)
    assert "[{error_type}] {error_msg}" in src


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
