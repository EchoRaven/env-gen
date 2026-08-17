r"""#566t (netflix r128): a create body that DROPPED a NOT-NULL column (verifier authored the wrong key,
e.g. {"rating":"thumbs_up"} instead of {"value":"up"}) INSERTs NULL → 400 even when the column has a DB
DEFAULT (SQLAlchemy emits an explicit NULL for the unset non-null column, so the DB default never fires).
Fix: the projected POST create handler calls _fw_fill_required_defaults(cls, valid, db), which applies the
column's DB default (information_schema) for any absent NOT-NULL no-model-default column.
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
    "ratings": {"cls": "Rating", "cols": ["id", "profile_id", "value"],
                "fks": {"profile_id": "profiles"}, "types": {}, "required": ["profile_id", "value"]},
}


def test_fill_wired_into_post_create_only():
    post = _generate_handler("POST", "/api/titles/{id}/rating", True, _MODELS, 0)
    assert "_fw_fill_required_defaults(Rating, valid, db)" in post, post
    # GET handlers must NOT call the create-only fill
    get = _generate_handler("GET", "/api/ratings", True, _MODELS, 1)
    assert "_fw_fill_required_defaults" not in get, get


def test_fill_runs_after_coerce_body():
    post = _generate_handler("POST", "/api/titles/{id}/rating", True, _MODELS, 0)
    i_coerce = post.find("_coerce_body(")
    i_fill = post.find("_fw_fill_required_defaults(")
    assert i_coerce != -1 and i_fill != -1 and i_fill > i_coerce, "fill must run after _coerce_body"


def test_rendered_main_defines_helper_and_compiles():
    tables = {
        "users": {"columns": [{"name": "id", "type": "Integer", "primary_key": True}]},
        "profiles": {"columns": [{"name": "id", "type": "Integer", "primary_key": True},
                                 {"name": "user_id", "type": "Integer", "foreign_key": "users.id"}]},
        "ratings": {"columns": [{"name": "id", "type": "Integer", "primary_key": True},
                                {"name": "profile_id", "type": "Integer", "foreign_key": "profiles.id"},
                                {"name": "value", "type": "String"}]},
    }
    src = render_skeleton_main([{"method": "POST", "path": "/api/ratings", "auth_required": True}], tables)
    assert "def _fw_fill_required_defaults(" in src
    p = os.path.join(tempfile.mkdtemp(), "main.py")
    open(p, "w").write(src)
    py_compile.compile(p, doraise=True)


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
