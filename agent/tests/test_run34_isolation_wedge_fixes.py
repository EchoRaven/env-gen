"""run-34 STUCK-abort forensics → router-prologue repair + skeleton owner-scope union
(2026-07-02).

run-34 died on business_chain isolation probes: the lane's custom_routes.py used
``@router.get`` without ever defining ``router`` → NameError at import → main.py's include
swallowed it → the lane's properly OWNER-SCOPED reads vanished → the projected by-id GET
(UNSCOPED, because render_skeleton_main only reads table METADATA and the chain-probe union
applied only to project_missing_routes fill-ins) leaked cross-user rows → isolation probes
failed 7 cycles → STUCK. Two fixes:
- repair_custom_routes_router_prologue: mechanical missing-prologue insert.
- generate_backend_skeleton unions chain-probed tables into metadata before rendering, so
  the FULL skeleton emits owner-scoped reads for isolation-probed tables.
ENV-AGNOSTIC + LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.backend_scaffold import repair_custom_routes_router_prologue  # noqa: E402
from multi_agent.runtime.backend_skeleton import render_skeleton_main  # noqa: E402


_RUN34_SHAPE = (
    "from fastapi import Depends, HTTPException\n"
    "from sqlalchemy.orm import Session\n"
    "\n"
    '@router.get("/api/events/{eventId}")\n'
    "def get_event(eventId: int, db: Session = Depends(get_db)):\n"
    "    return {}\n"
)


def test_missing_router_prologue_inserted_and_compiles(tmp_path):
    p = tmp_path / "custom_routes.py"
    p.write_text(_RUN34_SHAPE, encoding="utf-8")
    out = repair_custom_routes_router_prologue(tmp_path)
    assert out["repaired"] is True
    src = p.read_text(encoding="utf-8")
    assert "router = APIRouter()" in src
    compile(src, "custom_routes.py", "exec")
    # the prologue lands AFTER the imports and BEFORE first @router use
    assert src.index("router = APIRouter()") < src.index("@router.get")
    # idempotent
    assert repair_custom_routes_router_prologue(tmp_path)["repaired"] is False


def test_defined_router_untouched(tmp_path):
    body = "from fastapi import APIRouter\nrouter = APIRouter()\n\n@router.get('/x')\ndef x():\n    return {}\n"
    (tmp_path / "custom_routes.py").write_text(body, encoding="utf-8")
    assert repair_custom_routes_router_prologue(tmp_path)["repaired"] is False
    assert (tmp_path / "custom_routes.py").read_text(encoding="utf-8") == body


def test_no_router_usage_untouched(tmp_path):
    body = "def helper():\n    return 1\n"
    (tmp_path / "custom_routes.py").write_text(body, encoding="utf-8")
    assert repair_custom_routes_router_prologue(tmp_path)["repaired"] is False


def test_metadata_owner_scope_reaches_rendered_handler():
    """The exact run-34 gap: with owner_scoped_reads metadata set (as the scaffolder
    union now does for chain-probed tables), the rendered by-id GET filters by owner."""
    tables = {
        "users": {"columns": [{"name": "id", "type": "integer", "primary_key": True},
                              {"name": "email", "type": "text"}]},
        "events": {"columns": [{"name": "id", "type": "integer", "primary_key": True},
                               {"name": "user_id", "type": "integer", "foreign_key": "users.id"},
                               {"name": "title", "type": "text"}],
                   "metadata": {"owner_scoped_reads": True}},
    }
    endpoints = [{"method": "GET", "path": "/api/events/{eventId}"},
                 {"method": "GET", "path": "/api/events"}]
    src = render_skeleton_main(endpoints, tables)
    compile(src, "main.py", "exec")
    # the by-id GET handler body must carry an owner filter, not a bare db.get
    get_block = src.split('@app.get("/api/events/{eventId}")')[1].split("@app.")[0]
    assert "user" in get_block and ("user_id" in get_block or "owner" in get_block), get_block


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
