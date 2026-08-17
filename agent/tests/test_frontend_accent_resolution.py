"""#431 (netflix r27 shipped a BLUE nav + blue CTAs while r29 — same app, same
code — shipped the brand RED; the visual judge penalized 'primary CTA blue vs
brand red'). Root cause: design_prep keys the brand accent NON-DETERMINISTICALLY
— top-level 'accent' on some runs, only 'brand'/'brand_red' or an 'accents' map
on others — and the projector's lone pal.get('accent') MISSED it and fell back
to a hardcoded blue (#2563eb) that fights a red/dark design. Worse, the auth
page picked the alphabetically-FIRST accents hue, so 'accents:{blue,red}' →
blue. FIX: _resolve_accent checks every common accent key, then the accents map
(most-SATURATED hue wins — the brand color is vivid), then a NEUTRAL gray, never
a stray blue. Generalizable — no product/hue literals. Locks it in."""
from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _resolve_accent, _hex_saturation, _auth_page_classes, _render_reference_page)


# ── _resolve_accent: finds the accent regardless of palette SHAPE ──
def test_resolve_top_level_accent():
    assert _resolve_accent({"accent": "#e50914"}) == "#e50914"


def test_resolve_falls_through_scalar_keys():
    # no 'accent' key, but the brand red lives under 'brand_red'
    assert _resolve_accent({"bg": "#141414", "brand_red": "#e50914"}) == "#e50914"
    assert _resolve_accent({"primary": "#e50914"}) == "#e50914"


def test_resolve_picks_most_saturated_hue_from_accents_map():
    # 'accents:{blue,red}' must resolve to the VIVID brand hue, not alphabetical blue
    pal = {"bg": "#141414", "accents": {"blue": "#2563eb", "red": "#e50914"}}
    assert _resolve_accent(pal) == "#e50914", "most-saturated (brand) hue must win"


def test_resolve_neutral_fallback_never_blue():
    # a palette with no accent anywhere → a NEUTRAL gray, never the old #2563eb blue
    out = _resolve_accent({"bg": "#141414", "text": "#f5f5f5"})
    assert out != "#2563eb", "must not fall back to a stray blue"
    assert out == "#6b7280", "neutral fallback"


def test_resolve_handles_non_mapping():
    assert _resolve_accent(None) == "#6b7280"


def test_saturation_orders_vivid_over_neutral():
    assert _hex_saturation("#e50914") > _hex_saturation("#2563eb")   # red > blue
    assert _hex_saturation("#808080") < 0.05                          # gray ~0
    assert _hex_saturation("#141414") < 0.05                          # near-black ~0


# ── the MAIN scored surface: reference page uses the resolved accent, no blue.
#    A top nav bar (y1<=0.22, full width) carries the persistent navigation whose
#    ACTIVE link is painted with the resolved accent — the surface r27 shipped blue.
_HOME = {"route": "/browse", "name": "browse_home", "components": [
    {"id": "topnav", "role": "top navigation bar", "region": [0.0, 0.0, 1.0, 0.08]},
    {"id": "hero", "role": "hero billboard title art",
     "region": [0.0, 0.1, 1.0, 0.55]},
    {"id": "rail", "role": 'poster rail of "Trending"',
     "region": [0.0, 0.6, 1.0, 0.82], "geometry": {"columns": 6}}]}


def _render(pal):
    design = {"design_system": {"palette": pal, "theme": {"default": "dark"}},
              "assets": []}
    return _render_reference_page("BrowseHomePage", {"route": "/browse"}, _HOME,
                                  design, [("Home", "/browse")], "/api/titles")


def test_reference_page_uses_brand_red_not_blue_when_accent_key_absent():
    # a palette shaped like r27's (brand red present, but NOT under 'accent')
    out = _render({"bg": "#141414", "brand_red": "#e50914"})
    assert "#2563eb" not in out, "no stray blue on the scored surface"
    assert "#e50914" in out, "the design's real brand accent must reach the page"


def test_reference_page_uses_accent_from_accents_map():
    out = _render({"bg": "#141414", "accents": {"blue": "#2563eb", "red": "#e50914"}})
    assert "#e50914" in out and "#2563eb" not in out


# ── auth page: accents map picks the saturated hue, not alphabetical blue ──
def test_auth_accents_map_picks_saturated_hue():
    design = {"design_system": {"palette": {
        "bg": "#141414", "accents": {"blue": "#2563eb", "red": "#e50914"}}}}
    cls = _auth_page_classes(design)
    assert cls["__CLS_SUBMIT__"].startswith("bg-accent-red"), \
        "auth submit must use the vivid brand hue, not alphabetical blue"
    assert cls["__CLS_LINK__"] == "text-accent-red"


def test_auth_top_level_accent_unchanged():
    # regression: a palette WITH a top-level accent still uses the bg-accent token
    design = {"design_system": {"palette": {"bg": "#141414", "accent": "#e50914"}}}
    cls = _auth_page_classes(design)
    assert cls["__CLS_SUBMIT__"].startswith("bg-accent ")
    assert cls["__CLS_LINK__"] == "text-accent"


def test_auth_no_palette_byte_identical_light_default():
    # no design input at all → the neutral light form is preserved unchanged
    cls = _auth_page_classes({})
    assert cls["__CLS_SUBMIT__"] == "bg-blue-600 text-white hover:bg-blue-700"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
