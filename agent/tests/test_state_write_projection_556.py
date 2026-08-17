"""#556 — HEAL for the missing-write-path class (the #557 oracle's heal side).

The #557 oracle (``completeness_audit.completeness_state_entity_no_write``) DETECTS
a STATE-BEARING entity (a table with a mutable data column — ``progress_seconds`` /
``status`` / ``position`` / ``is_*``) that is READABLE (has a GET) but has NO write
endpoint: the feature is non-functional (Netflix "resume watching" only ever reflects
seed data because playback progress can never be recorded). #556 is the framework HEAL:
``route_projector.project_state_write_endpoints`` auto-projects an idempotent UPSERT
write handler for each such entity, keyed off the table's natural owner+subject FKs,
and returns descriptors the heal registers in RegistryHub so the loop closes.

These tests pin:
  * a state entity (mutable col) with only GET  → an upsert POST handler is projected,
    registered-descriptor shape is correct, and #557 goes clean once the POST exists;
  * a non-state (pure lookup / catalog) entity  → NOTHING projected (byte-identical);
  * an entity that already has a POST           → NOT duplicated (byte-identical);
  * the emitted handler upserts by owner+subject keys, injects the owner from the
    authenticated caller, and persists the mutable state column — proven by EXECUTING
    the generated handler against a real SQLite ORM (insert then update the same key
    → one row, updated progress);
  * detection is the SAME classifier the oracle uses (single source of truth).

Generalizable: derived from the table's mutable column(s) + owner/subject FKs, never
from any product literal.
"""
import ast
import importlib.util
import pathlib

from env_generator.llm_generator.multi_agent.runtime import route_projector as rp
from env_generator.llm_generator.multi_agent.runtime import completeness_audit as ca


# ---------------------------------------------------------------------------
# schema / endpoint / model fixtures (mirror test_completeness_audit_557 shapes)
# ---------------------------------------------------------------------------

def _col(name, type_="integer", **kw):
    return {"name": name, "type": type_, **kw}


def _table(name, columns, status="implemented"):
    return {"id": name, "name": name, "status": status, "schema": {"columns": columns}}


def _ep(method, path, status="implemented", **kw):
    return {"method": method, "path": path, "status": status, **kw}


# A netflix-shaped state entity: PK + owner FK (profile_id) + subject FK (title_id)
# + a mutable scalar (progress_seconds) + a timestamp.
_CW_TABLE = _table("continue_watching", [
    _col("id", "integer", primary_key=True),
    _col("profile_id", "integer", references="profiles.id"),
    _col("title_id", "integer", references="titles.id"),
    _col("progress_seconds", "integer", default=0),
    _col("updated_at", "timestamp"),
])

# A read-only catalog table: PK + descriptive column only (NOT state-bearing).
_GENRES_TABLE = _table("genres", [
    _col("id", "integer", primary_key=True),
    _col("name", "string", unique=True),
])

_MODELS_PY = """
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from database import Base


class ContinueWatching(Base):
    __tablename__ = "continue_watching"
    id = Column(Integer, primary_key=True)
    profile_id = Column(Integer, ForeignKey("profiles.id"))
    title_id = Column(Integer, ForeignKey("titles.id"))
    progress_seconds = Column(Integer, default=0)
    updated_at = Column(DateTime)


class Genre(Base):
    __tablename__ = "genres"
    id = Column(Integer, primary_key=True)
    name = Column(String)
"""

_MAIN_PY = '''
from fastapi import FastAPI

app = FastAPI()


@app.get("/api/continue-watching")
def get_cw():
    return {"items": [], "total": 0}


@app.get("/api/genres")
def get_genres():
    return {"items": [], "total": 0}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app)
'''


def _write_backend(tmp_path, models_py=_MODELS_PY, main_py=_MAIN_PY):
    bd = tmp_path / "app" / "backend"
    bd.mkdir(parents=True)
    (bd / "models.py").write_text(models_py, encoding="utf-8")
    (bd / "main.py").write_text(main_py, encoding="utf-8")
    return bd


# ---------------------------------------------------------------------------
# detection is the single #557 classifier
# ---------------------------------------------------------------------------

def test_detection_reuses_557_oracle_classifier():
    # project_state_write_endpoints must heal EXACTLY what the oracle flags.
    tables = {"continue_watching": _CW_TABLE, "genres": _GENRES_TABLE}
    endpoints = {"g1": _ep("GET", "/api/continue-watching"),
                 "g2": _ep("GET", "/api/genres")}
    flagged = {r.entity for r in ca.check_state_entity_no_write(tables, endpoints)}
    healed = set(ca.state_entities_missing_write(tables, endpoints).keys())
    assert flagged == healed == {"continue_watching"}


# ---------------------------------------------------------------------------
# state entity with only GET → upsert POST projected + registered
# ---------------------------------------------------------------------------

def test_state_entity_only_get_projects_upsert_write(tmp_path):
    bd = _write_backend(tmp_path)
    tables = {"continue_watching": _CW_TABLE, "genres": _GENRES_TABLE}
    endpoints = {"g1": _ep("GET", "/api/continue-watching"),
                 "g2": _ep("GET", "/api/genres")}

    res = rp.project_state_write_endpoints(bd, endpoints, tables)

    # exactly one write projected — for the state entity, on its collection
    assert res["projected"] == ["POST /api/continue-watching"]
    eps = res["endpoints"]
    assert len(eps) == 1
    d = eps[0]
    assert d["method"] == "POST"
    assert d["path"] == "/api/continue-watching"
    assert d["table"] == "continue_watching"
    assert d["cls"] == "ContinueWatching"
    # UPSERT keys = owner FK (profile_id) + subject FK (title_id)
    assert d["owner_fk"] == "profile_id"
    assert d["subject_fks"] == ["title_id"]
    assert d["natural_keys"] == ["profile_id", "title_id"]
    # persists the mutable state column
    assert d["state_columns"] == ["progress_seconds"]
    # a write is a mutation → owner-scoped (auth required)
    assert d["auth_required"] is True
    assert d["response_key"] == "item"

    # the route is actually on the served surface + main.py still valid python
    new_main = (bd / "main.py").read_text(encoding="utf-8")
    ast.parse(new_main)
    routes = rp._existing_routes(new_main)
    assert ("POST", "/api/continue-watching") in routes
    assert ("GET", "/api/continue-watching") in routes  # untouched


def test_emitted_handler_shape_upsert_owner_scoped(tmp_path):
    bd = _write_backend(tmp_path)
    tables = {"continue_watching": _CW_TABLE}
    endpoints = {"g1": _ep("GET", "/api/continue-watching")}
    rp.project_state_write_endpoints(bd, endpoints, tables)
    new_main = (bd / "main.py").read_text(encoding="utf-8")

    # the projected handler carries the by-construction upsert shape
    assert "@app.post(\"/api/continue-watching\")" in new_main
    # owner injected from the authenticated caller (never trust a client owner id)
    assert 'valid["profile_id"] = _fw_owner_val(ContinueWatching, "profile_id", user)' in new_main
    # natural-key lookup then insert-or-update
    assert "for _nk in ['profile_id', 'title_id']:" in new_main
    assert "obj = _q.first() if _have_key else None" in new_main
    assert "obj = ContinueWatching(**valid)" in new_main   # insert branch
    assert "setattr(obj, _k, _v)" in new_main               # update branch
    # body coercion reused from the create pattern
    assert "valid = _coerce_body(ContinueWatching, valid)" in new_main


# ---------------------------------------------------------------------------
# byte-identical when there is nothing to heal
# ---------------------------------------------------------------------------

def test_non_state_entity_projects_nothing_byte_identical(tmp_path):
    # genres is a read-only catalog table (only PK + descriptive 'name') → not state.
    main_only_genres = '''
from fastapi import FastAPI

app = FastAPI()


@app.get("/api/genres")
def get_genres():
    return {"items": [], "total": 0}
'''
    bd = _write_backend(tmp_path, main_py=main_only_genres)
    before = (bd / "main.py").read_text(encoding="utf-8")
    tables = {"genres": _GENRES_TABLE}
    endpoints = {"g2": _ep("GET", "/api/genres")}

    res = rp.project_state_write_endpoints(bd, endpoints, tables)
    assert res["projected"] == []
    assert res["endpoints"] == []
    after = (bd / "main.py").read_text(encoding="utf-8")
    assert after == before  # byte-identical: no write projected


def test_state_entity_with_existing_post_not_duplicated(tmp_path):
    # the app already declares a POST for the state entity → nothing to heal.
    main_with_post = '''
from fastapi import FastAPI

app = FastAPI()


@app.get("/api/continue-watching")
def get_cw():
    return {"items": [], "total": 0}


@app.post("/api/continue-watching")
def post_cw(body: dict = None):
    return {"item": {}}
'''
    bd = _write_backend(tmp_path, main_py=main_with_post)
    before = (bd / "main.py").read_text(encoding="utf-8")
    tables = {"continue_watching": _CW_TABLE}
    endpoints = {"g1": _ep("GET", "/api/continue-watching"),
                 "p1": _ep("POST", "/api/continue-watching")}

    res = rp.project_state_write_endpoints(bd, endpoints, tables)
    assert res["projected"] == []
    assert res["endpoints"] == []
    assert (bd / "main.py").read_text(encoding="utf-8") == before  # not duplicated


def test_state_entity_with_put_on_nested_path_not_duplicated(tmp_path):
    # a PUT reaching the entity (even via a by-id path) counts as a write → no heal.
    bd = _write_backend(tmp_path)
    before = (bd / "main.py").read_text(encoding="utf-8")
    tables = {"continue_watching": _CW_TABLE}
    endpoints = {"g1": _ep("GET", "/api/continue-watching"),
                 "u1": _ep("PUT", "/api/continue-watching/{id}")}
    res = rp.project_state_write_endpoints(bd, endpoints, tables)
    assert res["projected"] == []
    assert (bd / "main.py").read_text(encoding="utf-8") == before


# ---------------------------------------------------------------------------
# EXECUTE the emitted handler: prove the upsert semantics on a real ORM
# ---------------------------------------------------------------------------

def _exec_upsert_handler(handler_src, cls, session_factory, user):
    """Exec the projected handler source in a namespace wired to a real ORM +
    session, returning the callable handler function."""
    class _HTTPException(Exception):
        def __init__(self, status_code=500, detail=""):
            self.status_code = status_code
            self.detail = detail

    from sqlalchemy.exc import IntegrityError, DataError

    ns = {
        # a fake FastAPI app whose .post just returns the identity decorator
        "app": type("App", (), {"post": staticmethod(lambda *a, **k: (lambda fn: fn)),
                                 "get": staticmethod(lambda *a, **k: (lambda fn: fn)),
                                 "put": staticmethod(lambda *a, **k: (lambda fn: fn))})(),
        "Depends": lambda x=None: None,
        "get_db": lambda: None,
        "get_current_user": lambda: None,
        "HTTPException": _HTTPException,
        "IntegrityError": IntegrityError,
        "DataError": DataError,
        "_coerce_body": lambda _cls, valid: valid,
        "_fw_owner_val": lambda _cls, col, u: u["id"],
        cls.__name__: cls,
    }
    exec(handler_src, ns)
    fn_name = [k for k in ns if k.startswith("_projected_upsert_")][0]
    return ns[fn_name]


def test_emitted_handler_upserts_and_persists_state_column(tmp_path):
    from sqlalchemy import Column, Integer, DateTime, create_engine
    from sqlalchemy.orm import declarative_base, sessionmaker

    Base = declarative_base()

    class ContinueWatching(Base):
        __tablename__ = "continue_watching"
        id = Column(Integer, primary_key=True, autoincrement=True)
        profile_id = Column(Integer)
        title_id = Column(Integer)
        progress_seconds = Column(Integer, default=0)
        updated_at = Column(DateTime)

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    # emit the handler for this state entity
    meta = {"cls": "ContinueWatching",
            "cols": ["id", "profile_id", "title_id", "progress_seconds", "updated_at"],
            "fks": {"profile_id": "profiles", "title_id": "titles"},
            "types": {"id": "Integer", "profile_id": "Integer", "title_id": "Integer",
                      "progress_seconds": "Integer", "updated_at": "DateTime"}}
    handler_src = rp._generate_upsert_handler(
        "POST", "/api/continue-watching", "ContinueWatching",
        meta["cols"], "profile_id", ["profile_id", "title_id"], True, 0)

    user = {"id": 7}
    handler = _exec_upsert_handler(handler_src, ContinueWatching, Session, user)

    # 1) first write for (profile 7, title 42) INSERTS the row w/ progress 120
    out1 = handler(body={"title_id": 42, "progress_seconds": 120}, db=db, user=user)
    assert out1["item"]["profile_id"] == 7        # owner injected from the caller
    assert out1["item"]["title_id"] == 42
    assert out1["item"]["progress_seconds"] == 120
    assert db.query(ContinueWatching).count() == 1

    # 2) a SECOND write for the SAME natural key UPDATES (idempotent — no dup row)
    out2 = handler(body={"title_id": 42, "progress_seconds": 300}, db=db, user=user)
    assert db.query(ContinueWatching).count() == 1                # still one row
    assert out2["item"]["progress_seconds"] == 300               # progress persisted
    row = db.query(ContinueWatching).one()
    assert row.progress_seconds == 300

    # 3) a DIFFERENT subject (title 99) INSERTS a distinct row (scoped by natural key)
    handler(body={"title_id": 99, "progress_seconds": 5}, db=db, user=user)
    assert db.query(ContinueWatching).count() == 2

    # 4) a DIFFERENT owner is derived from the caller, never the body — a client that
    #    tries to spoof profile_id is overridden with its own id.
    other = {"id": 8}
    handler2 = _exec_upsert_handler(handler_src, ContinueWatching, Session, other)
    handler2(body={"profile_id": 7, "title_id": 42, "progress_seconds": 1},
             db=db, user=other)
    # profile 8 gets its OWN row for title 42 (did not overwrite profile 7's)
    assert db.query(ContinueWatching).filter_by(profile_id=8, title_id=42).count() == 1
    assert db.query(ContinueWatching).filter_by(profile_id=7, title_id=42).one().progress_seconds == 300


# ---------------------------------------------------------------------------
# the heal closes the #557 oracle for the entity
# ---------------------------------------------------------------------------

def test_heal_closes_557_oracle(tmp_path):
    bd = _write_backend(tmp_path)
    tables = {"continue_watching": _CW_TABLE, "genres": _GENRES_TABLE}
    endpoints = {"g1": _ep("GET", "/api/continue-watching"),
                 "g2": _ep("GET", "/api/genres")}

    # BEFORE: oracle flags continue_watching (read but no write)
    before = ca.check_state_entity_no_write(tables, endpoints)
    assert [r.entity for r in before] == ["continue_watching"]

    # HEAL: project the write path + simulate the hub registration the heal performs
    res = rp.project_state_write_endpoints(bd, endpoints, tables)
    for i, d in enumerate(res["endpoints"]):
        endpoints[f"proj{i}"] = _ep(d["method"], d["path"])

    # AFTER: the oracle is clean for the entity
    after = ca.check_state_entity_no_write(tables, endpoints)
    assert after == []


def test_project_returns_cleanly_when_main_absent(tmp_path):
    # best-effort: a missing main.py never raises, projects nothing.
    res = rp.project_state_write_endpoints(tmp_path / "nope", {}, {})
    assert res["projected"] == []
    assert res["endpoints"] == []


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
