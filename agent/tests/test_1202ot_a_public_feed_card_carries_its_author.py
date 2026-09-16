"""#1202ot: a projected list folds the author's PUBLIC display columns into a public feed.

`_expandable_fks_1202fh` refuses an actor target unless the actor table is served anonymously
somewhere (#1202ir) and is not owner-scoped (#1202ip). In a social app neither can ever hold:
`users` is the framework's own spine table, registered owner-scoped, and no app serves
`GET /api/users` to anonymous callers. So `_ACTOR_DISPLAY_COLS_1202IR` — the safe display set the
project already defined — was unreachable, and the measured result is that of the 159 projected
lists carrying an actor FK across the 22 most recent runs, 154 ship it bare: a video card renders
`author_id: 3` with no name and no avatar, against a reference screen full of @handles.

The permission now comes from the MATERIALS (this content is public), and the safety still comes from the column allowlist minus #1202jb's private
denylist — which this test checks against a model that carries email, phone and a password hash.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.route_projector import project_missing_routes  # noqa: E402

_MODELS = '''
from sqlalchemy import Column, Integer, String, ForeignKey
from db import Base

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String)
    avatar_url = Column(String)
    verified = Column(String)
    email = Column(String)
    phone = Column(String)
    password_hash = Column(String)

class Video(Base):
    __tablename__ = "videos"
    id = Column(Integer, primary_key=True)
    author_id = Column(Integer, ForeignKey("users.id"))
    caption = Column(String)

class Note(Base):
    __tablename__ = "notes"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    body = Column(String)
'''


def _project(tmp_path, entities, endpoints):
    backend = tmp_path / "app" / "backend"
    backend.mkdir(parents=True)
    (backend / "models.py").write_text(_MODELS)
    (backend / "main.py").write_text(
        "from fastapi import Depends, FastAPI, Query\napp = FastAPI()\n")
    design = tmp_path / "design"
    design.mkdir()
    (design / "reference_spec.json").write_text(json.dumps({"entities": entities}))
    project_missing_routes(backend, endpoints, owner_scoped_tables=["users", "notes"])
    return (backend / "main.py").read_text()


def _body(src, path):
    m = re.search(r'@app\.get\("%s"\)\ndef \w+\([^\n]*\):\n(.*?)(?=\n@app|\Z)'
                  % re.escape(path), src, re.S)
    assert m, f"no projected handler for {path}"
    return m.group(1)


def test_a_public_feed_card_gets_the_author_object(tmp_path):
    src = _project(tmp_path, [{"name": "videos", "visibility": "public"}],
                   [{"method": "GET", "path": "/api/videos", "auth_required": False}])
    body = _body(src, "/api/videos")
    assert '"author"' in body, body
    assert "username" in body and "avatar_url" in body, body


def test_the_fold_never_carries_contact_or_credentials(tmp_path):
    src = _project(tmp_path, [{"name": "videos", "visibility": "public"}],
                   [{"method": "GET", "path": "/api/videos", "auth_required": False}])
    body = _body(src, "/api/videos")
    for private in ("email", "phone", "password_hash"):
        assert private not in body, (private, body)


def test_my_own_rows_do_not_fold_the_author_who_is_me(tmp_path):
    src = _project(tmp_path, [{"name": "notes", "visibility": "owner"}],
                   [{"method": "GET", "path": "/api/notes", "auth_required": True}])
    body = _body(src, "/api/notes")
    assert '"user"' not in body, body


def test_content_the_materials_do_not_publish_keeps_both_gates(tmp_path):
    """No verdict, no fold — the previous behaviour, so nothing is published by accident."""
    src = _project(tmp_path, [], [{"method": "GET", "path": "/api/videos",
                                   "auth_required": False}])
    body = _body(src, "/api/videos")
    assert '"author"' not in body, body
