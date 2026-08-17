r"""#566s (netflix r127 cross-user IDOR): owner-scoped create handlers trusted a client-supplied owner
sub-entity FK (body `profile_id`) without verifying ownership → userB could POST a rating/my-list under
userA's profile (r127 main.py:1046 `valid.setdefault("profile_id", _fw_owner_val(...))` — setdefault
no-ops when the body already carries a bound foreign profile_id). Fix: the projected create emitters now
REJECT (403) a body owner-FK the caller does not own (via `_fw_owns`), while honoring a caller's OWN
non-default profile (multi-profile) and resolving the caller's own when absent.
"""
import py_compile
import tempfile
import os

from env_generator.llm_generator.multi_agent.runtime.route_projector import (
    _generate_handler, _owner_fk, _resource_model,
)
from env_generator.llm_generator.multi_agent.runtime.backend_skeleton import render_skeleton_main

# internal models format (as _orm_models / _models_meta emit): fks = {col: target_table}
_MODELS = {
    "users": {"cls": "User", "cols": ["id", "email"], "fks": {}, "types": {}, "required": []},
    "profiles": {"cls": "Profile", "cols": ["id", "user_id", "name"],
                 "fks": {"user_id": "users"}, "types": {}, "required": ["user_id"]},
    "ratings": {"cls": "Rating", "cols": ["id", "profile_id", "title_id", "value"],
                "fks": {"profile_id": "profiles", "title_id": "titles"}, "types": {},
                "required": ["profile_id", "title_id", "value"]},
    "titles": {"cls": "Title", "cols": ["id", "name"], "fks": {}, "types": {}, "required": []},
}


def test_owner_fk_resolves_to_sub_entity():
    assert _resource_model("/api/titles/{id}/rating", _MODELS)[0] == "ratings"
    assert _owner_fk(_MODELS["ratings"]) == "profile_id"


def test_create_handler_rejects_foreign_owner_fk():
    block = _generate_handler("POST", "/api/titles/{id}/rating", True, _MODELS, 0)
    # the IDOR guard: a body profile_id not owned by the caller → 403
    assert '_fw_owns(Rating, "profile_id"' in block, block
    assert 'status_code=403' in block and "does not belong to the caller" in block, block
    # still honors an OWNED body value / resolves own when absent (multi-profile)
    assert 'valid.setdefault("profile_id", _fw_owner_val(Rating, "profile_id", user))' in block, block


def test_emitted_handler_block_compiles():
    block = _generate_handler("POST", "/api/titles/{id}/rating", True, _MODELS, 0)
    # wrap with the names the handler references so it parses as a module
    module = (
        "from fastapi import HTTPException, Depends\n"
        "def get_db(): ...\n"
        "def get_current_user(): ...\n"
        "class Rating: ...\n"
        "def _coerce_body(cls, v): return v\n"
        "def _fw_owns(cls, col, val, user): return True\n"
        "def _fw_owner_val(cls, col, user): return 1\n"
        + block + "\n"
    )
    p = os.path.join(tempfile.mkdtemp(), "h.py")
    open(p, "w").write(module)
    py_compile.compile(p, doraise=True)   # raises on any syntax error in the emitted block


def test_rendered_main_defines_fw_owns_and_compiles():
    tables = {
        "users": {"columns": [{"name": "id", "type": "Integer", "primary_key": True},
                              {"name": "email", "type": "String"}]},
        "profiles": {"columns": [{"name": "id", "type": "Integer", "primary_key": True},
                                 {"name": "user_id", "type": "Integer", "foreign_key": "users.id"},
                                 {"name": "name", "type": "String"}]},
        "ratings": {"columns": [{"name": "id", "type": "Integer", "primary_key": True},
                                {"name": "profile_id", "type": "Integer", "foreign_key": "profiles.id"},
                                {"name": "value", "type": "Integer"}]},
    }
    endpoints = [{"method": "POST", "path": "/api/ratings", "auth_required": True}]
    src = render_skeleton_main(endpoints, tables)
    assert "def _fw_owns(" in src
    p = os.path.join(tempfile.mkdtemp(), "main.py")
    open(p, "w").write(src)
    py_compile.compile(p, doraise=True)
    # the projected create for the owner-scoped resource carries the IDOR guard
    assert "_fw_owns(" in src.split("def _fw_owns(", 1)[1], "expected a _fw_owns CALL site in a handler"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
