"""N-P0-2: per-profile owner FK recognition (netflix ratings/my_list/continue_watching).

The projected create handler injects the owner FK from the caller, but only for columns
_owner_fk() recognizes. `profile_id` wasn't recognized → ratings insert left it NULL →
NOT-NULL violation → business_chain failed. profile_id is now an owner FK (last, so a
user-level owner still wins when both exist); the VALUE is resolved to the caller's
profile by backend _fw_owner_val (DB-dependent, validated on a live run).
"""
from env_generator.llm_generator.multi_agent.runtime.route_projector import _owner_fk

def _m(cols, fks): return {"cols": cols, "fks": fks}

def test_profile_owned_table():
    assert _owner_fk(_m(["id","profile_id","title_id","value"],
                        {"profile_id":"profiles","title_id":"titles"})) == "profile_id"

def test_user_owner_still_wins_over_profile():
    assert _owner_fk(_m(["id","user_id","profile_id"],
                        {"user_id":"users","profile_id":"profiles"})) == "user_id"

def test_plain_user_owned_unregressed():
    assert _owner_fk(_m(["id","user_id","caption"], {"user_id":"users"})) == "user_id"

def test_fk_to_users_unregressed():
    assert _owner_fk(_m(["id","author","body"], {"author":"users"})) == "author"

def test_no_owner():
    assert _owner_fk(_m(["id","name"], {})) is None

if __name__ == "__main__":
    import pytest; raise SystemExit(pytest.main([__file__, "-q"]))
