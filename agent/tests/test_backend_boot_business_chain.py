"""Audit rank-8 (render+boot+business_chain integration net): the whack-a-mole bugs
(#392 boot NameError, #393 ORM/DDL NotNull, #394/#395 rating coercion, #390/#391 profile
auto-create) all slipped past the unit tests because those ran EXTRACTED functions with
clean inputs — the bugs only surfaced when the rendered backend actually BOOTED and served
a request. This renders the netflix per-profile shape (users/profiles/titles/ratings), boots
the generated FastAPI app against a real (SQLite) database, and runs the rating
business_chain with the exact loosely-typed body ({"value":"up"}) that wedged the live runs.
It locks in, at test speed:

  * BOOT — the app imports + create_all + serves /health (would catch #392's SessionLocal
    NameError and any import/render break).
  * COERCION RUNS in the real handler path — {"value":"up"} is persisted as 0, not "up".
  * PROFILE AUTO-CREATE + OWNER-SCOPING — a fresh user with no profile can rate: the handler
    auto-creates their profile (#390/#391) and scopes the rating to it. (FK enforcement is
    left OFF — see the fixture — so the asserts, not the DB, carry the load: an un-run
    auto-create leaves `profiles` empty and the profile/owner-scoping asserts fail.)

This box has no postgres (no binary/psycopg), so SQLite is the stand-in; the DB-free
ORM/DDL parity is separately locked by test_orm_ddl_parity.py (#396).
"""
import os
import sys

import pytest

from env_generator.llm_generator.multi_agent.runtime.backend_skeleton import (
    render_skeleton_main, render_models, _DATABASE_PY)

_TABLES = {
    "users": {"columns": [
        {"name": "id", "type": "integer", "primary_key": True},
        {"name": "email", "type": "text not null"},
        {"name": "name", "type": "text not null"}]},
    "profiles": {"columns": [
        {"name": "id", "type": "integer", "primary_key": True},
        {"name": "user_id", "type": "integer references users(id)"},
        {"name": "name", "type": "text not null"}]},
    "titles": {"columns": [
        {"name": "id", "type": "integer", "primary_key": True},
        {"name": "name", "type": "text"}]},
    "ratings": {"columns": [
        {"name": "id", "type": "integer", "primary_key": True},
        {"name": "profile_id", "type": "integer references profiles(id)"},
        {"name": "title_id", "type": "integer references titles(id)"},
        {"name": "value", "type": "integer not null"}]},
}
_EPS = [{"method": "POST", "path": "/api/titles/{id}/rating", "auth_required": True},
        {"method": "GET", "path": "/api/ratings", "auth_required": True}]

_AUTH_STUB = '''"""test stub auth dep — returns a settable current user."""
_USER = {"id": 1, "sub": "1"}


def set_user(u):
    global _USER
    _USER = u


def get_current_user():
    return _USER
'''

_GEN_MODS = ("database", "models", "auth_dependency", "seed_data", "main",
             "custom_routes", "oauth_store", "jwt_manager", "oauth_routes")


@pytest.fixture
def app_ctx(tmp_path):
    be = tmp_path
    (be / "database.py").write_text(_DATABASE_PY, encoding="utf-8")
    (be / "models.py").write_text(render_models(_TABLES), encoding="utf-8")
    (be / "auth_dependency.py").write_text(_AUTH_STUB, encoding="utf-8")
    (be / "main.py").write_text(render_skeleton_main(_EPS, _TABLES), encoding="utf-8")

    saved_path = list(sys.path)
    saved_env = os.environ.get("DATABASE_URL")
    saved_mods = {k: sys.modules[k] for k in _GEN_MODS if k in sys.modules}
    for k in _GEN_MODS:
        sys.modules.pop(k, None)
    os.environ["DATABASE_URL"] = "sqlite:///" + str(be / "app.db")
    sys.path.insert(0, str(be))
    try:
        import main as gen_main  # BOOT: import + Base.metadata.create_all + seed (guarded)
        # NB: SQLite FK enforcement is left OFF (postgres-spine tenants FK would need a full
        # spine seed). The assertions carry the load anyway: an un-run auto-create leaves
        # `profiles` empty and the profile/owner-scoping asserts fail regardless of FKs.
        import auth_dependency as gen_auth
        # The framework auth middleware walls every /api/ route on a valid bearer token it
        # verifies against module-global _FW_PEM/_FWALG (the AS public key — absent here, so
        # it would 401 everything). Override to a symmetric key and send a matching token so
        # requests reach the projected handlers; get_current_user (the stub) supplies the user.
        import jwt as _pyjwt
        gen_main._FW_PEM = "fw-integration-test-secret-key-0123456789"
        gen_main._FWALG = "HS256"
        from fastapi.testclient import TestClient
        client = TestClient(gen_main.app)
        client.headers.update(
            {"Authorization": "Bearer " + _pyjwt.encode({"sub": "1"}, "fw-integration-test-secret-key-0123456789",
                                                         algorithm="HS256")})
        yield gen_main, gen_auth, client
    finally:
        sys.path[:] = saved_path
        if saved_env is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = saved_env
        for k in _GEN_MODS:
            sys.modules.pop(k, None)
        sys.modules.update(saved_mods)


def _seed_user_and_title(gen_main):
    db = gen_main.SessionLocal()
    try:
        # the framework spine `users` table carries password_hash + tenant_id NOT NULL;
        # set them so the seed insert succeeds (FK enforcement is off, so no tenants row).
        db.add(gen_main.User(id=1, email="a@example.com", name="Ann",
                             password_hash="x", tenant_id="default"))
        db.add(gen_main.Title(id=1, name="Inception"))
        db.commit()
    finally:
        db.close()


def test_app_boots_and_serves_health(app_ctx):
    gen_main, _auth, client = app_ctx
    r = client.get("/health")
    assert r.status_code == 200, r.text
    assert r.json().get("status") == "healthy"


def test_rating_chain_coerces_and_autocreates_profile(app_ctx):
    gen_main, gen_auth, client = app_ctx
    _seed_user_and_title(gen_main)
    gen_auth.set_user({"id": 1, "sub": "1"})

    # the exact live wedge: a thumbs rating POSTed as a STRING into the INTEGER value column
    r = client.post("/api/titles/1/rating", json={"value": "up"})
    assert r.status_code < 500, "rating POST 500'd (the pre-#395 wedge): %s" % r.text
    assert r.status_code < 400, "rating POST 4xx'd (the pre-#390/#395 wedge): %s" % r.text

    db = gen_main.SessionLocal()
    try:
        profiles = db.query(gen_main.Profile).all()
        ratings = db.query(gen_main.Rating).all()
    finally:
        db.close()

    # #390/#391: a fresh user with no profile got one auto-created, owned by them
    assert len(profiles) == 1, "profile was not auto-created (#390/#391)"
    assert profiles[0].user_id == 1
    # #395: "up" was coerced to the INTEGER column's type (0), not inserted raw
    assert len(ratings) == 1, ratings
    assert ratings[0].value == 0, "rating value not coerced: %r" % ratings[0].value
    # owner-scoping: the rating is bound to the caller's (auto-created) profile
    assert ratings[0].profile_id == profiles[0].id


def test_second_rating_reuses_the_same_profile(app_ctx):
    # auto-create is once-per-user: a second rating must not spawn a duplicate profile
    gen_main, gen_auth, client = app_ctx
    _seed_user_and_title(gen_main)
    db = gen_main.SessionLocal()
    try:
        db.add(gen_main.Title(id=2, name="Tenet"))
        db.commit()
    finally:
        db.close()
    gen_auth.set_user({"id": 1, "sub": "1"})

    r1 = client.post("/api/titles/1/rating", json={"value": 5})
    r2 = client.post("/api/titles/2/rating", json={"value": 4})
    assert r1.status_code < 400 and r2.status_code < 400, (r1.text, r2.text)

    db = gen_main.SessionLocal()
    try:
        assert db.query(gen_main.Profile).count() == 1, "duplicate profile auto-created"
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
