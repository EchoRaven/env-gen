"""Fix #60 — the backend container exports DB connection facts under every
common env convention (outlook run-45, live 2026-07-02).

A frontend/backend lane routinely hand-rolls its OWN db client in
custom_routes.py (run-45: an asyncpg pool) reading whatever env-var convention
it guesses — DB_HOST/DB_PORT/DB_USER/..., PGHOST/PGPORT/..., or
POSTGRES_HOST/... . The compose only exported DATABASE_URL (the SQLAlchemy URL
the framework's own database.py consumes), so the lane's guess fell through to
its localhost/postgres defaults and EVERY custom-route read 500'd
(OSError: Connect call failed ('127.0.0.1', 5433)). business_endpoints_reachable
+ business_chain then wedged on a functionally-correct app. The compose now
exports the SAME connection facts (host=database, port=db_port, user/pass=
sandbox, db=app) under all three conventions, so any reasonable lane guess
resolves BY CONSTRUCTION. LOCAL-ONLY (agent/tests/ gitignored).
"""

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCAFFOLDER = (ROOT / "env_generator" / "llm_generator" / "multi_agent"
              / "runtime" / "scaffolder.py")


def _rendered_backend_env(db_port=5433, backend_port=8000, api_port=3001,
                          ui_port=8080):
    src = SCAFFOLDER.read_text(encoding="utf-8")
    m = re.search(r"docker_compose = f'''(.*?)'''", src, re.DOTALL)
    assert m, "compose template not found"
    out = m.group(1).format(db_port=db_port, backend_port=backend_port,
                            api_port=api_port, ui_port=ui_port)
    doc = yaml.safe_load(out)
    return doc, doc["services"]["backend"]["environment"]


def test_all_three_conventions_point_at_the_container_db():
    _doc, env = _rendered_backend_env(db_port=5433)
    triples = [
        ("DB_HOST", "DB_PORT", "DB_USER", "DB_PASSWORD", "DB_NAME"),
        ("PGHOST", "PGPORT", "PGUSER", "PGPASSWORD", "PGDATABASE"),
        ("POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_USER",
         "POSTGRES_PASSWORD", "POSTGRES_DB"),
    ]
    for host, port, user, pw, name in triples:
        assert env.get(host) == "database", host
        assert str(env.get(port)) == "5433", port
        assert env.get(user) == "sandbox", user
        assert env.get(pw) == "sandbox", pw
        assert env.get(name) == "app", name


def test_convention_facts_agree_with_database_url():
    """Every convention must describe the SAME db as the canonical DATABASE_URL
    (host, port, creds) — a divergent guess would connect to the wrong place."""
    _doc, env = _rendered_backend_env(db_port=5433)
    url = env["DATABASE_URL"]
    assert "sandbox:sandbox@database:5433/app" in url
    for host in ("DB_HOST", "PGHOST", "POSTGRES_HOST"):
        assert env[host] == "database"
    for port in ("DB_PORT", "PGPORT", "POSTGRES_PORT"):
        assert str(env[port]) == "5433"


def test_port_tracks_db_port_placeholder():
    """The exported port must follow the run's actual db_port, not a constant."""
    _doc, env = _rendered_backend_env(db_port=5599)
    for port in ("DB_PORT", "PGPORT", "POSTGRES_PORT"):
        assert str(env[port]) == "5599", port
    # and the DB actually listens there (PGPORT on the database service)
    doc, _ = _rendered_backend_env(db_port=5599)
    assert str(doc["services"]["database"]["environment"]["PGPORT"]) == "5599"


def test_compose_still_valid_yaml_and_backend_depends_on_db():
    doc, _ = _rendered_backend_env()
    assert doc["services"]["backend"]["depends_on"]["database"]["condition"] \
        == "service_healthy"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
