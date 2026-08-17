r"""#911: r83 shipped `<Route path="/netflix-top-nav">` — a nav bar served as a full page.

Registration is deliberately permissive, so lanes register components as ui_pages (#243's tiktok
r33: `video_grid`, `explore_card`, `top_action_bar`). `scaffold_pages_from_contract` then derived a
route from the record's name and wrote `pages/<Comp>.jsx`. r83's App.jsx:

    import NetflixTopNav from './pages/NetflixTopNav.jsx';
    <Route path="/netflix-top-nav" element={<NetflixTopNav />} />

…while its **twelve** real importers use the lane's 139-line `components/NetflixTopNav.jsx`. The
78-line `pages/` copy exists only because this loop created it.

Measured: **77 same-named `pages/`+`components/` pairs** across the corpus; in **3** both copies are
genuinely imported, and all three DIFFER (r120 `LoginPage` 72 vs 33, r149 72 vs 3, r83
`NetflixTopNav` 78 vs 139) — two different UIs for one name inside one app.

★ The predicate is the one #905b built and #906 already shares, so the scaffold, the ui_flow gate
and the deliverability audit now answer "page or component?" the same way by construction rather
than by three hand-written copies agreeing today. Corpus effect: 8 records stop producing a page —
`tenant_picker`, `netflix_top_nav`, `search_overlay`, `profile_menu`, `footer`. Everything
page-named, routed, or without a `components/` path is untouched, including the 22 `login_page`
records the lane filed under `components/`.
"""
import re
import tempfile
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime import frontend_scaffold as fs
from env_generator.llm_generator.multi_agent.runtime.flow_coverage import _is_navigable_page


def _scaffold(pages, extra_components=()):
    fe = Path(tempfile.mkdtemp()) / "app" / "frontend"
    (fe / "src" / "pages").mkdir(parents=True)
    (fe / "src" / "components").mkdir(parents=True)
    for c in extra_components:
        (fe / "src" / "components" / f"{c}.jsx").write_text(
            "export default () => <nav/>", encoding="utf-8")
    fs.scaffold_pages_from_contract(fe, pages)
    app = fe / "src" / "App.jsx"
    return (app.read_text(encoding="utf-8") if app.exists() else "",
            {p.name for p in (fe / "src" / "pages").glob("*.jsx")})


_BROWSE = {"name": "browse_home", "route": "/browse", "component": "BrowseHomePage",
           "apis_used": [], "path": "app/frontend/src/pages/BrowseHomePage.jsx"}
_TOPNAV = {"name": "netflix_top_nav", "route": "", "component": "NetflixTopNav",
           "apis_used": [], "path": "app/frontend/src/components/NetflixTopNav.jsx"}


def test_a_component_record_gets_no_route():
    """r83's actual defect."""
    app, _ = _scaffold([_BROWSE, _TOPNAV], extra_components=["NetflixTopNav"])
    assert "/netflix-top-nav" not in app, app


def test_a_component_record_gets_no_shadow_page_file():
    """★ The second half: the shadow is what makes two different UIs answer to one name."""
    _, files = _scaffold([_BROWSE, _TOPNAV], extra_components=["NetflixTopNav"])
    assert "NetflixTopNav.jsx" not in files, files


def test_a_real_page_filed_under_components_is_still_scaffolded():
    """★ Non-regression on #905b's 22: `login_page` lives under `components/` in 22 corpus records
    and is a page. If this ever starts failing, the login page silently loses its route."""
    _, files = _scaffold([
        _BROWSE,
        {"name": "login_page", "route": "", "component": "", "apis_used": [],
         "path": "app/frontend/src/components/LoginPage.jsx"},
    ])
    assert "LoginPage.jsx" in files, files


def test_the_ordinary_routed_page_is_untouched():
    app, files = _scaffold([_BROWSE])
    assert "/browse" in app
    assert "BrowseHomePage.jsx" in files


def test_a_record_with_no_path_is_untouched():
    """#243's conservative branch: we cannot prove it is a component, so it stays a page."""
    app, files = _scaffold([_BROWSE, {"name": "legacy_shape", "route": "", "component": "",
                                      "apis_used": []}])
    assert files - {"BrowseHomePage.jsx"}, "the legacy-shaped record must still get a page"


def test_a_routed_component_record_is_untouched():
    """An explicit `/`-route wins over every heuristic — the lane meant it to be navigable."""
    app, _ = _scaffold([_BROWSE, {**_TOPNAV, "route": "/nav"}], extra_components=["NetflixTopNav"])
    assert "/nav" in app


def test_the_three_consumers_share_one_predicate():
    """★ The point of doing it this way. Three hand-written copies that agree today are how the
    #905/#906 divergence happened in the first place."""
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import frontend_audit as fa
    assert fs._is_navigable_page is _is_navigable_page
    assert fa._is_navigable_page is _is_navigable_page
    src = inspect.getsource(fs.scaffold_pages_from_contract)
    assert "_is_navigable_page(page)" in src


def test_the_import_is_module_level():
    """A function-local import in the scaffold loop would raise where it is hardest to see, and
    `flow_coverage` imports nothing from this package so there is no cycle to dodge."""
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(fs))
    tops = [n for n in tree.body if isinstance(n, ast.ImportFrom) and n.module == "flow_coverage"]
    assert tops and any(a.name == "_is_navigable_page" for n in tops for a in n.names)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
