"""#1202gs — a chain step's 500 records "Internal Server Error" and nothing else.

r99 (live, reproduced on the delivered stack after the run died at its cap): the run reached
ONE failing gate check, `business_chain_failing`, and every broken step read:

    GET /api/videos/40   500   Internal Server Error

The reason was sitting in the backend container the whole time:

    File "/app/custom_routes.py", line 97, in _tiktok_public_read_middleware
        return JSONResponse({"item": _video_item(db, video)})
    TypeError: Object of type datetime is not JSON serializable

A seeded row reads fine (its `created_at` is NULL); a row the chain CREATES gets a real
timestamp and `JSONResponse`'s plain `json.dumps` has no datetime encoder. One lane edit.

`classify_endpoint_failure` only calls a 500 attributable when the RESPONSE BODY carries a
traceback, and FastAPI in production answers a bare `Internal Server Error` — the traceback
goes to stderr. So the one fact that names the file, the line and the exception never reaches
the lane, which is the same shape as #1202gb (opaque 400), #1202fr (401 with no endpoint) and
#1202gq (advice for the wrong rule): the framework holds an actionable fact and reports the
category. The capability already exists — `validation_runner` runs
`compose logs --tail 30 backend` — the chain executor just never asks.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.chain_executor import (  # noqa: E402
    _backend_traceback_1202gs, _last_exception_1202gs)

# Verbatim from `docker logs tiktok-web-r99-backend-1`, trimmed to the frames that matter.
_R99_LOG = '''INFO:     127.0.0.1:58558 - "GET /health HTTP/1.1" 200 OK
INFO:     172.18.0.1:41290 - "POST /api/videos HTTP/1.1" 201 Created
ERROR:    Exception in ASGI application
Traceback (most recent call last):
  File "/usr/local/lib/python3.11/site-packages/uvicorn/protocols/http/h11_impl.py", line 416, in run_asgi
    result = await app(
  File "/usr/local/lib/python3.11/site-packages/starlette/middleware/base.py", line 193, in __call__
    response = await self.dispatch_func(request, call_next)
  File "/app/custom_routes.py", line 97, in _tiktok_public_read_middleware
    return JSONResponse({"item": _video_item(db, video)})
  File "/usr/local/lib/python3.11/json/encoder.py", line 180, in default
    raise TypeError(f'Object of type {o.__class__.__name__} '
TypeError: Object of type datetime is not JSON serializable
INFO:     127.0.0.1:58600 - "GET /health HTTP/1.1" 200 OK
'''


def test_the_exception_line_survives():
    out = _last_exception_1202gs(_R99_LOG)
    assert "TypeError: Object of type datetime is not JSON serializable" in out, out


def test_the_app_frame_is_kept_and_the_library_frames_are_not():
    """The lane needs the file it can edit, not uvicorn's call stack."""
    out = _last_exception_1202gs(_R99_LOG)
    assert "custom_routes.py" in out and "97" in out, out
    assert "h11_impl" not in out and "site-packages" not in out, (
        "library frames crowd out the one line the lane can act on:\n%s" % out)


def test_health_chatter_is_not_mistaken_for_the_failure():
    out = _last_exception_1202gs(_R99_LOG)
    assert "GET /health" not in out, out


def test_a_log_with_no_traceback_yields_nothing():
    """#883/#1202ah — 'nothing found' must read as nothing, never as a fabricated cause."""
    assert _last_exception_1202gs('INFO: 1.2.3.4 - "GET /api/videos HTTP/1.1" 200 OK\n') == ""
    assert _last_exception_1202gs("") == ""
    assert _last_exception_1202gs(None) == ""


def test_the_most_recent_traceback_wins():
    """Two failures in one window: the step being recorded is the later one."""
    older = _R99_LOG.replace("datetime is not JSON serializable", "Decimal is not serializable")
    out = _last_exception_1202gs(older + _R99_LOG)
    assert "datetime" in out and "Decimal" not in out, out


def test_the_recorder_asks_for_it_on_a_5xx():
    """A mechanism nobody calls is the failure mode this codebase repeats most."""
    src = (LLM / "multi_agent" / "runtime" / "chain_executor.py").read_text(encoding="utf-8")
    at = src.index('entry["sent_body"] = _sent_body_1202ew(body)')
    block = src[at:src.index("if autofilled:", at)]
    assert "_backend_traceback_1202gs(" in block, (
        "the failing-step recorder never asks for the server's own traceback:\n%s" % block)


def test_it_is_not_asked_for_when_the_status_is_not_a_server_error():
    """#647 — a 404 or 422 is the server answering, not crashing; no log read for those."""
    import inspect
    src = inspect.getsource(_backend_traceback_1202gs)
    assert "500" in src, "the 5xx precondition is not stated where the read happens"


def test_a_missing_stack_is_not_an_error():
    """The stack is routinely down when a gate re-reads a chain; that must stay silent-safe."""
    assert _backend_traceback_1202gs("/nonexistent/project", 500) == ""
