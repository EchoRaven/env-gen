"""GenerationTask registry: model, status history, backfill migration, server wiring."""
import json

import pytest

from app.db import SessionLocal, init_db
from app import models
from app.models import Environment, GenerationTask


@pytest.fixture(scope="module", autouse=True)
def _schema():
    """Create the registry schema in the conftest temp db (idempotent)."""
    init_db()
    yield


def test_generation_task_persists_and_defaults():
    with SessionLocal() as db:
        t = GenerationTask(task_id="t-1", env_id="e-1", tenant_id="ten", created_by="u",
                           name="youtube", project_path="/x/youtube",
                           state_path="/x/youtube/.checkpoint", status="queued")
        db.add(t)
        db.commit()
        got = db.get(GenerationTask, "t-1")
        assert got is not None
        assert got.status == "queued"
        assert got.delivered is False
        assert got.status_history_json == "[]"
        assert got.coordination_ticks == 0 and got.cost_usd == 0.0
        db.delete(got)
        db.commit()


def test_record_status_appends_history_and_sets_status():
    t = GenerationTask(task_id="t-2", env_id="e-1", status="queued")
    models.record_status(t, "generating", "spawned")
    models.record_status(t, "delivered", "gate passed")
    assert t.status == "delivered"
    hist = json.loads(t.status_history_json)
    assert [h["status"] for h in hist] == ["generating", "delivered"]
    assert hist[0]["reason"] == "spawned" and "at" in hist[0]


def test_environment_has_current_task_and_archived():
    with SessionLocal() as db:
        e = Environment(id="e-cols", name="e-cols", tenant_id="ten", created_by="u",
                        generated_dir="/x/e-cols", status="generating",
                        current_task_id="t-x", archived=False)
        db.add(e)
        db.commit()
        got = db.get(Environment, "e-cols")
        assert got.current_task_id == "t-x"
        assert got.archived is False
        db.delete(got)
        db.commit()


def test_run_table_removed():
    import app.models as mm
    assert not hasattr(mm, "Run")


def test_backfill_creates_one_task_per_env_and_is_idempotent():
    import app.db as dbmod
    with SessionLocal() as db:
        db.add(Environment(id="bf-env", name="bf-env", tenant_id="ten", created_by="u",
                           generated_dir="/envs/bf-env", status="completed",
                           model="gemini", provider="google", delivered=True))
        db.commit()
    dbmod._backfill_generation_tasks()
    dbmod._backfill_generation_tasks()  # second run must not duplicate
    with SessionLocal() as db:
        tasks = [t for t in db.query(GenerationTask).all() if t.env_id == "bf-env"]
        assert len(tasks) == 1
        t = tasks[0]
        assert t.project_path == "/envs/bf-env"
        assert t.state_path == "/envs/bf-env/.checkpoint"
        assert t.status == "delivered" and t.delivered is True
        assert t.model == "gemini" and t.provider == "google"
        e = db.get(Environment, "bf-env")
        assert e.current_task_id == t.task_id
        # cleanup
        db.delete(t); db.delete(e); db.commit()


# --- Task 4: server creates a GenerationTask when an env is created -------------
import os
import time

import jwt
from fastapi.testclient import TestClient
import app.main as m

_SECRET = os.environ["AGENTSUITE_JWT_SECRET"]


def _hdr(sub="u", tenant="t"):
    p = {"sub": sub, "is_admin": True, "tenant_id": tenant, "exp": int(time.time()) + 3600}
    return {"Authorization": "Bearer " + jwt.encode(p, _SECRET, algorithm="HS256")}


@pytest.fixture()
def client():
    with TestClient(m.app) as c:
        yield c


def test_create_env_also_creates_generation_task(client):
    r = client.post("/env-forge/environments",
                    json={"name": "wired-env", "reference": "", "model": "gemini",
                          "provider": "google", "requirements": "build X"},
                    headers=_hdr())
    assert r.status_code in (200, 201), r.text
    with SessionLocal() as db:
        tasks = [t for t in db.query(GenerationTask).all() if t.name == "wired-env"]
        assert len(tasks) == 1
        t = tasks[0]
        assert t.status == "generating"
        assert t.state_path.endswith("/.checkpoint")
        assert t.model == "gemini" and t.provider == "google"
        e = db.get(Environment, "wired-env")
        assert e.current_task_id == t.task_id
