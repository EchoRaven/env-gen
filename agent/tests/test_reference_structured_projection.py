"""FIX #221 — by-construction REFERENCE-STRUCTURED page projection.

When a routed page has a measured design screen (design_system.json screens[]
carry route + per-component fractional regions/roles/colors — #132/#220), the
framework must project a REAL page: the reference's region structure (e.g.
TikTok = left nav sidebar + center media surface + right action rail), painted
with the MEASURED palette, fetching the route's declared endpoint and rendering
real rows — NOT the generic top-nav row list ("No data yet") fallback.
Covered pages carry data-projected="ref" (a real floor, not a fallback);
uncovered routes keep the generic marked fallback. LOCAL-ONLY (gitignored).
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.frontend_scaffold import (  # noqa: E402
    scaffold_pages_from_contract, scaffold_missing_local_pages,
)


def _mk_design(out: Path):
    """A TikTok-shaped measured design: '/' = left nav + center video + right
    action rail; '/messages' = left nav + conversation list."""
    (out / "design").mkdir(parents=True, exist_ok=True)
    ds = {
        "design_system": {
            "palette": {"bg": "#000000", "accent": "#fe2c55",
                        "accents": {"red": "#fe2c55", "blue": "#1f44f2"}},
            "theme": {"default": "dark", "themes": ["dark"]},
            "type_scale": [], "radius_scale": {}, "shadow_scale": [],
        },
        "screens": [
            {"name": "fyp_feed", "reference": "fyp_feed.png", "kind": "page",
             "requires_auth": False, "route": "/",
             "layout": "3-column flex: left sidebar, center video, right rail",
             "components": [
                 {"id": "side-navigation", "region": [0.0, 0.05, 0.17, 1.0],
                  "role": "Vertical list of navigation links with icons",
                  "colors": {"bg": "#000000", "accent": "#fe2c55"},
                  "geometry": {}, "assets": [], "state": "", "build_notes": ""},
                 {"id": "video-player", "region": [0.35, 0.02, 0.66, 0.98],
                  "role": "Main content area displaying a video",
                  "colors": {"bg": "#111111"}, "geometry": {},
                  "assets": [], "state": "", "build_notes": ""},
                 {"id": "interaction-buttons", "region": [0.67, 0.5, 0.70, 0.98],
                  "role": "Vertical stack of buttons for like, comment, save, share",
                  "colors": {"bg": "#000000"}, "geometry": {},
                  "assets": [], "state": "", "build_notes": ""},
             ]},
            {"name": "messages", "reference": "messages.png", "kind": "page",
             "requires_auth": True, "route": "/messages",
             "layout": "left sidebar + conversation list",
             "components": [
                 {"id": "side-navigation", "region": [0.0, 0.05, 0.17, 1.0],
                  "role": "Vertical navigation", "colors": {"bg": "#000000"},
                  "geometry": {}, "assets": [], "state": "", "build_notes": ""},
                 {"id": "conversation-list", "region": [0.2, 0.1, 0.95, 1.0],
                  "role": "List of DM conversations", "colors": {"bg": "#000000"},
                  "geometry": {"columns": 1}, "assets": [], "state": "",
                  "build_notes": ""},
             ]},
        ],
    }
    (out / "design" / "design_system.json").write_text(
        json.dumps(ds), encoding="utf-8")


def _mk_frontend(out: Path) -> Path:
    fe = out / "app" / "frontend"
    (fe / "src" / "pages").mkdir(parents=True)
    return fe


_PAGES = [
    {"name": "feed_page", "component": "FeedPage", "route": "/",
     "apis_used": ["GET /api/videos"], "kind": "page"},
    {"name": "messages_page", "component": "MessagesPage", "route": "/messages",
     "apis_used": ["GET /api/messages"], "kind": "page"},
    {"name": "settings_page", "component": "SettingsPage", "route": "/settings",
     "apis_used": ["GET /api/settings"], "kind": "page"},   # NOT design-covered
]


def test_covered_route_projects_reference_structure(tmp_path):
    out = tmp_path
    _mk_design(out)
    fe = _mk_frontend(out)
    scaffold_pages_from_contract(fe, _PAGES)

    feed = (fe / "src" / "pages" / "FeedPage.jsx").read_text(encoding="utf-8")
    # a real reference-structured page, not a fallback
    assert 'data-projected="ref"' in feed
    assert "data-fallback" not in feed
    # fetches the route's OWN declared endpoint
    assert "/api/videos" in feed
    # reference structure: a left sidebar band + a media surface + action rail
    assert "<aside" in feed
    assert "<video" in feed
    assert "17.0%" in feed or "17%" in feed          # sidebar width from region
    # measured palette painted, not hardcoded zinc light
    assert "#000000" in feed
    assert "bg-zinc-50" not in feed
    # functional: media navigation through real rows
    assert "setIdx" in feed
    # navigable: links to the app's other routes
    assert '"/messages"' in feed


def test_covered_list_route_renders_row_list(tmp_path):
    out = tmp_path
    _mk_design(out)
    fe = _mk_frontend(out)
    scaffold_pages_from_contract(fe, _PAGES)
    msgs = (fe / "src" / "pages" / "MessagesPage.jsx").read_text(encoding="utf-8")
    assert 'data-projected="ref"' in msgs
    assert "/api/messages" in msgs
    assert "rows.map" in msgs                        # populated list from real data
    assert "data-fallback" not in msgs


def test_uncovered_route_with_palette_gets_measured_floor(tmp_path):
    # #296/#297: an uncovered GET route no longer ships a data-fallback list when
    # THIS env's measured palette is available — it gets a measured, structured
    # floor that counts as BUILT (the lane still refines it). Supersedes the old
    # test_uncovered_route_keeps_marked_generic_fallback.
    out = tmp_path
    _mk_design(out)
    fe = _mk_frontend(out)
    scaffold_pages_from_contract(fe, _PAGES)
    st = (fe / "src" / "pages" / "SettingsPage.jsx").read_text(encoding="utf-8")
    assert 'data-projected="ref"' in st              # structured, not fallback
    assert 'data-fallback="1"' not in st
    assert "#000000" in st                            # measured canvas paint
    assert "/api/settings" in st                      # still fetches its OWN endpoint


def test_uncovered_route_no_palette_keeps_marked_fallback(tmp_path):
    # #296 §2 guard: with NO measured palette, an uncovered GET route still ships
    # the honest data-fallback list (so the lane is still forced to build it).
    out = tmp_path
    fe = _mk_frontend(out)                             # NO _mk_design → no palette
    scaffold_pages_from_contract(fe, _PAGES)
    st = (fe / "src" / "pages" / "SettingsPage.jsx").read_text(encoding="utf-8")
    assert 'data-fallback="1"' in st                 # honest: still a fallback
    assert "/api/settings" in st


def test_comp_kind_scoring_not_first_keyword(tmp_path):
    """r18 explore_grid: 'Grid layout of video thumbnails with like counts'
    contains 'video' but IS a grid — keyword-order classification rendered a
    video player for the masonry grid. Score by hit count, not first match."""
    from multi_agent.runtime.frontend_scaffold import _comp_kind_221
    assert _comp_kind_221({"id": "video-grid",
                           "role": "Grid layout of video thumbnails with user info and like counts"}) == "list"
    assert _comp_kind_221({"id": "video-player",
                           "role": "Main content area displaying a video",
                           "state": "Video playing, muted icon visible"}) == "media"
    assert _comp_kind_221({"id": "interaction-buttons",
                           "role": "Vertical stack of buttons for like, comment, save, and share"}) == "actions"
    assert _comp_kind_221({"id": "conversation-list",
                           "role": "List of DM conversations"}) == "list"
    assert _comp_kind_221({"id": "sidebar-navigation",
                           "role": "Vertical navigation menu containing logo, search, main links"}) == "nav"


def test_grid_without_measured_geometry_gets_multi_columns(tmp_path):
    """A grid-role main region on an OLD design doc (no #220 geometry) must not
    degrade to a 1-column list — derive columns from the region width."""
    out = tmp_path
    (out / "design").mkdir(parents=True)
    ds = {
        "design_system": {"palette": {"bg": "#000000", "accent": "#fe2c55"},
                          "theme": {"default": "dark"}},
        "screens": [{"name": "explore", "reference": "explore.png",
                     "kind": "page", "route": "/explore",
                     "components": [
                         {"id": "video-grid", "region": [0.17, 0.08, 1.0, 1.0],
                          "role": "Grid layout of video thumbnails",
                          "colors": {}, "assets": [], "state": "",
                          "build_notes": ""}]}],
    }
    (out / "design" / "design_system.json").write_text(json.dumps(ds),
                                                       encoding="utf-8")
    fe = _mk_frontend(out)
    scaffold_pages_from_contract(fe, [
        {"name": "explore_page", "component": "ExplorePage", "route": "/explore",
         "apis_used": ["GET /api/videos"], "kind": "page"}])
    ex = (fe / "src" / "pages" / "ExplorePage.jsx").read_text(encoding="utf-8")
    assert "gridTemplateColumns" in ex
    assert "repeat(1," not in ex


def test_kind_terms_match_word_boundaries():
    """'displaying' must not hit the media term 'playing' (r18 friends user
    cards all classified media → a Follow-card wall rendered as a video player)."""
    from multi_agent.runtime.frontend_scaffold import _comp_kind_221
    assert _comp_kind_221({"id": "user-card-x",
                           "role": "Card displaying a user profile with a background "
                                   "image, profile picture, name, handle, and a "
                                   "'Follow' button."}) != "media"


def test_repeated_cards_become_measured_grid(tmp_path):
    """N same-role card components tiled over the main band (r18 friends: 9
    user-cards in 3 columns) → a grid with the MEASURED column count + the
    card's quoted action button, not a video player or a 1-col list."""
    out = tmp_path
    (out / "design").mkdir(parents=True)
    cards = []
    for i, (x0, y0) in enumerate([(x, y) for y in (0.02, 0.41, 0.79)
                                  for x in (0.33, 0.49, 0.66)]):
        cards.append({"id": f"user-card-{i}", "region": [x0, y0, x0 + 0.15, y0 + 0.36],
                      "role": "Card displaying a user profile with a background image, "
                              "profile picture, name, handle, and a 'Follow' button.",
                      "colors": {}, "assets": [], "state": "", "build_notes": ""})
    ds = {"design_system": {"palette": {"bg": "#000000", "accent": "#fe2c55"},
                            "theme": {"default": "dark"}},
          "screens": [{"name": "friends", "reference": "friends.png",
                       "kind": "page", "route": "/friends",
                       "components": [{"id": "sidebar-navigation",
                                       "region": [0.0, 0.0, 0.16, 1.0],
                                       "role": "Vertical navigation menu",
                                       "colors": {}, "assets": [], "state": "",
                                       "build_notes": ""}] + cards}]}
    (out / "design" / "design_system.json").write_text(json.dumps(ds),
                                                       encoding="utf-8")
    fe = _mk_frontend(out)
    scaffold_pages_from_contract(fe, [
        {"name": "friends_page", "component": "FriendsPage", "route": "/friends",
         "apis_used": ["GET /api/users"], "kind": "page"}])
    fr = (fe / "src" / "pages" / "FriendsPage.jsx").read_text(encoding="utf-8")
    assert "<video" not in fr
    assert "repeat(3," in fr                     # measured columns from card x0s
    assert ">Follow<" in fr                      # the card's quoted action


def test_media_plus_list_main_renders_both(tmp_path):
    """A main band with a featured media surface AND a thumbnail list (r18
    live_discover) renders BOTH bands — not featured-only.

    #479: the featured surface is an <img> hero, not a <video>. A lone "video
    player" phrase in a component role no longer classifies a screen as a player,
    because it produced false positives that scored 0.20 — r49's my_list "video
    player hero", r52's Browse-by-Languages rendering as a player off its
    "Subtitles" language selector. A player now needs a player-EXCLUSIVE control
    (scrub/playhead/skip/pause) or >=2 distinct control terms, and this fixture has
    neither. The property this test is named for — both bands render — is
    unchanged."""
    out = tmp_path
    (out / "design").mkdir(parents=True)
    ds = {"design_system": {"palette": {"bg": "#000000", "accent": "#fe2c55"},
                            "theme": {"default": "dark"}},
          "screens": [{"name": "live", "reference": "live.png",
                       "kind": "page", "route": "/live",
                       "components": [
                           {"id": "featured-live-stream",
                            "region": [0.17, 0.09, 1.0, 0.75],
                            "role": "Large video player showing a featured live stream",
                            "colors": {}, "assets": [], "state": "", "build_notes": ""},
                           {"id": "live-stream-thumbnails",
                            "region": [0.17, 0.82, 1.0, 1.0],
                            "role": "Horizontal grid of live stream thumbnails with viewer counts",
                            "colors": {}, "assets": [], "state": "", "build_notes": ""},
                       ]}]}
    (out / "design" / "design_system.json").write_text(json.dumps(ds),
                                                       encoding="utf-8")
    fe = _mk_frontend(out)
    scaffold_pages_from_contract(fe, [
        {"name": "live_page", "component": "LivePage", "route": "/live",
         "apis_used": ["GET /api/streams"], "kind": "page"}])
    lv = (fe / "src" / "pages" / "LivePage.jsx").read_text(encoding="utf-8")
    assert "<img" in lv                          # the featured media surface (#479: hero,
                                                 # not a <video> without player evidence)
    assert "overflow-x-auto" in lv               # the thumbnail strip


def test_design_covered_page_is_reprojected_but_an_uncovered_one_is_not_221(tmp_path):
    """#221 replaced "never overwrite a lane page" and the docstring lagged.

    A ui_page covered by a MEASURED design screen is re-projected over whatever is
    there; one that is not covered keeps the lane's file. The scaffolder's own note
    records both the change and the confusion it caused — "alternating 59 lines
    (projection) / 241 lines (lane) across 9 rounds looked like a contract violation
    until the #221 note turned up" — and the measurement behind it: on my_list the
    lane's 241-line page and the 59-line projection BOTH scored 0.60, on player 214
    vs 87 lines both scored 0.55. "The projection is a floor, not a downgrade."

    So the property to pin is the SPLIT, not immunity."""
    out = tmp_path
    _mk_design(out)
    fe = _mk_frontend(out)
    for comp in ("FeedPage", "SettingsPage"):
        (fe / "src" / "pages" / f"{comp}.jsx").write_text(
            "export default function %s() { return <div>lane</div>; }\n" % comp,
            encoding="utf-8")
    scaffold_pages_from_contract(fe, _PAGES)

    feed = (fe / "src" / "pages" / "FeedPage.jsx").read_text(encoding="utf-8")
    assert "lane" not in feed, "a design-covered page is re-projected (#221)"

    settings = (fe / "src" / "pages" / "SettingsPage.jsx").read_text(encoding="utf-8")
    assert "lane" in settings, "an UNcovered page keeps the lane's file"


def test_missing_local_import_heal_path_uses_design(tmp_path):
    """scaffold_missing_local_pages (build-integrity path) must also project the
    reference structure when the dangling import's route is design-covered."""
    out = tmp_path
    _mk_design(out)
    fe = _mk_frontend(out)
    (fe / "src" / "App.jsx").write_text(
        "import MessagesPage from './pages/MessagesPage';\n"
        "export default function App() {\n"
        "  return (<Routes><Route path=\"/messages\" element={<MessagesPage />} /></Routes>);\n"
        "}\n", encoding="utf-8")
    scaffold_missing_local_pages(fe, ui_pages=_PAGES)
    msgs = (fe / "src" / "pages" / "MessagesPage.jsx").read_text(encoding="utf-8")
    assert 'data-projected="ref"' in msgs
    assert "/api/messages" in msgs


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))


def test_fuzzy_route_match_covers_kickoff_screen_drift(tmp_path):
    """#226 (r20 live): kickoff declares the page at /activity but the screen
    classified /notifications (name notifications_activity) — exact-route
    matching missed, so the page fell to the generic fallback while a twin
    got the structured projection. Token-overlap fuzzy match closes it."""
    from multi_agent.runtime.frontend_scaffold import _design_screen_for_route
    design = {"screens": [
        {"name": "notifications_activity", "kind": "page", "route": "/notifications",
         "components": [{"id": "notification-list", "role": "List of notifications"}]},
        {"name": "explore_grid", "kind": "page", "route": "/explore",
         "components": [{"id": "video-grid", "role": "Grid"}]},
    ]}
    s = _design_screen_for_route(design, "/activity")
    assert s and s["name"] == "notifications_activity"
    # no token overlap → no match (never a wrong graft)
    assert _design_screen_for_route(design, "/settings") is None


def test_nav_renders_mapped_staged_assets(tmp_path):
    """#227 (r20 live): the visual gate's #1 remediation is 'render the staged
    asset SVGs, do not approximate' — the structured projection must render the
    nav component's MAPPED assets itself (icon per matching nav label, logo at
    top), lifting the floor's fidelity by construction."""
    out = tmp_path
    (out / "design").mkdir(parents=True)
    ds = {
        "design_system": {"palette": {"bg": "#000000", "accent": "#fe2c55"},
                          "theme": {"default": "dark"}},
        "assets": [
            {"id": "explore-ae9e44cc", "type": "svg",
             "file": "icons/explore_ae9e44cc.svg",
             "staged_path": "public/assets/icons/explore_ae9e44cc.svg"},
            {"id": "logo-dark-1a2b3c4d", "type": "svg",
             "file": "brand/logo-dark_1a2b3c4d.svg",
             "staged_path": "public/assets/brand/logo-dark_1a2b3c4d.svg"},
            {"id": "TikTokFont-Bold", "type": "font",
             "file": "fonts/TikTokFont-Bold.woff2",
             "staged_path": "public/assets/fonts/TikTokFont-Bold.woff2"},
        ],
        "screens": [{"name": "explore_grid", "kind": "page", "route": "/explore",
                     "reference": "explore.png",
                     "components": [
                         {"id": "sidebar-navigation", "region": [0.0, 0.0, 0.17, 1.0],
                          "role": "Vertical navigation menu",
                          "assets": ["explore-ae9e44cc", "logo-dark-1a2b3c4d",
                                     "TikTokFont-Bold"],
                          "colors": {}, "state": "", "build_notes": ""},
                         {"id": "video-grid", "region": [0.2, 0.1, 1.0, 1.0],
                          "role": "Grid of video thumbnails", "assets": [],
                          "colors": {}, "state": "", "build_notes": ""}]}],
    }
    (out / "design" / "design_system.json").write_text(json.dumps(ds),
                                                       encoding="utf-8")
    fe = _mk_frontend(out)
    scaffold_pages_from_contract(fe, [
        {"name": "explore_page", "component": "ExplorePage", "route": "/explore",
         "apis_used": ["GET /api/videos"], "kind": "page"}])
    ex = (fe / "src" / "pages" / "ExplorePage.jsx").read_text(encoding="utf-8")
    assert '/assets/icons/explore_ae9e44cc.svg' in ex     # icon on the Explore link
    assert '/assets/brand/logo-dark_1a2b3c4d.svg' in ex   # logo at aside top
    assert 'woff2' not in ex                              # fonts never <img>'d


def test_fuzzy_match_uses_page_name_hints(tmp_path):
    """#229 (r21 live): the `profile` page is declared at /@:username — the
    route's only token is the param name, so route-only fuzzy matching missed
    the profile_own screen at /profile and shipped the generic fallback. The
    page's own name/id/component must join the fuzzy vocabulary."""
    from multi_agent.runtime.frontend_scaffold import _design_screen_for_route
    design = {"screens": [
        {"name": "profile_own", "kind": "page", "route": "/profile",
         "components": [{"id": "profile-header", "role": "Profile header"}]},
    ]}
    assert _design_screen_for_route(design, "/@:username") is None  # route alone: no match
    s = _design_screen_for_route(design, "/@:username",
                                 hints=("profile", "profile_page", "ProfilePage"))
    assert s and s["name"] == "profile_own"


def test_page_name_hint_reaches_projection(tmp_path):
    out = tmp_path
    (out / "design").mkdir(parents=True)
    ds = {"design_system": {"palette": {"bg": "#000000", "accent": "#fe2c55"},
                            "theme": {"default": "dark"}},
          "screens": [{"name": "profile_own", "kind": "page", "route": "/profile",
                       "reference": "p.png",
                       "components": [
                           {"id": "profile-header", "region": [0.2, 0.05, 1.0, 0.3],
                            "role": "Profile header with stats", "colors": {},
                            "assets": [], "state": "", "build_notes": ""},
                           {"id": "video-grid", "region": [0.2, 0.35, 1.0, 1.0],
                            "role": "Grid of video thumbnails", "colors": {},
                            "assets": [], "state": "", "build_notes": ""}]}]}
    (out / "design" / "design_system.json").write_text(json.dumps(ds),
                                                       encoding="utf-8")
    fe = _mk_frontend(out)
    scaffold_pages_from_contract(fe, [
        {"name": "profile", "component": "ProfilePage", "route": "/@:username",
         "apis_used": ["GET /api/users/:username"], "kind": "page"}])
    pr = (fe / "src" / "pages" / "ProfilePage.jsx").read_text(encoding="utf-8")
    assert 'data-projected="ref"' in pr
    assert "data-fallback" not in pr
