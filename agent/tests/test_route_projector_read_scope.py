"""route_projector: OPT-IN owner-scoped READS.

By default the projector leaves reads OPEN — the reference model is a public
feed (anyone may GET /api/posts/{id}), so "only see your own rows" must NOT be
hardcoded (see test_route_projector_owner_authz docstring).

But a whole class of apps (notes, email, calendar, todos, files, DMs, drafts)
is per-user PRIVATE: every read must be owner-scoped, exactly as writes already
are. That intent lives in the contract as a per-resource signal
``owner_scoped_reads`` carried on the resource's endpoint metadata. When set,
the projector scopes the by-id GET, the flat collection GET, and search to the
owner FK — by construction, so the lane never has to override a projected route
(which fd56c2e closed for CRUD) and the isolation chain passes without a
remediation loop.

Default OFF ⇒ public feeds + every existing projection are unchanged (no
regression). Skipped when the model has no owner FK (can't attribute a row).
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.runtime.route_projector import project_missing_routes  # noqa: E402

# Post has an owner FK (author_id); PublicDoc has none.
_MODELS = '''
from sqlalchemy import Column, Integer, String, Text, DateTime
from database import Base

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True)

class Post(Base):
    __tablename__ = "posts"
    id = Column(Integer, primary_key=True)
    author_id = Column(Integer)
    caption = Column(Text)
    created_at = Column(DateTime)

class PublicDoc(Base):
    __tablename__ = "publicdocs"
    id = Column(Integer, primary_key=True)
    title = Column(String)
    body = Column(Text)
'''

_MAIN = '''
from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models import User, Post, PublicDoc

app = FastAPI()

def get_current_user():
    ...

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app)
'''


def _backend(tmp_path):
    (tmp_path / "models.py").write_text(_MODELS, encoding="utf-8")
    (tmp_path / "main.py").write_text(_MAIN, encoding="utf-8")
    return tmp_path


def _handler_src(main_src: str, method: str, path: str) -> str:
    lines = main_src.splitlines()
    dec = f'@app.{method.lower()}("{path}"'
    for i, ln in enumerate(lines):
        if ln.startswith(dec):
            j, out = i + 1, []
            while j < len(lines):
                if lines[j].startswith("@app.") or (
                        lines[j].startswith("def ") and out):
                    break
                out.append(lines[j])
                j += 1
            return "\n".join(out)
    return ""


def _project(be, eps):
    project_missing_routes(be, eps)
    return (be / "main.py").read_text(encoding="utf-8")


# ---- DEFAULT OFF: reads stay open (public-feed reference behavior) ----------

def test_byid_read_unscoped_by_default(tmp_path):
    be = _backend(tmp_path)
    src = _project(be, [{"method": "GET", "path": "/api/posts/{id}"}])
    ast.parse(src)
    h = _handler_src(src, "GET", "/api/posts/{id}")
    assert "db.get(Post, id)" in h
    assert "!= user.id" not in h           # NOT scoped — open by default


def test_collection_read_unscoped_by_default(tmp_path):
    be = _backend(tmp_path)
    src = _project(be, [{"method": "GET", "path": "/api/posts"}])
    h = _handler_src(src, "GET", "/api/posts")
    assert "db.query(Post)" in h
    assert "== user.id" not in h           # no owner filter (author_id may appear in the serialized row)


# ---- FLAG ON: reads owner-scoped, mirroring writes -------------------------

def test_byid_read_scoped_when_flagged(tmp_path):
    be = _backend(tmp_path)
    src = _project(be, [{"method": "GET", "path": "/api/posts/{id}",
                         "metadata": {"owner_scoped_reads": True}}])
    ast.parse(src)
    h = _handler_src(src, "GET", "/api/posts/{id}")
    assert "db.get(Post, id)" in h
    assert 'getattr(obj, "author_id", None) != _fw_owner_val(type(obj), "author_id", user)' in h   # scoped


def test_collection_read_scoped_when_flagged(tmp_path):
    be = _backend(tmp_path)
    src = _project(be, [{"method": "GET", "path": "/api/posts",
                         "metadata": {"owner_scoped_reads": True}}])
    h = _handler_src(src, "GET", "/api/posts")
    assert 'getattr(Post, "author_id") == _fw_owner_val(Post, "author_id", user)' in h        # owner filter


def test_search_scoped_when_flagged(tmp_path):
    be = _backend(tmp_path)
    src = _project(be, [{"method": "GET", "path": "/api/posts/search",
                         "metadata": {"owner_scoped_reads": True}}])
    ast.parse(src)
    h = _handler_src(src, "GET", "/api/posts/search")
    assert 'getattr(Post, "author_id") == _fw_owner_val(Post, "author_id", user)' in h


def test_flag_applies_per_resource_from_any_endpoint(tmp_path):
    # The flag set on ONE of the resource's endpoints scopes ALL of its reads —
    # robust to the contract marking only the collection (or only the item).
    be = _backend(tmp_path)
    src = _project(be, [
        {"method": "GET", "path": "/api/posts",
         "metadata": {"owner_scoped_reads": True}},
        {"method": "GET", "path": "/api/posts/{id}"},   # not marked here
    ])
    h_item = _handler_src(src, "GET", "/api/posts/{id}")
    assert 'getattr(obj, "author_id", None) != _fw_owner_val(type(obj), "author_id", user)' in h_item


# ---- safety: no owner FK ⇒ cannot scope (degrade to open) ------------------

def test_scoped_read_skipped_without_owner_fk(tmp_path):
    be = _backend(tmp_path)
    src = _project(be, [{"method": "GET", "path": "/api/publicdocs/{id}",
                         "metadata": {"owner_scoped_reads": True}}])
    h = _handler_src(src, "GET", "/api/publicdocs/{id}")
    assert "!= user.id" not in h           # no owner col → no scope


# ---- table-level signal (the heal_pipeline → projector path) --------------

def test_owner_scoped_tables_param_scopes_reads(tmp_path):
    # The reliable source: table names the contract marked private, passed as a
    # set (heal_pipeline reads owner_scoped_reads off registryhub table metadata).
    be = _backend(tmp_path)
    project_missing_routes(
        be,
        [{"method": "GET", "path": "/api/posts/{id}"},
         {"method": "GET", "path": "/api/posts"}],
        owner_scoped_tables={"posts"},
    )
    src = (be / "main.py").read_text(encoding="utf-8")
    item = _handler_src(src, "GET", "/api/posts/{id}")
    coll = _handler_src(src, "GET", "/api/posts")
    assert 'getattr(obj, "author_id", None) != _fw_owner_val(type(obj), "author_id", user)' in item
    assert 'getattr(Post, "author_id") == _fw_owner_val(Post, "author_id", user)' in coll


def test_owner_scoped_tables_param_leaves_other_tables_open(tmp_path):
    be = _backend(tmp_path)
    project_missing_routes(
        be,
        [{"method": "GET", "path": "/api/posts/{id}"}],
        owner_scoped_tables={"notes"},   # a DIFFERENT table is private
    )
    h = _handler_src((be / "main.py").read_text(encoding="utf-8"),
                     "GET", "/api/posts/{id}")
    assert "!= user.id" not in h         # posts stays open


# ---- writes remain scoped regardless of the read flag (regression) ---------

def test_writes_still_scoped_independent_of_read_flag(tmp_path):
    be = _backend(tmp_path)
    src = _project(be, [{"method": "DELETE", "path": "/api/posts/{id}"}])
    h = _handler_src(src, "DELETE", "/api/posts/{id}")
    assert 'getattr(obj, "author_id", None) != _fw_owner_val(type(obj), "author_id", user)' in h


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
