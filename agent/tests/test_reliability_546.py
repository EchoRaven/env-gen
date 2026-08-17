"""#546 (netflix, run netflix-web-r102, 2026-08-06) — make the three high-variance
Part-A screens render RELIABLY by keying their archetype/spec decisions off the
STABLE contract page (route + component name), not the design analyst's per-run
component phrasing — the SAME determinism principle that made #539 robust for
new_and_popular. Plus a shared hero-title type-scale clamp.

ROOT CAUSE (r102 browse_by_languages 0.28, was 0.60 r100 / 0.35 r101 — plus/minus 0.30 swing):
  The selector-grid archetype (_wants_rows_539) and the invented-aside suppression
  keyed ONLY off the analyst's design `screen`. That screen is non-deterministic:
  the route /browse/languages is claimed by MULTIPLE analyst screens (browse_by_
  languages kind=page, card_preview kind=overlay, ...), the analyst re-phrases roles/
  names run-to-run, and the frontend LANE can (re)author the page as a content
  hero+carousel copying browse_home. When the analyst phrased browse_by_languages as
  content rows (or a hero screen won the render), #545's screen-only override never
  fired and the page shipped as a billboard + "New" carousel — a language SELECTOR
  page rendered as a content browse (the r102 gate png: a "Disclosure Day" hero over
  a poster carousel, 0.28).

  The STABLE signal was in hand all along: the contract page's route
  (/browse/languages) and component (BrowseByLanguagesPage) ALWAYS carry the selector
  token, deterministically, whatever the analyst does.

#546 FIXES (each deterministic from the stable name/route; byte-identical when the
signal is absent; no product literals):
  1. _wants_rows_539(screen, data, page) + the aside suppression ALSO read the
     contract page's route/component -> a selector/preference/settings/account/
     profile/by-languages page is a GRID with NO invented content aside, regardless
     of analyst phrasing or which twin screen claimed the route.
  2. the detail-MODAL archetype reads the contract page's param route (/title/:id)
     and component ('TitleDetailPage' -> 'detail'), so title_detail is a modal even
     when the analyst gave the screen a non-param route + generic name (#523's r94
     failure mode: route '/browse', kind 'overlay').
  3. a LOGIN/SIGNIN route ALWAYS renders the spec-driven single-field template
     (deterministic from the route), even when the analyst quoted no copy — removing
     the run-to-run login variance (spec present -> single-field; spec absent -> the
     base two-field template). SIGNUP/register stays base when spec-less.
  4. the shared hero-title type-scale is capped (max 64px -> responsive clamp) so a
     96px vision-variance measurement can never wrap/overflow the billboard (games
     0.72->0.50 swing). Byte-identical when the measured size is within the cap.
"""
import env_generator.llm_generator.multi_agent.runtime.frontend_scaffold as fs
from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _wants_rows_539, _name_route_tokens_539, _SELECTOR_GRID_TOKENS_539,
    _render_reference_page, _project_page_component, _auth_page_src_540,
    _auth_spec_540, _is_login_route_546, _type_scale_style_438)


# --------------------------------- shared fixtures ---------------------------------

def _design(type_scale=None, assets=False):
    ds = {"palette": {"bg": "#141414", "accent": "#e50914"},
          "theme": {"default": "dark"}}
    if type_scale is not None:
        ds["type_scale"] = type_scale
    d = {"design_system": ds, "screens": [], "assets": []}
    if assets:
        d["assets"] = [{"id": "m1", "file": "backdrops/m1.jpg", "type": "jpg",
                        "staged_path": "public/assets/backdrops/m1.jpg"}]
    return d


_TOP_NAV = {"role": "top nav bar", "region": [0.0, 0.0, 1.0, 0.07]}
_CAROUSEL = {"role": "horizontal carousel of poster tiles",
             "region": [0.0, 0.12, 0.78, 0.4], "geometry": {"columns": 6, "rows": 1}}
_RIGHT_LIST = {"role": "vertical list of titles with thumbnails and descriptions",
               "region": [0.78, 0.1, 1.0, 0.95]}


def _rows_phrased_screen(name="browse", route="/browse"):
    """The analyst mis-decomposed a selector screen as a content browse: rows-token
    NAME + carousels + an invented right list panel — the exact r101/r102 phrasing
    that defeated #545's screen-only override."""
    return {"name": name, "route": route,
            "components": [_TOP_NAV, _CAROUSEL, _RIGHT_LIST]}


_GRID_MARKER = "gridTemplateColumns: 'repeat("


# ===== (1) selector screens: GRID + no invented aside, from the STABLE page =====

_SELECTOR_PAGES = [
    ("BrowseByLanguagesPage", "/browse/languages", "browse_by_languages"),
    ("ByLanguagesPage", "/by-languages", "by_languages"),
    ("PreferencesPage", "/preferences", "preferences"),
    ("SettingsPage", "/settings", "settings"),
    ("AccountPage", "/account", "account"),
    ("ProfilePage", "/profile", "profile"),
]


def test_546_selector_pages_force_grid_from_stable_page_despite_rows_screen():
    # The analyst screen is a generic rows-phrased content browse; the STABLE contract
    # page (route + component) forces GRID — deterministically for every selector page.
    for comp, route, nm in _SELECTOR_PAGES:
        screen = _rows_phrased_screen()                 # generic, rows-phrased
        page = {"name": nm, "route": route, "component": comp}
        assert _wants_rows_539(screen, None, page) == "grid", (comp, route)


def test_546_rows_phrased_selector_screen_alone_is_rows_baseline():
    # WITHOUT the stable page the analyst's rows-phrased screen misfires to rows
    # (the pre-#546 swing); the page-based override is what makes it robust.
    assert _wants_rows_539(_rows_phrased_screen(), None) == "rows"


def test_546_selector_grid_from_page_even_when_screen_missing():
    # a selector page whose analyst screen didn't resolve at all still grids.
    page = {"name": "browse_by_languages", "route": "/browse/languages",
            "component": "BrowseByLanguagesPage"}
    assert _wants_rows_539(None, None, page) == "grid"
    assert _wants_rows_539({}, None, page) == "grid"


def test_546_browse_by_languages_renders_grid_no_aside_no_carousel():
    screen = _rows_phrased_screen()
    page = {"name": "browse_by_languages", "route": "/browse/languages",
            "component": "BrowseByLanguagesPage", "apis_used": ["GET /api/titles"]}
    out = _render_reference_page("BrowseByLanguagesPage", page, screen, _design(),
                                 [("Home", "/browse")], "/api/titles")
    assert _GRID_MARKER in out                          # rendered as an option GRID
    assert "overflow-x-auto" not in out                # not content carousels
    assert "<aside" not in out                         # invented sidebar suppressed
    assert "justify-end overflow-hidden" not in out    # no hero billboard


def test_546_r102_exact_browse_by_languages_screen_is_grid():
    # the EXACT r102 case that scored 0.28 as a wrongly-rendered carousel: name
    # 'browse_by_languages' + route '/browse/languages' + preference/language-dropdown
    # components. The selector token wins over the co-present "browse" rows token ->
    # "grid" (deterministic even from the analyst screen alone, no page needed).
    screen = {"name": "browse_by_languages", "route": "/browse/languages", "components": [
        {"role": "preferences-label", "id": "preferences-label"},
        {"role": "original-language-dropdown", "id": "original-language-dropdown"}]}
    assert _wants_rows_539(screen, None, None) == "grid"


def test_546_by_languages_slug_tokenizes():
    # the "by-languages"/"bylanguages" slug forms are caught (not only "languages").
    for route in ("/by-languages", "/browse/languages", "/bylanguages"):
        page = {"route": route, "component": "P"}
        assert _name_route_tokens_539(page) & _SELECTOR_GRID_TOKENS_539, route


# -- byte-identical: a NON-selector page keeps its screen-only archetype + its aside --

def test_546_non_selector_page_archetype_byte_identical():
    screen = _rows_phrased_screen(name="movies", route="/movies")
    page = {"name": "movies", "route": "/movies", "component": "MoviesPage"}
    assert _wants_rows_539(screen, None) == _wants_rows_539(screen, None, page)


def test_546_non_selector_render_keeps_aside():
    screen = {"name": "messages", "route": "/messages", "components": [
        _TOP_NAV,
        {"role": "grid of tiles", "region": [0.0, 0.12, 0.78, 1.0],
         "geometry": {"columns": 6, "rows": 4}},
        _RIGHT_LIST]}
    page = {"name": "messages", "route": "/messages", "component": "MessagesPage"}
    out = _render_reference_page("MessagesPage", page, screen, _design(),
                                 [("Home", "/")], "/api/messages")
    assert "<aside" in out                              # suppression scoped to selectors


# ============ (2) title_detail: modal from the STABLE page route ============

def test_546_title_detail_modal_from_page_route_despite_generic_screen():
    # #523 r94 failure mode: the analyst gave the detail screen a NON-param route
    # ('/browse') + a generic name; the contract page (/title/:id + TitleDetailPage)
    # still forces the detail MODAL.
    screen = {"name": "browse", "route": "/browse", "kind": "page",
              "components": [{"role": "hero", "region": [0.0, 0.0, 1.0, 0.6]}]}
    page = {"name": "title_detail", "route": "/title/:id", "component": "TitleDetailPage"}
    out = _render_reference_page("TitleDetailPage", page, screen, _design(),
                                 [("Home", "/browse")], "/api/titles/{id}")
    assert "fixed inset-0 z-50" in out                  # scrim + centered modal
    assert "flex min-h-screen" not in out               # NOT the app-shell page
    assert 'aria-label="Close"' in out


def test_546_detail_named_param_component_is_modal():
    # a param route whose COMPONENT carries 'detail' (name/screen generic) -> modal.
    screen = {"name": "x", "route": "/x", "components": [
        {"role": "hero", "region": [0.0, 0.0, 1.0, 0.6]}]}
    page = {"name": "x", "route": "/product/:id", "component": "ProductDetailPage"}
    out = _render_reference_page("ProductDetailPage", page, screen, _design(),
                                 [("Home", "/")], "/api/products/{id}")
    assert "fixed inset-0 z-50" in out


def test_546_non_detail_param_route_stays_page():
    # a param route WITHOUT a detail/dialog/modal name is NOT a modal (genre_category
    # is a hero+rows content page) — byte-identical, no over-fire.
    screen = {"name": "genre_category", "route": "/browse/genre/:slug", "components": [
        {"role": "hero billboard", "region": [0.0, 0.0, 1.0, 0.6]},
        {"role": "poster rail", "region": [0.0, 0.65, 1.0, 0.85],
         "geometry": {"columns": 6}}]}
    page = {"name": "genre_category", "route": "/browse/genre/:slug",
            "component": "GenreCategoryPage"}
    out = _render_reference_page("GenreCategoryPage", page, screen, _design(),
                                 [("Home", "/")], "/api/genres/{id}/titles")
    assert "fixed inset-0 z-50" not in out              # a content page, not a modal
    assert "flex min-h-screen" in out


# ============ (3) login: spec-driven single-field from the route ============

def _plain_login_screen(route="/login", name="login"):
    # analyst decomposed only a generic email input + CTA, NO quoted copy -> spec None.
    return {"name": name, "route": route, "kind": "page", "components": [
        {"id": "form", "role": "email input and submit button",
         "region": [0.36, 0.22, 0.64, 0.36]},
        {"id": "footer", "role": "footer link columns", "region": [0.0, 0.9, 1.0, 1.0]}]}


def _pal():
    return _design()["design_system"]["palette"]


def test_546_login_route_is_spec_driven_without_quoted_copy():
    screen = _plain_login_screen()
    assert _auth_spec_540(screen) is None              # analyst quoted no copy
    out = _auth_page_src_540("LoginPage", {"route": "/login", "component": "LoginPage"},
                             screen, _design(), _pal(), None)
    assert out is not None
    assert "const single = true" in out                # single-field-first step
    assert "'Continue'" in out                         # Continue CTA
    assert "sm:p-12" in out                            # spec-template card (not base)
    assert "text-white/50" in out                      # NEUTRAL footer links
    assert "not a bot" in out                          # reCAPTCHA chrome (matches base)
    assert "/auth/login" in out and "/auth/register" in out  # wiring intact


def test_546_login_spec_driven_via_project_page_component():
    # _project_page_component is the path auth pages ALWAYS take.
    screen = _plain_login_screen()
    design = _design()
    design["screens"] = [screen]
    out = _project_page_component(
        "LoginPage", {"route": "/login", "name": "login", "component": "LoginPage"},
        nav_routes=[], design=design, get_endpoints=[])
    assert "const single = true" in out
    assert 'type="password"' in out                    # step-1 password reveal present


def test_546_signin_route_is_spec_driven():
    screen = _plain_login_screen(route="/signin", name="signin")
    out = _auth_page_src_540("SignInPage", {"route": "/signin", "component": "SignInPage"},
                             screen, _design(), _pal(), None)
    assert out is not None and "const single = true" in out


def test_546_signup_route_spec_less_falls_to_base():
    # a spec-less SIGNUP/register route returns None -> the caller keeps the base
    # template (byte-identical). #546 changes LOGIN only.
    screen = {**_plain_login_screen(route="/signup", name="signup"),
              "components": [{"id": "f", "role": "name email password field",
                              "region": [0.0, 0.0, 1.0, 1.0]}]}
    assert _auth_spec_540(screen) is None
    out = _auth_page_src_540("SignupPage", {"route": "/signup", "component": "SignupPage"},
                             screen, _design(), _pal(), None)
    assert out is None


def test_546_is_login_route_unit():
    assert _is_login_route_546("LoginPage", {"route": "/login"}) is True
    assert _is_login_route_546("SignInPage", {"route": "/signin"}) is True
    assert _is_login_route_546("X", {"route": "/x", "component": "LoginPage"}) is True
    # signup/register excluded (kept on the base template when spec-less)
    assert _is_login_route_546("SignupPage", {"route": "/signup"}) is False
    assert _is_login_route_546("RegisterPage", {"route": "/register"}) is False
    # non-auth route
    assert _is_login_route_546("MoviesPage", {"route": "/movies"}) is False


def test_546_login_spec_copy_still_used_when_analyst_quotes_it():
    # when the analyst DID quote copy, the spec drives the page (unchanged from #540).
    rich = {"name": "login", "route": "/login", "kind": "page", "components": [
        {"role": "primary page heading 'Enter your info to sign in'",
         "region": [0.36, 0.13, 0.62, 0.2]},
        {"role": "labeled email/mobile input", "region": [0.36, 0.24, 0.63, 0.32]},
        {"role": "primary CTA button 'Continue'", "region": [0.36, 0.33, 0.63, 0.4]}]}
    out = _auth_page_src_540("LoginPage", {"route": "/login", "component": "LoginPage"},
                             rich, _design(), _pal(), None)
    assert "Enter your info to sign in" in out
    assert 'placeholder="Email or phone number"' in out    # emailmobile from the spec


# ============ (4) hero-title type-scale clamp ============

def test_546_hero_title_clamped_over_cap():
    D = _design(type_scale=[{"role": "hero-title", "size_px": 96, "weight": 900}])
    s = _type_scale_style_438(D, ("hero-title",), max_px=64)
    assert "clamp(28px, 5vw, 64px)" in s
    assert "'96px'" not in s
    assert "fontWeight: 900" in s                       # weight untouched


def test_546_hero_title_within_cap_byte_identical():
    D = _design(type_scale=[{"role": "hero-title", "size_px": 56, "weight": 700}])
    s_cap = _type_scale_style_438(D, ("hero-title",), max_px=64)
    s_nocap = _type_scale_style_438(D, ("hero-title",))
    assert s_cap == s_nocap == ", fontSize: '56px', fontWeight: 700"


def test_546_type_scale_no_max_px_byte_identical():
    # default (no max_px) NEVER clamps -> byte-identical for every non-hero caller.
    D = _design(type_scale=[{"role": "modal-title", "size_px": 120, "weight": 700}])
    assert _type_scale_style_438(D, ("modal-title",)) == ", fontSize: '120px', fontWeight: 700"


def test_546_hero_render_caps_title():
    D = _design(type_scale=[{"role": "hero-title", "size_px": 96, "weight": 900}],
                assets=True)
    hero = {"route": "/browse", "name": "browse_home", "components": [
        {"id": "hero", "role": "hero billboard title art",
         "region": [0.0, 0.05, 1.0, 0.6], "assets": ["m1"]},
        {"id": "rail", "role": "poster rail of Trending",
         "region": [0.0, 0.65, 1.0, 0.85], "geometry": {"columns": 6}}]}
    out = _render_reference_page("BrowseHomePage", {"route": "/browse"}, hero, D,
                                 [("Home", "/browse")], "/api/titles")
    assert "clamp(28px, 5vw, 64px)" in out
    assert "fontSize: '96px'" not in out


# ============ no-regression: the robust #539 wins are preserved ============

def test_546_new_and_popular_stays_rows():
    screen = {"route": "/new", "name": "new_and_popular", "components": []}
    page = {"route": "/new", "name": "new_and_popular", "component": "NewAndPopularPage"}
    assert _wants_rows_539(screen, None) == "rows"
    assert _wants_rows_539(screen, None, page) == "rows"     # page never flips it


def test_546_movies_defers_unchanged():
    screen = {"route": "/movies", "name": "movies", "components": []}
    page = {"route": "/movies", "name": "movies", "component": "MoviesPage"}
    assert _wants_rows_539(screen, None) is None
    assert _wants_rows_539(screen, None, page) is None


def test_546_games_not_reclassified_to_grid():
    screen = {"route": "/games", "name": "games", "components": [
        {"role": "hero billboard", "region": [0.0, 0.07, 1.0, 0.82]},
        {"role": "horizontal carousel of game tiles",
         "region": [0.0, 0.86, 1.0, 1.0], "geometry": {"columns": 6, "rows": 1}}]}
    page = {"route": "/games", "name": "games", "component": "GamesPage"}
    assert _wants_rows_539(screen, None, page) != "grid"


def test_546_data_shape_signal_survives_page_arg():
    # #539 data-shape classifier is unchanged when a page is threaded through.
    grouped = [{"genre": "Action"}] * 3 + [{"genre": "Comedy"}] * 3
    assert _wants_rows_539({"name": "x"}, grouped, {"route": "/x"}) == "rows"
    flat = [{"title": "a"}, {"title": "b"}]
    assert _wants_rows_539({"name": "x"}, flat, {"route": "/x"}) == "grid"


# -------------------------------- no product literals --------------------------------

def test_546_no_product_literals():
    outs = [
        _render_reference_page(
            "BrowseByLanguagesPage",
            {"name": "browse_by_languages", "route": "/browse/languages",
             "component": "BrowseByLanguagesPage"},
            _rows_phrased_screen(), _design(), [("Home", "/browse")], "/api/titles"),
        _auth_page_src_540("LoginPage", {"route": "/login", "component": "LoginPage"},
                           _plain_login_screen(), _design(), _pal(), None),
    ]
    for out in outs:
        low = (out or "").lower()
        for bad in ("netflix", "disney", "hulu", "spotify"):
            assert bad not in low


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
