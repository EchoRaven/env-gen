"""#526 (netflix, 2026-08-06) — the projector must paint each screen's OWN
measured background, not one global content bg on every screen.

GROUND TRUTH: design/design_system.json captures per-screen surfaces at
design_system.material.surfaces (e.g. login -> a dark-red vertical gradient
{top_color:#3a1616, bottom_color:#000000}; player -> flat {color:#000000};
landing -> an image {kind: poster_mosaic_wallpaper}) plus per-component measured
colors.bg. The projector ignored all of it and filled every root with
_content_bg(pal). FIX #526: _screen_surface_bg(design, screen, pal) resolves the
screen's own surface (gradient / flat / component page-bg), wired into the three
root paint sites (reference page, landing, auth). None => byte-identical output.

These tests lock the helper's resolution order, the deferral of image surfaces,
the no-surfaces component fallback, the never-raise contract, the structural
kind aliases, and the byte-identical property (None => caller keeps _content_bg).
"""
from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _screen_surface_bg, _surf_style_attr_526, _content_bg)


def _design_grad():
    # login: measured dark-red -> black vertical gradient (top/bottom hex).
    return {"design_system": {"material": {"surfaces": {
        "login": {"kind": "dark_red_vignette_gradient",
                  "top_color": "#3a1616", "bottom_color": "#000000",
                  "notes": "measured top strip vs black body"}}}}}


def _design_flat():
    # player: pure black flat surface.
    return {"design_system": {"material": {"surfaces": {
        "player": {"kind": "flat", "color": "#000000"}}}}}


def _design_mosaic():
    # landing: image/kind-only surface -> deferred (#527), returns None.
    return {"design_system": {"material": {"surfaces": {
        "landing": {"kind": "poster_mosaic_wallpaper",
                    "notes": "rotated grid of posters"}}}}}


def _design_component_only():
    # NO surfaces map at all -> component-bg fallback is allowed.
    return {
        "design_system": {"palette": {"page": "#141414", "bg": "#000000"}},
        "screens": [{"name": "home", "kind": "page", "components": [
            {"id": "page-background", "region": [0.0, 0.0, 1.0, 1.0],
             "colors": {"bg": "#0b0b0b"}},
            {"id": "hero-billboard", "region": [0.0, 0.0, 1.0, 0.4],
             "colors": {"bg": "#ff0000"}},  # large but partial + not a page id
        ]}],
    }


def _design_surfaces_present_screen_unkeyed():
    # surfaces exist but this screen isn't keyed -> keep the global bg (no regress).
    return {
        "design_system": {
            "material": {"surfaces": {
                "login": {"top_color": "#3a1616", "bottom_color": "#000000"}}},
            "palette": {"page": "#141414", "bg": "#000000"}},
        "screens": [{"name": "browse_home", "kind": "page", "components": [
            {"id": "hero-billboard", "region": [0.0, 0.0, 1.0, 0.8],
             "colors": {"bg": "#000000"}}]}],
    }


# ── (a) gradient surface ─────────────────────────────────────────────────────
def test_gradient_surface_returns_linear_gradient():
    out = _screen_surface_bg(_design_grad(), {"name": "login", "kind": "page"})
    assert out is not None
    assert out["prop"] == "background"
    assert "linear-gradient" in out["value"]
    assert "#3a1616" in out["value"] and "#000000" in out["value"]


def test_gradient_surface_via_string_screen():
    out = _screen_surface_bg(_design_grad(), "login")
    assert out and out["prop"] == "background" and "linear-gradient" in out["value"]


# ── (a) flat surface ─────────────────────────────────────────────────────────
def test_flat_color_surface_returns_background_color():
    out = _screen_surface_bg(_design_flat(), {"name": "player", "kind": "page"})
    assert out == {"prop": "backgroundColor", "value": "#000000"}


# ── (a) image/kind-only surface is deferred ──────────────────────────────────
def test_mosaic_kind_only_surface_returns_none():
    assert _screen_surface_bg(_design_mosaic(), {"name": "landing"}) is None


# ── (b) no-surfaces component fallback ───────────────────────────────────────
def test_component_bg_fallback_when_no_surfaces():
    d = _design_component_only()
    # via string (looks up screens[]) and via the screen dict directly.
    assert _screen_surface_bg(d, "home") == {
        "prop": "backgroundColor", "value": "#0b0b0b"}
    assert _screen_surface_bg(d, d["screens"][0]) == {
        "prop": "backgroundColor", "value": "#0b0b0b"}


def test_component_fallback_ignores_large_but_partial_non_page_component():
    # the partial red hero (area 0.4, no page id) must never win the page bg.
    out = _screen_surface_bg(_design_component_only(), "home")
    assert out["value"] != "#ff0000"


# ── (c) / byte-identical: None => caller keeps _content_bg ────────────────────
def test_surfaces_present_but_screen_unkeyed_returns_none():
    d = _design_surfaces_present_screen_unkeyed()
    screen = d["screens"][0]
    assert _screen_surface_bg(d, screen) is None
    # semantic: the render root then still paints _content_bg(pal) = the page bg.
    pal = d["design_system"]["palette"]
    assert _content_bg(pal) == "#141414"


def test_empty_and_missing_design_return_none_no_raise():
    for d in ({}, None, {"design_system": {}},
              {"design_system": {"material": {"surfaces": "not-a-dict"}}}):
        assert _screen_surface_bg(d, "login") is None
    # malformed screen inputs never raise either.
    assert _screen_surface_bg(_design_grad(), None) is None
    assert _screen_surface_bg(_design_grad(), 123) is None


# ── structural kind aliases (auth->login, watch->player) ─────────────────────
def test_kind_aliases_resolve_login_and_player():
    assert _screen_surface_bg(_design_grad(), "LoginPage")["prop"] == "background"
    assert _screen_surface_bg(_design_grad(), {"route": "/login"})["prop"] == "background"
    assert _screen_surface_bg(_design_grad(), {"name": "SignUp"})["prop"] == "background"
    assert _screen_surface_bg(_design_flat(), {"name": "player_controls",
                                               "kind": "overlay"}) == {
        "prop": "backgroundColor", "value": "#000000"}


def test_alias_is_whole_token_not_substring():
    # "watchlist" contains "watch" as a substring but must NOT alias to player.
    assert _screen_surface_bg(_design_flat(), "watchlist") is None
    assert _screen_surface_bg(_design_flat(), "my_list") is None


# ── JSX style-attr fragment ──────────────────────────────────────────────────
def test_surf_style_attr_fragment():
    assert _surf_style_attr_526(None) == ""
    grad = {"prop": "background", "value": "linear-gradient(180deg, #3a1616 0%, #000000 100%)"}
    assert _surf_style_attr_526(grad) == (
        " style={{ background: 'linear-gradient(180deg, #3a1616 0%, #000000 100%)' }}")
    assert _surf_style_attr_526({"prop": "backgroundColor", "value": "#000000"}) == (
        " style={{ backgroundColor: '#000000' }}")
