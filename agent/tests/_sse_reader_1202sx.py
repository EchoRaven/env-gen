"""#1202sx: read an SSE endpoint from a worker thread that cannot outlive its test.

Six readers across three files (three in `test_run_log_stream.py`, two in
`test_live_monitor_sse.py`, one in `test_global_sse_and_agents.py`) were written the same
way: open the connection with ``timeout=5``, then read for a 1.5-3.0s
window. When the window closes while ``read1`` is blocked, the socket goes on waiting for
the REST of its five seconds -- past ``rt.join(...)``, past the ``finally`` that shuts the
server down, and into whichever test pytest has started by then, where the ``TimeoutError``
surfaces as a ``PytestUnhandledThreadExceptionWarning`` attributed to a file that has
nothing to do with it. Measured: reported under `test_global_sse_and_agents.py` and
`test_live_monitor_endpoints.py`, raised from the other two files.

Two things follow from that, and both are why this helper exists rather than six copies:

* **The socket must be bounded BELOW the read window**, so a blocked read ends inside the
  window instead of after it. And a timeout must BREAK, not retry: once a socket read has
  timed out the buffered reader is poisoned and every later read raises
  ``OSError: cannot read from timed out object`` (the first version of this helper retried,
  and all three tests failed on exactly that).
* **Nothing may be asserted in the thread.** Three of the six called
  ``self.assertEqual(resp.status, 200)`` inside ``reader()``, where unittest's exception
  escapes into the thread and becomes the same warning -- an assertion with no power to
  fail its test, which is the one thing a test may never contain.

An idle stream is NOT an error: the window decides when reading stops. A real fault is
recorded and handed back, never swallowed -- the caller asserts ``errors == []``.
"""
import threading
import time
from http.client import HTTPConnection

# Strictly below every caller's read window (the shortest is 1.5s), so a blocked read
# cannot outlive it.
READ_TIMEOUT_1202SX = 1.0


def read_stream_1202sx(port, path, seconds, chunk=512, host="127.0.0.1"):
    """Read ``path`` for ``seconds``. Returns ``(received, meta, errors, thread)``.

    The thread is handed back so the caller can ``join`` it AND assert it is dead --
    a reader still alive at the end of its test is the defect this helper removes.
    """
    received = []
    meta = {}
    errors = []

    def reader():
        conn = None
        try:
            conn = HTTPConnection(host, port, timeout=READ_TIMEOUT_1202SX)
            conn.request("GET", path)
            resp = conn.getresponse()
            meta["status"] = resp.status
            meta["content_type"] = resp.getheader("Content-Type", "")
            deadline = time.time() + seconds
            while time.time() < deadline:
                try:
                    data = resp.fp.read1(chunk)
                except TimeoutError:
                    break             # idle stream; retrying would hit the poisoned reader
                if not data:
                    break
                received.append(data)
        except Exception as exc:      # recorded, never hidden -- the caller asserts on it
            errors.append("%s: %s" % (type(exc).__name__, exc))
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    rt = threading.Thread(target=reader, daemon=True)
    rt.start()
    return received, meta, errors, rt
