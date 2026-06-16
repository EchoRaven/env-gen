"""By-construction route projector — fills declared-but-uncoded endpoints.

Root fix for the hollow-release bug (instagram MM, 2026-06-08): a lane declares
endpoints in RegistryHub but stops before coding all of them; the projector projects a
working handler for every declared business endpoint with no route, so the shipped
contract is complete (no 404 on a declared route).
"""

import ast
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.route_projector import (  # noqa: E402
    _existing_routes,
    _primary_content_model,
    _resource_model,
    project_missing_routes,
)

_MODELS = '''
from sqlalchemy import Column, Integer, String, Text, DateTime
from database import Base

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True)
    full_name = Column(String)
    bio = Column(Text)
    password_hash = Column(String)
    created_at = Column(DateTime)

class Post(Base):
    __tablename__ = "posts"
    id = Column(Integer, primary_key=True)
    author_id = Column(Integer)
    caption = Column(Text)
    created_at = Column(DateTime)
'''

_MAIN = '''
from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models import User, Post

app = FastAPI()

def get_current_user():
    ...

@app.get("/api/users/me")
def me(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return {"item": {}}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app)
'''


_MODELS_NESTED = _MODELS + '''
class Comment(Base):
    __tablename__ = "comments"
    id = Column(Integer, primary_key=True)
    post_id = Column(Integer)
    user_id = Column(Integer)
    text = Column(Text)
    created_at = Column(DateTime)

class Follow(Base):
    __tablename__ = "follows"
    id = Column(Integer, primary_key=True)
    follower_id = Column(Integer)
    following_id = Column(Integer)
    created_at = Column(DateTime)
'''


def _backend(tmp_path):
    (tmp_path / "models.py").write_text(_MODELS, encoding="utf-8")
    (tmp_path / "main.py").write_text(_MAIN, encoding="utf-8")
    return tmp_path


def test_existing_routes_parsed_from_decorators(tmp_path):
    routes = _existing_routes(_MAIN)
    assert ("GET", "/api/users/me") in routes


def test_projects_only_missing_and_output_parses(tmp_path):
    be = _backend(tmp_path)
    declared = [
        {"method": "GET", "path": "/api/users/me"},          # exists → skip
        {"method": "GET", "path": "/api/users/{username}"},  # missing
        {"method": "GET", "path": "/api/posts/{post_id}"},   # missing
        {"method": "DELETE", "path": "/api/posts/{post_id}"},  # missing
        {"method": "POST", "path": "/api/posts"},            # missing
    ]
    res = project_missing_routes(be, declared)
    projected = res["projected"]
    assert "GET /api/users/me" not in projected           # existing not re-projected
    assert "GET /api/users/{username}" in projected
    assert "DELETE /api/posts/{post_id}" in projected
    assert len(projected) == 4
    # the rewritten main.py must be valid Python
    ast.parse((be / "main.py").read_text(encoding="utf-8"))


def test_idempotent(tmp_path):
    be = _backend(tmp_path)
    declared = [{"method": "GET", "path": "/api/posts/{post_id}"}]
    assert len(project_missing_routes(be, declared)["projected"]) == 1
    assert len(project_missing_routes(be, declared)["projected"]) == 0  # 2nd run: nothing


def test_auth_paths_never_projected(tmp_path):
    be = _backend(tmp_path)
    declared = [{"method": "POST", "path": "/auth/register"}]
    assert project_missing_routes(be, declared)["projected"] == []  # AS-owned, not lane-projected


def test_mutating_handlers_are_500_safe(tmp_path):
    """A relational create the projector can't fully wire must roll back, not 500."""
    be = _backend(tmp_path)
    project_missing_routes(be, [{"method": "POST", "path": "/api/posts"}])
    src = (be / "main.py").read_text(encoding="utf-8")
    # the projected create body wraps the commit and rolls back on failure
    assert "db.rollback()" in src
    assert "try:" in src


def test_search_handler_columns_are_domain_general(tmp_path):
    """GENERALITY: the projected search handler must consider generic text columns
    (description/content/body/summary/...), not only social-shaped ones
    (caption/username) — so search works for ANY domain, not just instagram-style
    apps. Runtime stays safe via the hasattr guard (absent columns are skipped)."""
    be = _backend(tmp_path)
    project_missing_routes(be, [{"method": "GET", "path": "/api/users/search"}])
    src = (be / "main.py").read_text(encoding="utf-8")
    line = next((ln for ln in src.splitlines() if "cols_to_search" in ln), "")
    assert line, "no search handler was projected"
    for generic in ("description", "content", "body", "summary", "bio"):
        assert generic in line, f"search candidates omit generic text column {generic!r} (social-biased)"
    # social columns still covered — no regression for instagram-style apps
    assert "caption" in line and "username" in line


def test_nested_collection_lists_child_by_owner_fk(tmp_path):
    """/api/users/{username}/posts must resolve the user and LIST their posts by
    author_id — not the old naive ``Post.id == username`` (a 500: int = varchar)."""
    be = _backend(tmp_path)
    project_missing_routes(be, [{"method": "GET", "path": "/api/users/{username}/posts"}])
    src = (be / "main.py").read_text(encoding="utf-8")
    ast.parse(src)
    assert 'getattr(User, "username") == username' in src      # resolve the parent
    assert 'getattr(Post, "author_id") == parent.id' in src    # scope child by FK
    assert 'getattr(Post, "id") == username' not in src        # the old 500 bug is gone


def test_create_injects_authenticated_owner(tmp_path):
    """POST /api/posts must attribute the row to the caller (author_id), not null."""
    be = _backend(tmp_path)
    project_missing_routes(be, [{"method": "POST", "path": "/api/posts"}])
    src = (be / "main.py").read_text(encoding="utf-8")
    ast.parse(src)
    assert 'valid.setdefault("author_id", user.id)' in src


def test_raw_sql_app_no_models_does_not_reference_User(tmp_path):
    """A lane that wrote a RAW-SQL app (no models.py) must NOT get projected handlers
    that reference ``User``/``Session`` in annotations — that crashed the whole app at
    import with NameError (instagram MM run #13). Deps use bare ``=Depends(...)`` and a
    guarded ``from models import *`` so the module still loads."""
    (tmp_path / "main.py").write_text(_MAIN, encoding="utf-8")  # no models.py written
    res = project_missing_routes(tmp_path, [{"method": "GET", "path": "/api/feed"},
                                            {"method": "POST", "path": "/api/posts"}])
    assert res["projected"]
    out = (tmp_path / "main.py").read_text(encoding="utf-8")
    ast.parse(out)  # must still be importable
    # the PROJECTED handler signatures must use bare deps, never ``: User``/``: Session``
    proj_defs = [ln for ln in out.splitlines() if ln.startswith("def _projected_")]
    assert proj_defs
    assert all("user: User" not in ln and "db: Session" not in ln for ln in proj_defs)
    assert any("user=Depends(get_current_user)" in ln for ln in proj_defs)
    assert "try:\n    from models import *" in out      # guarded model import


def test_nested_create_binds_parent_target_and_owner(tmp_path):
    """POST /api/users/{username}/follow → following_id=path-param user, follower_id=caller."""
    (tmp_path / "models.py").write_text(_MODELS_NESTED, encoding="utf-8")
    (tmp_path / "main.py").write_text(_MAIN, encoding="utf-8")
    project_missing_routes(tmp_path, [{"method": "POST", "path": "/api/users/{username}/follow"}])
    src = (tmp_path / "main.py").read_text(encoding="utf-8")
    ast.parse(src)
    assert 'valid["following_id"] = _parent.id' in src         # target = path-param user
    assert 'valid.setdefault("follower_id", user.id)' in src   # actor = authenticated caller


# ---------------------------------------------------------------------------
# Feed/timeline resolution is DOMAIN-AGNOSTIC (generality sweep 2026-06-15):
# a /feed path that names no table must resolve to the app's primary content
# table by SHAPE, not the hardcoded social `posts` — so news/activity/task feeds
# work, not only the Instagram surface. Social apps stay back-compatible.
# ---------------------------------------------------------------------------
def _m(cls, cols, fks=None):
    return {"cls": cls, "cols": cols, "fks": fks or {}}


def test_feed_resolves_to_posts_for_social_app_backcompat():
    models = {
        "users": _m("User", ["id", "username"]),
        "posts": _m("Post", ["id", "author_id", "caption", "created_at"], {"author_id": "users"}),
    }
    res = _resource_model("/api/feed", models)
    assert res is not None and res[0] == "posts", res


def test_feed_resolves_to_primary_content_table_for_non_social_app():
    # a news app: no 'posts' table; /feed should list articles (timestamped + authored)
    models = {
        "users": _m("User", ["id", "email"]),
        "articles": _m("Article", ["id", "title", "body", "author_id", "created_at"], {"author_id": "users"}),
        "tags": _m("Tag", ["id", "name"]),  # not feed-shaped (no timestamp)
    }
    res = _resource_model("/api/feed", models)
    assert res is not None and res[0] == "articles", res


def test_timeline_does_not_guess_when_no_feed_shaped_table():
    # only a non-timestamped lookup table besides users → resolve to nothing, never
    # force a wrong table onto a feed route.
    models = {
        "users": _m("User", ["id", "email"]),
        "tags": _m("Tag", ["id", "name"]),
    }
    assert _resource_model("/api/timeline", models) is None


def test_primary_content_prefers_timestamped_authored_over_unowned():
    models = {
        "users": _m("User", ["id"]),
        "categories": _m("Category", ["id", "name", "created_at"]),          # ts, no owner → rank 1
        "tasks": _m("Task", ["id", "title", "owner_id", "created_at"], {"owner_id": "users"}),  # ts + owner → rank 2
    }
    res = _primary_content_model(models)
    assert res is not None and res[0] == "tasks", res


def test_primary_content_excludes_identity_and_auth_spine():
    # spine tables (users/tenants/oauth/sessions) are never the content a feed lists,
    # even though they carry created_at.
    models = {
        "users": _m("User", ["id", "created_at"]),
        "tenants": _m("Tenant", ["id", "created_at"]),
        "oauth_tokens": _m("OAuthToken", ["id", "created_at"]),
        "sessions": _m("Session", ["id", "created_at"]),
    }
    assert _primary_content_model(models) is None
