"""Database wiring — SQLAlchemy 2.0, SQLite by default (Postgres-ready via
``DATABASE_URL``). Holds the env/run REGISTRY; the rich per-env collaboration-hub
state is read live from each generated environment (see ``hub_reader``)."""
from __future__ import annotations

import os
from collections.abc import Iterator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./forgingground_gen.db")

_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=_connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


class Base(DeclarativeBase):
    pass


def init_db() -> None:
    from . import models  # noqa: F401 — register mappers
    Base.metadata.create_all(engine)
    _ensure_tenant_columns()
    _ensure_environment_columns()
    _backfill_generation_tasks()


def _ensure_tenant_columns() -> None:
    """Lightweight migration: add the multi-tenancy columns to a pre-existing
    ``environments`` table (``create_all`` never ALTERs existing tables).
    Idempotent and dialect-agnostic (SQLite + Postgres)."""
    insp = inspect(engine)
    if "environments" not in insp.get_table_names():
        return
    have = {c["name"] for c in insp.get_columns("environments")}
    adds = []
    if "tenant_id" not in have:
        adds.append("ADD COLUMN tenant_id VARCHAR DEFAULT ''")
    if "created_by" not in have:
        adds.append("ADD COLUMN created_by VARCHAR DEFAULT ''")
    if not adds:
        return
    with engine.begin() as conn:
        for clause in adds:
            conn.execute(text(f"ALTER TABLE environments {clause}"))


def _ensure_environment_columns() -> None:
    """Idempotent ALTER: add current_task_id + archived to a pre-existing
    ``environments`` table (create_all never ALTERs). SQLite + Postgres."""
    insp = inspect(engine)
    if "environments" not in insp.get_table_names():
        return
    have = {c["name"] for c in insp.get_columns("environments")}
    adds = []
    if "current_task_id" not in have:
        adds.append("ADD COLUMN current_task_id VARCHAR")
    if "archived" not in have:
        adds.append("ADD COLUMN archived BOOLEAN DEFAULT 0")
    if not adds:
        return
    with engine.begin() as conn:
        for clause in adds:
            conn.execute(text(f"ALTER TABLE environments {clause}"))


def _backfill_generation_tasks() -> None:
    """One-shot, idempotent: ensure every Environment has at least one
    GenerationTask (the legacy registry had no per-attempt rows). Maps the env's
    status/config onto the task; points current_task_id at it iff delivered.
    Safe to re-run (skips envs that already have a task)."""
    from . import models  # local import avoids a models<->db import cycle
    with SessionLocal() as db:
        envs = db.query(models.Environment).all()
        have = {row[0] for row in db.query(models.GenerationTask.env_id).all()}
        made = False
        for e in envs:
            if e.id in have:
                continue
            if e.delivered or e.status in ("completed", "delivered"):
                status = "delivered"
            elif e.status == "failed":
                status = "failed"
            else:
                status = e.status or "queued"
            gd = e.generated_dir or ""
            t = models.GenerationTask(
                task_id=f"{e.id}:backfill", env_id=e.id, tenant_id=e.tenant_id,
                created_by=e.created_by, name=e.name, project_path=gd,
                state_path=(gd + "/.checkpoint") if gd else "",
                status=status, reference=e.reference, model=e.model,
                provider=e.provider, scope=e.scope, requirements=e.requirements,
                gates_json=e.gates_json, max_wallclock_min=e.max_wallclock_min,
                max_ticks=e.max_ticks, delivered=bool(e.delivered),
            )
            models.record_status(t, status, "backfill")
            db.add(t)
            if status == "delivered":
                e.current_task_id = t.task_id
            made = True
        if made:
            db.commit()


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
