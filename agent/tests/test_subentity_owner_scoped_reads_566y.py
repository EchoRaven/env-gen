r"""#566y (netflix r131, live cross-user leak): the projected collection/item/search READ
owner-scoped ONLY when the contract carried the per-table `owner_scoped_reads` flag, while the
projected CREATE for the SAME resource unconditionally enforced ownership on the same column --
#566s rejects a body owner-FK the caller does not own (403) and `_fw_owner_val` auto-fills the
caller's own. Write into your own scope, read out of everybody's.

r131 ground truth: the contract marked `profiles` owner-scoped but NOT `continue_watching`, so

    @app.get("/api/continue-watching")
    def _projected_get_api_continue_watching_6(db=..., user=...):
        rows = db.query(ContinueWatching).limit(100).all()      # every profile's rows

and chain `profile_ownership_isolation` caught it live: user B probing
GET /api/continue-watching?profile_id=<A's profile 17> got 200 with rows carrying profile_id=1 --
a THIRD party's seeded watch progress. This became reachable when #566w stopped the lane's custom
read (which DID own-check, correctly) from shadowing the projected one, so #566w handed the route
to a less safe handler. The lane cannot fix it: its route is shadowed and the projected handler is
framework-emitted -> deterministic wedge.

Fix: a read is owner-scoped when the contract says so OR when the owner FK's SHAPE already settles
it -- a PER-USER SUB-ENTITY owner (continue_watching.profile_id -> profiles.user_id -> users) is
per-persona private by construction. A DIRECT user FK (posts.author_id -> users) stays opt-in: a
public feed is a list of rows each owned by some user, and scoping it would break every feed app.
"""
import ast
import py_compile
import tempfile

from env_generator.llm_generator.multi_agent.runtime.backend_skeleton import render_skeleton_main
from env_generator.llm_generator.multi_agent.runtime.route_projector import (
    _generate_handler,
    _is_per_user_sub_entity_fk,
)

# continue_watching.profile_id -> profiles.user_id -> users   (SUB-ENTITY owner)
# posts.author_id             -> users                        (DIRECT owner)
_MODELS = {
    "users": {"cls": "User", "cols": ["id", "email"], "fks": {}},
    "profiles": {"cls": "Profile", "cols": ["id", "user_id", "name"],
                 "fks": {"user_id": "users"}},
    "continue_watching": {"cls": "ContinueWatching",
                          "cols": ["id", "profile_id", "title_id", "progress_seconds"],
                          "fks": {"profile_id": "profiles", "title_id": "titles"}},
    "titles": {"cls": "Title", "cols": ["id", "name"], "fks": {}},
    "posts": {"cls": "Post", "cols": ["id", "author_id", "text"],
              "fks": {"author_id": "users"}},
}


def test_shape_predicate_separates_sub_entity_from_direct_and_shared():
    assert _is_per_user_sub_entity_fk(_MODELS["continue_watching"], "profile_id", _MODELS)
    # direct user FK -> NOT a sub-entity owner (public-feed ambiguity preserved)
    assert not _is_per_user_sub_entity_fk(_MODELS["posts"], "author_id", _MODELS)
    # a FK to a table that is NOT user-owned (shared catalog) is not an owner at all
    assert not _is_per_user_sub_entity_fk(_MODELS["continue_watching"], "title_id", _MODELS)
    # missing / unknown column -> False, never a crash
    assert not _is_per_user_sub_entity_fk(_MODELS["continue_watching"], "nope", _MODELS)
    assert not _is_per_user_sub_entity_fk({}, "profile_id", _MODELS)


def _gen(path, method="GET", *, auth=True, scoped=False, idx=1):
    return _generate_handler(method, path, auth, _MODELS, idx, owner_scoped_reads=scoped)


def test_r131_leak_subentity_collection_read_is_scoped_without_the_contract_flag():
    src = _gen("/api/continue-watching")            # owner_scoped_reads NOT set — the r131 draw
    assert "_fw_owner_val(ContinueWatching, \"profile_id\", user)" in src, src
    assert ".filter(" in src
    assert "db.query(ContinueWatching).limit(100).all()" not in src, "unscoped read still emitted"


def test_subentity_item_read_and_search_are_scoped_too():
    item = _gen("/api/continue-watching/{id}", idx=2)
    assert "_fw_owner_val" in item and "status_code=404" in item
    search = _gen("/api/continue-watching/search", idx=3)
    if "query = db.query(ContinueWatching)" in search:      # search shape is emitted
        assert "_fw_owner_val" in search, search


def test_direct_user_owned_feed_stays_open_unless_the_contract_opts_in():
    """The guard rail: scoping a public feed would break every feed-shaped app."""
    open_feed = _gen("/api/posts", idx=4)
    assert "db.query(Post).limit(100).all()" in open_feed, open_feed
    assert "_fw_owner_val" not in open_feed
    # ...and the contract's explicit opt-in still works, exactly as before
    private = _gen("/api/posts", scoped=True, idx=5)
    assert '_fw_owner_val(Post, "author_id", user)' in private


def test_shared_catalog_read_is_untouched():
    src = _gen("/api/titles", idx=6)
    assert "db.query(Title).limit(100).all()" in src
    assert "_fw_owner_val" not in src


def test_unauthenticated_read_is_never_scoped():
    """No actor -> nothing to scope to; must not emit a filter that would crash."""
    src = _gen("/api/continue-watching", auth=False, idx=7)
    assert "_fw_owner_val" not in src


def test_write_and_read_now_agree_on_the_same_owner_column():
    """The invariant the fix restores: the create fills profile_id with the caller's own
    scope, so the read must filter by the same expression."""
    create = _gen("/api/continue-watching", method="POST", idx=8)
    read = _gen("/api/continue-watching", idx=9)
    assert '_fw_owner_val(ContinueWatching, "profile_id", user)' in create
    assert '_fw_owner_val(ContinueWatching, "profile_id", user)' in read


def test_every_emitted_handler_shape_is_syntactically_valid():
    """A bad emit breaks EVERY app's generation — parse each shape this change touches."""
    shapes = [
        ("GET", "/api/continue-watching", True, False),      # sub-entity collection (scoped now)
        ("GET", "/api/continue-watching/{id}", True, False),  # sub-entity item
        ("GET", "/api/continue-watching/search", True, False),
        ("POST", "/api/continue-watching", True, False),
        ("GET", "/api/posts", True, False),                   # direct-owner feed (still open)
        ("GET", "/api/posts", True, True),                    # direct-owner, contract opt-in
        ("GET", "/api/titles", False, False),                 # shared catalog
        ("GET", "/api/titles/{id}", False, False),
    ]
    for i, (m, p, auth, scoped) in enumerate(shapes):
        src = _generate_handler(m, p, auth, _MODELS, 100 + i, owner_scoped_reads=scoped)
        ast.parse(src)                                        # raises SyntaxError on a bad emit


def test_rendered_main_still_compiles():
    """MANDATORY for any emitter change: a bad emit breaks EVERY app's generation."""
    tables = {
        "users": {"columns": [{"name": "id", "type": "Integer", "primary_key": True},
                              {"name": "email", "type": "String"}]},
        "profiles": {"columns": [{"name": "id", "type": "Integer", "primary_key": True},
                                 {"name": "user_id", "type": "Integer",
                                  "foreign_key": "users.id"}]},
        "continue_watching": {"columns": [
            {"name": "id", "type": "Integer", "primary_key": True},
            {"name": "profile_id", "type": "Integer", "foreign_key": "profiles.id"},
            {"name": "title_id", "type": "Integer", "foreign_key": "titles.id"},
            {"name": "progress_seconds", "type": "Integer"}]},
        "titles": {"columns": [{"name": "id", "type": "Integer", "primary_key": True}]},
    }
    endpoints = [
        {"method": "GET", "path": "/api/continue-watching", "auth_required": True},
        {"method": "POST", "path": "/api/continue-watching", "auth_required": True},
        {"method": "GET", "path": "/api/titles", "auth_required": False},
    ]
    src = render_skeleton_main(tables=tables, endpoints=endpoints)
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as fh:
        fh.write(src)
        path = fh.name
    py_compile.compile(path, doraise=True)
