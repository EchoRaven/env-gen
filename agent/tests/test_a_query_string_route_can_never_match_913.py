r"""#913: `<Route path="/browse?title=:id">` is dead on arrival.

React Router matches the PATHNAME only, so a route carrying a query or fragment can never match.
`design_prep` already knows this — #355, on r93's `/?comments=1`: *"Scaffolding it as a page emitted
`<Route path="/?comments=1">`, which React Router matches against the PATHNAME only, so it could
never match — a dead route."* Its answer is that such a screen is an **overlay** of the base path,
not a second page.

That guard lives on the **design-screen** producer. A `ui_page` record registered with the same
shape reaches `scaffold_pages_from_contract` unfiltered and is wired verbatim. One rule, one
producer, and the other one ships the dead route.

Corpus: **1 dead route in 2120** — and it is in r153, the arc's best run:

    <Route path="/browse?title=:id" element={<BrowseHomePage />} />

★ Its consequence is out of all proportion to its rarity. That was r153's only *detail* route, so
`wire_detail_modal_534` — which mounts the lane's detail modal at a `detail`-ish param route — found
no target and no-opped. `TitleDetailModal`, `EpisodeList` and `GET /api/titles/{id}/episodes` are
all present and correct in the delivered app, and **no page renders any of them**: a user cannot see
a show's episodes. (Removing the dead route does not by itself restore the feature — the contract
declares the detail as a query STATE of `/browse`, so it needs `BrowseHomePage` to open the modal,
and that page is the #910 projection which renders no components. That half is the recorded user
decision.)

#355's own answer, applied here: the query is a state of the base page, so when that path is already
claimed the record adds no route; when it is not claimed, keep the path part rather than dropping
the page entirely.
"""
import re
import tempfile
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime import frontend_scaffold as fs


def _wire(pages):
    fe = Path(tempfile.mkdtemp()) / "app" / "frontend"
    (fe / "src" / "pages").mkdir(parents=True)
    (fe / "src" / "components").mkdir(parents=True)
    fs.scaffold_pages_from_contract(fe, pages)
    app = fe / "src" / "App.jsx"
    return set(re.findall(r'<Route\s+path="([^"]+)"', app.read_text(encoding="utf-8"))) \
        if app.exists() else set()


_BROWSE = {"name": "browse_home", "route": "/browse", "component": "BrowseHomePage",
           "apis_used": [], "path": "app/frontend/src/pages/BrowseHomePage.jsx"}


_DETAIL_Q = {"name": "title_detail", "route": "/browse?title=:id",
             "component": "TitleDetailPage", "apis_used": [],
             "path": "app/frontend/src/pages/TitleDetailPage.jsx"}


def test_no_route_carries_a_query_string():
    """★ A DISTINCT component, deliberately. With `BrowseHomePage` on both records the
    `seen_components` dedup swallows the second one first and this case never reaches the guard —
    the first version of this test passed with the guard disabled."""
    routes = _wire([_BROWSE, _DETAIL_Q])
    assert not [r for r in routes if "?" in r or "#" in r], routes


def test_the_base_page_survives():
    routes = _wire([_BROWSE, _DETAIL_Q])
    assert "/browse" in routes


def test_an_unclaimed_base_path_is_kept_not_dropped():
    """★ Dropping the record entirely would lose a page. #355 keeps the full route for the visual
    gate to navigate to; here the PATH is what React Router can actually serve."""
    routes = _wire([{"name": "anchor", "route": "/x", "component": "Anchor", "apis_used": [],
                     "path": "app/frontend/src/pages/Anchor.jsx"},
                    {"name": "comments", "route": "/feed?comments=1", "component": "CommentsPage",
                     "apis_used": [], "path": "app/frontend/src/pages/CommentsPage.jsx"}])
    assert "/feed" in routes, routes
    assert not [r for r in routes if "?" in r], routes


def test_a_fragment_is_treated_the_same():
    routes = _wire([_BROWSE,
                    {"name": "browse_top", "route": "/browse#top", "component": "BrowseTopPage",
                     "apis_used": [], "path": "app/frontend/src/pages/BrowseTopPage.jsx"}])
    assert not [r for r in routes if "#" in r], routes


# --------------------------------------------------------------------------- #913b (the audit)

def _audit_route(declared_route: str, app_route: str):
    """The half that would have caught r153: its App.jsx is LANE-authored (no
    `@framework-managed-routes` marker), so the scaffolder guard never sees it. The audit does."""
    from env_generator.llm_generator.multi_agent.runtime import frontend_audit as fa
    src = Path(tempfile.mkdtemp()) / "src"
    (src / "pages").mkdir(parents=True)
    (src / "App.jsx").write_text(
        f'<Routes><Route path="{app_route}" element={{<XPage />}} /></Routes>', encoding="utf-8")
    (src / "pages" / "XPage.jsx").write_text(
        "export default function XPage(){ return <div onClick={()=>{}}>x</div> }", encoding="utf-8")
    _ok, missing = fa.audit_ui_page(
        src, {"name": "x", "route": declared_route, "component": "XPage", "apis_used": []})
    return missing


def test_a_lane_wired_dead_route_is_reported():
    """★ r153's real case. `_route_is_wired` is a string match, so a route the lane copied
    verbatim SATISFIES the wiring check — the audit confirmed a dead route as wired."""
    miss = _audit_route("/browse?title=:id", "/browse?title=:id")
    assert any("can NEVER match" in m for m in miss), miss


def test_the_report_names_the_base_path_to_use():
    miss = _audit_route("/browse?title=:id", "/browse?title=:id")
    msg = next(m for m in miss if "can NEVER match" in m)
    assert "`/browse`" in msg, msg


def test_it_is_not_a_hard_blocker():
    """A contract typo must not wedge a run — same discipline as #909/#910."""
    from env_generator.llm_generator.multi_agent.runtime import frontend_audit as fa
    miss = _audit_route("/browse?title=:id", "/browse?title=:id")
    dead = [m for m in miss if "can NEVER match" in m]
    assert dead and not any(fa._is_hard_miss(m) for m in dead)


def test_a_clean_route_is_not_reported():
    miss = _audit_route("/browse", "/browse")
    assert not [m for m in miss if "can NEVER match" in m], miss


def test_ordinary_routes_are_untouched():
    routes = _wire([_BROWSE,
                    {"name": "genre_category", "route": "/browse/genre/:genreId",
                     "component": "GenreCategoryPage", "apis_used": [],
                     "path": "app/frontend/src/pages/GenreCategoryPage.jsx"}])
    assert "/browse" in routes and "/browse/genre/:genreId" in routes


def test_a_param_route_is_not_mistaken_for_a_query():
    """`:id` is the thing React Router DOES understand — the guard must key on `?`/`#` only."""
    routes = _wire([{"name": "title_detail", "route": "/title/:id", "component": "TitleDetailPage",
                     "apis_used": [], "path": "app/frontend/src/pages/TitleDetailPage.jsx"}])
    assert "/title/:id" in routes


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
