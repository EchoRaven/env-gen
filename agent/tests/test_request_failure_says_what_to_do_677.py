r"""#677: "Connection refused" told the agent an errno and nothing else, 1778 times.

Last of the wasted-STEPS ranking that produced #674, #675 and #676. `test_api` is the largest
single source of failed tool calls in the corpus:

    test_api                                 5248 failures across 123 runs, median 22/run
      1778  Request failed: <urlopen error [Errno 111] Connection refused>   <- this one
      1750  HTTP Error: N with no body                                        -> #674
      1622  HTTP Error: N — this endpoint requires AUTH...                    (already good)

The connection-refused half spans 100 runs at a median of 8 and a maximum of **220** in one run.
Per #257 each retry is a whole step re-sending the prompt — and retrying a connection to a
process that is not running cannot succeed however many times it is tried.

The exception already distinguishes the causes; the message just never used them. Refused,
unresolvable, reset and timed-out need four different actions, and only the last is worth
retrying as-is.
"""
import socket
import urllib.error

import pytest

from env_generator.llm_generator.tools.runtime_tools import (
    _request_failure_reason_677 as why,
)

URL = "http://localhost:8000/api/titles"


def _refused():
    return urllib.error.URLError(ConnectionRefusedError(111, "Connection refused"))


# --- each cause gets its own remedy -----------------------------------------------------------

def test_refused_says_nothing_is_listening():
    msg = why(_refused(), URL)
    assert "NOTHING IS LISTENING" in msg
    assert "localhost:8000" in msg


def test_refused_says_retrying_cannot_work():
    """The behaviour the 220-repeat run needed corrected."""
    assert "retrying this call cannot succeed" in why(_refused(), URL)


def test_refused_names_the_two_real_remedies():
    msg = why(_refused(), URL)
    assert "docker compose" in msg
    assert "port matches" in msg


def test_an_unresolvable_host_is_told_about_service_names():
    e = urllib.error.URLError(socket.gaierror(-2, "Name or service not known"))
    msg = why(e, "http://backend:8000/x")
    assert "does not resolve" in msg
    assert "SERVICE name, not localhost" in msg


def test_a_reset_points_at_the_container_log():
    msg = why(ConnectionResetError(104, "Connection reset by peer"), URL)
    assert "accepted then RESET" in msg
    assert "container log" in msg


def test_a_timeout_suggests_a_blocked_dependency():
    msg = why(TimeoutError("timed out"), URL)
    assert "before the timeout" in msg
    assert "DB not ready" in msg


def test_the_four_causes_are_distinguishable():
    msgs = {why(_refused(), URL),
            why(urllib.error.URLError(socket.gaierror(-2, "Name or service not known")), URL),
            why(ConnectionResetError(104, "Connection reset by peer"), URL),
            why(TimeoutError("timed out"), URL)}
    assert len(msgs) == 4


# --- the original text is never lost ---------------------------------------------------------

@pytest.mark.parametrize("exc", [
    _refused(),
    ConnectionResetError(104, "Connection reset by peer"),
    TimeoutError("timed out"),
    ValueError("something else"),
])
def test_the_raw_error_still_leads(exc):
    assert why(exc, URL).startswith("Request failed: ")


def test_an_unrecognised_error_is_passed_through_unchanged():
    assert why(ValueError("something else"), URL) == "Request failed: something else"


# --- the target is derived, not assumed ---------------------------------------------------------

def test_the_port_comes_from_the_url():
    assert "localhost:9999" in why(_refused(), "http://localhost:9999/x")


def test_https_defaults_to_443():
    assert "example.com:443" in why(_refused(), "https://example.com/x")


def test_http_defaults_to_80():
    assert "example.com:80" in why(_refused(), "http://example.com/x")


@pytest.mark.parametrize("url", [None, "", "not a url", 12345])
def test_a_bad_url_does_not_break_the_message(url):
    assert why(_refused(), url).startswith("Request failed: ")


def test_it_never_raises():
    class _Odd(Exception):
        def __str__(self):
            raise RuntimeError("boom")

    try:
        why(_Odd(), URL)
    except Exception as exc:  # pragma: no cover
        pytest.fail(f"raised {exc!r}")


# --- wiring + provenance ------------------------------------------------------------------------

def test_the_tool_calls_it():
    import inspect
    from env_generator.llm_generator.tools import runtime_tools as rt
    src = inspect.getsource(rt)
    assert "_request_failure_reason_677(e, url)" in src


def test_the_measurement_is_recorded():
    import inspect
    from env_generator.llm_generator.tools import runtime_tools as rt
    flat = " ".join(inspect.getsource(rt._request_failure_reason_677).replace("#", " ").split())
    assert "1778 of those" in flat and "maximum of 220" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
