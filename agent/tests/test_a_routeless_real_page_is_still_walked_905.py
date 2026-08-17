r"""#905: the ui_flow gate exempted 643 REAL pages and swallowed 24 recorded failures.

#243 exempts a ui_page with a blank route from the required flow set, on the premise that such an
entry is *a component mis-registered as a page* and that **"a ui_flow record for a routeless entry
can NEVER be produced"** — requiring one would be an unwinnable gate.

Measured over the corpus (144 of 153 runs registered any ui_page), both halves of that premise
are wrong for most of what it hits:

    ui_page records                                 2390
      carrying route=''                              673   28%, in 78% of runs
        exempted, path under /components/             26   #243's real class
        exempted, path under /pages/                 643   REAL pages, route never recorded
    ★ of those 643, a ui_flow record EXISTS for      403   63% — "can never exist" is false
    ★ ...and is FAILING, but the gate never saw it    24

r116 alone hid seven failing flows — landing, login, profiles, browse_home, shows, movies,
title_detail. The records exist because the browser walk visits **App.jsx's** real routes and keys
records by page NAME; the registry's empty `route` field never enters that path.

It matters more than it looks: `_extract_required_flows` falls back to *"every declared ui_page is
a flow to validate"*, and this filter runs **before** that fallback. In r153 it cut the required set
from 12 pages to 4.

★ The discriminator was in the record all along. `path` is overloaded — a route in the kickoff spec
shape, a SOURCE FILE in the registry shape — and `app/frontend/src/pages/X.jsx` never starts with
`/`, so every registry record reaching that branch was exempted outright. A file under `src/pages/`
is the framework's own page convention (the scaffolder writes there; `_project_page_component` tests
`"/pages/" in rel`).

Safe in both directions, which is why the fix is not a revert of #243: a newly-required flow with no
record reads MISSING, and `deliverability` already drops *"ui flow(s) missing"* on a functionally
validated app (#489/#240 also author the records from a real pre-gate walk); a FAILED record always
blocked — it just never reached the gate.
"""
import inspect

import pytest

from env_generator.llm_generator.multi_agent.runtime import flow_coverage as fc
from env_generator.llm_generator.multi_agent.runtime.flow_coverage import _is_navigable_page


def _page(**kw):
    base = {"name": "x", "route": "", "path": "app/frontend/src/pages/XPage.jsx"}
    base.update(kw)
    return base


def test_a_component_with_no_route_is_still_exempt():
    """★ #243 must keep working — this is the class it was written for (tiktok r33 M2)."""
    assert _is_navigable_page(
        _page(name="top_action_bar", path="app/frontend/src/components/TopActionBar.jsx")) is False


def test_a_real_page_with_no_route_is_required():
    """The defect: 643 of these, of which 403 already had a record and 24 were failing."""
    assert _is_navigable_page(_page(name="languages_page")) is True


def test_a_routed_page_is_unchanged():
    assert _is_navigable_page(_page(name="games_page", route="/games")) is True


def test_an_entry_with_no_route_and_no_path_is_unchanged():
    """Non-regression on #243's documented conservative branch: we cannot prove it is a
    component, so it stays required."""
    assert _is_navigable_page({"name": "legacy_shape"}) is True


def test_a_non_mapping_is_unchanged():
    assert _is_navigable_page("not a page") is True


def test_a_route_shaped_path_still_wins():
    """`path` doubles as the ROUTE in the kickoff spec shape — a `/`-rooted value must keep
    meaning navigable, whatever the file test would say."""
    p = {"name": "explore", "path": "/explore"}
    assert _is_navigable_page(p) is True


def test_a_windows_style_page_path_is_recognised():
    assert _is_navigable_page(_page(path=r"app\frontend\src\pages\XPage.jsx")) is True


def test_the_filter_runs_before_the_all_pages_fallback():
    """★ The severity claim, pinned to the code. This exemption would be minor if the required set
    came only from `critical:true` pages — it is major because the fallback requires EVERY declared
    page and the filter is applied first. If that order ever changes, this ticket's numbers stop
    meaning what they say."""
    src = inspect.getsource(fc._extract_required_flows)
    assert "_is_navigable_page(p)" in src
    assert src.index("_is_navigable_page(p)") < src.index("CONTRACT-DERIVED FALLBACK")


def test_the_required_set_actually_grows_for_a_routeless_page_set():
    """End to end through the real extractor, not just the predicate."""
    spec = {"critical_flows": [], "pages": [
        _page(name="languages_page", path="app/frontend/src/pages/LanguagesPage.jsx"),
        _page(name="games_page", route="/games", path="app/frontend/src/pages/GamesPage.jsx"),
        _page(name="top_action_bar", path="app/frontend/src/components/TopActionBar.jsx"),
    ]}
    required, source = fc._extract_required_flows(spec)
    assert "languages_page" in required, required
    assert "games_page" in required, required
    assert "top_action_bar" not in required, required


def test_the_frontend_audit_shares_the_predicate_rather_than_copying_it():
    """★ #906. The same test was open-coded a third time in `frontend_audit`, carrying the claim
    *"A genuinely-declared page always carries a '/'-anchored route"* — which the 643 refute. Two
    copies of one concept drift; this asserts there is one.

    Measured before the change: including those pages in the audit yields ZERO hard blockers across
    153 runs. (The first measurement said one — an artifact of passing an EMPTY `_src_cache`, which
    `audit_ui_page` treats as the entire source tree.)"""
    from env_generator.llm_generator.multi_agent.runtime import frontend_audit as fa
    assert fa._is_navigable_page is _is_navigable_page
    src = inspect.getsource(fa.ui_page_delivery_blockers)
    assert src.count("_is_navigable_page(") == 2, "both the audit loop and the map check"
    assert 'str(page.get("route") or "").strip().startswith("/")' not in src


def test_the_shared_import_is_module_level():
    """★ A function-local import here would raise inside the `except Exception: pass` that wraps
    the ui_page audit and silently disable every blocker it produces — #827's exact shape, which
    cost r152. Module level fails loudly at import instead.

    ★ Asserted through the AST. The first version compared source offsets against `"def "`, which
    the module DOCSTRING contains — anchoring on a bare substring that prose can quote, for the
    nth time this session."""
    import ast
    from env_generator.llm_generator.multi_agent.runtime import frontend_audit as fa
    tree = ast.parse(inspect.getsource(fa))
    top = [n for n in tree.body if isinstance(n, ast.ImportFrom) and n.module == "flow_coverage"]
    assert top, "the import must be a MODULE-LEVEL statement, not nested in a function"
    assert any(a.name == "_is_navigable_page" for n in top for a in n.names)


def test_missing_is_suppressed_on_a_validated_app():
    """★ The safety argument, asserted rather than claimed. Widening the required set is only
    responsible because a MISSING record is already waived on a functionally-validated app — if
    that waiver is ever removed, this widening becomes a source of false blocks and this test is
    where that gets noticed."""
    from env_generator.llm_generator.multi_agent.runtime import deliverability as dv
    src = inspect.getsource(dv)
    assert 'if ui_validated:' in src
    assert '"ui flow(s) missing" not in b.lower()' in src



# --------------------------------------------------------------------------- #907

def test_an_empty_source_cache_is_not_read_as_an_empty_tree():
    """★ #907. `audit_ui_page` treats a passed `_src_cache` as the WHOLE source tree, so an empty
    dict used to mean "there are no source files" and every component audited as absent. All four
    real call sites populate it first — nothing in the framework was wrong — but the shape produced
    a confident false blocker in a measurement of mine that reached a commit message (item 251).

    Driven against a real tree so it fails if the fallback is ever narrowed back to `is None`."""
    import tempfile
    from pathlib import Path
    from env_generator.llm_generator.multi_agent.runtime import frontend_audit as fa

    src = Path(tempfile.mkdtemp()) / "src"
    (src / "pages").mkdir(parents=True)
    (src / "App.jsx").write_text(
        '<Routes><Route path="/x" element={<XPage />} /></Routes>', encoding="utf-8")
    (src / "pages" / "XPage.jsx").write_text(
        "export default function XPage(){ return <div onClick={()=>{}}>x</div> }", encoding="utf-8")
    page = {"name": "x_page", "route": "/x", "component": "XPage", "apis_used": [],
            "path": "app/frontend/src/pages/XPage.jsx"}

    none_ok, _ = fa.audit_ui_page(src, page)                      # populates internally
    empty_ok, empty_missing = fa.audit_ui_page(src, page, _src_cache={})
    assert none_ok == empty_ok, (none_ok, empty_ok, empty_missing)
    assert not any("not found" in m for m in empty_missing), empty_missing


def test_a_populated_cache_is_still_trusted_verbatim():
    """Non-regression: the fallback must not re-walk when the caller has already done it — that is
    the entire point of the parameter, and `sync_ui_page_statuses` calls it once per page."""
    import tempfile
    from pathlib import Path
    from env_generator.llm_generator.multi_agent.runtime import frontend_audit as fa

    src = Path(tempfile.mkdtemp()) / "src"
    (src / "pages").mkdir(parents=True)
    (src / "App.jsx").write_text("nothing here", encoding="utf-8")
    cache = {str(src / "App.jsx"): '<Route path="/x" element={<XPage />} />',
             str(src / "pages" / "XPage.jsx"): "export default function XPage(){return <div/>}"}
    before = dict(cache)
    fa.audit_ui_page(src, {"name": "x", "route": "/x", "component": "XPage", "apis_used": []},
                     _src_cache=cache)
    assert cache == before, "a populated cache must not be refilled from disk"

# --------------------------------------------------------------------------- #905b

def test_a_page_the_lane_filed_under_components_is_still_required():
    """★ #905b. `/pages/` was the wrong half of the question — it asks WHERE THE FILE IS, and what
    matters is WHETHER THE RECORD IS A PAGE.

    Of the 30 corpus records whose path points into `components/`, **22 are `login_page`** with
    component `LoginPage`: the login page, which the lane simply filed under components/. #905 left
    every one of them exempt from the flow gate — arguably the single page most worth gating."""
    assert _is_navigable_page(
        {"name": "login_page", "route": "",
         "path": "app/frontend/src/components/LoginPage.jsx"}) is True
    assert _is_navigable_page(
        {"name": "login", "component": "LoginPage", "route": "",
         "path": "app/frontend/src/components/LoginPage.jsx"}) is True


def test_the_real_component_class_stays_exempt():
    """The other 8, and #243's tiktok class. The name is what separates them, and it separates
    them perfectly on the corpus — no `/components/` record is both page-named and a component."""
    for nm, comp in (("tenant_picker", "TenantPicker"), ("netflix_top_nav", "NetflixTopNav"),
                     ("search_overlay", "SearchOverlay"), ("profile_menu", "ProfileMenu"),
                     ("footer", "Footer"), ("top_action_bar", "TopActionBar"),
                     ("explore_card", "ExploreCard"), ("video_grid", "VideoGrid")):
        rec = {"name": nm, "component": comp, "route": "",
               "path": f"app/frontend/src/components/{comp}.jsx"}
        assert _is_navigable_page(rec) is False, nm


def test_a_component_whose_name_merely_contains_page_is_not_rescued():
    """`PageHeader` is a component that starts with the word; the test is the SUFFIX, so it stays
    exempt. Anchoring on a bare substring is how this session's self-matches happened."""
    assert _is_navigable_page(
        {"name": "page_header", "component": "PageHeader", "route": "",
         "path": "app/frontend/src/components/PageHeader.jsx"}) is False


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))


# --------------------------------------------------------------------------- #911b

def test_a_routeless_record_with_no_path_stays_a_page():
    """★ #911b — the regression #911 caused and three existing tests caught.

    #905/#905b asked *"can I prove this is a page?"* and treated **no answer** as "component". A
    routeless record with no `path` at all — `{"name": "settings", "route": "", "component": ""}`,
    the shape `test_frontend_route_dedup` uses — was therefore exempt, and once #911 made the
    scaffold share this predicate those pages stopped being wired at all.

    The rule is now #243's own conservatism, generalised: exempt ONLY on positive evidence of
    component-ness. On the corpus exactly one record has no path (r11's `__probe_only`), so
    measurement alone would never have surfaced this — the existing tests did."""
    assert _is_navigable_page({"name": "settings", "route": "", "component": ""}) is True
    assert _is_navigable_page({"name": "browse_history", "route": "", "component": "",
                               "apis_used": ["GET /api/history"]}) is True


def test_the_kickoff_shape_where_path_is_the_route_still_works():
    assert _is_navigable_page({"name": "explore", "path": "/explore"}) is True


def test_only_a_components_file_proves_a_component():
    """The single accepted proof, stated as a test so a future widening has to argue with it."""
    assert _is_navigable_page(
        {"name": "footer", "route": "", "path": "app/frontend/src/components/Footer.jsx"}) is False
    assert _is_navigable_page(
        {"name": "footer", "route": "", "path": "app/frontend/src/widgets/Footer.jsx"}) is True
