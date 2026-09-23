r"""#1202sx: a ratchet — an SSE reader thread must not be able to outlive its own test.

Six readers across three files opened a connection with `timeout=5` and then read for a
1.5–3.0s window. When the window closed while `read1` was blocked, the socket went on
waiting for the rest of its five seconds — past `rt.join(...)`, past the `finally` that
shuts the server down, and into whichever test pytest had started by then, where the
`TimeoutError` surfaced as `PytestUnhandledThreadExceptionWarning` attributed to an
unrelated file. Measured before the fix: reported under `test_global_sse_and_agents.py`
and `test_live_monitor_endpoints.py`, raised from `test_run_log_stream.py:116` and
`test_live_monitor_sse.py:157`.

Three of them also asserted INSIDE the thread, where unittest's exception escapes into the
thread and becomes the same warning — an assertion with no power to fail its test.

Counter-proved when the helper landed: restoring the 5s socket timeout reds 4 tests and
takes the two files from 9.5s to 28.7s, because every reader blocks for the full timeout.

This file is the ratchet. The per-test assertions (`assertFalse(rt.is_alive())`) catch a
regression in the READERS; these catch a regression in the RULE.

LOCAL-ONLY (gitignored)."""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

TESTS = Path(__file__).resolve().parent
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

import _sse_reader_1202sx as helper  # noqa: E402

# Every file that reads an SSE endpoint from a worker thread.
_SSE_TEST_FILES = (
    "test_run_log_stream.py",
    "test_live_monitor_sse.py",
    "test_global_sse_and_agents.py",
)
# The shortest read window any caller passes; the socket must be bounded below it.
_SHORTEST_WINDOW = 1.5


def test_the_socket_is_bounded_below_the_shortest_read_window():
    assert helper.READ_TIMEOUT_1202SX < _SHORTEST_WINDOW, (
        "a blocked read must end INSIDE the window, or the thread outlives the test")


def test_a_timeout_breaks_rather_than_retries():
    """Once a socket read has timed out the buffered reader is poisoned — every later read
    raises `OSError: cannot read from timed out object`. The first version retried and all
    three log-stream tests failed on exactly that."""
    src = (TESTS / "_sse_reader_1202sx.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "reader")
    handlers = [h for n in ast.walk(fn) if isinstance(n, ast.Try) for h in n.handlers]
    timeout_h = [h for h in handlers
                 if isinstance(h.type, ast.Name) and h.type.id == "TimeoutError"]
    assert timeout_h, "the idle-stream case must be handled explicitly"
    assert any(isinstance(st, ast.Break) for st in timeout_h[0].body), (
        "retrying after a socket timeout hits the poisoned reader")


def test_faults_are_handed_back_not_swallowed():
    """The standing rule: a fallback that hides a failure is worse than no fallback. The
    helper records; the caller asserts `errors == []`."""
    src = (TESTS / "_sse_reader_1202sx.py").read_text(encoding="utf-8")
    assert "errors.append(" in src
    assert "except Exception:\n            pass" not in src.replace("\r", "")


def test_no_sse_test_still_opens_its_own_connection():
    """One helper, not five copies — a new hand-rolled reader is how this comes back."""
    offenders = []
    for name in _SSE_TEST_FILES:
        src = (TESTS / name).read_text(encoding="utf-8")
        if "HTTPConnection(" in src and "read1(" in src:
            offenders.append(name)
    assert offenders == [], (
        "these files read an SSE stream without the bounded helper: %s" % offenders)


def test_no_sse_test_asserts_inside_its_reader_thread():
    """An assertion in a worker thread cannot fail its test; it becomes a warning."""
    bad = []
    for name in _SSE_TEST_FILES:
        src = (TESTS / name).read_text(encoding="utf-8")
        for fn in (n for n in ast.walk(ast.parse(src))
                   if isinstance(n, ast.FunctionDef) and n.name == "reader"):
            calls = {getattr(c.func, "attr", "") for c in ast.walk(fn)
                     if isinstance(c, ast.Call)}
            if any(a.startswith("assert") for a in calls):
                bad.append("%s:%d" % (name, fn.lineno))
    assert bad == [], "assertions inside a reader thread: %s" % bad


def test_every_caller_joins_and_then_proves_the_thread_is_dead():
    """`join(timeout=…)` returns whether or not the thread ended — the proof is `is_alive`."""
    missing = []
    for name in _SSE_TEST_FILES:
        src = (TESTS / name).read_text(encoding="utf-8")
        starts = len(re.findall(r"read_stream_1202sx\(", src))
        deads = src.count("self.assertFalse(rt.is_alive()")
        if starts and deads != starts:
            missing.append("%s: %d reader(s), %d liveness assertion(s)" % (name, starts, deads))
    assert missing == [], missing
