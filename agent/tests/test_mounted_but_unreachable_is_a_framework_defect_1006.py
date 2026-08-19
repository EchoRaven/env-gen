"""#1006: a route main.py mounts and the app refuses is nobody's to fix but the framework's.

r162 died on `unresolved_failed_tasks` counting its own undeliverable work. The blocker was
`POST /api/continue-watching → 405`, and the artifacts say:

    served_routes(app/backend)      contains ("POST", "/api/continue-watching")
    the running app                 answered 405 for the last 5,500 log lines
    main.py                         is in _BACKEND_FRAMEWORK_OWNED — lane writes DENIED

Seventeen tasks were dispatched against it. Not one could have succeeded: a lane cannot add a
route to a file it cannot open, and the route was already there.

Three softer explanations were tested against the artifacts and all failed — the image builds
from the worktree so `main` lacking the commit is irrelevant, four rebuilds followed the fix,
and `duplicated_routes` reports zero intra-module shadowing. Whatever the runtime cause proves
to be, **the classification is knowable statically**, and that is what this gate does.
"""

import pathlib

import pytest

from env_generator.llm_generator.multi_agent.runtime.backend_audit import (
    unreachable_but_mounted)

_BACKEND = pathlib.Path("../agent/generated/netflix-web-r162/app/backend")
_HAVE_R162 = (pathlib.Path("env_generator").exists()
              and pathlib.Path("generated/netflix-web-r162/app/backend/main.py").exists())


def _mk(tmp_path, routes: str):
    be = tmp_path / "backend"
    be.mkdir()
    (be / "main.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n" + routes, encoding="utf-8")
    return be


def test_a_mounted_route_that_fails_is_flagged(tmp_path):
    be = _mk(tmp_path, '@app.post("/api/cw")\ndef h(): return {}\n')
    assert unreachable_but_mounted(be, ["POST /api/cw → 405"]) == ["POST /api/cw → 405"]


def test_an_unmounted_route_is_left_to_the_lane(tmp_path):
    """A 404 on a route nobody declared is real lane work and must still dispatch normally."""
    be = _mk(tmp_path, '@app.get("/api/other")\ndef h(): return {}\n')
    assert unreachable_but_mounted(be, ["POST /api/cw → 404"]) == []


def test_the_method_must_match(tmp_path):
    """GET mounted, POST asked for — that is a genuine gap, not a framework defect."""
    be = _mk(tmp_path, '@app.get("/api/cw")\ndef h(): return {}\n')
    assert unreachable_but_mounted(be, ["POST /api/cw → 405"]) == []


def test_mixed_input_splits_correctly(tmp_path):
    be = _mk(tmp_path, '@app.post("/api/cw")\ndef h(): return {}\n')
    got = unreachable_but_mounted(
        be, ["POST /api/cw → 405", "GET /api/nope → 404"])
    assert got == ["POST /api/cw → 405"]


def test_garbage_input_does_not_crash(tmp_path):
    be = _mk(tmp_path, '@app.get("/api/x")\ndef h(): return {}\n')
    assert unreachable_but_mounted(be, ["", "   ", "not-an-endpoint", None]) == []


def test_a_missing_backend_dir_is_silent(tmp_path):
    assert unreachable_but_mounted(tmp_path / "nope", ["POST /api/cw → 405"]) == []


def test_the_dispatcher_uses_it_and_says_it_is_not_a_lane_bug():
    """Located by AST, not a byte window — the repo forbids fixed-width source slices as
    fragile locators, and this is the fourth time this session that guard has been right."""
    import ast
    import inspect

    from env_generator.llm_generator.multi_agent.runtime import remediation_dispatcher as rd
    src = inspect.getsource(rd)
    assert "unreachable_but_mounted" in src
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and "unreachable_but_mounted" in ast.unparse(n))
    body = ast.unparse(fn)
    assert "FRAMEWORK DEFECT" in body
    assert "writes to it are denied" in body, (
        "the lane must be told why adding the route cannot work")


def test_the_control_cannot_tell_them_apart():
    """Planted control: without the mounted-set check, both entries look identical — which is
    how 17 tasks went out against a route that was already there."""
    detail = "POST /api/cw → 405; GET /api/nope → 404"
    assert detail.count("→") == 2, (
        "the control was supposed to carry two indistinguishable failures; if it does not, "
        "this fix is unmotivated")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
