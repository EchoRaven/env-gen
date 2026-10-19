r"""#579 (netflix r142, live): `backfill_page_apis` only rescues a page whose `apis_used` is
EMPTY. A page with a WRONG-but-non-empty list gets no help, and the projector faithfully builds
a data-less page from it.

r142's kickoff filled nearly every page with the same placeholder:

    title_detail_page  route=/title/:id          apis=['GET /api/profiles']
    games_page         route=/games              apis=['GET /api/profiles']
    shows_page         route=/shows              apis=['GET /api/profiles']
    my_list_page       route=/my-list            apis=['GET /api/profiles']
    browse_home_page   route=/browse             apis=['GET /api/profiles']
    player_page        route=/watch/:titleId     apis=['GET /api/titles/top10']

and NO page in the draw declared `/api/titles/{id}/episodes`. The projected detail page fetched
no title and rendered no episodes list — components 0.35, copy 0.60, similarity **0.50** — where
r137, whose kickoff declared all six relevant APIs, reached 0.70 on the same screen with the
same projector.

Fix: add what the ROUTE plainly implies, strictly additively, and only when the endpoint is
actually registered.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import backfill_page_apis

# r142's real endpoint surface (the subset that matters here).
_EPS = [{"method": "GET", "path": p} for p in (
    "/api/titles", "/api/titles/{id}", "/api/titles/{id}/episodes", "/api/titles/trending",
    "/api/titles/top10", "/api/genres", "/api/genres/{id}/titles", "/api/my-list",
    "/api/profiles", "/api/continue-watching", "/api/search",
)] + [{"method": "POST", "path": "/api/my-list"}]


def _apis(pages, name):
    return next(p["apis_used"] for p in pages if p["name"] == name)


def test_r142_detail_page_gains_its_own_read_and_child_collection():
    pages = [{"name": "title_detail_page", "route": "/title/:id",
              "apis_used": ["GET /api/profiles"]}]
    got = _apis(backfill_page_apis(pages, _EPS), "title_detail_page")
    assert "GET /api/titles/{id}" in got, got
    assert "GET /api/titles/{id}/episodes" in got, got
    assert "GET /api/profiles" in got, "the authored entry must survive — additive only"


def test_a_collection_route_gains_its_collection_read():
    pages = [{"name": "my_list_page", "route": "/my-list", "apis_used": ["GET /api/profiles"]}]
    got = _apis(backfill_page_apis(pages, _EPS), "my_list_page")
    assert "GET /api/my-list" in got, got          # kebab route -> kebab endpoint


def test_an_unmatched_route_is_left_alone_not_guessed():
    """`/browse`, `/watch/:titleId` and `/games` name no registered resource — guessing would
    be worse than the placeholder."""
    pages = [{"name": "browse_home_page", "route": "/browse", "apis_used": ["GET /api/profiles"]},
             {"name": "player_page", "route": "/watch/:titleId",
              "apis_used": ["GET /api/titles/top10"]},
             {"name": "games_page", "route": "/games", "apis_used": ["GET /api/profiles"]}]
    out = backfill_page_apis(pages, _EPS)
    assert _apis(out, "browse_home_page") == ["GET /api/profiles"]
    assert _apis(out, "player_page") == ["GET /api/titles/top10"]
    assert _apis(out, "games_page") == ["GET /api/profiles"]


def test_a_correctly_authored_page_is_unchanged():
    authored = ["GET /api/titles/{id}", "GET /api/titles/{id}/episodes"]
    pages = [{"name": "title_detail_page", "route": "/title/:id", "apis_used": list(authored)}]
    assert _apis(backfill_page_apis(pages, _EPS), "title_detail_page") == authored


def test_a_collection_route_does_not_pull_in_by_id_endpoints():
    """`/titles` is a list — it should not be handed `/api/titles/{id}`."""
    pages = [{"name": "titles_page", "route": "/titles", "apis_used": []}]
    got = _apis(backfill_page_apis(pages, _EPS), "titles_page")
    assert "GET /api/titles" in got
    assert not any("{id}" in a for a in got), got


def test_a_detail_route_does_not_pull_in_sibling_action_paths():
    """`/api/titles/trending` and `/top10` are param-less siblings, not this page's data."""
    pages = [{"name": "title_detail_page", "route": "/title/:id", "apis_used": []}]
    got = _apis(backfill_page_apis(pages, _EPS), "title_detail_page")
    assert not any(a.endswith("/trending") or a.endswith("/top10") for a in got), got


def test_writes_are_never_backfilled():
    """#1203pf: this used to assert `a.startswith("GET ")`, which CANNOT FAIL -- the emitter
    is `add.append(f"GET {path}")`, so the prefix is hardcoded and the assertion was true by
    construction. Worse, it hid the failure it was written for: drop the GET filter on the
    candidate list and a POST-only path is backfilled AND LABELLED `GET`, naming an endpoint
    the contract does not have. The property is about the PATH's registered method, so that
    is what this asserts now.
    """
    pages = [{"name": "my_list_page", "route": "/my-list", "apis_used": []}]
    got = _apis(backfill_page_apis(pages, _EPS), "my_list_page")
    get_paths = {e["path"] for e in _EPS if e["method"] == "GET"}
    for entry in got:
        method, _, path = str(entry).partition(" ")
        assert method == "GET", entry
        assert path in get_paths, (
            "%s names a path that is not a registered GET endpoint -- "
            "`POST /api/my-list` exists, `GET` of it does not" % entry)


def test_a_WRITE_ONLY_endpoint_is_never_backfilled():
    """#1203pf: the shared fixture's only POST (`POST /api/my-list`) has a GET TWIN, so
    removing the write filter changed nothing and the property was never driven -- a mutation
    that dropped the filter came back MISSED. This endpoint set has a write with no GET of the
    same path, which is the only shape that can exercise it.
    """
    eps = [{"method": "GET", "path": "/api/titles"},
           {"method": "POST", "path": "/api/ratings"}]
    pages = [{"name": "ratings_page", "route": "/ratings", "apis_used": []}]
    got = _apis(backfill_page_apis(pages, eps), "ratings_page")
    assert got == [], (
        "a write-only endpoint was backfilled as %s -- and it would be LABELLED `GET`, "
        "naming a route the contract does not serve" % got)


def test_a_PARAMETERISED_path_is_not_offered_as_a_collection():
    """#1203pf: the candidate list keeps only unparameterised `/api/` paths, and nothing drove
    that. A detail endpoint backfilled as a page's collection read names a URL the page cannot
    build -- it has no id to put in it.

    Driven with a `{id}` path whose tokens DO match the page, and no collection twin: with the
    filter, nothing is backfilled; without it, `GET /api/ratings/{id}` appears.
    """
    eps = [{"method": "GET", "path": "/api/titles"},
           {"method": "GET", "path": "/api/ratings/{id}"}]
    pages = [{"name": "ratings_page", "route": "/ratings", "apis_used": []}]
    got = _apis(backfill_page_apis(pages, eps), "ratings_page")
    assert got == [], "a parameterised path was offered as a collection: %s" % got


def test_a_path_outside_the_api_surface_is_not_offered():
    """#1203pf: the same filter requires `/api/`. A backfill naming `/healthz` or a static
    asset path would put a non-API URL into `apis_used`, which every downstream consumer of
    that field then reasons about as an endpoint."""
    eps = [{"method": "GET", "path": "/api/titles"},
           {"method": "GET", "path": "/ratings"}]
    pages = [{"name": "ratings_page", "route": "/ratings", "apis_used": []}]
    got = _apis(backfill_page_apis(pages, eps), "ratings_page")
    assert got == [], "a non-/api path was offered: %s" % got


def test_no_registered_GET_collection_means_silence_not_a_guess():
    """#883 and the function's own rule: "writing a form no reader of the contract recognises
    would be worse than writing nothing". With only writes and parameterised reads registered,
    there is no collection to infer from, and the pages must come back untouched.
    """
    eps = [{"method": "POST", "path": "/api/ratings"},
           {"method": "GET", "path": "/api/ratings/{id}"}]
    pages = [{"name": "ratings_page", "route": "/ratings", "apis_used": []}]
    out = backfill_page_apis(pages, eps)
    assert out == pages, "an empty collection surface produced a guess: %s" % out


def test_no_endpoints_or_garbage_returns_the_input():
    pages = [{"name": "x", "route": "/title/:id", "apis_used": ["GET /api/profiles"]}]
    assert backfill_page_apis(pages, []) == pages
    assert backfill_page_apis(None, _EPS) in (None, [])
    assert backfill_page_apis(["not a dict"], _EPS) == ["not a dict"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
