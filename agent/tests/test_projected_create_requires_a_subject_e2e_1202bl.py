r"""#1202bl end to end: drive the real projector and read the handler it wrote.

The unit tests for this pin the EMISSION source in route_projector.py. This one runs the
projector over a contract shaped like netflix's and asserts the check reaches the
generated main.py — which is what r33 will actually execute. A syntax slip or a scoping
mistake in the emission would otherwise surface as a broken backend mid-run.

The shape under test is r32's, measured live:

    POST /api/continue-watching {}  ->  201  {"profile_id":28,"title_id":null}

`profile_id` is the owner FK, filled from the authenticated user, so requiring it would
reject every legitimate create. `title_id` is the SUBJECT, and a row without one means
nothing.
"""
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


class Title(Base):
    __tablename__ = "titles"
    id = Column(Integer, primary_key=True)
    name = Column(String)


class Profile(Base):
    __tablename__ = "profiles"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    name = Column(String)


class ContinueWatching(Base):
    __tablename__ = "continue_watching"
    id = Column(Integer, primary_key=True)
    profile_id = Column(Integer, ForeignKey("profiles.id"))
    title_id = Column(Integer, ForeignKey("titles.id"))
    progress_seconds = Column(Integer)
'''

_MAIN = '''
from fastapi import FastAPI, Depends, HTTPException
from database import get_db
from models import User, Title, Profile, ContinueWatching

app = FastAPI()
'''


def _project(tmp_path, eps):
    (tmp_path / "models.py").write_text(_MODELS, encoding="utf-8")
    (tmp_path / "main.py").write_text(_MAIN, encoding="utf-8")
    project_missing_routes(tmp_path, eps)
    return (tmp_path / "main.py").read_text(encoding="utf-8")


def _handler(src: str, needle: str) -> str:
    """Decorator line through the end of the function body.

    The first version stopped at the `def` immediately after the decorator and returned
    one line, which made two assertions look like real failures. A body has started only
    once a `def` has been seen.
    """
    lines = src.splitlines()
    for i, ln in enumerate(lines):
        if needle in ln:
            out, seen_def = [], False
            for j in range(i, len(lines)):
                cur = lines[j]
                if seen_def and (cur.startswith("@app.") or cur.startswith("def ")):
                    break
                if cur.startswith("def "):
                    seen_def = True
                out.append(cur)
            return "\n".join(out)
    return ""


def test_the_generated_main_still_parses(tmp_path):
    """The first thing a bad emission breaks, and the cheapest to catch."""
    src = _project(tmp_path, [{"method": "POST", "path": "/api/continue-watching"}])
    ast.parse(src)


def test_the_subject_check_reaches_the_generated_handler(tmp_path):
    src = _project(tmp_path, [{"method": "POST", "path": "/api/continue-watching"}])
    h = _handler(src, 'post("/api/continue-watching"')
    assert h, "the projector wrote no POST handler for the path"
    assert "title_id" in h, (
        "the create can still land a row with no subject — this is the r32 shape:\n" + h)
    assert "400" in h


def test_the_owner_fk_is_not_required(tmp_path):
    """profile_id is filled from the user; requiring it would reject every create."""
    src = _project(tmp_path, [{"method": "POST", "path": "/api/continue-watching"}])
    h = _handler(src, 'post("/api/continue-watching"')
    assert 'for _k in [\'profile_id\'' not in h
    assert "'profile_id', 'title_id'" not in h


def test_a_table_with_no_subject_fk_requires_some_field(tmp_path):
    """`POST /api/profiles {}` produced a nameless profile in r32."""
    src = _project(tmp_path, [{"method": "POST", "path": "/api/profiles"}])
    ast.parse(src)
    h = _handler(src, 'post("/api/profiles"')
    assert h, "the projector wrote no POST handler for /api/profiles"
    assert "if not valid:" in h, ("an empty create still lands a blank profile:\n" + h)
