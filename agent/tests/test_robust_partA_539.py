"""#539-#544 (netflix, run netflix-web-r100, 2026-08-06) — five generalizable
projector fixes that reliably lift Part-A visual fidelity despite the design
analyst's per-run PHRASING VARIANCE (r100 scored 0.534 vs r99 0.642 on identical
code: the #538 rows-vs-grid gate matched the literal substring "header"/"section
title", and r100 re-slugged the bands to "section heading" so a stacked-shelf home
collapsed into ONE flat grid).

  #539 robust rows-vs-grid archetype — decide from STABLE signals (route/name
       UI-pattern token -> row DATA shape -> a robust shelf-band count), never the
       fragile substring. Surface a rail's adjacent QUOTED title regardless of the
       run's wording; route a messy/undetected-header multi-rail through _deriveRows.
  #540 spec-driven auth template — heading/subheading/button copy + a single
       email-or-mobile step + help/reCAPTCHA + measured gradient + NEUTRAL footer.
  #541 spec-driven landing — poster-collage bg + subheadline + email-prompt + promo
       banner + language selector, from the measured spec.
  #543 data floor — pad an under-filled grid/rail from the staged poster pool.
  #544 player — full-bleed landscape media + real sized control icons.

Every fix is additive + byte-identical when its signal/spec/data is ABSENT; no
product literals — all copy is read from the design spec, all tokens are generic
UI-pattern words.
"""
import re

import env_generator.llm_generator.multi_agent.runtime.frontend_scaffold as fs
from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _render_reference_page, _landing_page_src, _wants_rows_539,
    _count_header_bands_539, _is_header_band_539, _auth_spec_540)


# ─────────────────────────────── shared fixtures ───────────────────────────────

def _design(assets=True):
    d = {"design_system": {"palette": {"bg": "#141414", "accent": "#e50914"},
                           "theme": {"default": "dark"}},
         "assets": []}
    if assets:
        d["assets"] = [
            {"id": "b%d" % i, "file": "backdrops/b%d.jpg" % i, "type": "jpg",
             "staged_path": "public/assets/backdrops/b%d.jpg" % i} for i in range(6)]
    return d


def _render(screen, name="Page", get_ep="/api/titles", design=None):
    return _render_reference_page(name, {"route": screen.get("route")}, screen,
                                  design or _design(), [("Home", "/")], get_ep)


_GRID_MARKER = "gridTemplateColumns: 'repeat("


# ═══════════════════════════ #539 rows-vs-grid archetype ═══════════════════════

# r100 phrasing: "section heading" bands (NOT "header"/"section title") + carousels.
def _new_and_popular_r100():
    return {"route": "/new", "name": "new_and_popular", "components": [
        {"role": "section heading for first rail", "region": [0.03, 0.13, 0.3, 0.17]},
        {"role": "horizontal carousel of large landscape thumbnails with TOP 10 badges",
         "region": [0.03, 0.17, 1.0, 0.32], "geometry": {"columns": 6, "rows": 1}},
        {"role": "section heading 'Top 10 TV Shows in the U.S. Today'",
         "region": [0.03, 0.36, 0.35, 0.4]},
        {"role": "horizontal carousel of ranked poster tiles with large numeral overlays",
         "region": [0.03, 0.4, 1.0, 0.62], "geometry": {"columns": 6, "rows": 1}},
        {"role": "section heading 'Coming This Week'", "region": [0.03, 0.65, 0.35, 0.69]},
        {"role": "horizontal carousel of ranked movie posters with numeric overlays",
         "region": [0.03, 0.69, 1.0, 0.92], "geometry": {"columns": 6, "rows": 1}},
    ]}


def test_539_new_and_popular_renders_rows_despite_reslug():
    """r100: 'section heading' bands would defeat the #538 substring test, but the
    name token ('new'+'popular') forces ROWS -> stacked carousels, not a flat grid."""
    out = _render(_new_and_popular_r100(), name="NewAndPopularPage")
    assert _GRID_MARKER not in out, "collapsed into a flat grid (the r100 regression)"
    assert "_railSlice(rows, 3, 0)" in out and "_railSlice(rows, 3, 2)" in out


def test_539_adjacent_quoted_title_surfaced():
    """A rail's adjacent QUOTED 'section heading' title is used as the shelf heading
    regardless of the run's wording (title extraction is phrasing-robust now)."""
    out = _render(_new_and_popular_r100(), name="NewAndPopularPage")
    assert "Top 10 TV Shows in the U.S. Today" in out
    assert "Coming This Week" in out


def test_539_my_list_stays_grid():
    """'my_list' -> the 'list' token forces GRID (a saved/owned collection), even
    when it decomposed into per-row rails."""
    scr = {"route": "/my-list", "name": "my_list", "components": [
        {"role": "poster row alpha", "region": [0.02, 0.24, 0.9, 0.37],
         "geometry": {"columns": 6}},
        {"role": "poster row beta", "region": [0.02, 0.40, 0.9, 0.53],
         "geometry": {"columns": 6}}]}
    out = _render(scr, name="MyListPage", get_ep="/api/my-list")
    assert _GRID_MARKER in out and "overflow-x-auto" not in out


def test_539_browse_route_forces_rows():
    """A /browse route (name token-less) forces ROWS -> generic rails are NOT
    flattened to a grid (rule A overrides the fragile structural expression)."""
    scr = {"route": "/browse", "name": "feed", "components": [
        {"role": "poster row one", "region": [0.0, 0.2, 1.0, 0.4],
         "geometry": {"columns": 6}},
        {"role": "poster row two", "region": [0.0, 0.45, 1.0, 0.65],
         "geometry": {"columns": 6}}]}
    out = _render(scr, name="BrowsePage")
    assert _GRID_MARKER not in out and "overflow-x-auto" in out


def test_539_data_shape_unit():
    # >=2 category groups of >=3 -> rows; rank field -> rows; flat -> grid
    grouped = [{"genre": "Action"}] * 3 + [{"genre": "Comedy"}] * 3
    assert _wants_rows_539({"name": "x"}, grouped) == "rows"
    ranked = [{"top10_rank": 1}, {"top10_rank": 2}]
    assert _wants_rows_539({"name": "x"}, ranked) == "rows"
    flat = [{"title": "a"}, {"title": "b"}]
    assert _wants_rows_539({"name": "x"}, flat) == "grid"
    assert _wants_rows_539({"name": "x"}, None) is None      # no signal -> defer


def test_539_header_band_detection_phrasing_robust():
    # real shelf-label bands are short wide strips (a region distinguishes them from
    # a full-width rail even when the role text happens to contain 'rail')
    _hb = lambda role: {"role": role, "region": [0.03, 0.1, 0.3, 0.14]}
    assert _is_header_band_539(_hb("section heading for first rail")) is True
    assert _is_header_band_539(_hb("row title 'TV Action & Adventure'")) is True
    assert _is_header_band_539(_hb("section heading 'Coming This Week'")) is True
    # a nav header BAR is not a shelf-label band; a rail is not a header band
    assert _is_header_band_539(
        {"role": "header bar with brand wordmark", "region": [0.0, 0.0, 1.0, 0.06]}) is False
    assert _is_header_band_539(
        {"role": "horizontal poster rail of trending",
         "region": [0, 0.2, 1, 0.4], "geometry": {"columns": 6}}) is False
    assert _count_header_bands_539(_new_and_popular_r100()) >= 3


def test_539_byte_identical_when_current_logic_agrees():
    """A single-collection screen (no name token, no data, no shelf bands) still
    renders a GRID -> _wants_rows_539 returns None and the #538 expression stands."""
    scr = {"route": "/movies", "name": "movies", "components": [
        {"role": "title thumbnails", "region": [0.0, 0.28, 1.0, 0.50],
         "geometry": {"columns": 5}},
        {"role": "title thumbnails", "region": [0.0, 0.52, 1.0, 0.74],
         "geometry": {"columns": 5}}]}
    assert _wants_rows_539(scr, None) is None
    out = _render(scr, name="MoviesPage")
    assert _GRID_MARKER in out and "overflow-x-auto" not in out


def test_539_messy_multirail_routed_through_derive_rows():
    """A multi-rail page whose header bands are ALL undetected (no title, no quoted
    copy) routes through _deriveRows so shelves get data-derived titles at runtime;
    with a rows-name token the archetype is rows, not a grid."""
    scr = {"route": "/new", "name": "new_and_popular", "components": [
        {"role": "poster carousel one", "region": [0.0, 0.2, 1.0, 0.4],
         "geometry": {"columns": 6}},
        {"role": "poster carousel two", "region": [0.0, 0.45, 1.0, 0.65],
         "geometry": {"columns": 6}}]}
    out = _render(scr, name="NewAndPopularPage")
    assert _GRID_MARKER not in out
    assert "_deriveRows" in out, "undetected-header multi-rail -> runtime data rows"


# ═══════════════════════════ #540 spec-driven auth ═════════════════════════════

_LOGIN_SPEC = {"route": "/login", "name": "login", "kind": "page", "components": [
    {"role": "header bar with brand wordmark logo at left", "region": [0.0, 0.0, 1.0, 0.095]},
    {"role": "primary page heading 'Enter your info to sign in'",
     "region": [0.36, 0.13, 0.62, 0.2]},
    {"role": "secondary line 'Or get started with a new account.'",
     "region": [0.36, 0.19, 0.55, 0.23]},
    {"role": "labeled email/mobile input containing prefilled value",
     "region": [0.36, 0.24, 0.63, 0.32]},
    {"role": "primary CTA button 'Continue' below input", "region": [0.36, 0.33, 0.63, 0.4]},
    {"role": "expandable 'Get Help' link with chevron", "region": [0.36, 0.42, 0.43, 0.46]},
    {"role": "reCAPTCHA protection disclaimer text", "region": [0.36, 0.475, 0.63, 0.51]},
    {"role": "footer section with contact info and link columns", "region": [0.0, 0.92, 1.0, 1.0]},
]}

# the pre-#540 fixture (no quoted copy, plain email input) -> no spec signal.
_LOGIN_NO_SPEC = {"route": "/login", "name": "login", "kind": "page", "components": [
    {"id": "form", "region": [0.36, 0.22, 0.64, 0.36], "role": "email input + CTA"},
    {"id": "footer", "region": [0.0, 0.9, 1.0, 1.0], "role": "footer link columns"}]}


def test_540_spec_extraction_unit():
    spec = _auth_spec_540(_LOGIN_SPEC)
    assert spec is not None
    assert spec["single"] is True and spec["emailmobile"] is True
    assert spec["heading"] == "Enter your info to sign in"
    assert spec["subheading"] == "Or get started with a new account."
    assert spec["button"] == "Continue" and spec["recaptcha"] is True
    # a plain email input with no quoted copy is NOT a spec signal
    assert _auth_spec_540(_LOGIN_NO_SPEC) is None


def test_540_single_input_and_spec_copy():
    out = _render_reference_page("LoginPage", {"route": "/login", "id": "login_page"},
                                 _LOGIN_SPEC, _design(), [("Home", "/browse")], "")
    # spec copy
    assert "Enter your info to sign in" in out
    assert "Or get started with a new account." in out
    # single email-or-mobile step + Continue
    assert "const single = true;" in out
    assert 'type="text"' in out and 'placeholder="Email or phone number"' in out
    assert "'Continue'" in out
    # help + reCAPTCHA disclaimer
    assert "Get Help" in out and "not a bot" in out
    # functional auth wiring intact
    assert "/auth/login" in out and "/auth/register" in out


def test_540_neutral_footer_links():
    out = _render_reference_page("LoginPage", {"route": "/login", "id": "login_page"},
                                 _LOGIN_SPEC, _design(), [("Home", "/browse")], "")
    # NEUTRAL footer (not the accent-red link class); reference legal columns present
    assert "text-white/50" in out
    assert "Terms of Use" in out and "Help Center" in out
    # the accent brand-red is never applied to a footer link anchor
    assert "text-accent" not in out.split("<footer", 1)[1]


def test_540_byte_identical_without_spec():
    # #546 SUPERSEDES this for LOGIN routes (a login route now ALWAYS renders the
    # spec-driven single-field template). A spec-less SIGNUP/register route still
    # uses the base template unchanged (byte-identical).
    signup = {**_LOGIN_NO_SPEC, "route": "/signup", "name": "signup", "id": "signup_page"}
    out = _render_reference_page("SignupPage", {"route": "/signup", "id": "signup_page"},
                                 signup, _design(), [("Home", "/browse")], "")
    # the base template (no single-step, no spec markers) is used unchanged
    assert "shadow-sm" in out                       # base-template card
    assert "sm:p-12" not in out                      # spec-template-only card padding
    assert "const single =" not in out
    assert "/auth/login" in out and "not a bot" in out


def test_540_no_product_literals():
    out = _render_reference_page("LoginPage", {"route": "/login", "id": "login_page"},
                                 _LOGIN_SPEC, _design(), [("Home", "/browse")], "")
    for bad in ("netflix", "disney", "hulu", "spotify"):
        assert bad not in out.lower()


# ═══════════════════════════ #541 spec-driven landing ═════════════════════════

_LANDING_RICH = {"route": "/", "name": "landing", "components": [
    {"role": "full-bleed background of tilted poster tiles behind hero content"},
    {"role": "large centered hero title text"},
    {"role": "smaller tagline text under headline 'Unlimited movies and shows'"},
    {"role": "instructional line above signup form 'Ready to watch?'"},
    {"role": "email input plus Get Started CTA arranged horizontally"},
    {"role": "bottom promotional banner 'Plans start low'"},
    {"role": "language dropdown pill in header right"},
]}


def test_541_rich_landing_emits_spec_elements():
    out = _landing_page_src("LandingPage", "Landing", {"route": "/"},
                            _design(), _LANDING_RICH)
    # poster-collage background from the staged pool
    assert "sm:grid-cols-6" in out and "/assets/backdrops/b0.jpg" in out
    assert "radial-gradient" in out                  # collage scrim
    # subheadline + email-prompt copy from the spec
    assert "Unlimited movies and shows" in out
    assert "Ready to watch?" in out
    # promo banner + language selector
    assert "Learn More" in out and "Plans start low" in out
    assert ">English<" in out or "English" in out
    # the email capture row survives
    assert 'type="email"' in out and "Get Started" in out


def test_541_absent_spec_is_stub_byte_identical():
    # a landing screen with no rich components -> the current stub (byte-identical)
    plain = {"route": "/", "name": "landing", "components": [
        {"role": "large centered marketing headline"}]}
    out = _landing_page_src("LandingPage", "Landing", {"route": "/"}, _design(), plain)
    assert 'className="flex min-h-screen flex-col"' in out    # no collage positioning
    assert "sm:grid-cols-6" not in out and "radial-gradient" not in out
    assert "Learn More" not in out
    # no-screen path is also the stub
    out2 = _landing_page_src("LandingPage", "Landing", {"route": "/"}, _design(), None)
    assert "sm:grid-cols-6" not in out2


def test_541_no_product_literals():
    out = _landing_page_src("LandingPage", "Landing", {"route": "/"},
                            _design(), _LANDING_RICH)
    for bad in ("netflix", "disney", "hulu", "spotify"):
        assert bad not in out.lower()


# ═══════════════════════════ #543 data floor padding ══════════════════════════

def test_543_pad_helper_emitted():
    out = _render(_new_and_popular_r100(), name="NewAndPopularPage")
    assert "const _padN = (arr, n) =>" in out
    # never pads an empty (loading) collection, and returns unchanged once >= n
    assert "if (!a.length || a.length >= n) return a;" in out


def test_543_rail_padded_to_six():
    out = _render(_new_and_popular_r100(), name="NewAndPopularPage")
    assert "_padN(_railSlice(rows, 3, 0), 6).map" in out


def test_543_grid_padded_to_eight():
    scr = {"route": "/my-list", "name": "my_list", "components": [
        {"role": "poster row alpha", "region": [0.02, 0.24, 0.9, 0.37],
         "geometry": {"columns": 6}}]}
    out = _render(scr, name="MyListPage", get_ep="/api/my-list")
    assert "_padN(rows, 8).map" in out


# ═══════════════════════════════ #544 player ═══════════════════════════════════

_PLAYER = {"route": "/watch/:id", "name": "player", "components": [
    {"id": "video", "region": [0.0, 0.0, 1.0, 1.0],
     "role": "full-screen video content area behind overlay controls"},
    {"id": "back", "region": [0.0, 0.0, 0.06, 0.09],
     "role": "top-left back arrow icon for exiting playback"}]}

# a NON-player media surface (single featured video area, no rail/hero).
_MEDIA = {"route": "/live", "name": "live_feed", "components": [
    {"id": "feat", "region": [0.0, 0.0, 1.0, 1.0],
     "role": "main area displaying a video stream"}]}


def test_544_player_full_bleed_and_svg_icons():
    out = _render_reference_page("PlayerPage", {"route": "/watch/:id"}, _PLAYER,
                                 _design(), [("Home", "/browse")], "")
    # full-bleed cover video (not a centered contained poster)
    assert ('<video key={_videoOf(cur)} src={_videoOf(cur)} autoPlay muted loop '
            'playsInline className="absolute inset-0 h-full w-full object-cover"') in out
    assert "max-h-full object-contain" not in out, "player must not center-contain"
    # real sized control icons (SVGs) with aria-labels preserved
    assert 'aria-label="Pause"' in out and 'aria-label="Fullscreen"' in out
    assert out.count("<svg") >= 5, "player controls use real SVG icons"
    # sized SVG back button (chevron), not the tiny glyph
    assert 'aria-label="Back"' in out and 'd="M15 18l-6-6 6-6"' in out


def test_544_non_player_media_byte_identical():
    out = _render_reference_page("LiveFeedPage", {"route": "/live"}, _MEDIA,
                                 _design(), [("Home", "/browse")], "")
    # a generic media surface keeps the centered contain render + glyph chrome
    assert "max-h-full object-contain" in out
    assert "{'\\u2039'}" in out                       # glyph back (unchanged)
    assert 'd="M15 18l-6-6 6-6"' not in out           # no player SVG back
    assert 'aria-label="Play"' in out                 # minimal chrome, not Pause


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
