"""#1202og/#1202oh: the materials' `visibility` reaches the projector, and lands on the right table.

`_declared_public_content_1202hh` and `_declared_owner_private_1202ht` both read
`meta["visibility"]`, and every call site in route_projector passes an `_orm_models` entry,
whose keys are exactly {cls, cols, fks, types, required}. So on the projector's path the
materials' verdict was unreachable and the SHAPE heuristics decided alone. On tiktok-r126's real
models `_structurally_private_resource_633` is True for `videos`/`comments` — the public feed,
owner-filtered AND behind `Depends(get_current_user)`, so a logged-out visitor gets 401 on the
front page — and False for `user_settings`/`dm_conversations`, whose per-user rows the projected
handler serves to any anonymous caller. That run's reference_spec says: public, public, owner,
owner.

#1202oh: r125 shows the second half. Its spec names singular entities and its registry holds both
twins — `video {visibility: public}` (stamped, read by nothing) next to `videos
{owner_scoped_reads: True}` (what every handler queries). `GET /api/feed`'s auth_required flipped
16 times in 3h21m over that gap; r126, plural spec and no twins, flipped 0.

Behavioural on purpose: these assert what the emitted handler DOES, not where a line sits in the
source — the weakness an audit of this suite found in seven other wiring tests.
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

from multi_agent.runtime.backend_skeleton import _spec_verdict_for_table_1202oh  # noqa: E402
from multi_agent.runtime.route_projector import (  # noqa: E402
    _orm_models, _stamp_spec_visibility_1202og, project_missing_routes)

_MODELS = '''
from sqlalchemy import Column, Integer, String, ForeignKey
from db import Base

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String)

class Sound(Base):
    __tablename__ = "sounds"
    id = Column(Integer, primary_key=True)
    name = Column(String)

class Video(Base):
    __tablename__ = "videos"
    id = Column(Integer, primary_key=True)
    author_id = Column(Integer, ForeignKey("users.id"))
    sound_id = Column(Integer, ForeignKey("sounds.id"))
    caption = Column(String)

class UserSetting(Base):
    __tablename__ = "user_settings"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    language = Column(String)
'''

_MAIN = '''from fastapi import Depends, FastAPI
app = FastAPI()
'''


def _run(tmp_path, spec_entities):
    backend = tmp_path / "app" / "backend"
    backend.mkdir(parents=True)
    (backend / "models.py").write_text(_MODELS)
    (backend / "main.py").write_text(_MAIN)
    design = tmp_path / "design"
    design.mkdir()
    (design / "reference_spec.json").write_text(json.dumps({"entities": spec_entities}))
    project_missing_routes(backend, [
        {"method": "GET", "path": "/api/videos", "auth_required": False},
        {"method": "GET", "path": "/api/user_settings", "auth_required": False},
    ])
    return (backend / "main.py").read_text()


def _handler(src, path):
    m = re.search(r'@app\.get\("%s"\)\ndef \w+\(([^\n]*)\):\n(.*?)(?=\n@app|\Z)'
                  % re.escape(path), src, re.S)
    assert m, f"no projected handler for {path}\n{src[-1500:]}"
    return m.group(1), m.group(2)


def test_r126_a_public_feed_is_not_owner_filtered_and_serves_anonymous(tmp_path):
    src = _run(tmp_path, [{"name": "videos", "visibility": "public"},
                          {"name": "user_settings", "visibility": "owner"}])
    sig, body = _handler(src, "/api/videos")
    assert "author_id" not in body.split("return")[0] or "_fw_owner_val" not in body
    assert "get_current_user" not in sig, sig       # the logged-out front page must not 401


def test_r126_a_per_user_table_is_scoped_even_when_the_endpoint_says_public(tmp_path):
    src = _run(tmp_path, [{"name": "videos", "visibility": "public"},
                          {"name": "user_settings", "visibility": "owner"}])
    sig, body = _handler(src, "/api/user_settings")
    assert "_fw_owner_val" in body and "user_id" in body, body[:400]
    assert "get_current_user" in sig, sig


def test_without_the_materials_the_shape_heuristics_still_decide(tmp_path):
    """No spec → byte-for-byte the old behaviour: videos filtered, user_settings wide open."""
    src = _run(tmp_path, [])
    _, videos = _handler(src, "/api/videos")
    _, settings = _handler(src, "/api/user_settings")
    assert "_fw_owner_val" in videos          # #633 fires unopposed
    assert "_fw_owner_val" not in settings    # and cannot see that this one is per-user


def test_the_stamp_is_a_backfill_and_never_overwrites(tmp_path):
    backend = tmp_path / "app" / "backend"
    backend.mkdir(parents=True)
    (backend / "models.py").write_text(_MODELS)
    design = tmp_path / "design"
    design.mkdir()
    (design / "reference_spec.json").write_text(
        json.dumps({"entities": [{"name": "videos", "visibility": "public"}]}))
    models = _orm_models(backend)
    models["videos"]["visibility"] = "owner"      # an earlier, authoritative stamp
    n = _stamp_spec_visibility_1202og(models, tmp_path)
    assert models["videos"]["visibility"] == "owner" and n == 0


def test_1202oh_the_verdict_finds_the_twin_the_handlers_read():
    vis = {"video": "public", "user_setting": "owner", "comments": "public"}
    assert _spec_verdict_for_table_1202oh("videos", vis) == "public"      # r125's twin
    assert _spec_verdict_for_table_1202oh("user_settings", vis) == "owner"
    assert _spec_verdict_for_table_1202oh("comments", vis) == "public"    # exact wins
    assert _spec_verdict_for_table_1202oh("sounds", vis) == ""            # no verdict, no guess
    assert _spec_verdict_for_table_1202oh("", vis) == ""
