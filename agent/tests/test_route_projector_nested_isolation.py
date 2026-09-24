"""route_projector: NESTED-resource isolation. When the PARENT table is per-user-private
(owner_scoped_reads), a nested route /api/projects/{id}/tasks must owner-check the parent —
else a user reaches another user's children via the nested path (smoke-proj 2026-06-29:
GET /api/projects/{otherId}/tasks → 200 leaked another user's tasks). The parent lookup
then filters by the parent's owner FK == user.id (a non-owned parent → None → 404).
Public parents (not owner-scoped) keep the open nested route (no regression).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.runtime.route_projector import project_missing_routes  # noqa: E402

_MODELS = '''
from sqlalchemy import Column, Integer, String, Text
from database import Base

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)

class Project(Base):
    __tablename__ = "projects"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer)
    name = Column(Text)

class Task(Base):
    __tablename__ = "tasks"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer)
    project_id = Column(Integer)
    title = Column(Text)
'''

_MAIN = '''
from fastapi import FastAPI, Depends, HTTPException
from database import get_db
from models import User, Project, Task

app = FastAPI()

def get_current_user():
    ...

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app)
'''

_NESTED_EPS = [
    {"method": "GET", "path": "/api/projects/{id}/tasks"},
    {"method": "POST", "path": "/api/projects/{id}/tasks"},
]


def _backend(tmp_path):
    (tmp_path / "models.py").write_text(_MODELS, encoding="utf-8")
    (tmp_path / "main.py").write_text(_MAIN, encoding="utf-8")
    return tmp_path


def _handler(main_src, method, path):
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


def test_nested_get_owner_checks_private_parent(tmp_path):
    be = _backend(tmp_path)
    project_missing_routes(be, _NESTED_EPS, owner_scoped_tables={"projects", "tasks"})
    src = (be / "main.py").read_text(encoding="utf-8")
    h = _handler(src, "GET", "/api/projects/{id}/tasks")
    # the parent lookup must owner-check the project (so another user's project → None → 404)
    assert 'getattr(Project, "user_id") == _fw_owner_val(Project, "user_id", user)' in h, h


def test_nested_post_owner_checks_private_parent(tmp_path):
    be = _backend(tmp_path)
    project_missing_routes(be, _NESTED_EPS, owner_scoped_tables={"projects", "tasks"})
    src = (be / "main.py").read_text(encoding="utf-8")
    h = _handler(src, "POST", "/api/projects/{id}/tasks")
    assert 'getattr(Project, "user_id") == _fw_owner_val(Project, "user_id", user)' in h, h


def test_nested_parent_open_when_parent_public(tmp_path):
    # parent NOT owner-scoped → nested route stays open (no regression for public feeds)
    be = _backend(tmp_path)
    project_missing_routes(be, _NESTED_EPS, owner_scoped_tables=set())
    src = (be / "main.py").read_text(encoding="utf-8")
    h = _handler(src, "GET", "/api/projects/{id}/tasks")
    assert "== user.id" not in h.split("rows =")[0], h   # no owner filter on the parent lookup


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
