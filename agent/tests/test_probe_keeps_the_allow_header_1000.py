"""#1000: a 405 without its `Allow` header is a number the lane has to reproduce.

r162's terminal blocker was one failed task — `POST /api/continue-watching is registered
implemented but returns 405`. It spawned 17 tasks (see #998) and was never fixed.

Static analysis of the worktree came back clean on every line: the route is declared in both
custom_routes.py and main.py, the router IS included, a broken import WOULD be logged with a
specific message, and the image is rebuilt (11 builds in r162). The one fact that settles it —
which methods the RUNNING app bound for that path — is carried by the `Allow` header, which
HTTP requires every 405 to include.

It was discarded at capture, in four lines:

    class _UrllibResponse:
        def __init__(self, raw):
            self.status_code = getattr(raw, "status", getattr(raw, "code", 0))

Everything downstream — the smoke verdict, the verifier's paraphrase of it, the orchestrator's
dispatch to backend — was working from a bare integer, which is why the task said "reproduce
POST /api/continue-watching returning 405" instead of showing it.

This is the deepest instance of the session's running class (#973, #978, #981, #982, #983,
#987): not "the check name without the instance" but **the instance without the evidence**.
"""

import pytest

from env_generator.llm_generator.multi_agent.runtime.hubs.runhub.compose import (
    _UrllibResponse)


class _Raw:
    def __init__(self, status, headers=None):
        self.status = status
        self.headers = headers or {}


def test_the_wrapper_keeps_the_allow_header():
    r = _UrllibResponse(_Raw(405, {"Allow": "GET, HEAD"}))
    assert r.status_code == 405
    assert r.headers.get("Allow") == "GET, HEAD", (
        "the header naming the bound methods is the whole diagnosis")


def test_the_wrapper_still_reports_the_status():
    assert _UrllibResponse(_Raw(200, {})).status_code == 200


def test_a_response_without_headers_does_not_crash():
    class _Bare:
        status = 500

    assert _UrllibResponse(_Bare()).headers == {}


def test_unreadable_headers_degrade_to_empty():
    class _Hostile:
        status = 405

        @property
        def headers(self):
            raise RuntimeError("no headers for you")

    r = _UrllibResponse(_Hostile())
    assert r.status_code == 405 and r.headers == {}


def test_the_probe_result_carries_the_diagnostic_headers():
    """The verdict dict must forward the small set that explains a failure, and nothing else —
    a probe result is quoted into task descriptions, so it must not become a header dump."""
    import inspect

    from env_generator.llm_generator.multi_agent.runtime.hubs.runhub import service
    src = inspect.getsource(service)
    assert '"headers": _hdrs' in src
    for wanted in ("allow", "content-type", "location", "www-authenticate"):
        assert wanted in src


def test_the_control_loses_the_diagnosis():
    """Planted control: the PRE-FIX wrapper kept status only, so a 405 arrived downstream as
    the integer 405 and nothing else."""
    class _PreFix:
        def __init__(self, raw):
            self.status_code = getattr(raw, "status", 0)

    r = _PreFix(_Raw(405, {"Allow": "GET, HEAD"}))
    assert not hasattr(r, "headers"), (
        "the control was supposed to drop the headers; if it does not, this fix is "
        "unmotivated")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
