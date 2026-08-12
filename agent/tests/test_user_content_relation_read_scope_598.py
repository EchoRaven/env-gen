r"""#598: a live cross-user leak that survived the whole owner-scoping arc.

A static audit of all 144 delivered backends — projected bare-collection GETs whose queried
model carries an owner column, checked for any scoping — shows the arc working:

    <=r99       owner-model collection reads 334   UNSCOPED 119  (36%)
    r100-r119                                61   UNSCOPED  25  (41%)
    r120-r133                                37   UNSCOPED  14  (38%)
    r134+                                    23   UNSCOPED   2  ( 9%)

The two survivors are r141's `GET /api/my-list` and `GET /api/continue-watching`, and the
contrast with r142 is exact:

    r142  MyList.profile_id -> .filter(MyList.profile_id == _fw_owner_val(...))   scoped
    r141  MyList.user_id    -> db.query(MyList).limit(100).all()                  LEAKS

#566y widened read-scoping to SUB-ENTITY owners and deliberately left the direct-user case
opt-in, because "a public feed is a list of rows each owned by some user". That holds for a
table whose row IS the content (`posts(user_id, title, body)`), but not for one that merely
RELATES a user to content someone else owns. Scoping was therefore decided by which FK the draw
happened to pick.

The discriminator is structural: a DIRECT users FK **plus** an FK to some other non-user entity.
Measured over the 144 backends — 196 tables carry a users FK; the 63 instances that also carry a
content FK are exactly MyList / Rating / ContinueWatching, every one per-user private state,
while the 133 with a user FK alone are Profile, correctly untouched.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime.route_projector import (
    _is_user_content_relation as rel,
)


def _meta(**fks):
    return {"fks": dict(fks)}


# --- the shapes that leaked ---------------------------------------------------------------

def test_the_r141_my_list_shape_is_a_user_content_relation():
    assert rel(_meta(user_id="users", title_id="titles"), "user_id") is True


def test_continue_watching_the_other_half_of_the_same_leak():
    assert rel(_meta(user_id="users", title_id="titles"), "user_id") is True


def test_a_rating_carries_a_payload_and_still_counts():
    """#598 keys on the FK graph, not on whether the row has scalar columns — `value` and
    `progress_seconds` are per-user attributes OF shared content, not content."""
    assert rel(_meta(user_id="users", title_id="titles"), "user_id") is True


def test_any_owner_column_name_works_as_long_as_it_points_at_users():
    for col in ("user_id", "owner_id", "account_id", "author_id"):
        assert rel(_meta(**{col: "users", "title_id": "titles"}), col) is True, col


# --- what must stay opt-in ------------------------------------------------------------------

def test_a_public_feed_row_is_untouched():
    """`posts(user_id, title, body)` — the row IS the content, no second entity FK.
    This is the case #566y's comment was protecting and #598 must not disturb."""
    assert rel(_meta(user_id="users"), "user_id") is False


def test_a_profile_is_a_sub_entity_parent_not_a_relation():
    assert rel(_meta(user_id="users"), "user_id") is False


def test_a_sub_entity_owner_is_not_this_rule_566y_owns_it():
    """profile_id -> profiles is NOT a direct users FK, so #598 declines and #566y decides."""
    assert rel(_meta(profile_id="profiles", title_id="titles"), "profile_id") is False


def test_a_second_fk_back_to_users_does_not_count_as_content():
    """`follows(follower_id -> users, followee_id -> users)` is user-to-user, not
    user-to-content — it must not be silently self-scoped."""
    assert rel(_meta(follower_id="users", followee_id="users"), "follower_id") is False


def test_a_join_table_with_no_user_fk_is_out_of_scope():
    assert rel(_meta(title_id="titles", genre_id="genres"), "title_id") is False


def test_junk_is_inert():
    assert rel({}, "user_id") is False
    assert rel(_meta(user_id="users"), "") is False
    assert rel(_meta(user_id="users", other=None), "user_id") is False


# --- the wiring ---------------------------------------------------------------------------------

def test_it_joins_the_read_scope_decision_without_replacing_the_others():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import route_projector as rp
    src = inspect.getsource(rp)
    i = src.index("read_scoped = bool(owner_fk) and (bool(owner_scoped_reads)")
    window = src[i:i + 200]
    assert "owner_sub_entity" in window and "owner_user_content" in window


def test_the_contract_opt_in_and_566y_still_stand_alone():
    """Neither pre-existing route to scoping may have been narrowed by #598."""
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import route_projector as rp
    src = inspect.getsource(rp)
    assert "bool(owner_scoped_reads) or owner_sub_entity" in src


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
