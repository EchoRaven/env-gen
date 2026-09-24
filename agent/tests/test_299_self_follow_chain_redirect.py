"""#299 — a SUCCESS-expecting social action targeting the chain user's OWN id
must be recognised (so the executor re-targets a different user), else
business_chain wedges forever on 'cannot follow yourself' (r80 M2 STUCK).
"""
import sys
from pathlib import Path
THIS = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS.parent / "env_generator" / "llm_generator"))
from multi_agent.runtime.chain_executor import _self_targeted_social_user_action  # noqa: E402


def test_self_follow_success_expected_is_flagged():
    got = _self_targeted_social_user_action([200, 201], "/api/users/81/follow", 81)
    assert got == ("/api/users", "81")


def test_self_follow_with_string_own_id():
    assert _self_targeted_social_user_action([201], "/api/users/40/follow", "40") == ("/api/users", "40")


def test_versioned_users_collection():
    assert _self_targeted_social_user_action([200], "/api/v1/users/7/subscribe", 7) == ("/api/v1/users", "7")


def test_deliberate_self_deny_test_not_flagged():
    # a_cannot_follow_self expects [400] — it SHOULD self-target; leave it alone
    assert _self_targeted_social_user_action([400], "/api/users/81/follow", 81) is None


def test_follow_different_user_not_flagged():
    assert _self_targeted_social_user_action([200, 201], "/api/users/42/follow", 81) is None


def test_non_social_verb_not_flagged():
    # a followers LIST or a profile read is not a social action
    assert _self_targeted_social_user_action([200], "/api/users/81/followers", 81) is None


def test_no_own_user_id_not_flagged():
    assert _self_targeted_social_user_action([200], "/api/users/81/follow", None) is None


def test_query_string_tolerated():
    assert _self_targeted_social_user_action([201], "/api/users/81/follow?x=1", 81) == ("/api/users", "81")
