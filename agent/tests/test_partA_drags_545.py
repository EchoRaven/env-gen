"""#545 (netflix, run netflix-web-r101, 2026-08-06) — the three Part-A drags that
kept blocking_average at 0.596 (< 0.65):

  browse_by_languages 0.60 -> 0.35 (DETERMINISTIC, #539 regression): #539's
     rows-forcing token set includes "browse", so a LANGUAGE-SELECTOR grid was
     rendered as content carousels; and the projector's right list-panel <aside>
     added an invented "Browse By Languages" sidebar. FIX: a SELECTOR/preference/
     settings name/route token (languages/preferences/settings/account/profile/
     genres) forces GRID (overrides "browse") AND suppresses the invented right
     aside — for those screens only (byte-identical everywhere else).

  games 0.72 -> 0.50 (VARIANCE, not a code regression): identical projected
     template both runs; only the design analyst's vision output moved (hero
     type-scale 18px -> 96px, GLOBAL to every hero page; CTA decomposition
     "Play Game" -> "Play"). No #539/#543 side-effect -> no code change. Guarded
     here so the selector-grid change never accidentally reclassifies games.

  login ~0.50 (DETERMINISTIC, #540 never fired): #540's spec-driven auth page
     (single email/mobile step + Continue + neutral footer + gradient) was wired
     ONLY into _render_reference_page, but auth pages are ALWAYS projected via
     _project_page_component (base two-field template). FIX: wire #540 into
     _project_page_component's auth branch. _auth_spec_540 already detects the
     single-step STRUCTURALLY (an email/mobile input, no quoted copy needed).

Every fix is additive + byte-identical when its selector/spec signal is ABSENT;
no product literals — all copy is read from the design spec or generic fallbacks,
all tokens are generic UI-pattern words.
"""
import env_generator.llm_generator.multi_agent.runtime.frontend_scaffold as fs
from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _wants_rows_539, _name_route_tokens_539, _SELECTOR_GRID_TOKENS_539,
    _render_reference_page, _project_page_component, _auth_spec_540)


# ─────────────────────────────── shared fixtures ───────────────────────────────

def _design():
    return {"design_system": {"palette": {"bg": "#141414", "accent": "#e50914"},
                              "theme": {"default": "dark"}},
            "screens": [], "assets": []}


def _screen(name, route, components=None):
    return {"name": name, "route": route, "components": components or []}


# a right-band component the projector turns into a list-panel <aside> (kind "list").
_RIGHT_LIST = {"role": "vertical list of titles with thumbnails and descriptions",
               "region": [0.78, 0.1, 1.0, 0.95]}
_MAIN_GRID = {"role": "grid of poster tiles", "region": [0.0, 0.12, 0.78, 1.0],
              "geometry": {"columns": 6, "rows": 4}}
_TOP_NAV = {"role": "top nav bar", "region": [0.0, 0.0, 1.0, 0.07]}


def _render(screen, name="Page", get_ep="/api/titles", design=None):
    return _render_reference_page(name, {"route": screen.get("route")}, screen,
                                  design or _design(), [("Home", "/")], get_ep)


# ═══════════════ (1) browse_by_languages: SELECTOR grid overrides "browse" ═══════════════

def test_545_browse_by_languages_is_grid_not_rows():
    # name/route carries BOTH "browse" (rows) and "languages" (selector) — selector wins.
    s = _screen("browse_by_languages", "/browse/languages")
    assert _wants_rows_539(s, None) == "grid"


def test_545_selector_preference_settings_screens_are_grids():
    for name, route in (("languages", "/languages"),
                        ("preferences", "/preferences"),
                        ("settings", "/settings"),
                        ("account", "/account"),
                        ("profile", "/profile"),
                        ("browse_by_languages", "/browse/languages")):
        assert _wants_rows_539(_screen(name, route), None) == "grid", name


def test_545_content_browses_still_rows():
    # the win screens must NOT be reclassified — content browses stay rows.
    for name, route in (("browse_home", "/browse"),
                        ("home", "/"),
                        ("trending", "/trending"),
                        ("browse", "/browse")):
        assert _wants_rows_539(_screen(name, route), None) == "rows", name


def test_545_genre_category_singular_stays_rows():
    # 'genres' (plural, the picker) is a selector token; 'genre' (a single genre's
    # content page) is NOT — genre_category must remain a hero+rows content page.
    s = _screen("genre_category", "/browse/genre/:genreId")
    assert _wants_rows_539(s, None) == "rows"


def test_545_selector_tokens_dont_collide_with_content_screens():
    for name in ("browse_home", "movies", "shows", "new_and_popular",
                 "games", "login", "my_list", "genre_category", "player",
                 "title_detail", "landing"):
        toks = _name_route_tokens_539(_screen(name, "/" + name))
        assert not (toks & _SELECTOR_GRID_TOKENS_539), (name, toks & _SELECTOR_GRID_TOKENS_539)


def test_545_browse_by_languages_render_is_grid_without_invented_sidebar():
    s = _screen("browse_by_languages", "/browse/languages",
                [_TOP_NAV, _MAIN_GRID, _RIGHT_LIST])
    out = _render(s, name="BrowseByLanguagesPage")
    assert "gridTemplateColumns: 'repeat(" in out          # rendered as a grid
    assert "overflow-x-auto" not in out                    # not content carousels
    assert "<aside" not in out                             # invented sidebar suppressed


def test_545_right_aside_preserved_for_non_selector_screens():
    # SAME right-band list on a NON-selector screen keeps its <aside> — the
    # suppression is scoped to selector/preference/settings screens (byte-identical
    # right-band behavior for every other screen).
    s = _screen("messages", "/messages", [_TOP_NAV, _MAIN_GRID, _RIGHT_LIST])
    out = _render(s, name="MessagesPage")
    assert "<aside" in out


# ═══════════════ (2) games: VARIANCE guard — never reclassified to grid ═══════════════

def test_545_games_not_reclassified_to_grid():
    games = _screen("games", "/games", [
        {"role": "hero billboard", "region": [0.0, 0.07, 1.0, 0.82]},
        {"role": "section heading for first rail", "region": [0.03, 0.82, 0.3, 0.86]},
        {"role": "horizontal carousel of game tiles",
         "region": [0.0, 0.86, 1.0, 1.0], "geometry": {"columns": 6, "rows": 1}},
    ])
    # games carries no selector token -> the #545 grid precedence must not fire.
    assert _wants_rows_539(games, None) != "grid"


# ═══════════════ (3) login: #540 spec-detection + wiring into the real path ═══════════════

def _login_screen(emailmobile=True, password=False, heading_quote=None):
    comps = [
        {"role": "header bar with brand logo", "id": "top-bar",
         "region": [0.0, 0.0, 1.0, 0.09]},
        {"role": (("primary page heading %r" % heading_quote) if heading_quote
                  else "primary page heading for sign-in form"),
         "id": "signin-heading", "region": [0.35, 0.12, 0.65, 0.17]},
        {"role": ("labeled text input field for email/mobile" if emailmobile
                  else "labeled email input field"),
         "id": "email-input", "region": [0.35, 0.3, 0.65, 0.36]},
        {"role": "primary CTA button spanning form width", "id": "continue-button",
         "region": [0.35, 0.4, 0.65, 0.46]},
        {"role": "small legal/recaptcha disclaimer line", "id": "recaptcha",
         "region": [0.35, 0.5, 0.65, 0.54]},
    ]
    if password:
        comps.append({"role": "password input field", "id": "password-input",
                      "region": [0.35, 0.36, 0.65, 0.4]})
    return {"name": "login", "route": "/login", "kind": "page", "components": comps}


def _design_with(login_screen):
    d = _design()
    d["screens"] = [login_screen]
    return d


def test_545_auth_spec_detects_single_step_structurally():
    # an email/mobile input with NO quoted copy is still a signal (single-step flow).
    spec = _auth_spec_540(_login_screen(emailmobile=True, password=False))
    assert spec is not None
    assert spec["single"] is True
    assert spec["emailmobile"] is True


def test_545_auth_spec_two_field_is_not_single():
    # a declared password field makes it a two-step form: single=False. (Give it a
    # quoted heading so the spec is returned rather than None-for-no-signal.)
    spec = _auth_spec_540(_login_screen(emailmobile=True, password=True,
                                        heading_quote="Sign in to continue"))
    assert spec is not None and spec["single"] is False


def test_545_login_projected_via_real_path_is_spec_driven():
    # _project_page_component is the path auth pages ALWAYS take; #540 must fire here.
    login = _login_screen(emailmobile=True, password=False)
    out = _project_page_component(
        "LoginPage", {"route": "/login", "name": "login", "component": "LoginPage"},
        nav_routes=[], design=_design_with(login), get_endpoints=[])
    assert "const single = true" in out          # single-step flow
    assert "'Continue'" in out                   # Continue CTA (not "Log in")
    assert "text-white/50" in out                # NEUTRAL (gray) footer links
    assert "New to Netflix" not in out           # not the base two-field template


def test_545_login_uses_spec_copy_when_quoted():
    login = _login_screen(emailmobile=True, password=False,
                          heading_quote="Enter your info to sign in")
    out = _project_page_component(
        "LoginPage", {"route": "/login", "name": "login", "component": "LoginPage"},
        nav_routes=[], design=_design_with(login), get_endpoints=[])
    assert "Enter your info to sign in" in out


def test_545_spec_less_auth_falls_back_to_base_template():
    # #546 SUPERSEDES this for LOGIN routes (a login route now ALWAYS renders the
    # spec-driven single-field template — see test_reliability_546). A spec-less
    # SIGNUP/register route still falls to the base template (byte-identical).
    plain = {**_login_screen(emailmobile=False, password=True),
             "name": "signup", "route": "/signup"}
    assert _auth_spec_540(plain) is None
    out = _project_page_component(
        "SignupPage", {"route": "/signup", "name": "signup", "component": "SignupPage"},
        nav_routes=[], design=_design_with(plain), get_endpoints=[])
    assert "const single = true" not in out      # NOT the spec-driven page
    assert 'type="password"' in out              # base template
