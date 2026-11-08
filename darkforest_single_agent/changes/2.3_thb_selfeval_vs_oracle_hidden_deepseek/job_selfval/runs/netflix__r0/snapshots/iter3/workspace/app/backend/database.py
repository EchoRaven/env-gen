import os
import time

from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker


def _database_url() -> str:
    explicit = os.getenv("DATABASE_URL")
    if explicit:
        return explicit
    host = os.getenv("POSTGRES_HOST", "database")
    port = os.getenv("POSTGRES_PORT", "5432")
    db = os.getenv("POSTGRES_DB", "netflix")
    user = os.getenv("POSTGRES_USER", "netflix")
    password = os.getenv("POSTGRES_PASSWORD", "netflix")
    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{db}"


engine = create_engine(_database_url(), pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)
Base = declarative_base()


def wait_for_database(attempts: int = 45, delay: float = 1.0) -> None:
    last_error = None
    for _ in range(attempts):
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return
        except Exception as exc:  # pragma: no cover - startup retry
            last_error = exc
            time.sleep(delay)
    raise RuntimeError(f"database did not become ready: {last_error}")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
