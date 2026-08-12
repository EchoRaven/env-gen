r"""#593: a page is its ROUTE — one route must not hold two conflicting contracts.

The ui_page store is keyed by NAME, so the two seeding paths (`<name>_page` from the #225
design-screen seed, `<name>` from the contract) each created their own record for one route.
Measured over 45 runs: 28 duplicate routes in 6 runs, and ALL 28 disagree on `apis_used` and/or
`components`. r142 — a *** MULTI-MILESTONE VALIDATED *** run — carries 9; r133 carries 8.

r142 `/games`, both `implemented`, both written by the orchestrator 6 minutes apart:

    page:ui:games_page   apis ['GET /api/profiles']   comps [TopNav, PosterRail]
    page:ui:games        apis ['GET /api/titles']     comps [top_nav, category_header,
                                                             hero_billboard, poster_rail]

The router dispatches on the ROUTE, so one page had two contracts and every consumer that
iterates the store (frontend_audit, remediation_dispatcher, the gate's ui_page_unwired) acted on
whichever it reached first — dict-insertion order.

Honest scope: contract hygiene, NOT a fidelity fix. Duplicate-route screens scored 0.641 against
0.624 for single-record screens and the within-run paired deltas swing +0.183 to -0.252 — no
effect. What this removes is the non-determinism. Merging is strictly not-worse than the status
quo: both records were already live and already audited, so the union of their apis_used is
exactly the set the audit demanded anyway.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime.registryhub import RegistryHub


@pytest.fixture()
def hub(tmp_path):
    return RegistryHub(str(tmp_path))


def _reg(hub, name, **kw):
    kw.setdefault("agent", "orchestrator")
    return hub.register_ui_page(name=name, **kw)


def _pages(hub):
    return {k: v for k, v in (hub.list_ui_pages() or {}).items()} if hasattr(hub, "list_ui_pages") \
        else {k: v for k, v in (hub._ui_pages.value() or {}).items()}


# --- the r142 /games collision, replayed -------------------------------------------------------

def test_the_second_registration_does_not_create_a_second_record(hub):
    _reg(hub, "games_page", route="/games", component="GamesPage",
         apis_used=["GET /api/profiles"], components=["TopNav", "PosterRail"],
         path="app/frontend/src/pages/GamesPage.jsx", status="implemented")
    _reg(hub, "games", route="/games", component="GamesPage",
         apis_used=["GET /api/titles"],
         components=["top_nav", "category_header", "hero_billboard", "poster_rail"],
         status="implemented")
    pages = _pages(hub)
    routed = [k for k, v in pages.items() if isinstance(v, dict) and v.get("route") == "/games"]
    assert routed == ["games_page"], pages


def test_the_merged_record_carries_BOTH_contracts(hub):
    _reg(hub, "games_page", route="/games", component="GamesPage",
         apis_used=["GET /api/profiles"], components=["TopNav"])
    _reg(hub, "games", route="/games", apis_used=["GET /api/titles"],
         components=["hero_billboard"])
    rec = _pages(hub)["games_page"]
    assert rec["apis_used"] == ["GET /api/profiles", "GET /api/titles"]
    assert rec["components"] == ["TopNav", "hero_billboard"]


def test_the_alias_stays_findable(hub):
    _reg(hub, "games_page", route="/games", component="GamesPage")
    _reg(hub, "games", route="/games")
    assert _pages(hub)["games_page"]["metadata"]["merged_route_aliases"] == ["games"]


def test_a_non_empty_path_survives_a_thin_re_registration(hub):
    """`page:ui:games` had `path: ""` — merging must not blank the real one."""
    _reg(hub, "games_page", route="/games", component="GamesPage",
         path="app/frontend/src/pages/GamesPage.jsx")
    _reg(hub, "games", route="/games")
    assert _pages(hub)["games_page"]["path"] == "app/frontend/src/pages/GamesPage.jsx"


def test_the_first_registered_key_is_the_one_that_survives(hub):
    """Stable identity: other records reference a page by id, so the newcomer yields."""
    _reg(hub, "games", route="/games", component="GamesPage")
    _reg(hub, "games_page", route="/games", component="GamesPage")
    assert list(_pages(hub)) == ["games"]
    assert _pages(hub)["games"]["id"] == "page:ui:games"


# --- what must keep working ---------------------------------------------------------------------

def test_distinct_routes_stay_distinct(hub):
    _reg(hub, "games", route="/games", component="GamesPage")
    _reg(hub, "movies", route="/movies", component="MoviesPage")
    assert sorted(_pages(hub)) == ["games", "movies"]


def test_re_registering_the_SAME_name_still_REPLACES_not_unions(hub):
    """Only a cross-name route collision merges; a page correcting its own declaration
    must still be able to REMOVE an api it no longer calls."""
    _reg(hub, "games", route="/games", apis_used=["GET /api/titles", "GET /api/profiles"])
    _reg(hub, "games", route="/games", apis_used=["GET /api/titles"])
    assert _pages(hub)["games"]["apis_used"] == ["GET /api/titles"]


def test_a_routeless_placeholder_never_collides(hub):
    """PROPOSAL #47: thin design-phase registrations are legal and must not all merge
    into one record just because they share an empty route."""
    _reg(hub, "a_page")
    _reg(hub, "b_page")
    assert sorted(_pages(hub)) == ["a_page", "b_page"]


def test_the_union_does_not_duplicate_a_shared_entry(hub):
    _reg(hub, "games_page", route="/games", apis_used=["GET /api/titles"])
    _reg(hub, "games", route="/games", apis_used=["GET /api/titles", "GET /api/profiles"])
    assert _pages(hub)["games_page"]["apis_used"] == ["GET /api/titles", "GET /api/profiles"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
