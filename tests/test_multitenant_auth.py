"""Security guard: Env Forge is admin-only and STRICTLY tenant-isolated.

Pins the no-cross-tenant-leakage contract so it cannot regress. Auth config is
read at import time, so we enable auth before importing the app. Run with:

    cd forgingground-gen && pytest tests/test_multitenant_auth.py
"""
import base64
import os
import tempfile
import time
from pathlib import Path

# ── enable real auth before importing the app (constants are import-time) ─────
_DB = tempfile.mktemp(suffix=".db")
os.environ["AGENTSUITE_AUTH_ENABLED"] = "true"
os.environ["AGENTSUITE_JWT_SECRET"] = "guard-test-secret"
os.environ["DATABASE_URL"] = f"sqlite:///{_DB}"
os.environ["ENVS_ROOT"] = tempfile.mkdtemp()  # empty → no disk envs get synced

import jwt
import pytest
from fastapi.testclient import TestClient

import app.main as m
from app.db import SessionLocal
from app.models import Environment

SECRET = os.environ["AGENTSUITE_JWT_SECRET"]


def tok(sub="u", tenant="t", admin=True, with_tenant=True):
    p = {"sub": sub, "is_admin": admin, "exp": int(time.time()) + 3600}
    if with_tenant:
        p["tenant_id"] = tenant
    return jwt.encode(p, SECRET, algorithm="HS256")


def hdr(**kw):
    return {"Authorization": "Bearer " + tok(**kw)}


@pytest.fixture()
def client():
    with TestClient(m.app) as c:  # context manager fires startup → init_db
        yield c


def _add_env(eid, tenant, by="u"):
    with SessionLocal() as db:
        db.add(Environment(id=eid, name=eid, tenant_id=tenant, created_by=by,
                           generated_dir="", status="completed"))
        db.commit()


def test_no_token_is_401(client):
    assert client.get("/env-forge/environments").status_code == 401


def test_non_admin_is_403(client):
    assert client.get("/env-forge/environments", headers=hdr(admin=False)).status_code == 403


def test_tokenless_tenant_is_403(client):
    # A token with no tenant_id claim can't be scoped → fail closed.
    assert client.get("/env-forge/environments", headers=hdr(with_tenant=False)).status_code == 403


def test_admin_sees_only_own_tenant(client):
    _add_env("iso-a", "tenantA", "uA")
    _add_env("iso-b", "tenantB", "uB")
    ids = [e["id"] for e in client.get("/env-forge/environments", headers=hdr(sub="uA", tenant="tenantA")).json()]
    assert "iso-a" in ids and "iso-b" not in ids


def test_cross_tenant_get_is_404_not_403(client):
    _add_env("iso-a2", "tenantA", "uA")
    # 404 (not 403) so we never even confirm another tenant's env exists.
    assert client.get("/env-forge/environments/iso-a2", headers=hdr(sub="uB", tenant="tenantB")).status_code == 404


def test_cross_tenant_subresources_are_404(client):
    _add_env("iso-a3", "tenantA", "uA")
    hB = hdr(sub="uB", tenant="tenantB")
    for sub in ("", "/runs", "/state", "/files", "/chat", "/references/x.png"):
        assert client.get(f"/env-forge/environments/iso-a3{sub}", headers=hB).status_code == 404, sub


def test_orphan_env_is_invisible_to_everyone(client):
    # _sync_envs registers disk/pipeline envs with empty tenant_id; they must
    # never surface to a real tenant (nor a tenantless token, which is 403'd).
    _add_env("orphan", "", "")
    assert "orphan" not in [e["id"] for e in client.get("/env-forge/environments", headers=hdr(tenant="tenantZ")).json()]
    assert client.get("/env-forge/environments/orphan", headers=hdr(tenant="tenantZ")).status_code == 404


def test_create_sets_owner_and_isolates(client):
    r = client.post("/env-forge/environments", headers=hdr(sub="uA", tenant="tenantA"),
                    json={"name": "made-by-a", "reference": "", "model": "m", "provider": "p"})
    assert r.status_code == 200
    hB = hdr(sub="uB", tenant="tenantB")
    assert "made-by-a" not in [e["id"] for e in client.get("/env-forge/environments", headers=hB).json()]
    assert client.get("/env-forge/environments/made-by-a", headers=hB).status_code == 404
    assert client.get("/env-forge/environments/made-by-a", headers=hdr(sub="uA", tenant="tenantA")).status_code == 200


@pytest.mark.parametrize("bad", ["../evil", "..", "a/b", "foo/../../bar", "", ".", "  ", "x" * 65, "/etc/passwd"])
def test_create_rejects_traversal_names(client, bad):
    r = client.post("/env-forge/environments", headers=hdr(tenant="tenantA"),
                    json={"name": bad, "reference": "", "model": "m", "provider": "p"})
    assert r.status_code == 400, (bad, r.status_code)


def test_created_env_dir_stays_in_envs_root(client):
    r = client.post("/env-forge/environments", headers=hdr(tenant="tenantA"),
                    json={"name": "safe-slug_9", "reference": "", "model": "m", "provider": "p"})
    assert r.status_code == 200
    with SessionLocal() as db:
        e = db.get(Environment, "safe-slug_9")
        envs_root = os.path.realpath(os.environ["ENVS_ROOT"])
        assert os.path.realpath(e.generated_dir).startswith(envs_root)


def test_upload_references_cannot_escape_env_dir(client):
    envs_root = Path(os.environ["ENVS_ROOT"])
    assert client.post("/env-forge/environments", headers=hdr(tenant="tenantA"),
                       json={"name": "upl", "reference": "", "model": "m", "provider": "p"}).status_code == 200
    blob = base64.b64encode(b"x").decode()
    files = [
        {"filename": "ok.png", "content_b64": blob},
        {"filename": "../../../../escape.txt", "content_b64": blob},     # try to climb out of ENVS_ROOT
        {"filename": "../../sibling/evil.txt", "content_b64": blob},     # try to write into a sibling env
    ]
    r = client.post("/env-forge/environments/upl/references", headers=hdr(tenant="tenantA"),
                    json={"files": files})
    assert r.status_code == 200
    refs = (envs_root / "upl" / "design" / "references").resolve()
    # the benign file landed; NOTHING escaped the references dir
    assert (refs / "ok.png").is_file()
    assert not (envs_root / "escape.txt").exists()
    assert not (envs_root / "sibling").exists()
    for s in r.json()["saved"]:
        assert (refs / s).resolve().parent == refs  # every saved file is a basename inside refs


def test_every_envforge_route_is_admin_gated():
    def calls(dep):
        out = []
        for d in dep.dependencies:
            out.append(getattr(d.call, "__name__", ""))
            out += calls(d)
        return out

    ungated = [getattr(r, "path", "") for r in m.app.routes
               if getattr(r, "path", "").startswith("/env-forge")
               and "current_admin" not in calls(r.dependant)]
    assert not ungated, f"un-gated /env-forge routes: {ungated}"
