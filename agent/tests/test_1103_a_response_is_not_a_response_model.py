"""#1103: the synonym fill-in let FastAPI infer a response model from `-> JSONResponse`.

`#235`'s BOOTSTRAP-SYNONYM FILL-IN aliases `/auth/signup` and `/auth/signin` onto the
AS's own `auth_register` / `auth_login` via ``app.add_api_route(path, fn, methods=…)``.
It passed no ``response_model``, so FastAPI infers one from the endpoint's return
annotation — and every AS handler is ``-> JSONResponse`` inside a module that begins
``from __future__ import annotations``, which makes that annotation the *string*
``"JSONResponse"``.

When the string does not resolve at the registration site, pydantic is handed
``ForwardRef('JSONResponse')`` and cannot build it. tiktok-r92 shipped a DELIVERED
milestone whose ``GET /openapi.json`` answers **500** for exactly this — four routes
(``/auth/signup``, ``/api/auth/signup``, ``/auth/signin``, ``/api/auth/signin``) each
carrying ``response_model=ForwardRef('JSONResponse')``.

★ Registration does not complain. ``add_api_route`` stores the ForwardRef and returns,
so the app boots clean and the fill-in's ``except Exception`` never sees anything; the
failure only surfaces when the schema is built. That is why it shipped. It reproduces on
the FastAPI this repo runs today (0.121 / pydantic 2.12) and is asserted below — the
first draft of that assertion claimed the raise happened at registration, which is what
the corpus artifact would have looked like only if anyone had ever called /openapi.json
during the run.

A ``JSONResponse`` return is a Response, and a Response is never a response model:
FastAPI skips it whenever it CAN resolve the annotation. Pinning ``response_model=None``
states what the annotation already means and makes the alias independent of how any
FastAPI version resolves annotations.
"""
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.backend_skeleton import (  # noqa: E402
    render_skeleton_main, write_backend_skeleton)
from multi_agent.runtime.oauth_scaffold import (  # noqa: E402
    render_oauth_module, write_oauth_as)

# a handler shaped exactly like the AS's: future-annotations + `-> JSONResponse`,
# with the name NOT resolvable in the module namespace
_UNRESOLVABLE = '''
from __future__ import annotations
async def handler() -> JSONResponse:
    from fastapi.responses import JSONResponse as J
    return J({"ok": True})
'''


def _handler(src):
    m = types.ModuleType("m_1103")
    exec(compile(src, "m_1103", "exec"), m.__dict__)
    return m.handler


def test_the_mechanism_breaks_without_the_pin():
    """★ Non-vacuity: prove the input really is poison before pinning it.

    And prove WHERE it breaks. Registration succeeds and quietly stores the ForwardRef —
    which is precisely why r92 shipped — and only building the schema fails."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    app = FastAPI()
    app.add_api_route("/x", _handler(_UNRESOLVABLE), methods=["POST"])   # no raise
    rm = next(getattr(r, "response_model", None) for r in app.routes
              if getattr(r, "path", "") == "/x")
    assert "ForwardRef" in repr(rm), rm
    with pytest.raises(Exception) as e:
        TestClient(app).get("/openapi.json")
    assert "JSONResponse" in str(e.value)


def test_the_pin_makes_the_same_registration_safe():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    app = FastAPI()
    app.add_api_route("/x", _handler(_UNRESOLVABLE), methods=["POST"],
                      response_model=None)
    r = TestClient(app).get("/openapi.json")
    assert r.status_code == 200
    assert "/x" in r.json()["paths"]


def test_the_route_still_works():
    """The pin must not change what the endpoint returns."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    app = FastAPI()
    app.add_api_route("/x", _handler(_UNRESOLVABLE), methods=["POST"],
                      response_model=None)
    assert TestClient(app).post("/x").json() == {"ok": True}


def test_the_fill_in_pins_it():
    src = render_skeleton_main([{"method": "GET", "path": "/api/videos"}], _T := {
        "videos": {"schema": {"columns": [
            {"name": "id", "type": "integer", "primary_key": True}]}}})
    i = src.index("_fw_alias_of = {")
    j = src.index("TENANTS-LIST FILL-IN", i)
    seg = src[i:j]
    assert "add_api_route" in seg
    assert "response_model=None" in seg


def test_the_as_handlers_really_are_annotated_that_way():
    """If the AS stopped returning JSONResponse this pin would be pointless — pin the
    premise so the reason stays visible."""
    src = render_oauth_module("oauth_routes.py")
    assert "from __future__ import annotations" in src
    assert "-> JSONResponse:" in src


_TABLES = {"videos": {"schema": {"columns": [
    {"name": "id", "type": "integer", "primary_key": True},
    {"name": "title", "type": "text"}]}}}


def test_a_rendered_app_serves_signup_and_a_working_openapi(tmp_path):
    """End to end: the alias exists AND the schema builds."""
    write_backend_skeleton(tmp_path, [{"method": "GET", "path": "/api/videos"}], _TABLES)
    write_oauth_as(tmp_path)
    be = tmp_path / "app" / "backend"
    keys = tmp_path / "k"
    keys.mkdir(exist_ok=True)
    env = dict(os.environ, DATABASE_URL=f"sqlite:///{tmp_path}/t.db",
               JWT_SECRET="x", JWT_DATA_DIR=str(keys))
    code = (
        "import sys,json;sys.path.insert(0,'.')\n"
        "import main\n"
        "from fastapi.testclient import TestClient\n"
        "r = TestClient(main.app).get('/openapi.json')\n"
        "print('STATUS', r.status_code)\n"
        "print('PATHS', json.dumps(sorted(r.json().get('paths', {}))))\n"
        "print('FWDREF', sum(1 for x in main.app.routes "
        "if 'ForwardRef' in repr(getattr(x, 'response_model', None))))\n")
    r = subprocess.run([sys.executable, "-c", code], cwd=str(be), env=env,
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr[-1500:]
    assert "STATUS 200" in r.stdout, r.stdout
    assert "/auth/signup" in r.stdout
    assert "FWDREF 0" in r.stdout, r.stdout


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
