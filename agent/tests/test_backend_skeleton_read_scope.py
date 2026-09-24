"""backend_skeleton (the PRIMARY main.py generator) must apply the per-table
owner_scoped_reads signal identically to route_projector + heal_pipeline.

It runs FIRST, so if it emitted an unscoped read the delivery-time projector would
see the route already present and skip its scoped re-projection — exactly the leak
observed live on smoke-notes-exp3 (the `notes` table was flagged owner_scoped_reads
in the contract, yet the projected GET /api/notes/{id} had no owner check). Both
projection sites must honour the contract flag.
"""

import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.backend_skeleton import render_skeleton_main  # noqa: E402


def _tables(private: bool):
    return {
        "users": {"schema": {"columns": [
            {"name": "id", "type": "serial", "primary_key": True},
            {"name": "username", "type": "text", "unique": True},
        ]}},
        "notes": {
            "schema": {"columns": [
                {"name": "id", "type": "serial", "primary_key": True},
                {"name": "user_id", "type": "integer", "fk": "users.id"},
                {"name": "title", "type": "text"},
                {"name": "body", "type": "text"},
            ]},
            # the contract signal — set by kickoff for per-user-private tables
            "metadata": {"owner_scoped_reads": True} if private else {},
        },
    }


_ENDPOINTS = [
    {"method": "GET", "path": "/api/notes", "auth_required": True,
     "schema": {"response_key": "items"}},
    {"method": "GET", "path": "/api/notes/{id}", "auth_required": True,
     "schema": {"response_key": "item"}},
    {"method": "PUT", "path": "/api/notes/{id}", "auth_required": True},
    {"method": "DELETE", "path": "/api/notes/{id}", "auth_required": True},
]


def _handler(main_src: str, method: str, path: str) -> str:
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


def test_skeleton_scopes_private_table_reads():
    main = render_skeleton_main(_ENDPOINTS, _tables(private=True))
    import ast as _ast
    _ast.parse(main)
    byid = _handler(main, "GET", "/api/notes/{id}")
    coll = _handler(main, "GET", "/api/notes")
    # #134: the owner value is coerced to the column type via _fw_owner_val (was bare user.id)
    assert 'getattr(obj, "user_id", None) != _fw_owner_val(type(obj), "user_id", user)' in byid  # by-id read scoped
    assert 'getattr(Note, "user_id") == _fw_owner_val(Note, "user_id", user)' in coll             # collection scoped


def test_skeleton_leaves_public_table_reads_open():
    main = render_skeleton_main(_ENDPOINTS, _tables(private=False))
    byid = _handler(main, "GET", "/api/notes/{id}")
    coll = _handler(main, "GET", "/api/notes")
    assert "!= user.id" not in byid                              # open (default)
    assert "== user.id" not in coll


def test_skeleton_writes_still_scoped_regardless():
    # write authz is independent of the read flag (owner FK present)
    main = render_skeleton_main(_ENDPOINTS, _tables(private=False))
    dele = _handler(main, "DELETE", "/api/notes/{id}")
    assert 'getattr(obj, "user_id", None) != _fw_owner_val(type(obj), "user_id", user)' in dele


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
