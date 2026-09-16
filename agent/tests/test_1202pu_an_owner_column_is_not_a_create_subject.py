"""#1202pu: an owner-shaped column (actor_id, sender_id, ...) is never the subject a create
must name. tiktok-r126's M1 aborted on its last failing check, `POST /api/notifications -> 400
"one of actor_id is required"`, while the same handler 403s any actor_id but the caller's."""
from __future__ import annotations

import ast
import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

from multi_agent.runtime.route_projector import project_missing_routes  # noqa: E402

_MODELS = '''
from sqlalchemy import Column, Integer, String, ForeignKey
from database import Base


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String)


class Video(Base):
    __tablename__ = "videos"
    id = Column(Integer, primary_key=True)
    caption = Column(String)


class Notification(Base):
    __tablename__ = "notifications"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    actor_id = Column(Integer, ForeignKey("users.id"))
    title = Column(String)


class Mention(Base):
    __tablename__ = "mentions"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    actor_id = Column(Integer, ForeignKey("users.id"))
    video_id = Column(Integer, ForeignKey("videos.id"))
'''

_MAIN = '''
from fastapi import FastAPI, Depends, HTTPException
from database import get_db
from models import User, Video, Notification, Mention

app = FastAPI()
'''


def _project(tmp_path, path):
    (tmp_path / "models.py").write_text(_MODELS, encoding="utf-8")
    (tmp_path / "main.py").write_text(_MAIN, encoding="utf-8")
    project_missing_routes(tmp_path, [{"method": "POST", "path": path, "auth_required": True}])
    src = (tmp_path / "main.py").read_text(encoding="utf-8")
    ast.parse(src)
    return src


def test_actor_id_is_not_demanded_from_the_client(tmp_path):
    src = _project(tmp_path, "/api/notifications")
    assert 'post("/api/notifications"' in src
    assert "one of actor_id is required" not in src


def test_a_real_subject_beside_an_actor_is_still_required(tmp_path):
    src = _project(tmp_path, "/api/mentions")
    assert "for _k in ['video_id']" in src, src[-3000:]
    assert "'actor_id'" not in src.split("for _k in ['video_id']")[0][-300:]
