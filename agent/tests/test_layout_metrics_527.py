"""#527 (netflix, 2026-08-06) — the catalog rail+grid+card render must honour the
design's OWN MEASURED layout density, not one hardcoded spacing for every app.

GROUND TRUTH: generated/netflix-web-r95/design/design_system.json measured
design_system.layout_constants = {page_gutter_left_px:60, card_gap_px:6,
cards_per_rail_at_1920:6, row_vertical_gap_px:48, hero_backdrop_height_vh:56, ...}
and radius_scale = {card:4, poster:4, md:4, ...}. The projector IGNORED all of it
and hardcoded px-6 / gap-3 / rounded-md / rounded-lg / py-4, so catalog rows
rendered sparse ("amateur clone", collapse_checklist #14 row_density_tight).

FIX #527: _layout_metrics_527(design) resolves gutter / inter-card gap / poster
radius / rail-to-rail gap (+ informational cards_per_rail, hero_vh) to concrete px
with SAFE per-metric fallbacks == today's hardcoded Tailwind values. The four safe
density levers (gutter, card gap, radius, row gap) are wired at the rail + catalog
grid + card sites via INLINE px style, keeping the original class when a metric was
NOT measured -> byte-identical output for any app that measured no layout metrics.

These tests lock: the resolver's measured read, its per-metric range validation +
fallbacks, the never-raise contract, and the render byte-identity property (no
metrics -> original classes; with metrics -> the measured px, no product literals).
"""
import copy

from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _layout_metrics_527, _px_str_527, _LAYOUT_FALLBACKS_527, _render_reference_page)


# ── the measured constants netflix actually captured ──────────────────────────
_FULL_LC = {
    "design_viewport_px": 1920, "top_nav_height_px": 68,
    "page_gutter_left_px": 60, "page_gutter_right_px": 60,
    "hero_backdrop_height_vh": 56, "row_vertical_gap_px": 48,
    "cards_per_rail_at_1920": 5, "card_gap_px": 6,
}
_FULL_RS = {"none": 0, "sm": 4, "md": 4, "card": 4, "poster": 4, "pill": 999}


def _design(lc=None, rs=None):
    ds = {"palette": {"bg": "#141414", "accent": "#e50914"},
          "theme": {"default": "dark"}}
    if lc is not None:
        ds["layout_constants"] = lc
    if rs is not None:
        ds["radius_scale"] = rs
    return {"design_system": ds,
            "assets": [{"id": "m1", "file": "backdrops/m1.jpg", "type": "jpg",
                        "dims": [1280, 720],
                        "staged_path": "public/assets/backdrops/m1.jpg"}]}


# ============================ resolver: measured ==============================

def test_full_metrics_returns_the_measured_numbers():
    m = _layout_metrics_527(_design(_FULL_LC, _FULL_RS))
    assert m["gutter_px"] == 60 and m["gutter_px_measured"]
    assert m["card_gap_px"] == 6 and m["card_gap_px_measured"]
    assert m["row_gap_px"] == 48 and m["row_gap_px_measured"]
    assert m["radius_px"] == 4 and m["radius_px_measured"]
    assert m["cards_per_rail"] == 5 and m["cards_per_rail_measured"]
    assert m["hero_vh"] == 56 and m["hero_vh_measured"]


def test_radius_prefers_card_key_then_falls_through():
    # no card/poster -> reads the generic md token
    m = _layout_metrics_527(_design(rs={"md": 4}))
    assert m["radius_px"] == 4 and m["radius_px_measured"]
    # card key wins when present
    m2 = _layout_metrics_527(_design(rs={"card": 10, "md": 4}))
    assert m2["radius_px"] == 10


# ======================= resolver: fallbacks / validation ====================

def test_empty_and_none_design_are_all_fallbacks_no_raise():
    for d in (None, {}, {"design_system": {}}, "nonsense", []):
        m = _layout_metrics_527(d)
        assert m["gutter_px"] == 24 and not m["gutter_px_measured"]
        assert m["card_gap_px"] == 12 and not m["card_gap_px_measured"]
        assert m["cards_per_rail"] == 6 and not m["cards_per_rail_measured"]
        assert m["row_gap_px"] == 32 and not m["row_gap_px_measured"]
        assert m["radius_px"] == 6 and not m["radius_px_measured"]
        assert m["hero_vh"] is None and not m["hero_vh_measured"]


def test_fallbacks_match_documented_today_defaults():
    # the fallback table IS the projector's hardcoded equivalents
    assert _LAYOUT_FALLBACKS_527 == {
        "gutter_px": 24, "card_gap_px": 12, "cards_per_rail": 6,
        "row_gap_px": 32, "radius_px": 6, "hero_vh": None}


def test_insane_values_fall_back_to_today_defaults():
    bad_lc = {"page_gutter_left_px": 5,        # < 8
              "card_gap_px": 100,              # > 64
              "cards_per_rail_at_1920": 1,     # < 3
              "row_vertical_gap_px": 500,      # > 200
              "hero_backdrop_height_vh": 10}   # < 20
    bad_rs = {"card": 50}                       # > 24
    m = _layout_metrics_527(_design(bad_lc, bad_rs))
    assert m["gutter_px"] == 24 and not m["gutter_px_measured"]
    assert m["card_gap_px"] == 12 and not m["card_gap_px_measured"]
    assert m["cards_per_rail"] == 6 and not m["cards_per_rail_measured"]
    assert m["row_gap_px"] == 32 and not m["row_gap_px_measured"]
    assert m["hero_vh"] is None and not m["hero_vh_measured"]
    assert m["radius_px"] == 6 and not m["radius_px_measured"]


def test_non_numeric_and_bool_values_fall_back():
    m = _layout_metrics_527(_design(
        {"page_gutter_left_px": "60px", "card_gap_px": True,
         "row_vertical_gap_px": None},
        {"card": "tight"}))
    assert not m["gutter_px_measured"] and m["gutter_px"] == 24
    assert not m["card_gap_px_measured"] and m["card_gap_px"] == 12
    assert not m["row_gap_px_measured"] and m["row_gap_px"] == 32
    assert not m["radius_px_measured"] and m["radius_px"] == 6


def test_partial_metrics_resolve_independently():
    # layout_constants only (no radius_scale): spacing measured, radius falls back
    m = _layout_metrics_527(_design(lc=_FULL_LC))
    assert m["gutter_px_measured"] and m["card_gap_px_measured"]
    assert not m["radius_px_measured"] and m["radius_px"] == 6
    # radius_scale only: radius measured, spacing falls back
    m2 = _layout_metrics_527(_design(rs=_FULL_RS))
    assert m2["radius_px_measured"] and m2["radius_px"] == 4
    assert not m2["gutter_px_measured"] and m2["gutter_px"] == 24


# ============================ _px_str_527 helper =============================

def test_px_str_drops_needless_decimal():
    assert _px_str_527(24) == "24px"
    assert _px_str_527(48 / 2.0) == "24px"       # row-gap half-split, even
    assert _px_str_527(47 / 2.0) == "23.5px"     # odd row-gap keeps the fraction
    assert _px_str_527(6) == "6px"


# ================= render: byte-identity (no metrics) vs measured =============

_SCREEN = {"route": "/browse", "name": "browse_home", "components": [
    {"id": "hero", "region": [0.0, 0.0, 1.0, 0.55],
     "role": "hero billboard title art", "assets": ["m1"]},
    {"id": "rail", "region": [0.0, 0.6, 1.0, 0.85],
     "role": "horizontal poster rail", "geometry": {"columns": 6, "rows": 1}}]}


def _render(design):
    return _render_reference_page("BrowseHomePage", {}, _SCREEN, design,
                                  [("Home", "/browse")], "/api/titles")


def test_render_without_metrics_keeps_original_classes():
    out = _render(_design())  # no layout_constants, no radius_scale
    # rail wrapper gutter + row-gap, rail flex gap, poster radius (img + placeholder)
    assert '<div className="px-6 py-4">' in out
    assert '<div className="flex gap-3 overflow-x-auto pb-2">' in out
    assert 'className="w-full rounded-md object-cover"' in out
    assert 'className="w-full rounded-md"' in out
    # no measured px leaked anywhere
    for px in ("60px", "gap: '6px'", "borderRadius: '4px'", "paddingLeft: '60px'"):
        assert px not in out


def test_render_with_metrics_emits_measured_px():
    out = _render(_design(dict(_FULL_LC, cards_per_rail_at_1920=6), _FULL_RS))
    assert "paddingLeft: '60px'" in out and "paddingRight: '60px'" in out  # gutter
    assert "paddingTop: '24px'" in out and "paddingBottom: '24px'" in out  # row gap/2
    assert "gap: '6px'" in out                                             # inter-card
    assert "borderRadius: '4px'" in out                                    # poster
    # the replaced spacing utilities are gone from the rail/poster
    assert '<div className="px-6 py-4">' not in out
    assert "flex gap-3 overflow-x-auto" not in out
    assert "rounded-md" not in out


def test_render_partial_metrics_mixes_px_and_classes():
    # radius_scale only -> poster radius becomes px, but gutter/gap keep their class
    out = _render(_design(rs=_FULL_RS))
    assert "borderRadius: '4px'" in out and "rounded-md" not in out
    assert '<div className="px-6 py-4">' in out               # gutter unmeasured
    assert '<div className="flex gap-3 overflow-x-auto pb-2">' in out  # gap unmeasured


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
