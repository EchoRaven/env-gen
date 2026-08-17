r"""#577 (netflix r141, live cross-user WRITE): #566s emitted its ownership guard for the ONE
column `_owner_fk` returns, but a table can carry SEVERAL owner columns.

r141's `my_list` has BOTH `user_id` and `profile_id`. `_owner_fk` prefers the user-level one
(deliberately — `_OWNER_FK_NAMES` orders `profile_id` last so a user-level owner wins), so the
projected create guarded `user_id` and let `profile_id` through untouched:

    if valid.get("user_id") is not None and not _fw_owns(MyList, "user_id", …): 403
    valid.setdefault("user_id", _fw_owner_val(MyList, "user_id", user))
    # profile_id: unchecked

Chain `mylist_lifecycle_and_isolation` step [9]:

    POST /api/my-list  auth=tokenB  body={"profile_id": 10 (user A's), "title_id": 1}
                       expect [403, 404]  ->  201

The row landed in A's profile while `user_id` auto-filled to B. The LANE's own handler verified
it correctly (`_verify_profile_owned(db, body.get("profile_id"), uid)`), but writes stay
projected, so the safer handler never ran — the same displacement as #566y/#568, now on the
write path.

Fix: guard EVERY owner-shaped column the model has; auto-fill only the primary one.
"""
import ast

import pytest

from env_generator.llm_generator.multi_agent.runtime.route_projector import _generate_handler

# r141's shape: my_list carries BOTH owner columns.
_MODELS = {
    "users": {"cls": "User", "cols": ["id", "email"], "fks": {}},
    "profiles": {"cls": "Profile", "cols": ["id", "user_id", "name"],
                 "fks": {"user_id": "users"}},
    "my_list": {"cls": "MyList", "cols": ["id", "user_id", "profile_id", "title_id"],
                "fks": {"user_id": "users", "profile_id": "profiles", "title_id": "titles"}},
    "titles": {"cls": "Title", "cols": ["id", "name"], "fks": {}},
    # single-owner control
    "notes": {"cls": "Note", "cols": ["id", "user_id", "body"], "fks": {"user_id": "users"}},
}


def _create(table_path, idx=1):
    return _generate_handler("POST", table_path, True, _MODELS, idx)


def test_r141_both_owner_columns_are_guarded():
    src = _create("/api/my-list")
    assert '_fw_owns(MyList, "user_id"' in src, src
    assert '_fw_owns(MyList, "profile_id"' in src, "the r141 leak: profile_id was unchecked"
    assert src.count("does not belong to the caller") == 2, src


def test_only_the_primary_owner_is_auto_filled():
    """Auto-filling BOTH would invent a profile for a caller who did not ask for one."""
    src = _create("/api/my-list")
    assert src.count("valid.setdefault(") == 1, src
    assert 'valid.setdefault("user_id", _fw_owner_val(MyList, "user_id", user))' in src


def test_a_single_owner_table_is_unchanged():
    src = _create("/api/notes", idx=2)
    assert src.count("_fw_owns(Note,") == 1
    assert '_fw_owns(Note, "user_id"' in src
    assert src.count("valid.setdefault(") == 1


def test_a_subject_fk_is_never_guarded_as_an_owner():
    """`title_id` points at a shared catalog — guarding it would 403 every legitimate write."""
    src = _create("/api/my-list")
    assert '_fw_owns(MyList, "title_id"' not in src


def test_an_ownerless_table_gets_no_guard():
    src = _generate_handler("POST", "/api/titles", True, _MODELS, 3)
    assert "_fw_owns(" not in src


def test_unauthenticated_creates_are_untouched():
    src = _generate_handler("POST", "/api/my-list", False, _MODELS, 4)
    assert "_fw_owns(" not in src


def test_every_emitted_shape_still_parses():
    for i, (m, p, auth) in enumerate([("POST", "/api/my-list", True),
                                      ("POST", "/api/notes", True),
                                      ("POST", "/api/titles", True),
                                      ("POST", "/api/my-list", False),
                                      ("GET", "/api/my-list", True)]):
        ast.parse(_generate_handler(m, p, auth, _MODELS, 200 + i))


def test_rendered_main_compiles():
    import py_compile
    import tempfile
    from env_generator.llm_generator.multi_agent.runtime.backend_skeleton import (
        render_skeleton_main)
    tables = {
        "users": {"columns": [{"name": "id", "type": "serial", "primary_key": True},
                              {"name": "email", "type": "text"}]},
        "profiles": {"columns": [{"name": "id", "type": "serial", "primary_key": True},
                                 {"name": "user_id", "type": "int",
                                  "references": "users.id"}]},
        "my_list": {"columns": [{"name": "id", "type": "serial", "primary_key": True},
                                {"name": "user_id", "type": "int", "references": "users.id"},
                                {"name": "profile_id", "type": "int",
                                 "references": "profiles.id"},
                                {"name": "title_id", "type": "int",
                                 "references": "titles.id"}]},
        "titles": {"columns": [{"name": "id", "type": "serial", "primary_key": True}]},
    }
    src = render_skeleton_main(tables=tables, endpoints=[
        {"method": "POST", "path": "/api/my-list", "auth_required": True},
        {"method": "GET", "path": "/api/my-list", "auth_required": True}])
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as fh:
        fh.write(src)
        path = fh.name
    py_compile.compile(path, doraise=True)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
