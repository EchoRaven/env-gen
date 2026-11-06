"""Database engine/session wiring. Postgres in docker, any SQLAlchemy URL locally."""
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker


def _database_url() -> str:
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    host = os.getenv("NETFLIX_PG_HOST", "127.0.0.1")
    port = os.getenv("NETFLIX_PG_PORT", "5432")
    dbname = os.getenv("NETFLIX_PG_DB", "netflix")
    user = os.getenv("NETFLIX_PG_USER", "netflix")
    password = os.getenv("NETFLIX_PG_PASSWORD", "netflix")
    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{dbname}"


engine = create_engine(_database_url(), echo=False, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """Sync generator — FastAPI runs sync deps in a threadpool (monkeypatched in-process)."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
