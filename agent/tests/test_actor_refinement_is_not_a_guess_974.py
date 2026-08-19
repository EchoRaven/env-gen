"""#974: an actor REFINEMENT is not a guess — resolve it; siblings still refuse.

netflix r158 died here. `my_list`, `ratings` and `continue_watching` each carry BOTH
`user_id` and `profile_id`, so `repair_handler_fk_aliases` declined 90 times, the handlers
kept raising, `business_chain` wedged for 7 post-cap cycles and the run aborted without
delivering — final error `null value in column "profile_id" violates not-null constraint`.

#784's refusal was right for the case it was written against: `messages(sender_id,
recipient_id)` points BOTH at `users`, and picking one hands an inbox handler the caller's
sent mail — a wrong-owner read no test would catch. But that is SIBLINGS. When one actor
table transitively references the other (`profiles.user_id -> users.id`), the descendant is
a refinement, and choosing it is a deduction from the declared FK graph.

★ The asymmetry is what makes it admissible: the narrower actor can only ever return TOO
LITTLE, while the wider one can return another user's rows. A mistake here is a visible
over-restriction, never a silent cross-user leak — which is precisely the harm #784 exists
to prevent. That is why this resolves the refinement case and leaves the sibling case
failing loudly.
"""

import pytest

from env_generator.llm_generator.multi_agent.runtime.handler_fk_repair import (
    _narrowest_actor_974, _reachable_tables_974, _table_of)

# r158's real shape: profiles is a child of users.
NETFLIX_MODELS = {
    "users": {"cls": "User", "cols": ["id", "email"], "fks": {}},
    "profiles": {"cls": "Profile", "cols": ["id", "user_id"], "fks": {"user_id": "users.id"}},
    "my_list": {"cls": "MyList", "cols": ["id", "user_id", "profile_id", "title_id"],
                "fks": {"user_id": "users.id", "profile_id": "profiles.id",
                        "title_id": "titles.id"}},
}

# The case #784 was written for: both actors are the SAME table.
MESSAGES_MODELS = {
    "users": {"cls": "User", "cols": ["id"], "fks": {}},
    "messages": {"cls": "Message", "cols": ["id", "sender_id", "recipient_id"],
                 "fks": {"sender_id": "users.id", "recipient_id": "users.id"}},
}


@pytest.mark.parametrize("ref,expected", [
    ("users", "users"),
    ("users.id", "users"),
    ("ForeignKey('users.id')", "users"),
    ('ForeignKey("profiles.id")', "profiles"),
    ("", ""),
    (None, ""),
])
def test_table_of(ref, expected):
    assert _table_of(ref) == expected


def test_profiles_is_reachable_to_users():
    assert "users" in _reachable_tables_974("profiles", NETFLIX_MODELS)
    assert _reachable_tables_974("users", NETFLIX_MODELS) == set()


def test_the_refinement_resolves_to_the_narrower_actor():
    got = _narrowest_actor_974(
        ["profile_id", "user_id"], NETFLIX_MODELS["my_list"]["fks"], NETFLIX_MODELS)
    assert got == "profile_id", (
        "profiles references users, so profile_id is the narrower scope — and the narrower "
        "scope cannot leak across users, which is what makes choosing it safe")


def test_siblings_still_refuse():
    got = _narrowest_actor_974(
        ["recipient_id", "sender_id"], MESSAGES_MODELS["messages"]["fks"], MESSAGES_MODELS)
    assert got is None, (
        "both point at users with no refinement between them; guessing would give an inbox "
        "handler the caller's SENT mail — #784's case must keep failing loudly")


def test_an_unresolvable_reference_refuses():
    models = {"t": {"cls": "T", "cols": ["a_id", "b_id"], "fks": {"a_id": "", "b_id": "users.id"}}}
    assert _narrowest_actor_974(["a_id", "b_id"], models["t"]["fks"], models) is None


def test_a_cycle_does_not_hang():
    """Generated schemas are not guaranteed acyclic; the walk must terminate."""
    cyclic = {
        "a": {"cls": "A", "cols": ["b_id"], "fks": {"b_id": "b.id"}},
        "b": {"cls": "B", "cols": ["a_id"], "fks": {"a_id": "a.id"}},
        "t": {"cls": "T", "cols": ["a_id", "b_id"],
              "fks": {"a_id": "a.id", "b_id": "b.id"}},
    }
    _narrowest_actor_974(["a_id", "b_id"], cyclic["t"]["fks"], cyclic)  # must return


def test_three_actors_pick_the_deepest():
    models = {
        "users": {"cls": "User", "cols": ["id"], "fks": {}},
        "profiles": {"cls": "Profile", "cols": ["user_id"], "fks": {"user_id": "users.id"}},
        "devices": {"cls": "Device", "cols": ["profile_id"], "fks": {"profile_id": "profiles.id"}},
        "t": {"cls": "T", "cols": ["user_id", "profile_id", "device_id"],
              "fks": {"user_id": "users.id", "profile_id": "profiles.id",
                      "device_id": "devices.id"}},
    }
    assert _narrowest_actor_974(
        ["device_id", "profile_id", "user_id"], models["t"]["fks"], models) == "device_id"


def test_the_control_cannot_tell_them_apart():
    """Planted control: #784's rule — count the owner-ish columns — treats the netflix case
    and the messages case identically, which is why one of them was collateral damage."""
    def _pre_fix(owner_ish):
        return None if len(owner_ish) > 1 else owner_ish[0]

    assert _pre_fix(["profile_id", "user_id"]) is None
    assert _pre_fix(["recipient_id", "sender_id"]) is None


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
