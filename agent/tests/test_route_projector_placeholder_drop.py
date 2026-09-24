"""Projected create/update handlers must DROP unresolved verification-chain placeholders
before constructing the ORM row (outlook run-14, 2026-06-30).

Live-proven root cause: the app exposed GET /api/calendars but NO POST /api/calendars, so a
verifier chain could never bind ${calendar_id}; it sent the LITERAL token in the POST /api/events
body, and the projected insert passed it to the INTEGER column:
    (psycopg.errors.InvalidTextRepresentation) invalid input syntax for type integer: "${calendar_id}"
→ 500 that wedged business_chain for 7 cycles → STUCK-ABORT. A minimal POST (no calendar_id)
returned 201, so dropping the unresolvable FK placeholder (nullable FK → null) fixes it by
construction. ENV-AGNOSTIC + LOCAL-ONLY (agent/tests/ gitignored).
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

_MODELS = '''
from sqlalchemy import Column, Integer, Text, DateTime, ForeignKey
from database import Base

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)

class Calendar(Base):
    __tablename__ = "calendars"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))

class Event(Base):
    __tablename__ = "events"
    id = Column(Integer, primary_key=True)
    calendar_id = Column(Integer, ForeignKey("calendars.id"))
    user_id = Column(Integer, ForeignKey("users.id"))
    title = Column(Text)
    start_at = Column(DateTime)
'''

_MAIN = '''
from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models import User, Calendar, Event

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


def _filter_line(handler_src: str) -> str:
    for ln in handler_src.splitlines():
        if "isidentifier()" in ln and "valid = {" in ln:
            return ln.strip()
    return ""


def test_post_handler_emits_placeholder_drop_filter(tmp_path):
    be = _backend(tmp_path)
    project_missing_routes(be, [{"method": "POST", "path": "/api/events"}])
    main_src = (be / "main.py").read_text(encoding="utf-8")
    ast.parse(main_src)  # projection stays valid python
    post = _handler_src(main_src, "POST", "/api/events")
    assert 'Event(**valid)' in post                    # still the create path
    assert _filter_line(post), "create handler must emit the placeholder-drop filter"
    assert 'v.startswith("${")' in post
    assert 'v[1:-1].isidentifier()' in post


def test_patch_handler_also_emits_filter(tmp_path):
    be = _backend(tmp_path)
    project_missing_routes(be, [{"method": "PATCH", "path": "/api/events/{eventId}"}])
    patch = _handler_src((be / "main.py").read_text(encoding="utf-8"),
                         "PATCH", "/api/events/{eventId}")
    assert _filter_line(patch), "update handler must also drop placeholders before setattr"


def test_generated_filter_drops_placeholders_keeps_real_values(tmp_path):
    """Exec the ACTUAL generated filter line — not a hand-copy — against a representative
    body: unresolved ${x}/{x_id} tokens dropped; real scalars, JSON strings, datetimes kept."""
    be = _backend(tmp_path)
    project_missing_routes(be, [{"method": "POST", "path": "/api/events"}])
    post = _handler_src((be / "main.py").read_text(encoding="utf-8"), "POST", "/api/events")
    line = _filter_line(post)
    assert line, "no filter line found"
    ns = {"valid": {
        "title": "Weekly Sync",              # real text — keep
        "calendar_id": "${calendar_id}",     # unresolved ${} FK — DROP (the run-14 500)
        "folder_id": "{folder_id}",          # unresolved bare-brace id — DROP
        "user_id": 7,                        # real int — keep
        "prefs": '{"a":1}',                 # legit JSON string value — keep
        "note": "{}",                       # empty braces, not a placeholder — keep
        "start_at": "2026-07-01T10:00:00",  # datetime string — keep
    }}
    exec(line, ns)
    out = ns["valid"]
    assert "calendar_id" not in out
    assert "folder_id" not in out
    assert out == {"title": "Weekly Sync", "user_id": 7,
                   "prefs": '{"a":1}', "note": "{}", "start_at": "2026-07-01T10:00:00"}


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
