r"""#1203l4: "the delivered page renders NONE of them" was mostly the comparison, not the page.

#909 asks whether a page uses the components its contract declares, and #1202bc files a P2 task
from the answer: "Build the N page(s) whose declared components are missing ... Build each
declared component under `src/components/` and have the page import and render it."

Two things made that answer wrong far more often than right.

ONE -- the registry keys a component by a SLUG and the JSX renders a NAME, and nothing
translated between them. `registryhub_ui_components` keys over every run on disk: 1526
snake_case against 448 PascalCase, in EVERY era -- so this is not a regression, the comparison
has been false by construction since #909 landed. r174's `home_feed` declares `auth_shell`,
`feed_card`, `suggestions_sidebar`, `messages_dock`, `notification_modal`; the delivered
`HomeFeedPage.jsx` renders `AuthShell`, `FeedCard`, `SuggestionsSidebar`, `MessagesDock` and
`NotificationModal` -- all five -- and was reported as rendering NONE. The registry already
carries the translation in each entry's `component` field, which `audit_ui_component` reads for
exactly this purpose (291 of 533 modern entries have it; in all but 2 it is the PascalCase of
the key).

TWO -- `_rendered_components_909` recorded a tag only when a FILE was named for it, because one
test did both the recording and the walking. r161's `NotificationsActivityPage.jsx` line 3 is
`import { CollapsedRail } from '../components/LeftSidebar'` and line 45 is
`<CollapsedRail active="Activity" />`; with no `CollapsedRail.jsx` the page was reported as
rendering nothing. The mirror case is r152, whose pages open with
`import { Shell, VideoStage } from '../components/TikTokUI'` while the contract names the
component `TikTokUI`, which appears as no JSX tag at all -- so a module the page imports FROM
counts too.

MEASURED by replaying the audit over the 39 modern runs' delivered frontends and hub state:
110 of 239 evaluated pages (46%) report drift today -- #909's own docstring measured the same
rate, 246 of 45%, and read it as the finding -- and 31 after this ticket. The check keeps its
teeth: r151's `LeftSidebar`/`TopActionBar`/`FeedViewport` appear nowhere in its src at all.
"""
import inspect
import re
import tempfile
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime import frontend_audit as fa


def _tree(pages: dict, components: dict) -> Path:
    root = Path(tempfile.mkdtemp())
    src = root / "app" / "frontend" / "src"
    (src / "pages").mkdir(parents=True)
    (src / "components").mkdir(parents=True)
    (src / "App.jsx").write_text(
        '<Routes><Route path="/x" element={<XPage />} /></Routes>', encoding="utf-8")
    for name, body in pages.items():
        (src / "pages" / f"{name}.jsx").write_text(body, encoding="utf-8")
    for name, body in components.items():
        (src / "components" / f"{name}.jsx").write_text(body, encoding="utf-8")
    return root


def _cache(root: Path) -> dict:
    src = root / "app" / "frontend" / "src"
    return {str(f): f.read_text(encoding="utf-8")
            for f in list(src.rglob("*.jsx")) + list(src.rglob("*.js"))}


def _used(root, page="XPage"):
    return fa._rendered_components_909(
        root, {"path": f"app/frontend/src/pages/{page}.jsx"}, _cache(root))


# --------------------------------------------------------------- the helper's two blind spots

def test_a_named_export_from_another_module_is_recorded():
    """r161's shape, verbatim: the tag is rendered and no file is named for it."""
    root = _tree({"XPage": ("import { CollapsedRail } from '../components/LeftSidebar';\n"
                            "export default () => <div><CollapsedRail active='Activity'/></div>")},
                 {"LeftSidebar": "export const CollapsedRail = () => <nav/>;\n"})
    used = _used(root)
    assert "CollapsedRail" in used, used
    # and the module it came from counts as used as well
    assert "LeftSidebar" in used, used


def test_a_module_the_page_imports_from_is_recorded():
    """r152's shape: the contract names the MODULE and the page renders its named exports."""
    root = _tree({"XPage": ("import { Shell, VideoStage } from '../components/TikTokUI';\n"
                            "export default () => <Shell><VideoStage/></Shell>")},
                 {"TikTokUI": ("export const Shell = ({children}) => <div>{children}</div>;\n"
                               "export const VideoStage = () => <video/>;\n")})
    used = _used(root)
    assert "TikTokUI" in used, used


def test_the_module_collection_is_transitive_too(tmp_path):
    """Consistency with the rule #909 established: a page that renders `<PosterRail/>` uses
    `PosterCard`, so a page that renders `<Shell/>` where Shell imports from `DataGrid` uses
    DataGrid. Mutation found this: dropping the transitive half of the module collection
    changed no test, because every other fixture imports the module from the PAGE."""
    root = _tree({"XPage": ("import Shell from '../components/Shell';\n"
                            "export default () => <Shell/>")},
                 {"Shell": ("import { Row } from '../components/DataGrid';\n"
                            "export default () => <Row/>"),
                  "DataGrid": "export const Row = () => <tr/>;\n"})
    used = _used(root)
    assert "DataGrid" in used, used
    assert {"Shell", "Row"} <= used, used


def test_the_walk_is_still_transitive_and_still_terminates():
    """Non-regression on what the helper already guaranteed."""
    root = _tree({"XPage": "export default () => <PosterRail/>"},
                 {"PosterRail": "export default () => <PosterCard/>",
                  "PosterCard": "export default () => <img/>"})
    used = _used(root)
    assert {"PosterRail", "PosterCard"} <= used, used
    cyc = _tree({"XPage": "export default () => <A/>"},
                {"A": "export default () => <B/>", "B": "export default () => <A/>"})
    assert {"A", "B"} <= _used(cyc)


def test_an_unknown_page_still_returns_empty_and_it_never_raises():
    root = _tree({"XPage": "export default () => <A/>"}, {"A": "export default () => <i/>"})
    assert fa._rendered_components_909(
        root, {"path": "app/frontend/src/pages/NotThere.jsx"}, _cache(root)) == set()
    for bad in ({}, {"path": None}, {"path": 123}, None):
        assert fa._rendered_components_909(Path("/nonexistent"), bad or {}, None) == set()


# --------------------------------------------------------------- the slug/name translation

def test_the_normaliser_erases_separators_and_case():
    n = fa._norm_component_1203l4
    assert n("auth_shell") == n("AuthShell") == n("Auth-Shell") == "authshell"
    assert n(None) == "" and n("") == ""
    # NON-VACUITY: it does not collapse DIFFERENT names
    assert n("auth_shell") != n("auth_shelf")


class _StubWorkHub:
    def __init__(self, pages, components):
        self._pages, self._components = pages, components
        self.page_updates = []

    def get_ui_pages(self):
        return self._pages

    def get_ui_components(self):
        return self._components

    def update_ui_page(self, name, patch, **kw):
        self.page_updates.append((name, patch))

    def update_ui_component(self, *a, **kw):
        pass


def _drift(page_body, declared, components, *, component_field=True):
    """Drive the REAL sync_ui_page_statuses and return its component_drift report."""
    root = _tree({"XPage": page_body}, components)
    comp_reg = {}
    for slug in declared:
        pascal = "".join(p.title() for p in slug.split("_")) if "_" in slug else slug
        entry = {"name": slug, "path": f"app/frontend/src/components/{pascal}.jsx",
                 "apis_used": [], "status": "implemented"}
        if component_field:
            entry["component"] = pascal
        comp_reg[slug] = entry
    wh = _StubWorkHub(
        {"x_page": {"name": "x_page", "route": "/x", "component": "XPage",
                    "path": "app/frontend/src/pages/XPage.jsx",
                    "components": list(declared), "apis_used": [], "status": "implemented"}},
        comp_reg)
    out = fa.sync_ui_page_statuses(root, wh)
    return (out.get("component_drift") or {}), wh


def test_the_r174_shape_is_no_longer_reported(tmp_path):
    """Declared as slugs, rendered as names, all five present."""
    body = ("import AuthShell from '../components/AuthShell';\n"
            "import FeedCard from '../components/FeedCard';\n"
            "export default () => <AuthShell><FeedCard/></AuthShell>")
    drift, _ = _drift(body, ["auth_shell", "feed_card"],
                      {"AuthShell": "export default ({children}) => <div>{children}</div>",
                       "FeedCard": "export default () => <article/>"})
    assert drift == {}, drift


def test_it_falls_back_to_the_key_when_the_registry_has_no_component_field(tmp_path):
    """240 of the 533 modern entries carry no `component`, so the normalised key has to work."""
    body = ("import AuthShell from '../components/AuthShell';\n"
            "export default () => <AuthShell/>")
    drift, _ = _drift(body, ["auth_shell"],
                      {"AuthShell": "export default () => <div/>"}, component_field=False)
    assert drift == {}, drift


def test_real_drift_is_still_reported_and_still_only_on_a_total_miss(tmp_path):
    """The teeth. r151 declares LeftSidebar/TopActionBar/FeedViewport and its src has none of
    them -- that is the page #909 exists for."""
    body = "export default () => <div><h1>inline</h1></div>"
    drift, _wh = _drift(body, ["left_sidebar", "top_action_bar"],
                       {"LeftSidebar": "export default () => <nav/>",
                        "TopActionBar": "export default () => <header/>"})
    assert "x_page" in drift, drift
    assert sorted(drift["x_page"]) == ["left_sidebar", "top_action_bar"], drift
    # NOT asserted here: that the page's status stayed put. This fixture's page renders
    # nothing at all, so the OTHER rollup ("referenced component `x` not implemented yet")
    # flips it to `defined` for its own reasons -- my first version read that as the drift
    # report touching the status. The property that the report itself leaves `ok` alone is
    # pinned by source at the bottom of this file and by #909's own owner test.

    # a PARTIAL miss is still not reported -- unchanged from #909
    body2 = ("import LeftSidebar from '../components/LeftSidebar';\n"
             "export default () => <LeftSidebar/>")
    drift2, _ = _drift(body2, ["left_sidebar", "top_action_bar"],
                       {"LeftSidebar": "export default () => <nav/>",
                        "TopActionBar": "export default () => <header/>"})
    assert drift2 == {}, drift2


def test_the_call_site_compares_the_resolved_name():
    """Pinned at the call site: the tests above could be satisfied by a looser helper, and
    #909's own file records that its report was once checked only by reading the source."""
    src = inspect.getsource(fa.sync_ui_page_statuses)
    block = src[src.index("_decl_909"):src.index("if ok and status")]
    assert "_norm_component_1203l4" in block, block
    assert '.get("component")' in block, block
    # the original rule survives: only a TOTAL miss is reported
    assert "len(_orphaned) == len(_decl_909)" in block, block
    assert not re.search(r"^\s*ok\s*=", block, re.M), block
