r"""#596: a page's `path` must be able to be its component's file.

frontend_audit states the canonical layout — "a page's root component lives in src/pages/,
name == filename" — but nothing enforced it at the WRITE boundary, so one ui_page record could
name two different files at once. Measured over the 623 records carrying BOTH fields, 16
disagree (2.6%, in 4 runs), in two distinct shapes:

    r54   every page            component=<X>Page          path stem=App        <- the ROUTER file
    r27   browse_home_page      component=BrowseHomePage   path stem=browse     <- a ROUTE
          genre_category_page   component=GenreCategoryPage path stem=:slug
    r115  login                 component=Login            path stem=LoginPage
    r139  title_detail          component=BrowseHomePage   path stem=TitleDetailPage

The first two shapes are unambiguously junk — a route, or the framework's own entry point, is
never a page component file — so the path is dropped and the audit's canonical
`src/pages/<Component>.jsx` lookup takes over.

The last two are deliberately NOT arbitrated: both stems are plausible page components and the
corrupted field DIFFERS between them (r115's `component` looks right; r139's looks wrong — its
title_detail page claims BrowseHomePage). Guessing would have made r139 worse. They get a
breadcrumb and are left exactly as written.

Context for why this matters: r115's fork is what ships a 72-line framework LoginPage while the
lane's own 162-line Login.jsx — with router navigation, a real auth service and a logo component
— sits unrouted. Across 45 runs there are 24 forked page pairs in 8 runs; this is one source.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime.registryhub import RegistryHub


@pytest.fixture()
def hub(tmp_path):
    return RegistryHub(str(tmp_path))


def _reg(hub, name, **kw):
    kw.setdefault("agent", "orchestrator")
    return hub.register_ui_page(name=name, **kw)


def _rec(hub, name):
    return (hub._ui_pages.value() or {}).get(name) or {}


# --- unambiguous junk is dropped ------------------------------------------------------------

def test_the_r54_shape_the_router_file_is_never_a_page(hub):
    _reg(hub, "browse_home_page", route="/browse", component="BrowseHomePage",
         path="app/frontend/src/App.jsx")
    r = _rec(hub, "browse_home_page")
    assert r["path"] == ""
    assert r["metadata"]["path_rejected_596"].endswith("App.jsx")


def test_the_r27_shape_a_route_is_never_a_file(hub):
    for nm, comp, bad in (("browse_home_page", "BrowseHomePage", "browse"),
                          ("genre_category_page", "GenreCategoryPage", ":slug"),
                          ("games_page", "GamesPage", "games")):
        _reg(hub, nm, component=comp, path=bad)
        assert _rec(hub, nm)["path"] == "", nm


def test_every_reserved_identifier_is_refused(hub):
    for bad in ("App", "Routes", "Route", "React", "BrowserRouter"):
        _reg(hub, f"p_{bad.lower()}", component="SomePage", path=f"src/pages/{bad}.jsx")
        assert _rec(hub, f"p_{bad.lower()}")["path"] == "", bad


# --- the ambiguous pair is left alone -------------------------------------------------------

def test_the_r115_shape_is_flagged_not_arbitrated(hub):
    _reg(hub, "login", route="/login", component="Login",
         path="app/frontend/src/pages/LoginPage.jsx")
    r = _rec(hub, "login")
    assert r["path"] == "app/frontend/src/pages/LoginPage.jsx"   # untouched
    assert r["component"] == "Login"                             # untouched
    assert r["metadata"]["path_component_mismatch"] == "Login vs LoginPage"


def test_the_r139_shape_is_flagged_the_same_way(hub):
    """Here the COMPONENT is the corrupted field — a title_detail page claiming
    BrowseHomePage. Guessing 'trust the component' would have made this worse."""
    _reg(hub, "title_detail", component="BrowseHomePage",
         path="app/frontend/src/pages/TitleDetailPage.jsx")
    r = _rec(hub, "title_detail")
    assert r["path"].endswith("TitleDetailPage.jsx")
    assert r["metadata"]["path_component_mismatch"] == "BrowseHomePage vs TitleDetailPage"


# --- what must be untouched -------------------------------------------------------------------

def test_a_canonical_record_is_unchanged_and_unflagged(hub):
    _reg(hub, "browse_home", route="/browse", component="BrowseHomePage",
         path="app/frontend/src/pages/BrowseHomePage.jsx")
    r = _rec(hub, "browse_home")
    assert r["path"] == "app/frontend/src/pages/BrowseHomePage.jsx"
    assert "path_rejected_596" not in r["metadata"]
    assert "path_component_mismatch" not in r["metadata"]


def test_a_non_canonical_DIRECTORY_is_still_allowed(hub):
    """frontend_audit supports an any-location fallback and only reports the drift —
    #596 judges the FILENAME, never the folder."""
    _reg(hub, "shows", component="ShowsPage", path="app/frontend/src/views/ShowsPage.jsx")
    r = _rec(hub, "shows")
    assert r["path"] == "app/frontend/src/views/ShowsPage.jsx"
    assert "path_rejected_596" not in r["metadata"]


def test_a_record_with_no_component_is_not_judged(hub):
    """PROPOSAL #47 keeps thin design-phase registrations legal."""
    _reg(hub, "placeholder", path="app/frontend/src/pages/App.jsx")
    assert _rec(hub, "placeholder")["path"] == "app/frontend/src/pages/App.jsx"


def test_a_record_with_no_path_is_not_judged(hub):
    _reg(hub, "games", route="/games", component="GamesPage")
    assert _rec(hub, "games")["path"] == ""
    assert "path_rejected_596" not in _rec(hub, "games")["metadata"]


def test_a_windows_style_path_is_parsed(hub):
    _reg(hub, "movies", component="MoviesPage", path=r"app\frontend\src\pages\App.jsx")
    assert _rec(hub, "movies")["path"] == ""


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
