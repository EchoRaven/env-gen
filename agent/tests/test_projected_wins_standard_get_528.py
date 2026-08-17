"""#528 (netflix, live): generated apps 500 on GET /api/titles (and other entity LIST/item
reads) because a LANE-authored custom route with raw SQL over non-existent columns SHADOWS the
framework's correct projected read handler. The projected read (db.query(Model) / db.get) is
schema-safe and 200/404 by construction, so for the two STANDARD-CRUD read shapes — a bare
collection GET (/api/titles) and an item-by-id GET (/api/titles/{id}) — the PROJECTED handler
must win for ALL registered resources, not just the owner-scoped subset (#77). That trades any
lane-added filtering/sorting on PUBLIC lists for guaranteed reachability/correctness; lane
custom/non-standard routes (search, sub-collections, actions, custom verbs) are UNAFFECTED, and
writes are UNCHANGED.

`_custom_route_overrides_projected` returns True = lane custom route wins (overrides projected),
False = projected wins (lane route dropped). It lives inside the `_CUSTOM_ROUTES_INCLUDE` template
string (generated into main.py), so this test slices the function source out of the template and
execs it with controlled resource sets to exercise the exact branch logic."""
from env_generator.llm_generator.multi_agent.runtime import backend_skeleton as bs


def _load_fn():
    """Extract `_custom_route_overrides_projected` from the template and exec it with test
    resource sets. `_NESTED_CHILD_RESOURCES` = all registered tables (+ variants); the
    owner-scoped set is the private subset. 'search' is DELIBERATELY absent from both (it names
    no table) so it exercises the unregistered-collection-GET path."""
    tmpl = bs._CUSTOM_ROUTES_INCLUDE
    start = tmpl.index("def _custom_route_overrides_projected")
    end = tmpl.index("\ntry:", start)          # the include block that follows the function def
    func_src = tmpl[start:end]
    ns = {
        # registered resources (public + private) — projected handlers exist for these
        "_NESTED_CHILD_RESOURCES": {"titles", "title", "genres", "genre",
                                    "my_list", "my_lists", "ratings", "rating"},
        # per-user PRIVATE subset (#77) — projected read is owner-scoped by construction
        "_OWNER_SCOPED_RESOURCES": {"my_list", "my_lists"},
        # #568: resources whose projected model is PK-only, so the projected read can be
        # neither schema-safe nor owner-scoped and the LANE keeps it. Empty here on purpose:
        # every table in this fixture registered its columns, which is the world the #528
        # assertions below describe. The degenerate case has its own test (…_568.py).
        "_DEGENERATE_RESOURCES": set(),
    }
    exec(compile(func_src, "<custom_route_overrides_projected>", "exec"), ns)
    return ns["_custom_route_overrides_projected"]


_FN = _load_fn()


# ── NEW behaviour (#528): public registered resource GETs → PROJECTED wins (False) ──
def test_public_collection_get_projected_wins():
    # bare-collection GET on a public registered resource now returns False (projected wins).
    assert _FN("GET", "/api/titles") is False


def test_public_item_by_id_get_projected_wins():
    # item-by-id GET on a public registered resource now returns False (projected wins).
    assert _FN("GET", "/api/titles/{id}") is False


# ── UNCHANGED: owner-scoped resource GET already projected-wins (#77) ──
def test_owner_scoped_collection_get_still_projected_wins():
    assert _FN("GET", "/api/my_list") is False


def test_owner_scoped_item_get_still_projected_wins():
    assert _FN("GET", "/api/my_list/{id}") is False


# ── GUARD 1: NON-standard lane GETs still LANE-win (True) ──
def test_search_still_lane_wins():
    # /api/search names no registered table → no projected handler → lane must win (guard 2 too).
    assert _FN("GET", "/api/search") is True


def test_subcollection_action_still_lane_wins():
    # a sub-collection / action verb after the resource (/api/titles/trending) is non-standard.
    assert _FN("GET", "/api/titles/trending") is True
    assert _FN("GET", "/api/titles/top10") is True


def test_unregistered_collection_get_lane_wins():
    # a bare-collection GET whose segment is NOT a registered resource keeps lane-wins (guard 2:
    # no projected handler exists, so projected-wins would 404).
    assert _FN("GET", "/api/analytics") is True


# ── GUARD 3: writes on a public resource are UNCHANGED (projected already won; still False) ──
def test_public_collection_post_unchanged():
    # POST on a public collection was projected-wins (False) before #528 and stays False.
    assert _FN("POST", "/api/titles") is False


def test_public_item_write_verbs_unchanged():
    assert _FN("PUT", "/api/titles/{id}") is False
    assert _FN("PATCH", "/api/titles/{id}") is False
    assert _FN("DELETE", "/api/titles/{id}") is False


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
