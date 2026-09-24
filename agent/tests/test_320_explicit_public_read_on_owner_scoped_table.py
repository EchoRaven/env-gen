"""#320 — a table can hold OWNED-but-PUBLIC content (TikTok videos, IG posts): rows
have a creator yet the feed is public. A single per-table owner_scoped_reads flag
(set for the 'my videos' profile view / write ownership) otherwise owner-scopes +
#315-force-auths EVERY read, so the public feed 401s → ui_flow gate wedges (r88/r89).

Fix: an EXPLICIT auth_required=False on an owner-scoped table's read is the lane's
deliberate 'this read is public' declaration → serve it public (no owner row-filter,
no force-auth). UNSTATED reads on an owner-scoped table STILL force-auth + owner-scope
(r58/#315 leak protection: a private table's unstated read must not default open).
"""
import sys
from pathlib import Path

THIS = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS.parent / "env_generator" / "llm_generator"))
from multi_agent.runtime.route_projector import project_missing_routes  # noqa: E402

_MODELS = '''
from sqlalchemy import Column, Integer, String, Text
from database import Base

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)

class Post(Base):
    __tablename__ = "posts"
    id = Column(Integer, primary_key=True)
    author_id = Column(Integer)
    caption = Column(Text)
'''

_MAIN = '''
from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models import User, Post

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
                if lines[j].startswith("@app.") or (lines[j].startswith("def ") and out):
                    break
                out.append(lines[j]); j += 1
            return "\n".join(out)
    return ""


def test_explicit_public_read_on_owner_scoped_table_is_public(tmp_path):
    be = _backend(tmp_path)
    # posts is owner-scoped (table-level), but the collection feed is EXPLICITLY public.
    project_missing_routes(be, [
        {"method": "GET", "path": "/api/posts", "auth_required": False},   # public feed
    ], owner_scoped_tables={"posts"})
    src = (be / "main.py").read_text(encoding="utf-8")
    pub = _handler_src(src, "GET", "/api/posts")
    assert pub, "feed handler was projected"
    # deliberate public: no forced auth and no owner row-filter. (author_id appearing in
    # the RESPONSE serialization is fine — the feed shows each post's author; what must be
    # absent is the owner FILTER: get_current_user / .filter(...owner...) / user.id.)
    assert "get_current_user" not in pub, f"public feed must NOT force auth:\n{pub}"
    assert ".filter(" not in pub and "user.id" not in pub and "_fw_owner_val" not in pub, \
        f"public feed must NOT owner-filter its rows:\n{pub}"


def test_unstated_read_on_owner_scoped_table_stays_protected(tmp_path):
    # #315 leak protection intact: an UNSTATED read on an owner-scoped table is still
    # owner-scoped + auth (a private table's list must not default open).
    be = _backend(tmp_path)
    project_missing_routes(be, [
        {"method": "GET", "path": "/api/posts/{id}"},   # unstated
    ], owner_scoped_tables={"posts"})
    src = (be / "main.py").read_text(encoding="utf-8")
    priv = _handler_src(src, "GET", "/api/posts/{id}")
    assert priv, "by-id handler was projected"
    assert "get_current_user" in priv, f"unstated owner-scoped read must force auth:\n{priv}"
    assert "user.id" in priv or "_fw_owner_val" in priv, \
        f"unstated owner-scoped read must owner-filter:\n{priv}"


def test_explicit_public_does_not_affect_non_owner_scoped(tmp_path):
    # a public read on a NON-owner-scoped table is unchanged (already public).
    be = _backend(tmp_path)
    project_missing_routes(be, [
        {"method": "GET", "path": "/api/posts", "auth_required": False},
    ], owner_scoped_tables=set())
    src = (be / "main.py").read_text(encoding="utf-8")
    pub = _handler_src(src, "GET", "/api/posts")
    assert pub and "get_current_user" not in pub and ".filter(" not in pub and "user.id" not in pub
