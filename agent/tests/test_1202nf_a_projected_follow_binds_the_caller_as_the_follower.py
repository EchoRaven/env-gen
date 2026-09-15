"""#1202nf: a projected user->user create binds the PATH user as the target and the CALLER as the actor.

tiktok-r123 (delivered) and tiktok-r125 both projected

    POST /api/users/{user_id}/follow
        valid["follower_user_id"] = _parent.id          # the user in the path
        valid.setdefault("followed_user_id", _fw_owner_val(..., user))   # the caller

— "I follow user 7" stored as "user 7 follows me". `_target_fk` knew `followed_id` but not
`followed_user_id`, so it fell back to the first FK to `users`, which is the follower. Both runs'
lanes worked around it with a custom route; any run whose lane doesn't gets the inverted relation.

Across the corpus's models, two-user tables spelled `follower_user_id/followed_user_id` appear in
4 runs, `follower_user_id/following_user_id` in 1, and `sender_id/receiver_id` in 15.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

from multi_agent.runtime.route_projector import (  # noqa: E402
    _target_fk, project_missing_routes)

_MODELS = '''
from sqlalchemy import Column, Integer, String, ForeignKey, DateTime
from database import Base


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String)


class Follow(Base):
    __tablename__ = "follow"
    id = Column(Integer, primary_key=True)
    {first} = Column(Integer, ForeignKey("users.id"))
    {second} = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime)
'''

_MAIN = '''
from fastapi import FastAPI, Depends, HTTPException
from database import get_db
from models import User, Follow

app = FastAPI()
'''


def _bindings(tmp_path, first, second):
    (tmp_path / "models.py").write_text(_MODELS.format(first=first, second=second),
                                        encoding="utf-8")
    (tmp_path / "main.py").write_text(_MAIN, encoding="utf-8")
    project_missing_routes(tmp_path, [{"method": "POST", "path": "/api/users/{user_id}/follow"}])
    src = (tmp_path / "main.py").read_text(encoding="utf-8")
    ast.parse(src)
    lines = src.splitlines()
    start = next(i for i, ln in enumerate(lines) if 'post("/api/users/{user_id}/follow"' in ln)
    body = "\n".join(lines[start:start + 20])
    path_bound = [ln for ln in body.splitlines() if "= _parent.id" in ln]
    caller_bound = [ln for ln in body.splitlines() if "_fw_owner_val(" in ln and "setdefault" in ln]
    return body, path_bound, caller_bound


def test_r125_follower_user_id_is_the_caller(tmp_path):
    body, path_bound, caller_bound = _bindings(tmp_path, "follower_user_id", "followed_user_id")
    assert path_bound and '"followed_user_id"' in path_bound[0], body
    assert caller_bound and '"follower_user_id"' in caller_bound[0], body


def test_column_order_does_not_decide_the_role(tmp_path):
    body, path_bound, caller_bound = _bindings(tmp_path, "followed_user_id", "follower_user_id")
    assert '"followed_user_id"' in path_bound[0], body
    assert '"follower_user_id"' in caller_bound[0], body


def test_the_classic_spelling_is_unchanged(tmp_path):
    body, path_bound, caller_bound = _bindings(tmp_path, "follower_id", "following_id")
    assert '"following_id"' in path_bound[0], body
    assert '"follower_id"' in caller_bound[0], body


def test_an_unknown_second_role_still_avoids_binding_the_actor_to_the_path():
    meta = {"cols": ["id", "sender_user_id", "peer_ref"],
            "fks": {"sender_user_id": "users", "peer_ref": "users"}}
    assert _target_fk(meta, "users", "user") == "peer_ref"


def test_a_single_actor_fk_is_still_the_parent_bind():
    """/users/{id}/posts with only `author_id -> users`: nothing else can hold the path user."""
    meta = {"cols": ["id", "author_id", "body"], "fks": {"author_id": "users"}}
    assert _target_fk(meta, "users", "user") == "author_id"


def test_receiver_is_a_target():
    meta = {"cols": ["id", "sender_id", "receiver_id"],
            "fks": {"sender_id": "users", "receiver_id": "users"}}
    assert _target_fk(meta, "users", "user") == "receiver_id"
