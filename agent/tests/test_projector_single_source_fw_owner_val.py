"""Audit rank-3 (single-source _fw_owner_val): the route projector injects a `guard` block
of by-construction deps before the first route. That block used to carry an UNCONDITIONAL
``def _fw_owner_val(...)`` — a SIMPLE version lacking the skeleton header's per-profile
sub-entity resolution + auto-create (#390/#391) and the #393/#394 typed fills. Because the
guard is inserted right before the first ``@app.<method>`` route (i.e. AFTER the header's
rich def), that unconditional re-def silently OVERRODE the canonical version and re-activated
the per-profile rating-404 bug on netflix-shaped apps. The fix wraps it in
``try: _fw_owner_val / except NameError:`` so the simple fallback is defined ONLY when
main.py has no _fw_owner_val (a raw-SQL / lane-authored main). This locks that in.
"""
import re

from env_generator.llm_generator.multi_agent.runtime.route_projector import (
    project_missing_routes)

_MAIN = '''"""app"""
from fastapi import Depends, FastAPI, HTTPException, Query
app = FastAPI()


def _fw_uid(user):
    return getattr(user, "id", user)


def _fw_owner_val(cls, col, user):
    # RICH_CANONICAL_MARKER — the header's per-profile sub-entity + auto-create version.
    return "RICH_CANONICAL"


@app.get("/health")
def health():
    return {"ok": True}
'''

_MODELS = '''from sqlalchemy import Column, Integer, String
from database import Base


class Note(Base):
    __tablename__ = "notes"
    id = Column(Integer, primary_key=True)
    title = Column(String)
    user_id = Column(Integer)
'''


def _project(tmp_path):
    be = tmp_path
    (be / "main.py").write_text(_MAIN, encoding="utf-8")
    (be / "models.py").write_text(_MODELS, encoding="utf-8")
    res = project_missing_routes(
        be, [{"method": "POST", "path": "/api/notes", "auth_required": True}])
    return res, (be / "main.py").read_text(encoding="utf-8")


def test_a_handler_is_projected(tmp_path):
    res, _ = _project(tmp_path)
    assert res.get("projected"), res  # guard is only emitted when block_info is non-empty


def test_guard_is_conditional_not_unconditional(tmp_path):
    _, patched = _project(tmp_path)
    # the fix: guarded form present …
    assert "except NameError:" in patched
    assert re.search(r"try:\n\s*_fw_owner_val", patched), patched
    # … and the OLD unconditional module-level re-def is gone
    assert "def _fw_owner_val(cls, col, user):  # noqa: F811" not in patched


def test_canonical_definition_is_preserved(tmp_path):
    _, patched = _project(tmp_path)
    assert "RICH_CANONICAL_MARKER" in patched  # header's rich version still in the file


def _extract_guard(patched):
    m = re.search(r"try:\n    _fw_owner_val.*?\n        return _v\n", patched, re.S)
    assert m, "could not extract the guarded _fw_owner_val block"
    return m.group(0)


def test_guard_skips_fallback_when_canonical_present(tmp_path):
    _, patched = _project(tmp_path)
    snippet = _extract_guard(patched)
    ns = {"_fw_uid": lambda u: u,
          "_fw_owner_val": lambda cls, col, user: "CANON_WINS"}
    exec(snippet, ns)
    # the try binds the existing name → the except never runs → canonical untouched
    assert ns["_fw_owner_val"](None, "x", 7) == "CANON_WINS"


def test_guard_defines_fallback_when_canonical_absent(tmp_path):
    _, patched = _project(tmp_path)
    snippet = _extract_guard(patched)
    ns = {"_fw_uid": lambda u: u}  # no pre-existing _fw_owner_val
    exec(snippet, ns)
    assert callable(ns["_fw_owner_val"])
    # a cls with no such column → the inner getattr raises → returns _fw_uid(user)
    assert ns["_fw_owner_val"](object(), "missing", 7) == 7


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
