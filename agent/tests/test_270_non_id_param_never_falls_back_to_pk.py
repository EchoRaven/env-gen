"""#270 — a non-id path param must never be compared against an integer PK.

r58 (opus-4.7), live:

    GET/POST/DELETE /api/users/{username}/videos|follow -> 500
    backend traceback: main.py:772 in _projected_delete_api_users_username_follow

The projected handler read:

    parent = db.query(User).filter(getattr(User, "id") == username).first()

``User`` in that run has no ``username`` column (id / email / name / password_hash /
tenant_id / created_at — the username lives on a different model), so ``_lookup_field``
walked its ladder — not id-like, not a column, no username column, no slug — and hit the
final ``return "id"``. Comparing an Integer primary key to "avachen" is an unconditional
Postgres type error, so every request to those three routes 500s. It is not a data problem
and no lane can fix it: the framework emitted code that cannot work.

Same family as #263 — an identifier used for something it does not identify — and just as
env-agnostic: /api/orgs/{slug}/..., /api/posts/{slug}, any by-name nesting hits it.

The fallback itself is the bug. For an id-LIKE param, ``id`` is the right answer. For a
param NAMED after something else, falling back to the PK is a guaranteed 500; the honest
answers are the column the name denotes, or a miss the handler can turn into a 404.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from env_generator.llm_generator.multi_agent.runtime.route_projector import (  # noqa: E402
    _lookup_field,
)


def _meta(*cols):
    return {"cols": list(cols)}


def test_r58_regression_username_against_a_model_without_it():
    """The exact shape that 500'd: param 'username', parent has no such column."""
    got = _lookup_field("username", _meta("id", "email", "name", "password_hash"))
    assert got != "id", "comparing an Integer PK to a username string is a certain 500"


def test_id_like_params_still_resolve_to_the_pk():
    for p in ("id", "user_id", "userId", "channelId", "video_id"):
        assert _lookup_field(p, _meta("id", "email")) == "id", p


def test_an_exact_column_match_wins():
    assert _lookup_field("username", _meta("id", "username")) == "username"
    assert _lookup_field("slug", _meta("id", "slug")) == "slug"


def test_username_family_maps_to_the_username_column():
    for p in ("username", "handle", "user"):
        assert _lookup_field(p, _meta("id", "username")) == "username", p


def test_slug_is_used_when_present_and_the_name_matches_nothing_else():
    assert _lookup_field("permalink", _meta("id", "slug")) == "slug"


def test_a_name_param_prefers_a_name_column_over_the_pk():
    """'name' is not id-like; a model carrying `name` should be matched on it."""
    assert _lookup_field("name", _meta("id", "name")) == "name"


def test_unresolvable_non_id_param_does_not_claim_the_pk():
    """Nothing matches: the projector must not assert the PK — that is the 500."""
    got = _lookup_field("permalink", _meta("id", "email"))
    assert got != "id", got


def test_pk_is_still_the_answer_when_there_is_nothing_else_and_the_name_is_id_like():
    assert _lookup_field("pk", _meta("id")) == "id"
