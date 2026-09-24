"""FIX #86 — lane-defined RAW-psycopg get_db shadows the framework Session → every
SQLAlchemy-style handler 500s (instagram run-7 M3 STUCK, 2026-07-06 05:09, live traceback).

custom_routes.py defined its OWN get_db() = psycopg.connect(...) while writing its business
handlers in SQLAlchemy style (db.execute(text(...)).mappings()) → psycopg's _convert_query
raised `TypeError: object of type 'TextClause' has no len()` → unfollow/explore 500 →
business_endpoints_reachable + business_chain wedged 7 post-cap cycles → M3 never delivered
(M1/M2 had). The file was INTERNALLY mixed: 8 text()-style calls + 3 plain-str psycopg-style
calls, so no single handle type fixes it without both pieces:
 (a) the framework _Session.execute now ALSO accepts plain-str SQL (coerced to text(),
     %s-positional params converted to named binds, dict-like rows) — same philosophy as
     its existing .cursor() shim;
 (b) heal repair rewrites a lane get_db that psycopg.connect's into a delegation to the
     framework's database.get_db.
ENV-AGNOSTIC + LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _mk_session():
    """Instantiate the GENERATED database.py's _Session against in-memory sqlite."""
    from multi_agent.runtime.backend_skeleton import _DATABASE_PY
    src = _DATABASE_PY.replace(
        'os.getenv("DATABASE_URL", "postgresql+psycopg://sandbox:sandbox@database:5432/app")',
        '"sqlite://"')
    ns: dict = {"__name__": "generated_database"}
    exec(compile(src, "database.py", "exec"), ns)
    db = ns["SessionLocal"]()
    from sqlalchemy import text
    db.execute(text("CREATE TABLE tenants (id INTEGER PRIMARY KEY, name TEXT)"))
    db.execute(text("INSERT INTO tenants (id, name) VALUES (1, 'acme'), (2, 'globex')"))
    return db


def test_session_execute_accepts_plain_string_sql():
    db = _mk_session()
    rows = db.execute("SELECT * FROM tenants").fetchall()
    assert len(rows) == 2
    assert rows[0]["name"] == "acme"          # dict-style row access (psycopg dict_row habit)


def test_session_execute_converts_percent_s_positional_params():
    db = _mk_session()
    db.execute("DELETE FROM tenants WHERE id = %s", (1,))
    db.commit()
    rows = db.execute("SELECT * FROM tenants").fetchall()
    assert [r["id"] for r in rows] == [2]


def test_session_execute_textclause_native_path_untouched():
    from sqlalchemy import text
    db = _mk_session()
    rows = db.execute(text("SELECT * FROM tenants WHERE id = :i"), {"i": 2}).mappings().all()
    assert rows[0]["name"] == "globex"        # lane's text().mappings() chain works as before


def test_repair_rewrites_lane_psycopg_get_db(tmp_path):
    from multi_agent.runtime.backend_scaffold import repair_custom_routes_db_handle
    be = tmp_path / "backend"
    be.mkdir()
    src = '''import psycopg
from psycopg.rows import dict_row
from fastapi import APIRouter, Depends
router = APIRouter()

def get_db():
    conn = psycopg.connect("postgresql://x", row_factory=dict_row)
    try:
        yield conn
    finally:
        conn.close()

@router.get("/api/things")
def things(db = Depends(get_db)):
    return db.execute("SELECT 1").fetchall()
'''
    (be / "custom_routes.py").write_text(src, encoding="utf-8")
    out = repair_custom_routes_db_handle(be)
    assert out.get("repaired") is True
    new = (be / "custom_routes.py").read_text(encoding="utf-8")
    assert "psycopg.connect" not in new.split("def get_db")[1].split("@router")[0]
    assert "_framework_get_db" in new
    import ast
    ast.parse(new)                            # still valid python
    # idempotent
    assert repair_custom_routes_db_handle(be).get("repaired") is False


def test_repair_leaves_framework_importing_get_db_alone(tmp_path):
    from multi_agent.runtime.backend_scaffold import repair_custom_routes_db_handle
    be = tmp_path / "backend"
    be.mkdir()
    (be / "custom_routes.py").write_text(
        "from database import get_db\nfrom fastapi import APIRouter\nrouter = APIRouter()\n",
        encoding="utf-8")
    assert repair_custom_routes_db_handle(be).get("repaired") is False


def test_wired_into_heal_pipeline():
    import inspect
    from multi_agent.runtime import heal_pipeline
    assert "repair_custom_routes_db_handle" in inspect.getsource(heal_pipeline)


def test_repair_rewrites_str_param_on_int_pk_route(tmp_path):
    """FIX #106 (run-23 live): the lane annotated the by-id path param as `str` while the
    column is an INTEGER PK → SQLAlchemy emitted `WHERE posts.id = '20'::VARCHAR` →
    Postgres 'operator does not exist: integer = character varying' → 500 on every by-id
    read; and by design the lane's by-id GET SHADOWS the safe projected read (the
    isolation tradeoff), so the whole run wedged. Repair: parse models.py for integer-PK
    tables and rewrite the matching `param: str` annotations to `int`."""
    from multi_agent.runtime.backend_scaffold import repair_custom_routes_param_types
    be = tmp_path / "backend"
    be.mkdir()
    (be / "models.py").write_text(
        "from sqlalchemy import Column, Integer, String\n"
        "from database import Base\n"
        "class Post(Base):\n"
        "    __tablename__ = 'posts'\n"
        "    id = Column(Integer, primary_key=True)\n"
        "class Doc(Base):\n"
        "    __tablename__ = 'docs'\n"
        "    id = Column(String, primary_key=True)\n", encoding="utf-8")
    (be / "custom_routes.py").write_text(
        "from fastapi import APIRouter, Depends\n"
        "router = APIRouter()\n"
        "@router.get('/api/posts/{id}')\n"
        "def get_post(id: str, db=None):\n"
        "    return {'id': id}\n"
        "@router.get('/api/docs/{id}')\n"
        "def get_doc(id: str, db=None):\n"
        "    return {'id': id}\n"
        "@router.post('/api/posts/{id}/like')\n"
        "def like(id: str, db=None):\n"
        "    return {'id': id}\n", encoding="utf-8")
    out = repair_custom_routes_param_types(be)
    assert out.get("fixed") == 2                      # get_post + like (both posts, int PK)
    src = (be / "custom_routes.py").read_text(encoding="utf-8")
    assert "def get_post(id: int" in src              # int-PK read fixed
    assert "def get_doc(id: str" in src               # string-PK table untouched
    assert "def like(id: int" in src                  # action path on int-PK table fixed too
    import ast
    ast.parse(src)
    # idempotent
    assert repair_custom_routes_param_types(be).get("fixed") == 0
