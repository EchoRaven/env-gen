"""FIX #82 — framework-owned IntegrityError→REST-status mapping in the generated backend
(instagram-core-di run-2, 2026-07-06 00:13 STUCK).

Lane-written action handlers (POST /api/users/{id}/follow) INSERT a row whose FK comes from the
path WITHOUT checking the target exists → the psycopg ForeignKeyViolation escaped as a raw 500 →
the verifier's chain (which correctly tolerated [200, 201, 404]) never matched → business_chain
wedged 7 post-cap cycles → STUCK abort on a semantically-reasonable chain + app. The framework
owns the floor: inject a global SQLAlchemy IntegrityError exception handler into the generated
main.py mapping FK violation (23503) → 404, unique (23505) → 409, other integrity → 400.
ENV-AGNOSTIC + LOCAL-ONLY (agent/tests/ gitignored).
"""

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.backend_scaffold import repair_integrity_error_handler  # noqa: E402

_MAIN = '''\
from fastapi import FastAPI

app = FastAPI()


@app.get("/health")
def health():
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app)
'''


def _mk_backend(tmp_path, src=_MAIN):
    be = tmp_path / "backend"
    be.mkdir()
    (be / "main.py").write_text(src, encoding="utf-8")
    return be


def test_injects_handler_and_is_idempotent(tmp_path):
    be = _mk_backend(tmp_path)
    out = repair_integrity_error_handler(be)
    assert out.get("injected") is True
    src = (be / "main.py").read_text(encoding="utf-8")
    assert "_framework_integrity_error_handler" in src
    ast.parse(src)                                     # still valid python
    again = repair_integrity_error_handler(be)
    assert again.get("injected") is False              # idempotent


def test_graceful_without_main_py(tmp_path):
    be = tmp_path / "backend"
    be.mkdir()
    assert repair_integrity_error_handler(be).get("injected") is False


def test_graceful_without_fastapi_app(tmp_path):
    be = _mk_backend(tmp_path, src="print('not a fastapi app')\n")
    assert repair_integrity_error_handler(be).get("injected") is False


def test_runtime_maps_fk_unique_and_other(tmp_path):
    """Execute the INJECTED main.py for real: FK violation (pgcode 23503) → 404,
    unique (23505) → 409, other integrity → 400 — the statuses verifier chains tolerate."""
    from fastapi.testclient import TestClient
    from sqlalchemy.exc import IntegrityError

    be = _mk_backend(tmp_path)
    assert repair_integrity_error_handler(be).get("injected") is True
    src = (be / "main.py").read_text(encoding="utf-8")
    src = src[:src.index('if __name__ ==')]            # don't uvicorn.run in the test
    ns: dict = {"__name__": "generated_main"}
    exec(compile(src, str(be / "main.py"), "exec"), ns)
    app = ns["app"]

    class _Orig:  # a psycopg-shaped error carrying pgcode
        def __init__(self, pgcode):
            self.pgcode = pgcode

    def _raise(pgcode):
        raise IntegrityError("stmt", {}, _Orig(pgcode))

    @app.post("/api/users/{uid}/follow")
    def follow(uid: int):
        _raise("23503")                                 # FK: target user missing

    @app.post("/api/dup")
    def dup():
        _raise("23505")                                 # unique violation

    @app.post("/api/other")
    def other():
        _raise("23514")                                 # check violation → generic 400

    c = TestClient(app, raise_server_exceptions=False)
    assert c.post("/api/users/1001/follow").status_code == 404
    assert c.post("/api/dup").status_code == 409
    assert c.post("/api/other").status_code == 400
    assert c.get("/health").status_code == 200          # normal routes untouched


def test_runtime_reads_psycopg3_sqlstate_and_message_text(tmp_path):
    """the generated app depends on psycopg 3 (pyproject: psycopg[binary]) whose errors
    carry ``sqlstate`` — NOT psycopg2's ``pgcode``. And a driver-agnostic last resort:
    sniff 'foreign key' in the message."""
    from fastapi.testclient import TestClient
    from sqlalchemy.exc import IntegrityError

    be = _mk_backend(tmp_path)
    assert repair_integrity_error_handler(be).get("injected") is True
    src = (be / "main.py").read_text(encoding="utf-8")
    src = src[:src.index('if __name__ ==')]
    ns: dict = {"__name__": "generated_main"}
    exec(compile(src, str(be / "main.py"), "exec"), ns)
    app = ns["app"]

    class _Pg3Orig:                                  # psycopg3-shaped: sqlstate, no pgcode
        def __init__(self, sqlstate):
            self.sqlstate = sqlstate

    @app.post("/api/fk3")
    def fk3():
        raise IntegrityError("stmt", {}, _Pg3Orig("23503"))

    @app.post("/api/fktext")
    def fktext():
        raise IntegrityError(
            "stmt", {},
            Exception('insert or update on table "follows" violates foreign key '
                      'constraint "follows_following_id_fkey"'))

    c = TestClient(app, raise_server_exceptions=False)
    assert c.post("/api/fk3").status_code == 404
    assert c.post("/api/fktext").status_code == 404


def test_skeleton_main_includes_integrity_handler_by_construction():
    """run-3 (2026-07-06): the heal-time injection was ERASED every skeleton regeneration
    (regen → inject → regen race; the deployed container held an un-healed main.py). The
    handler must live in the BY-CONSTRUCTION skeleton itself."""
    from multi_agent.runtime.backend_skeleton import render_skeleton_main
    src = render_skeleton_main(
        [{"method": "GET", "path": "/api/things", "auth_required": True}],
        {"things": {"columns": [{"name": "id", "type": "integer"}]}})
    assert "_framework_integrity_error_handler" in src
    ast.parse(src)


def test_wired_into_heal_pipeline():
    import inspect
    from multi_agent.runtime import heal_pipeline
    src = inspect.getsource(heal_pipeline)
    assert "repair_integrity_error_handler" in src


def test_auth_guard_injects_user_id_into_request_state():
    """FIX #109 (run-28 live): the lane's feed handler read request.state.user_id —
    a convention the lane BELIEVES the framework provides (its own comment says so) —
    but the guard only validated the JWT and never populated state → user_id always
    None → 401 on a valid token → business_chain wedged while follow/unfollow (using
    Depends(get_current_user)) worked with the same token. Make the belief true: on
    successful validation the guard sets request.state.user_id from the sub claim."""
    from multi_agent.runtime.backend_scaffold import _AUTH_MIDDLEWARE
    assert "request.state.user_id" in _AUTH_MIDDLEWARE
    i = _AUTH_MIDDLEWARE.index("request.state.user_id")
    window = _AUTH_MIDDLEWARE[max(0, i - 800):i]
    assert "decode" in window          # set from the DECODED claims (post-validation)
