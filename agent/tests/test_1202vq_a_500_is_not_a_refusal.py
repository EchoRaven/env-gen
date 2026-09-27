"""#1202vq: a 500 is not a refusal — the route was REACHED and the handler raised.

#1006 classifies "main.py mounts it and the app still refuses it" as a defect no lane can
repair, and tells the lane so: *"Do NOT try to add them; main.py is framework-owned and your
writes to it are denied. Report what the running app returns and move on."*

It matched on the route alone. Whatever the app answered, a failure on a mounted route was
reported as unrepairable. Measured across every run log in the corpus — 23 firings, 12 runs,
r115 through r137 — **not one** was the 404/405 case the mechanism exists for:

    21   a 5xx, usually with the lane's own traceback in the same fragment
     2   ConnectionResetError, where nothing answered at all

So the check that carries the largest share of final blockers was telling the backend lane to
walk away from lines like::

    POST /api/videos/{video_id}/comments → 500 | backend traceback:
    custom_routes.py:1154 in create_video_comment — HTTPException: 422: text is required

`custom_routes.py` is the lane's file and the fragment names it. The two transport cases get
the sibling treatment (#1202od): nothing answered, so nothing here is evidence about code.
"""
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.backend_audit import (      # noqa: E402
    REFUSED_STATUSES_1202vq, fragment_status_1202vq, unreachable_but_mounted)


def _mk(tmp_path, routes: str):
    be = tmp_path / "backend"
    be.mkdir()
    (be / "main.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n" + routes, encoding="utf-8")
    return be


@pytest.mark.parametrize("status", sorted(REFUSED_STATUSES_1202vq))
def test_a_refusal_on_a_mounted_route_is_still_the_frameworks(tmp_path, status):
    be = _mk(tmp_path, '@app.post("/api/cw")\ndef h(): return {}\n')
    frag = f"POST /api/cw → {status}"
    assert unreachable_but_mounted(be, [frag]) == [frag]


def test_a_handler_that_raised_is_not_a_refusal(tmp_path):
    """The 21-of-23 case. The route was reached; the traceback names the lane's own file."""
    be = _mk(tmp_path, '@app.post("/api/cw")\ndef h(): return {}\n')
    frag = ("POST /api/cw → 500 | backend traceback: custom_routes.py:1154 in "
            "create_video_comment — HTTPException: 422: text is required")
    assert unreachable_but_mounted(be, [frag]) == []


@pytest.mark.parametrize("status", [500, 502, 503, 422, 401, 200])
def test_no_other_status_is_read_as_a_refusal(tmp_path, status):
    be = _mk(tmp_path, '@app.post("/api/cw")\ndef h(): return {}\n')
    assert unreachable_but_mounted(be, [f"POST /api/cw → {status}"]) == []


def test_an_unanswered_request_is_not_a_refusal_either(tmp_path):
    """The other 2 of 23. Nothing answered, so 'the app refuses it' is not a claim
    anyone can make (#1202od)."""
    be = _mk(tmp_path, '@app.get("/api/search")\ndef h(): return {}\n')
    frag = ("GET /api/search → ConnectionResetError: [Errno 104] Connection reset "
            "by peer")
    assert unreachable_but_mounted(be, [frag]) == []


def test_mixed_input_keeps_only_the_refusal(tmp_path):
    be = _mk(tmp_path, '@app.post("/api/cw")\ndef h(): return {}\n'
                       '@app.get("/api/feed")\ndef g(): return {}\n')
    got = unreachable_but_mounted(be, [
        "POST /api/cw → 405",
        "GET /api/feed → 500 | backend traceback: custom_routes.py:62",
        "GET /api/nope → 404",
    ])
    assert got == ["POST /api/cw → 405"]


def test_the_status_reader_handles_both_arrows_and_admits_when_there_is_none():
    assert fragment_status_1202vq("POST /api/cw → 405") == 405
    assert fragment_status_1202vq("POST /api/cw -> 500") == 500
    assert fragment_status_1202vq("POST /api/cw") is None
    assert fragment_status_1202vq("GET /x → ConnectionResetError: [Errno 104]") is None
    assert fragment_status_1202vq(None) is None
    # a number that is not the answer must not be mistaken for one
    assert fragment_status_1202vq("GET /api/v2/items/404") is None


def test_a_fragment_with_no_status_is_not_classified(tmp_path):
    """Silence about the answer is not evidence of a refusal."""
    be = _mk(tmp_path, '@app.post("/api/cw")\ndef h(): return {}\n')
    assert unreachable_but_mounted(be, ["POST /api/cw"]) == []


def test_the_dispatcher_says_the_true_thing_for_an_unanswered_request():
    """The narrowing alone would hand a socket error back to the lane as ordinary work,
    which is the harm #1202od exists to prevent. The dispatcher names it instead."""
    import ast
    import inspect

    from multi_agent.runtime import remediation_dispatcher as rd
    fn = next(n for n in ast.walk(ast.parse(inspect.getsource(rd)))
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and "unreachable_but_mounted" in ast.unparse(n))
    body = ast.unparse(fn)
    assert "is_transport_failure_1202od" in body, (
        "the transport case must be recognised with the framework's one copy of that rule")
    assert "DID NOT ANSWER" in body
    assert "Do NOT edit a handler for these" in body


def test_the_classifier_failing_is_not_silent():
    """#1202ah: if this classification raises, the lane silently gets the raw detail back —
    indistinguishable from 'there was nothing to classify'."""
    import ast
    import inspect

    from multi_agent.runtime import remediation_dispatcher as rd
    fn = next(n for n in ast.walk(ast.parse(inspect.getsource(rd)))
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and "unreachable_but_mounted" in ast.unparse(n))
    body = ast.unparse(fn)
    assert "warn_once_1201" in body


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
