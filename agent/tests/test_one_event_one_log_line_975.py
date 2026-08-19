"""#975: one event, one log line — the duplicate agent handler.

`BaseAgent._setup_logger` gave every `Agent.<name>` logger its own StreamHandler while
leaving `propagate` at its default True. In a real run `setup_logging()` has already
configured the root, so each record was emitted twice: once in this class's
`%(asctime)s - %(name)s - %(levelname)s - %(message)s` and once in the root's
`%H:%M:%S [%(levelname).1s]` form. The launcher pipes `2>&1 | tee`, so both copies land in
the same file — 10,355 of r158's 30,059 lines, 34% of a 4.1MB log.

The volume is the smaller half. Two lines per event doubles every count taken off the log,
and it produced a WRONG ANSWER this session: pairing consecutive `get_skill` lines paired
the two copies of ONE call and reported 66 SAME / 0 DIFFERENT, which would have shipped an
inert dedupe. Filtering to a single prefix inverted it to 31 DIFFERENT / 2 SAME.

The fix must not silence agents that run without a configured root (tests, library use), so
the handler is added only when nothing upstream will emit.
"""

import logging

import pytest

from utils.base_agent import BaseAgent


class _Concrete(BaseAgent):
    """BaseAgent is abstract; _setup_logger does not care, but instantiation does."""

    async def process_task(self, task):  # pragma: no cover - never called
        return None


class _Cfg:
    class logging_:  # noqa: N801 - mirrors the config object's shape
        level = None
        log_format = "%(name)s: %(message)s"

    logging = logging_


def _make_logger(name):
    """Call the real _setup_logger with only what it touches."""
    host = object.__new__(_Concrete)
    host._name = name
    host._config = _Cfg()
    return BaseAgent._setup_logger(host)


@pytest.fixture(autouse=True)
def _clean_loggers():
    root = logging.getLogger()
    saved = list(root.handlers)
    root.handlers = []
    yield
    root.handlers = saved
    for name in list(logging.Logger.manager.loggerDict):
        if name.startswith("Agent."):
            logging.getLogger(name).handlers = []


def test_no_second_handler_when_the_root_is_configured():
    logging.getLogger().addHandler(logging.NullHandler())
    lg = _make_logger("Dup Probe")
    assert lg.handlers == [], (
        "the root already emits and this logger propagates, so an own handler writes every "
        "line a second time — 34% of r158's log")


class _Counter(logging.Handler):
    def __init__(self):
        super().__init__()
        self.seen = []

    def emit(self, record):
        self.seen.append(record.getMessage())


def test_one_record_reaches_one_handler():
    """The property that matters, asserted end to end rather than by counting handlers."""
    counter = _Counter()
    root = logging.getLogger()
    root.addHandler(counter)
    root.setLevel(logging.INFO)
    lg = _make_logger("Count Probe")
    lg.info("hello")
    assert counter.seen.count("hello") == 1, (
        f"one call must produce one record, got {counter.seen}")


def test_an_unconfigured_root_still_gets_a_sink(monkeypatch):
    """Library/test use: without this the agent would log into the void.

    pytest's logging plugin installs its own root handlers, so the empty root has to be
    forced here rather than assumed."""
    monkeypatch.setattr(logging.getLogger(), "handlers", [])
    lg = _make_logger("Orphan Probe")
    assert len(lg.handlers) == 1


def test_the_control_adds_a_second_sink(monkeypatch):
    """Planted control: the PRE-FIX rule — add a handler whenever THIS logger has none —
    still fires when the root is already configured, which is exactly the double emission.
    Synthetic, so fixing the real setup can never turn this red."""
    monkeypatch.setattr(logging.getLogger(), "handlers", [logging.NullHandler()])
    lg = logging.getLogger("Agent.Control Probe")
    lg.handlers = []

    if not lg.handlers:                        # the whole pre-fix condition
        lg.addHandler(logging.NullHandler())
    assert len(lg.handlers) == 1, (
        "the control was supposed to add a sink on top of the configured root; if it does "
        "not, the assertion in test_no_second_handler_when_the_root_is_configured is vacuous")

    lg.handlers = []
    if not lg.handlers and not logging.getLogger().handlers:   # the fixed condition
        lg.addHandler(logging.NullHandler())
    assert lg.handlers == [], "the fixed condition must decline when the root already emits"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
