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
    pages = [{"name": "my_list_page", "route": "/my-list", "apis_used": []}]
    got = _apis(backfill_page_apis(pages, _EPS), "my_list_page")
    assert all(a.startswith("GET ") for a in got), got


def test_no_endpoints_or_garbage_returns_the_input():
    pages = [{"name": "x", "route": "/title/:id", "apis_used": ["GET /api/profiles"]}]
    assert backfill_page_apis(pages, []) == pages
    assert backfill_page_apis(None, _EPS) in (None, [])
    assert backfill_page_apis(["not a dict"], _EPS) == ["not a dict"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
