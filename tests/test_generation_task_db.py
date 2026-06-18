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
