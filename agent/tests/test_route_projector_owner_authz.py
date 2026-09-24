"""route_projector: projected mutating CRUD must (1) UPDATE-by-id on PUT/PATCH
(not INSERT a duplicate), and (2) authorize PUT/DELETE to the row OWNER.

Live on smoke-notes (2026-06-20): the projected PUT /api/notes/{id} fell through
to the create path (``Note(**valid); db.add``) → every edit INSERTED a new note.
And PUT/DELETE had no ownership check → any authenticated user could mutate or
delete another user's row. READ-scoping (GET list/item) is intentionally NOT
changed here — "only see your own rows" is domain-dependent (private notes vs a
public feed) and stays a separate decision.
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
    """Extract the function body for the @app.<method>("<path>"...) handler."""
    lines = main_src.splitlines()
    dec = f'@app.{method.lower()}("{path}"'
    for i, ln in enumerate(lines):
        if ln.startswith(dec):
            j = i + 1
            # def line + body until the next top-level decorator/def/blank-at-col0
            out = []
            while j < len(lines):
                if lines[j].startswith("@app.") or (
                        lines[j].startswith("def ") and out):
                    break
                out.append(lines[j])
                j += 1
            return "\n".join(out)
    return ""


def test_put_updates_existing_row_not_insert(tmp_path):
    be = _backend(tmp_path)
    project_missing_routes(be, [{"method": "PUT", "path": "/api/posts/{post_id}"}])
    main_src = (be / "main.py").read_text(encoding="utf-8")
    ast.parse(main_src)  # valid python
    put = _handler_src(main_src, "PUT", "/api/posts/{post_id}")
    assert "db.get(Post, post_id)" in put            # fetch existing by id
    assert "setattr(obj, k, v)" in put               # mutate in place
    assert "Post(**valid)" not in put                # NOT a fresh insert
    assert "db.add(" not in put


def test_put_authorizes_owner(tmp_path):
    be = _backend(tmp_path)
    project_missing_routes(be, [{"method": "PUT", "path": "/api/posts/{post_id}"}])
    put = _handler_src((be / "main.py").read_text(encoding="utf-8"),
                       "PUT", "/api/posts/{post_id}")
    assert 'getattr(obj, "author_id", None) != _fw_owner_val(type(obj), "author_id", user)' in put


def test_delete_authorizes_owner(tmp_path):
    be = _backend(tmp_path)
    project_missing_routes(be, [{"method": "DELETE", "path": "/api/posts/{post_id}"}])
    dele = _handler_src((be / "main.py").read_text(encoding="utf-8"),
                        "DELETE", "/api/posts/{post_id}")
    assert "db.get(Post, post_id)" in dele
    assert 'getattr(obj, "author_id", None) != _fw_owner_val(type(obj), "author_id", user)' in dele
    assert "db.delete(obj)" in dele


def test_owner_authz_skipped_when_model_has_no_owner_fk(tmp_path):
    # PublicDoc has no owner FK → PUT still updates-by-id, but NO ownership gate
    # (can't attribute it). Proves the authz is keyed on a real owner column.
    be = _backend(tmp_path)
    project_missing_routes(be, [{"method": "PUT", "path": "/api/publicdocs/{id}"}])
    put = _handler_src((be / "main.py").read_text(encoding="utf-8"),
                       "PUT", "/api/publicdocs/{id}")
    assert "db.get(PublicDoc, id)" in put     # still an update, not insert
    assert "setattr(obj, k, v)" in put
    assert "!= user.id" not in put            # no owner gate (no owner fk)


def test_post_create_still_injects_owner_and_inserts(tmp_path):
    # regression: POST must still CREATE (db.add) and inject the owner.
    be = _backend(tmp_path)
    project_missing_routes(be, [{"method": "POST", "path": "/api/posts"}])
    post = _handler_src((be / "main.py").read_text(encoding="utf-8"),
                        "POST", "/api/posts")
    assert "Post(**valid)" in post
    assert "db.add(" in post
    assert 'valid.setdefault("author_id", _fw_owner_val(Post, "author_id", user))' in post


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
