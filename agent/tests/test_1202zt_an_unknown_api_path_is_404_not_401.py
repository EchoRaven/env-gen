r"""#1202zt: the blanket auth guard answered 401 for routes that do not exist.

`_AUTH_MIDDLEWARE` is an `@app.middleware("http")`, so it runs BEFORE routing: it decides from
the PATH alone and refuses. Until now every unknown path under `/api/` came back 401 while an
unknown path anywhere else came back 404 — measured identical on all four delivered stacks still
running (r140/r139/r135/r132):

    GET /api/this-route-does-not-exist  -> 401
    GET /definitely-not-a-route         -> 404

A frontend that mistypes a path is then told its credentials are wrong. That is the user's
standing rule head on — a fallback that masks the failure instead of reporting it — and it is not
generically correct projected code either: there is no handler behind an unmatched path, so
nothing can be published by letting it through, and FastAPI's own 404 is the true answer.

MEASURED RISK, against every verification chain in the corpus: 153 runs, 29,605 chain steps,
1,768 of them expecting 401/403 on a NON-PUBLIC `/api/` path. Exactly ONE names a path its run
does not serve (r120 `PUT /api/dm_messages/${dm_id}`), and that step already accepts 404 — so no
chain in the corpus changes verdict.

★ THAT NUMBER TOOK FOUR TRIES and the first three were my own normalisation errors: globbing
`registryhub_chains.json` when the file is `registryhub_verification_chains.json` (0 of 0, read
as "no risk"), then 23.4% because `served_routes` does not list the OAuth AS router so
`/auth/login` looked absent, then 0.3% because `{video_id}` was not folded to `{}`. Only the
fourth run is quoted above.

★ `Match.PARTIAL` counts as existing, so a wrong METHOD on a real path keeps its 401 rather than
becoming a 405. The change is the narrowest one that fixes the reported cause: a path that
matches NOTHING.
"""
import ast
import os
import sys

import pytest

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

import multi_agent.runtime.backend_scaffold as BS  # noqa: E402

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402


def _app(public_pairs=()):
    """Run the PROJECTED middleware over a real FastAPI app, the way a delivered backend does."""
    import contextvars
    app = fastapi.FastAPI()

    @app.get("/api/videos")
    def _videos():
        return {"items": [], "total": 0}

    @app.post("/api/videos/{video_id}/like")
    def _like(video_id: int):
        return {"ok": True}

    @app.get("/api/open")
    def _open():
        return {"ok": True}

    ns = {
        "app": app,
        "_FW_PROFILE_CTX_1190": contextvars.ContextVar("p", default=None),
        "_FW_PUBLIC_API_1202KH": list(public_pairs),
    }
    exec(compile(ast.parse(BS._AUTH_MIDDLEWARE), "<middleware>", "exec"), ns)
    return TestClient(app, raise_server_exceptions=False)


# ── the fix ───────────────────────────────────────────────────────────────────────

def test_an_unknown_api_path_is_404():
    """★ The whole ticket."""
    assert _app().get("/api/this-route-does-not-exist-1202zt").status_code == 404


def test_an_unknown_nested_api_path_is_404():
    assert _app().get("/api/videos/1/definitely-not-here").status_code == 404


# ── everything that must NOT change ───────────────────────────────────────────────

def test_a_real_protected_route_still_refuses_without_a_token():
    assert _app().get("/api/videos").status_code == 401


def test_a_real_protected_param_route_still_refuses():
    assert _app().post("/api/videos/7/like").status_code == 401


def test_a_wrong_method_on_a_real_path_keeps_its_401():
    """`Match.PARTIAL` counts as existing: the narrowest possible change, and a caller that used
    the wrong verb is still told the route is guarded rather than that it is missing."""
    assert _app().post("/api/videos").status_code == 401


def test_a_contract_public_route_is_served():
    c = _app(public_pairs=[("GET", "/api/open")])
    assert c.get("/api/open").status_code == 200


def test_an_unknown_path_outside_api_is_untouched():
    assert _app().get("/definitely-not-a-route").status_code == 404


def test_health_is_still_public():
    # no /health route on this app, so the interesting assertion is that the guard let it THROUGH
    # to FastAPI rather than refusing it
    assert _app().get("/health").status_code == 404


# ── the helper's own contract ─────────────────────────────────────────────────────

def test_the_helper_says_yes_when_it_cannot_tell():
    """A fault must leave the refusal exactly as it was. Anything else would turn an internal
    error into an open door."""
    tree = ast.parse(BS._AUTH_MIDDLEWARE)
    fn = [n for n in ast.walk(tree)
          if isinstance(n, ast.FunctionDef) and n.name == "_fw_route_exists_1202zt"]
    assert fn, "the helper is gone"
    handlers = [h for h in ast.walk(fn[0]) if isinstance(h, ast.ExceptHandler)]
    assert handlers, "the helper no longer tolerates a fault"
    for h in handlers:
        rets = [n for n in h.body if isinstance(n, ast.Return)]
        assert rets, "an except branch that falls through would read as 'no route'"
        for r in rets:
            assert isinstance(r.value, ast.Constant) and r.value.value is True, \
                "a fault must answer True (refuse as before), not False"


def test_the_guard_calls_it_before_refusing():
    """★ I have tested a helper and not its caller repeatedly. The call must sit inside the
    `/api/`-and-not-public branch, ahead of the 401."""
    tree = ast.parse(BS._AUTH_MIDDLEWARE)
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and getattr(n.func, "id", "") == "_fw_route_exists_1202zt"]
    assert len(calls) == 1, "called %d times" % len(calls)
    guard = [n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)
             and n.name == "_framework_auth_guard"]
    assert guard, "the middleware is gone"
    lines = [n.lineno for n in ast.walk(guard[0])
             if isinstance(n, ast.Return) and isinstance(n.value, ast.Call)
             and "JSONResponse" in ast.dump(n.value)]
    assert lines, "the 401 response is gone"
    assert calls[0].lineno < min(lines), "the check must run BEFORE the refusal"
