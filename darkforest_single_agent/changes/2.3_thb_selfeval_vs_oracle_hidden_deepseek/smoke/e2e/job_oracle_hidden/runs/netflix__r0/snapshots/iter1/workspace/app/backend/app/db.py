"""PostgreSQL access helpers and idempotent schema/seed bootstrap."""
from __future__ import annotations

import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://netflix:netflix@database:5432/netflix"
)
BASE_DIR = Path(__file__).resolve().parent.parent


def connect():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


@contextmanager
def db_cursor(commit: bool = False) -> Iterator[RealDictCursor]:
    conn = connect()
    try:
        with conn.cursor() as cur:
            yield cur
        if commit:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_database() -> None:
    """Wait for Postgres, ensure the schema exists, and seed a blank catalog."""
    schema = (BASE_DIR / "db" / "schema.sql").read_text(encoding="utf-8")
    seed = (BASE_DIR / "db" / "seed.sql").read_text(encoding="utf-8")
    last_error: Exception | None = None
    for _ in range(60):
        try:
            with db_cursor(commit=True) as cur:
                cur.execute(schema)
                cur.execute("SELECT COUNT(*) AS count FROM titles")
                if cur.fetchone()["count"] == 0:
                    cur.execute(seed)
            return
        except Exception as exc:  # the database may still be running init scripts
            last_error = exc
            time.sleep(2)
    raise RuntimeError(f"Database initialization failed: {last_error}")
