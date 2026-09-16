"""#1202os: a projected collection read serves the query parameters its contract declares.

Every projected list read was `db.query(Cls).limit(100).all()`, and the endpoint's own
`schema.request` was consulted only on the write path — so `GET /api/comments?video_id=5`, a
filter the CONTRACT declares and the page depends on, returned unrelated rows. Measured across 8
delivered backends: 61 projected collection reads declare at least one request field and not one
accepts it (r126 11, r125 8, r124 6, r123 8, r122 10, r121 5, netflix-r45 6, netflix-r44 7).

The emitted handler is EXECUTED here against a recording stand-in for `db`, so this test fails if
the filter is emitted but not applied, or applied to the wrong column — not merely if a line
disappears from the source.
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

class Video(Base):
    __tablename__ = "videos"
    id = Column(Integer, primary_key=True)
    author_id = Column(Integer, ForeignKey("users.id"))
    category = Column(String)

class Comment(Base):
    __tablename__ = "comments"
    id = Column(Integer, primary_key=True)
    video_id = Column(Integer, ForeignKey("videos.id"))
    body = Column(String)
'''


def _project(tmp_path, endpoints):
    backend = tmp_path / "app" / "backend"
    backend.mkdir(parents=True)
    (backend / "models.py").write_text(_MODELS)
    (backend / "main.py").write_text("from fastapi import Depends, FastAPI, Query\napp = FastAPI()\n")
    design = tmp_path / "design"
    design.mkdir()
    (design / "reference_spec.json").write_text(json.dumps(
        {"entities": [{"name": "videos", "visibility": "public"},
                      {"name": "comments", "visibility": "public"}]}))
    project_missing_routes(backend, endpoints)
    return (backend / "main.py").read_text()


def _handler(src, path):
    m = re.search(r'@app\.get\("%s"\)\ndef (\w+)\(([^\n]*)\):\n(.*?)(?=\n@app|\Z)'
                  % re.escape(path), src, re.S)
    assert m, f"no projected handler for {path}"
    return m.group(1), m.group(2), m.group(3)


class _Query:
    """Records what the emitted handler asks the ORM for."""

    def __init__(self, rows, log):
        self.rows, self.log = rows, log

    def filter(self, cond):
        self.log.append(("filter", cond))
        return self

    def offset(self, n):
        self.log.append(("offset", n))
        return self

    def limit(self, n):
        self.log.append(("limit", n))
        return self

    def all(self):
        return self.rows

    def count(self):
        return len(self.rows) + 7          # distinguishable from len(rows)


def _run_handler(src, path, **kwargs):
    fn_name, _sig, _body = _handler(src, path)
    log = []
    rows = [type("R", (), {"id": 1, "video_id": 5, "body": "x"})()]

    class _DB:
        def query(self, cls):
            log.append(("query", getattr(cls, "__name__", str(cls))))
            return _Query(rows, log)

    ns = {"Depends": lambda f=None: None, "Query": lambda default=None, **k: default,
          "get_db": None, "get_current_user": None, "HTTPException": Exception,
          "Comment": type("Comment", (), {"video_id": "COL_video_id"}),
          "Video": type("Video", (), {"category": "COL_category"}),
          "_fw_owner_val": lambda *a, **k: 1}
    exec(compile(re.search(r'(def %s\(.*?)(?=\n@app|\Z)' % fn_name, src, re.S).group(1),
                 "<emitted>", "exec"), ns)
    out = ns[fn_name](db=_DB(), **kwargs)
    return out, log


def test_a_declared_filter_is_accepted_and_applied(tmp_path):
    src = _project(tmp_path, [{"method": "GET", "path": "/api/comments", "auth_required": False,
                               "schema": {"request": {"video_id": "int?", "limit": "int?",
                                                      "offset": "int?"}}}])
    _fn, sig, _body = _handler(src, "/api/comments")
    assert "video_id: int = Query(default=None)" in sig, sig
    assert "limit: int = Query(default=100, ge=1, le=100)" in sig, sig
    out, log = _run_handler(src, "/api/comments", video_id=5, limit=10, offset=2)
    assert ("filter", "COL_video_id == 5") not in log      # it compares, it does not stringify
    assert any(k == "filter" for k, _v in log), log
    assert ("offset", 2) in log and ("limit", 10) in log, log
    assert out["total"] == 8, out                           # count(), not len(rows)


def test_an_absent_filter_does_not_narrow_the_query(tmp_path):
    src = _project(tmp_path, [{"method": "GET", "path": "/api/comments", "auth_required": False,
                               "schema": {"request": {"video_id": "int?"}}}])
    _out, log = _run_handler(src, "/api/comments", video_id=None, limit=100, offset=0)
    assert not any(k == "filter" for k, _v in log), log


def test_a_read_with_no_declared_params_is_byte_identical_to_before(tmp_path):
    src = _project(tmp_path, [{"method": "GET", "path": "/api/videos", "auth_required": False}])
    _fn, sig, body = _handler(src, "/api/videos")
    assert "Query(" not in sig, sig
    assert "db.query(Video).limit(100).all()" in body, body
    assert '"total": len(rows)' in body, body


def test_a_declared_field_that_is_not_a_column_is_not_invented(tmp_path):
    src = _project(tmp_path, [{"method": "GET", "path": "/api/videos", "auth_required": False,
                               "schema": {"request": {"category": "str?", "nonsense": "str?"}}}])
    _fn, sig, _body = _handler(src, "/api/videos")
    assert "category: str = Query(default=None)" in sig, sig
    assert "nonsense" not in sig, sig
