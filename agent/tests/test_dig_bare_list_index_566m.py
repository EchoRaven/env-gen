r"""#566m (netflix r123 business_chain "profile IDOR"): profile-scoped chain steps read
GET /api/continue-watching?profile_id=${pid} but ${pid} resolved to a FOREIGN id (1) → 403
("profile does not belong to caller"). Root cause: the verifier-authored save {"pid": "0.id"} against
GET /api/profiles, but that endpoint ships a BARE list (`[ {id,...} ]`, not `{items:[...]}`), and
chain_executor._dig couldn't resolve a numeric index against a bare list (nor strip a wrong "items."
prefix) → pid unbound → fell back to a foreign id → 403.

Fix: _dig/_dig_path resolve numeric indices into bare lists AND {items|data|results|rows} envelopes,
and _dig progressively strips wrong leading path segments.
"""
from env_generator.llm_generator.multi_agent.runtime import chain_executor as ce


def test_numeric_index_on_bare_list():
    bare = [{"id": 47, "name": "Me"}, {"id": 48}]
    assert ce._dig(bare, "0.id") == 47      # the r123 profile-IDOR root: "0.id" on a bare list
    assert ce._dig(bare, "1.id") == 48
    assert ce._dig(bare, "-1.id") == 48     # negative index


def test_strip_wrong_items_prefix_on_bare_list():
    bare = [{"id": 47}]
    assert ce._dig(bare, "items.0.id") == 47   # verifier assumed an envelope; strip "items."


def test_numeric_index_on_envelope():
    env = {"items": [{"id": 47}], "total": 1}
    assert ce._dig(env, "0.id") == 47
    assert ce._dig(env, "items.0.id") == 47
    assert ce._dig(env, "id") == 47            # leaf via envelope descent (pre-existing)
    for k in ("data", "results", "rows"):
        assert ce._dig({k: [{"id": 9}]}, "0.id") == 9


def test_out_of_range_index_is_none_not_wrong_row():
    assert ce._dig([{"id": 1}], "2.id") is None   # safe: no false bind
    assert ce._dig({"items": []}, "0.id") is None


def test_existing_paths_unregressed():
    assert ce._dig({"item": {"id": 5}}, "id") == 5
    assert ce._dig({"item": {"id": 5}}, "item.id") == 5
    assert ce._dig({"a": {"b": 2}}, "a.b") == 2
    assert ce._dig({"id": 3}, "id") == 3
    assert ce._dig({"note": {"id": 7}}, "note.id") == 7
    assert ce._dig({"x": 1}, "missing") is None


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
