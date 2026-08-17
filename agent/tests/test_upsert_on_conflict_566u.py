r"""#566u (netflix r129): an owner-scoped STATE-WRITE (rating/my_list/continue_watching) re-created with the
same (owner, subject) natural key hit a UNIQUE constraint -> 409 "duplicate resource", flapping
business_chain (a re-rating must UPSERT, not 409). Fix: the projected POST create, on IntegrityError,
calls _fw_upsert_on_conflict(db, cls, valid, user, owner_fk, subject_fks) which loads the caller's existing
row by owner_fk + subject FKs and UPDATEs it (idempotent), returning it; None -> re-raise (409). Reactive
(only after a real conflict) + owner+subject match -> a non-unique/non-state-write resource is never
wrongly upserted.
"""
import py_compile
import tempfile
import os

from env_generator.llm_generator.multi_agent.runtime.route_projector import _generate_handler
from env_generator.llm_generator.multi_agent.runtime.backend_skeleton import render_skeleton_main

_MODELS = {
    "users": {"cls": "User", "cols": ["id"], "fks": {}, "types": {}, "required": []},
    "profiles": {"cls": "Profile", "cols": ["id", "user_id"], "fks": {"user_id": "users"},
                 "types": {}, "required": ["user_id"]},
    "ratings": {"cls": "Rating", "cols": ["id", "profile_id", "title_id", "value"],
                "fks": {"profile_id": "profiles", "title_id": "titles"}, "types": {},
                "required": ["profile_id", "title_id", "value"]},
    "titles": {"cls": "Title", "cols": ["id"], "fks": {}, "types": {}, "required": []},
}


def test_upsert_wired_into_owner_scoped_create():
    blk = _generate_handler("POST", "/api/titles/{id}/rating", True, _MODELS, 0)
    assert "_fw_upsert_on_conflict(db, Rating, valid, user," in blk, blk
    # the natural key = owner (profile_id) + subject (title_id)
    call = blk.split("_fw_upsert_on_conflict", 1)[1].split("\n", 1)[0]
    assert '"profile_id"' in call and "'title_id'" in call, call
    # it lives in the IntegrityError branch (before the re-raise)
    assert "except IntegrityError:" in blk and "_uc is not None" in blk


def test_non_owner_create_has_no_upsert():
    # a top-level resource with NO owner FK must not get the state-write upsert
    blk = _generate_handler("POST", "/api/titles", True, _MODELS, 1)
    assert "_fw_upsert_on_conflict" not in blk, blk


def test_emitted_block_compiles():
    blk = _generate_handler("POST", "/api/titles/{id}/rating", True, _MODELS, 0)
    mod = ("from fastapi import HTTPException, Depends\n"
           "from sqlalchemy.exc import IntegrityError, DataError\n"
           "def get_db(): ...\ndef get_current_user(): ...\n"
           "class Rating: ...\nclass Title: ...\n"
           "def _coerce_body(c, v): return v\n"
           "def _fw_owns(c, co, v, u): return True\n"
           "def _fw_owner_val(c, co, u): return 1\n"
           "def _fw_fill_required_defaults(c, v, d): return v\n"
           "def _fw_upsert_on_conflict(*a): return None\n" + blk + "\n")
    p = os.path.join(tempfile.mkdtemp(), "h.py")
    open(p, "w").write(mod)
    py_compile.compile(p, doraise=True)


def test_rendered_main_defines_helper_and_compiles():
    tables = {
        "users": {"columns": [{"name": "id", "type": "Integer", "primary_key": True}]},
        "profiles": {"columns": [{"name": "id", "type": "Integer", "primary_key": True},
                                 {"name": "user_id", "type": "Integer", "foreign_key": "users.id"}]},
        "ratings": {"columns": [{"name": "id", "type": "Integer", "primary_key": True},
                                {"name": "profile_id", "type": "Integer", "foreign_key": "profiles.id"},
                                {"name": "title_id", "type": "Integer", "foreign_key": "titles.id"},
                                {"name": "value", "type": "String"}]},
        "titles": {"columns": [{"name": "id", "type": "Integer", "primary_key": True}]},
    }
    src = render_skeleton_main([{"method": "POST", "path": "/api/titles/{id}/rating", "auth_required": True}], tables)
    assert "def _fw_upsert_on_conflict(" in src
    p = os.path.join(tempfile.mkdtemp(), "main.py")
    open(p, "w").write(src)
    py_compile.compile(p, doraise=True)


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
