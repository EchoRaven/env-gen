r"""#569 (netflix r134, live): the resource-less `GET /api/search` resolution asked
`_primary_content_model` FIRST, which REQUIRES a timestamp column. A catalog whose content
table has none (`titles`) was therefore skipped, and the only timestamped, non-spine, owned
table -- `profiles` -- won. The projection emitted

    @app.get("/api/search")
    def _projected_get_api_search_19(q: str = "", db=..., user=...):
        query = db.query(Profile)                       # every account's personas
        ...
        return {"items": [{"id":…, "user_id":…, "name":…, "avatar":…} …]}

i.e. an UNSCOPED enumeration of every user's profiles behind an authenticated global search.
The delivered app only escaped it because the LANE hand-wrote a workaround -- an HTTP
middleware plus a runtime mutation of `app.routes` at import time, commented
"FRAMEWORK-OVERRIDE FIX: the projector emits a leaky /api/search handler". That is not
something another draw can be relied on to reinvent.

`_search_target_model` was written for precisely this case (its docstring names the Netflix
`titles` shape) but sat unreachable behind an `or`. Fix: ask the SEARCH-specific resolver
first, and never let a global search target a per-user PERSONA table.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime.route_projector import (
    _generate_handler,
    _is_user_persona_table,
    _search_target_model,
)

# r134's shape: a rich catalog with NO timestamp, and a persona table that has one.
_NETFLIX = {
    "users": {"cls": "User", "cols": ["id", "email"], "fks": {}},
    "profiles": {"cls": "Profile",
                 "cols": ["id", "user_id", "name", "avatar", "is_kids", "created_at"],
                 "fks": {"user_id": "users"}},
    "titles": {"cls": "Title",
               "cols": ["id", "name", "kind", "year", "genre", "maturity_rating", "rating",
                        "synopsis", "poster", "backdrop", "video_url", "duration"],
               "fks": {}},
    "my_list": {"cls": "MyList", "cols": ["id", "profile_id", "title_id"],
                "fks": {"profile_id": "profiles", "title_id": "titles"}},
    "continue_watching": {"cls": "ContinueWatching",
                          "cols": ["id", "profile_id", "title_id", "progress_seconds"],
                          "fks": {"profile_id": "profiles", "title_id": "titles"}},
}

# A social app: posts are user-owned AND timestamped, and nothing is owned BY a post.
_SOCIAL = {
    "users": {"cls": "User", "cols": ["id", "email"], "fks": {}},
    "posts": {"cls": "Post",
              "cols": ["id", "author_id", "caption", "image", "created_at"],
              "fks": {"author_id": "users"}},
    "comments": {"cls": "Comment", "cols": ["id", "post_id", "author_id", "body"],
                 "fks": {"post_id": "posts", "author_id": "users"}},
}


def test_persona_table_is_recognised_by_shape():
    assert _is_user_persona_table("profiles", _NETFLIX)          # owned AND owned-BY others
    assert not _is_user_persona_table("titles", _NETFLIX)        # not user-owned
    assert not _is_user_persona_table("my_list", _NETFLIX)       # nothing is owned by it
    # a social feed table is user-owned but is NOT a persona — search must still target it
    assert not _is_user_persona_table("posts", _SOCIAL)


def test_r134_global_search_targets_the_catalog_not_the_personas():
    got = _search_target_model(_NETFLIX)
    assert got and got[0] == "titles", got
    src = _generate_handler("GET", "/api/search", True, _NETFLIX, 1)
    assert "db.query(Title)" in src, src
    assert "db.query(Profile)" not in src, "the r134 leak: search enumerated every persona"
    assert "user_id" not in src, "a global search must not expose account linkage"


def test_social_search_still_targets_the_feed_table():
    """The fix must not break a feed-shaped app, where both resolvers agree."""
    got = _search_target_model(_SOCIAL)
    assert got and got[0] == "posts", got
    src = _generate_handler("GET", "/api/search", True, _SOCIAL, 2)
    assert "db.query(Post)" in src


def test_search_still_resolves_when_a_resource_is_named():
    """`/api/<res>/search` already resolves <res> — untouched by this change."""
    src = _generate_handler("GET", "/api/titles/search", True, _NETFLIX, 3)
    assert "db.query(Title)" in src


def test_no_business_table_at_all_is_handled_without_crashing():
    spine_only = {"users": {"cls": "User", "cols": ["id", "email"], "fks": {}}}
    assert _search_target_model(spine_only) is None
    _generate_handler("GET", "/api/search", True, spine_only, 4)   # must not raise


def test_an_all_persona_app_falls_through_rather_than_leaking():
    """Every candidate is a persona → the search resolver declines (None) instead of
    handing back an account table."""
    personas = {
        "users": {"cls": "User", "cols": ["id", "email"], "fks": {}},
        "profiles": {"cls": "Profile", "cols": ["id", "user_id", "name", "created_at"],
                     "fks": {"user_id": "users"}},
        "settings_rows": {"cls": "SettingsRow", "cols": ["id", "profile_id"],
                          "fks": {"profile_id": "profiles"}},
    }
    got = _search_target_model(personas)
    assert got is None or got[0] != "profiles", got


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
