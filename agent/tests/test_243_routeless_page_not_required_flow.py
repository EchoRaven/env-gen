"""#243 (tiktok r33 M2, live): M2 registered COMPONENTS as ui_pages with an EMPTY
route (video_grid, explore_grid, explore_card, suggested_creator_card,
top_action_bar, content_tabs, more_menu_panel, suggested_creators_grid). The
deterministic browser walk only visits ROUTED pages, so a validation:ui_flow
record can never exist for them → 8 permanently-missing flows → the ui_flow gate
was unwinnable and M2 could not deliver. Routeless entries must not be REQUIRED
flows. Conservative: an entry with no route/path key at all stays required.

★ The exemption narrowed three times after this test was written, and the fixtures
below were not updated, so they stopped describing the rule they check. Current
contract (#905 -> #905b/#909 -> #911b):

    exempt  IFF  `path` contains "/components/"  AND  neither `name` nor
                 `component` ends in "page"

#905 measured that the original "blank route => component" rule exempted 643 REAL
pages (28% of all page records) and swallowed 24 recorded FAILURES; #909 rescued
the 22 `login_page` records the lane happened to file under components/; #911b
restored #243's own conservatism for the no-path case ("we cannot prove it is a
component" -> it stays a page), because once #911 made the scaffold share this
predicate, exempting them stopped those pages being WIRED at all.

So a routeless record now needs a component PATH to be exempt. The fixtures here
carry one; the no-path case is pinned below as required, which is #243's stated
conservatism, not a departure from it."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from env_generator.llm_generator.multi_agent.runtime.flow_coverage import (  # noqa: E402
    _extract_required_flows, _is_navigable_page,
)


def test_routeless_entry_is_not_navigable():
    assert _is_navigable_page({"name": "explore_card", "route": "",
                               "path": "src/components/ExploreCard.jsx"}) is False
    assert _is_navigable_page({"name": "x", "route": "   ",
                               "path": "src/components/X.jsx"}) is False
    assert _is_navigable_page({"name": "x", "route": None,
                               "path": "src/components/X.jsx"}) is False
    # A source-file "route" is not a URL, but #911b no longer treats "not a URL"
    # as proof of component-ness: with no component path this stays REQUIRED, so
    # the scaffold still wires it (which is what #911 broke by exempting it).
    assert _is_navigable_page({"name": "x", "route": "src/pages/X.jsx"}) is True
    # ...and with that proof, it is exempt.
    assert _is_navigable_page({"name": "x", "route": "src/pages/X.jsx",
                               "path": "src/components/X.jsx"}) is False


def test_routed_entry_is_navigable():
    assert _is_navigable_page({"name": "explore", "route": "/explore"}) is True
    assert _is_navigable_page({"name": "feed", "route": "/"}) is True
    assert _is_navigable_page({"name": "p", "path": "/@:username"}) is True


def test_no_route_key_stays_required_backcompat():
    # older spec shape without a route key: can't prove it's a component
    assert _is_navigable_page({"name": "legacy_page"}) is True


def test_routeless_with_no_path_stays_required_911b():
    """#911b: no path is not evidence of component-ness."""
    assert _is_navigable_page({"name": "settings", "route": "",
                               "component": ""}) is True


def test_routeless_page_file_stays_required_905():
    """#905: a blank route under src/pages/ is a page whose route nobody wrote
    down — 643 of them, 403 with records that existed all along."""
    assert _is_navigable_page({"name": "browse_home", "route": "",
                               "path": "src/pages/BrowseHome.jsx"}) is True


def test_component_filed_page_is_still_a_page_909():
    """#909: 22 corpus records are `login_page` filed under components/."""
    assert _is_navigable_page({"name": "login_page", "route": "",
                               "path": "src/components/LoginPage.jsx"}) is True


def test_required_set_drops_routeless_components():
    """r33 M2's exact shape: 3 real pages + 3 routeless components."""
    spec = {"pages": [
        {"name": "for_you_feed", "route": "/"},
        {"name": "explore", "route": "/explore"},
        {"name": "profile", "route": "/@:username"},
        {"name": "explore_card", "route": "", "path": "src/components/ExploreCard.jsx"},
        {"name": "top_action_bar", "route": "", "path": "src/components/TopActionBar.jsx"},
        {"name": "video_grid", "route": "", "path": "src/components/VideoGrid.jsx"},
    ]}
    names, source = _extract_required_flows(spec)
    assert source == "pages"
    assert names == ["for_you_feed", "explore", "profile"]


def test_critical_pages_also_filtered():
    spec = {"pages": [
        {"name": "feed", "route": "/", "critical": True},
        {"name": "some_widget", "route": "", "critical": True,
         "path": "src/components/SomeWidget.jsx"},
    ]}
    names, source = _extract_required_flows(spec)
    assert names == ["feed"]


def test_dict_form_pages_filtered():
    spec = {"pages": {
        "explore": {"route": "/explore"},
        "explore_card": {"route": "", "path": "src/components/ExploreCard.jsx"},
    }}
    names, _ = _extract_required_flows(spec)
    assert names == ["explore"]
