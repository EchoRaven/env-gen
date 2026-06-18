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


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
