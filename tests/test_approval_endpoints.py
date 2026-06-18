"""Guard: Env Forge approval endpoints (mode toggle + list + decide).

Pins the human side of the approval gate: an admin flips the env to 'ask', sees a
pending request the engine wrote to the hub, and approves/rejects it. Auth/DB env
is set centrally in conftest.py. Must never touch the live youtube env.
"""
import os
import sys
import time
from pathlib import Path

import jwt
import pytest
from fastapi.testclient import TestClient

import app.auth as auth
import app.main as m
from app.db import SessionLocal
from app.models import Environment

_ENGINE_ROOT = str(Path(__file__).resolve().parents[1] / "agent")
if _ENGINE_ROOT not in sys.path:
    sys.path.insert(0, _ENGINE_ROOT)
from env_generator.llm_generator.multi_agent.runtime import approval as A  # noqa: E402

SECRET = auth.JWT_SECRET or os.environ["AGENTSUITE_JWT_SECRET"]
TENANT, USER = "tenantA", "alice"


def _hdr():
    tok = jwt.encode({"sub": USER, "tenant_id": TENANT, "is_admin": True,
                      "exp": int(time.time()) + 3600}, SECRET, algorithm="HS256")
    return {"Authorization": "Bearer " + tok}


@pytest.fixture()
def client():
    with TestClient(m.app) as c:
        yield c


@pytest.fixture()
def env_dir(tmp_path):
    gen = tmp_path / "appr-env"
    (gen / "shared" / "hubs").mkdir(parents=True)
    return gen


def _register(eid, gen):
    with SessionLocal() as db:
        db.add(Environment(id=eid, name=eid, tenant_id=TENANT, created_by=USER,
                           generated_dir=str(gen), status="generating"))
        db.commit()


def test_mode_defaults_auto_then_toggles_ask(client, env_dir):
    _register("appr1", env_dir)
    assert client.get("/env-forge/environments/appr1/approval-mode", headers=_hdr()).json()["mode"] == "auto"
    r = client.put("/env-forge/environments/appr1/approval-mode", headers=_hdr(), json={"mode": "ask"})
    assert r.status_code == 200 and r.json()["mode"] == "ask"
    assert client.get("/env-forge/environments/appr1/approval-mode", headers=_hdr()).json()["mode"] == "ask"


def test_list_and_approve_request(client, env_dir):
    _register("appr2", env_dir)
    store = env_dir / "shared" / "hubs"
    A.write_config(store, mode="ask")
    # Engine writes a pending request (simulated).
    A._write_request(store, {"id": "appr_test1", "action_type": "task", "tool": "workhub_task",
                             "agent": "orchestrator", "summary": "Create task: Build feed",
                             "args": {}, "status": "pending", "created_at": time.time()})
    listed = client.get("/env-forge/environments/appr2/approvals?status=pending", headers=_hdr()).json()
    assert any(x["id"] == "appr_test1" for x in listed)
    # Approve it.
    r = client.post("/env-forge/environments/appr2/approvals/appr_test1/decision",
                    headers=_hdr(), json={"approve": True})
    assert r.status_code == 200 and r.json()["status"] == "approved"
    assert client.get("/env-forge/environments/appr2/approvals?status=pending", headers=_hdr()).json() == []


def test_reject_carries_feedback(client, env_dir):
    _register("appr3", env_dir)
    store = env_dir / "shared" / "hubs"
    A.write_config(store, mode="ask")
    A._write_request(store, {"id": "appr_test2", "action_type": "gate", "tool": "x", "agent": "verifier",
                             "summary": "Create gate", "args": {}, "status": "pending", "created_at": time.time()})
    r = client.post("/env-forge/environments/appr3/approvals/appr_test2/decision",
                    headers=_hdr(), json={"approve": False, "feedback": "too strict"})
    assert r.status_code == 200
    assert r.json()["status"] == "rejected" and r.json()["feedback"] == "too strict"


def test_decide_unknown_request_is_400(client, env_dir):
    _register("appr4", env_dir)
    r = client.post("/env-forge/environments/appr4/approvals/nope/decision",
                    headers=_hdr(), json={"approve": True})
    assert r.status_code == 400


def test_endpoints_require_admin(client, env_dir):
    _register("appr5", env_dir)
    # no token → 401
    assert client.get("/env-forge/environments/appr5/approval-mode").status_code == 401
    assert client.get("/env-forge/environments/appr5/approvals").status_code == 401
