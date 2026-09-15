"""#1202my: a projected create must not refuse what its own registered contract declares valid.

#1202bl refuses a create that names no subject FK, because such a row "is nothing but its own id
and owner" — true for netflix-r32's `POST /api/continue-watching {}`. tiktok-r125's M2 verification
chain sent `POST /api/videos {video_url, thumbnail, caption, category}` and got

    400 "one of sound_id is required ... [FRAMEWORK-PROJECTED route ... the lane cannot edit it]"

— for a video that has content and no linked sound, while the registered request schema says
`"sound_id": "string nullable references sounds.id"`. Framework validation failed 6/6 on it and
the verifier was re-woken for a fix no lane could make.

When EVERY subject FK is explicitly declared optional (`?` suffix or `nullable`; `not null` is the
opposite), the guard asks only that the request name the subject OR some other field of its own.
An empty create is still refused. An undeclared FK or a missing schema keeps #1202bl unchanged.

Corpus: 39 of 281 subject-FK POST endpoints declare every subject FK optional (`/api/videos` 17,
`/api/notifications` 7, ...); netflix's continue-watching declares `title_id: "int"` in every run.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

from multi_agent.runtime.route_projector import (  # noqa: E402
    _declared_optional_1202my, project_missing_routes)

_MODELS = '''
from sqlalchemy import Column, Integer, String, ForeignKey
from database import Base


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String)


class Sound(Base):
    __tablename__ = "sounds"
    id = Column(Integer, primary_key=True)
    title = Column(String)


class Video(Base):
    __tablename__ = "videos"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    sound_id = Column(Integer, ForeignKey("sounds.id"))
    video_url = Column(String)
    caption = Column(String)
'''

_MAIN = '''
from fastapi import FastAPI, Depends, HTTPException
from database import get_db
from models import User, Sound, Video

app = FastAPI()
'''

R125_REQUEST = {"video_url": "string", "thumbnail": "string", "caption": "text",
                "sound_id": "string nullable references sounds.id", "category": "string"}


def _project(tmp_path, request):
    (tmp_path / "models.py").write_text(_MODELS, encoding="utf-8")
    (tmp_path / "main.py").write_text(_MAIN, encoding="utf-8")
    ep = {"method": "POST", "path": "/api/videos"}
    if request is not None:
        ep["schema"] = {"request": request}
    project_missing_routes(tmp_path, [ep])
    src = (tmp_path / "main.py").read_text(encoding="utf-8")
    ast.parse(src)
    return src


def _handler(src):
    lines = src.splitlines()
    start = next(i for i, ln in enumerate(lines) if 'post("/api/videos"' in ln)
    out, seen_def = [], False
    for ln in lines[start:]:
        if seen_def and (ln.startswith("@app.") or ln.startswith("def ")):
            break
        seen_def = seen_def or ln.startswith("def ")
        out.append(ln)
    return "\n".join(out)


def _guard_fires(handler_src, payload, valid):
    """Execute the emitted `if ...:` condition of the #1202my guard against a request."""
    tree = ast.parse(handler_src)
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and "1202my" in ast.unparse(node.body[0]):
            # one namespace: the emitted generator expressions read `valid`/`payload` as
            # free names, which a separate locals dict would hide from them
            ns = {"Video": type("Video", (), {k: 1 for k in (
                      "id", "user_id", "sound_id", "video_url", "caption")}),
                  "payload": payload, "valid": valid}
            return eval(compile(ast.Expression(node.test), "<guard>", "eval"), ns)
    raise AssertionError("no #1202my guard in the handler:\n" + handler_src)


def test_r125s_videos_contract_no_longer_demands_a_sound(tmp_path):
    h = _handler(_project(tmp_path, R125_REQUEST))
    assert "one of sound_id is required" not in h, h
    assert "1202my" in h


def test_a_video_with_content_and_no_sound_is_accepted(tmp_path):
    h = _handler(_project(tmp_path, R125_REQUEST))
    body = {"video_url": "https://cdn/x.mp4", "caption": "hi"}
    assert _guard_fires(h, body, dict(body, user_id=7)) is False


def test_an_empty_create_is_still_refused(tmp_path):
    """The owner FK is filled in by the handler, so it must not count as the request's own."""
    h = _handler(_project(tmp_path, R125_REQUEST))
    assert _guard_fires(h, {}, {"user_id": 7}) is True
    assert _guard_fires(h, {"user_id": 7}, {"user_id": 7}) is True
    assert _guard_fires(h, {"caption": "${caption}"}, {"user_id": 7}) is True


def test_naming_the_subject_still_passes(tmp_path):
    h = _handler(_project(tmp_path, R125_REQUEST))
    assert _guard_fires(h, {"sound_id": 3}, {"sound_id": 3, "user_id": 7}) is False


def test_a_required_subject_keeps_the_full_guard(tmp_path):
    h = _handler(_project(tmp_path, dict(R125_REQUEST, sound_id="int")))
    assert "one of sound_id is required" in h
    assert "1202my" not in h


def test_no_request_schema_keeps_the_full_guard(tmp_path):
    h = _handler(_project(tmp_path, None))
    assert "one of sound_id is required" in h


def test_the_optional_markers_the_corpus_uses():
    for spec, want in (("str?", True), ("int", False),
                       ("string nullable references sounds.id", True),
                       ("integer references conversations.id not null", False),
                       ("int not nullable", False),
                       ({"required": False}, True), ({"type": "int?"}, True)):
        assert _declared_optional_1202my({"f": spec}, "f") is want, spec
    assert _declared_optional_1202my({}, "f") is False
    assert _declared_optional_1202my(None, "f") is False


def test_both_handler_generators_pass_the_contract():
    """The skeleton writes the main.py the run serves; the route projector fills gaps. Both call
    `_generate_handler`, and a guard fed by one of them only is #1202mg's shape again."""
    root = THIS_DIR.parent / "env_generator" / "llm_generator" / "multi_agent" / "runtime"
    for name in ("backend_skeleton.py", "route_projector.py"):
        tree = ast.parse((root / name).read_text(encoding="utf-8"))
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                 and getattr(n.func, "id", getattr(n.func, "attr", None)) == "_generate_handler"]
        assert calls, name
        for c in calls:
            assert "request_schema" in {k.arg for k in c.keywords}, (name, c.lineno)
