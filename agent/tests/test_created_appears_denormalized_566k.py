r"""#566k (netflix r121): the read-back "created X is ABSENT from the list" was a FALSE POSITIVE. A
create returns the ENTRY id (POST /api/my-list -> {"item":{"id": <my_list row>}}), but the DENORMALIZED
list view keys items by the RELATED entity — GET /api/my-list returns titles (item `id` = title id) with
the entry id under a `my_list_id` alias. `_find_by_id` matched only on `id`, so a genuinely-persisted row
read as ABSENT (13 false advisories in r121 on a working app; NOT _fw_owner_val, NOT profile scoping).

Fix: `_find_by_id` also matches `new_id` against a resource-derived `<res>_id` alias (restricted to the
resource's own alias, so an unrelated FK equal to new_id can't false-match).
"""
from env_generator.llm_generator.multi_agent.runtime.test_user_validation import (
    _find_by_id, _created_appears,
)


def _p(items):
    return {"items": items}


def test_denormalized_list_entry_id_under_alias_is_found():
    # GET /api/my-list returns titles: item id = TITLE id, entry id under my_list_id
    items = [{"id": 5, "name": "T5", "my_list_id": 23},
             {"id": 8, "name": "T8", "my_list_id": 24}]
    ok, msg = _created_appears(_p(items), "my list", 23, None, res_key="my-list")
    assert ok, msg


def test_normal_list_still_matches_on_id():
    ok, _ = _created_appears(_p([{"id": 23, "name": "x"}]), "my list", 23, None, res_key="my-list")
    assert ok


def test_genuinely_absent_still_broken():
    items = [{"id": 5, "my_list_id": 99}]
    ok, msg = _created_appears(_p(items), "my list", 23, None, res_key="my-list")
    assert not ok and "ABSENT" in msg


def test_no_false_match_on_unrelated_fk():
    # item carries title_id == new_id but a DIFFERENT my_list_id → must NOT match (alias is my_list_id)
    items = [{"id": 5, "title_id": 23, "my_list_id": 99}]
    ok, _ = _created_appears(_p(items), "my list", 23, None, res_key="my-list")
    assert not ok, "an unrelated FK (title_id) must not be treated as the my-list entry alias"


def test_alias_is_type_tolerant():
    items = [{"id": 5, "continue_watching_id": "42"}]
    assert _find_by_id(items, 42, res_key="continue-watching") is not None


def test_deplural_alias_matches():
    # res_key 'profiles' → also try singular 'profile_id'
    assert _find_by_id([{"id": 5, "profile_id": 7}], 7, res_key="profiles") is not None


def test_without_res_key_only_matches_id():
    # backward-compatible: no res_key → only the id field is consulted
    assert _find_by_id([{"id": 5, "my_list_id": 23}], 23) is None
    assert _find_by_id([{"id": 23}], 23) is not None


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
