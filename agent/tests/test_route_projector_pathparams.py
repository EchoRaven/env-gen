"""Guard tests for route-projector PATH-PARAM correctness (2026-06-16).

Two domain-agnostic framework bugs that blocked endpoint reachability for ANY app:

BUG #11 — Express-style ``:id`` path params were emitted VERBATIM as FastAPI route
decorators (``@app.get("/api/videos/:id")``). In FastAPI ``:id`` is a LITERAL segment,
so a real id 404/405s and ``business_endpoints_implemented`` fails. Fix: normalise
``:param`` → ``{param}`` wherever the projector turns a declared path into a route.

BUG (type coercion → 500) — a path param typed ``str`` and compared to an INTEGER PK/FK
column makes postgres raise ``invalid input syntax for integer`` → HTTP 500 on every
call. Fix: type the path param to the looked-up column (int PK/FK → ``int`` so FastAPI
coerces ``"123"→123`` and 422s non-numeric input — never a 500).
"""

import ast
import re
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.route_projector import (  # noqa: E402
    _express_to_fastapi,
    _param_column_type,
    _orm_models,
    project_missing_routes,
)

# A schema with an INTEGER PK (videos.id) plus an int FK (videos.channel_id → channels)
# and a STRING natural key (channels.slug) — enough to prove int vs str typing.
_MODELS = '''
from sqlalchemy import Column, Integer, BigInteger, String, Text, DateTime, ForeignKey
from database import Base

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True)
    created_at = Column(DateTime)

class Channel(Base):
    __tablename__ = "channels"
    id = Column(Integer, primary_key=True)
    slug = Column(String, unique=True)
    name = Column(String)
    owner_id = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime)

class Video(Base):
    __tablename__ = "videos"
    id = Column(Integer, primary_key=True)
    channel_id = Column(Integer, ForeignKey("channels.id"))
    title = Column(String)
    created_at = Column(DateTime)
'''

_MAIN = '''
from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models import User, Channel, Video

app = FastAPI()

def get_current_user():
    ...

@app.get("/api/health")
def health():
    return {"ok": True}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app)
'''


def _backend(tmp_path):
    (tmp_path / "models.py").write_text(_MODELS, encoding="utf-8")
    (tmp_path / "main.py").write_text(_MAIN, encoding="utf-8")
    return tmp_path


def _projected_defs(src):
    """Return ``{fn_name: (decorator_path, signature_line)}`` for every projected handler."""
    out = {}
    lines = src.splitlines()
    for i, ln in enumerate(lines):
        m = re.match(r'^def (_projected_\w+)\((.*)\):', ln)
        if not m:
            continue
        fn, sig = m.group(1), m.group(2)
        # the decorator is the nearest @app.<m>("...") above this def
        dec_path = None
        for j in range(i - 1, max(-1, i - 4), -1):
            dm = re.match(r'^@app\.\w+\("([^"]+)"', lines[j])
            if dm:
                dec_path = dm.group(1)
                break
        out[fn] = (dec_path, sig)
    return out


# ---------------------------------------------------------------------------
# BUG #11 — Express ``:id`` → FastAPI ``{id}``
# ---------------------------------------------------------------------------
def test_express_to_fastapi_helper_is_idempotent_and_total():
    assert _express_to_fastapi("/api/videos/:id") == "/api/videos/{id}"
    assert _express_to_fastapi("/api/channels/:id/messages") == "/api/channels/{id}/messages"
    assert _express_to_fastapi("/api/x/:channelId/y/:videoId") == "/api/x/{channelId}/y/{videoId}"
    # already-FastAPI paths are untouched (idempotent)
    assert _express_to_fastapi("/api/videos/{id}") == "/api/videos/{id}"
    assert _express_to_fastapi("/api/videos") == "/api/videos"


def test_express_param_projects_to_brace_route_no_literal_colon(tmp_path):
    be = _backend(tmp_path)
    res = project_missing_routes(be, [{"method": "GET", "path": "/api/videos/:id"}])
    assert "GET /api/videos/{id}" in res["projected"]  # normalised in the report too
    src = (be / "main.py").read_text(encoding="utf-8")
    ast.parse(src)
    # the emitted decorator must be a real path param, with NO literal ``:`` segment
    assert '@app.get("/api/videos/{id}")' in src
    assert "/api/videos/:id" not in src
    assert not re.search(r'@app\.\w+\("[^"]*/:', src), "a literal Express ``:`` segment leaked into a decorator"


def test_express_param_dedupes_against_existing_brace_route(tmp_path):
    """A declared ``:id`` that duplicates a route the lane already wrote as ``{x}`` must
    NOT emit a second decorator for the same method+path (FastAPI would shadow it)."""
    be = _backend(tmp_path)
    main = (be / "main.py").read_text(encoding="utf-8").replace(
        '@app.get("/api/health")\ndef health():\n    return {"ok": True}',
        '@app.get("/api/videos/{video_id}")\ndef get_video(video_id: int, db=Depends(get_db)):\n    return {"item": {}}',
    )
    (be / "main.py").write_text(main, encoding="utf-8")
    res = project_missing_routes(be, [{"method": "GET", "path": "/api/videos/:id"}])
    assert res["projected"] == [], "a :id dup of an existing {x} route must not be re-projected"
    src = (be / "main.py").read_text(encoding="utf-8")
    # exactly one GET handler for the videos/{*} path remains
    get_video_routes = re.findall(r'@app\.get\("/api/videos/\{[^}]+\}"\)', src)
    assert len(get_video_routes) == 1, get_video_routes


def test_express_dup_within_batch_emits_one_handler(tmp_path):
    """Two declared endpoints that collapse to the same method+path after normalisation
    (a ``:id`` and a ``{x}``) yield a single projected handler, not two shadowing decs."""
    be = _backend(tmp_path)
    res = project_missing_routes(be, [
        {"method": "GET", "path": "/api/videos/:id"},
        {"method": "GET", "path": "/api/videos/{video_id}"},  # same logical route
    ])
    assert len(res["projected"]) == 1, res["projected"]
    src = (be / "main.py").read_text(encoding="utf-8")
    ast.parse(src)
    get_video_routes = re.findall(r'@app\.get\("/api/videos/\{[^}]+\}"\)', src)
    assert len(get_video_routes) == 1, get_video_routes


# ---------------------------------------------------------------------------
# Type coercion — path param typed to the column it is compared against
# ---------------------------------------------------------------------------
def test_int_pk_path_param_is_typed_int(tmp_path):
    be = _backend(tmp_path)
    project_missing_routes(be, [{"method": "GET", "path": "/api/videos/:id"}])
    src = (be / "main.py").read_text(encoding="utf-8")
    defs = _projected_defs(src)
    sig = next(s for (p, s) in defs.values() if p == "/api/videos/{id}")
    assert re.search(r"\bid:\s*int\b", sig), f"int PK path param not typed int: {sig!r}"
    assert not re.search(r"\bid:\s*str\b", sig), f"int PK path param wrongly typed str: {sig!r}"


def test_nested_int_fk_parent_param_is_typed_int(tmp_path):
    """``/api/channels/{channelId}/videos`` — channelId is compared to Channel.id (an
    INTEGER PK), so it must be typed ``int`` (the exact 500 from the run: a str param
    vs an integer column → postgres 'invalid input syntax for integer')."""
    be = _backend(tmp_path)
    project_missing_routes(be, [{"method": "GET", "path": "/api/channels/:channelId/videos"}])
    src = (be / "main.py").read_text(encoding="utf-8")
    ast.parse(src)
    defs = _projected_defs(src)
    sig = next(s for (p, s) in defs.values() if p == "/api/channels/{channelId}/videos")
    assert re.search(r"\bchannelId:\s*int\b", sig), f"int-FK parent param not typed int: {sig!r}"


def test_string_keyed_lookup_stays_str(tmp_path):
    """A param resolving to a STRING column (channels.slug) must stay ``str`` — typing
    it int would 422 a legitimate textual key."""
    be = _backend(tmp_path)
    # {slug} matches the channels.slug String column → str
    assert _param_column_type("slug", "/api/channels/{slug}", _orm_models(be)) == "str"
    # {username} over users.username (String) → str
    assert _param_column_type("username", "/api/users/{username}", _orm_models(be)) == "str"


def test_int_typing_is_schema_derived_not_name_based(tmp_path):
    """Generality: typing must come from the COLUMN, not the param name. A param named
    ``slug`` resolving to an int PK would be typed int; a param resolving to a string
    column stays str even if other heuristics might guess otherwise."""
    models = _orm_models(_backend(tmp_path))
    # videos.id is Integer → {id} terminal over videos → int
    assert _param_column_type("id", "/api/videos/{id}", models) == "int"
    # channels.id Integer reached via the FK-style {channelId} parent → int
    assert _param_column_type("channelId", "/api/channels/{channelId}/videos", models) == "int"


def test_types_captured_from_models_ast(tmp_path):
    models = _orm_models(_backend(tmp_path))
    assert models["videos"]["types"]["id"] == "Integer"
    assert models["videos"]["types"]["channel_id"] == "Integer"
    assert models["channels"]["types"]["slug"] == "String"


def test_raw_sql_app_falls_back_to_name_heuristic(tmp_path):
    """No models.py → no schema. The projector still types ``:id`` int by NAME (safe
    fallback) and never crashes."""
    (tmp_path / "main.py").write_text(_MAIN, encoding="utf-8")  # no models.py
    res = project_missing_routes(tmp_path, [{"method": "GET", "path": "/api/videos/:id"}])
    assert "GET /api/videos/{id}" in res["projected"]
    src = (tmp_path / "main.py").read_text(encoding="utf-8")
    ast.parse(src)
    assert "/api/videos/:id" not in src
    defs = _projected_defs(src)
    sig = next(s for (p, s) in defs.values() if p == "/api/videos/{id}")
    assert re.search(r"\bid:\s*int\b", sig), sig
