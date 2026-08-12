r"""#602: the measured gradient the projector threw away.

`login` is the arc's #1 per-screen fidelity blocker (below 0.65 in 29 of 40 scored runs, mean
0.593) and clustering its 282 judge deviations puts **background/gradient FIRST at 49 mentions** —
"implementation is flat black; reference uses a dark red gradient".

§5.0v recorded this as *"evidence too thin, documented not fixed"* because `palette.gradient_note`
appears in 1 of 45 design systems. **That was the wrong field.** The region text carries it in
**141** runs, and each full-bleed band also carries its own measured `colors.bg`, so both stops
are derivable:

    top-bar          state "dark reddish gradient background, single logo mark"   #3b1717
    page-background                                                               #321213
    footer                                                                        #161616

`_screen_surface_bg` already emits a `linear-gradient` when the analyst authored
`surfaces[<screen>].top_color`/`bottom_color`; it just had no way to reach that shape from region
measurements, so branch (b) flattened the screen to its largest band's colour (#321213).

Two narrowings, each forced by a false positive over the corpus's 2880 screens:
  * a luminance-spread heuristic over full-bleed bands fires on **1759** — a hero band's measured
    `colors.bg` is the PHOTO's dominant colour, not the page (`shows` spread 235, one band
    #ffffff). Requiring a band whose own `state` says "gradient" cuts it to 276.
  * that still keeps hero bands (`movies` #504f4d, `shows` #ffffff). Excluding bands whose
    id/role names imagery gives **128 — 126 `login`, 2 `player`**.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _measured_vertical_gradient_602 as grad,
    _screen_surface_bg,
    _surf_style_attr_526,
)


def _band(id_, y0, y1, bg, state="", role="", x0=0.0, x1=1.0):
    return {"id": id_, "role": role, "state": state,
            "region": [x0, y0, x1, y1], "colors": {"bg": bg}}


# the real r142 `login` bands
_LOGIN = [
    _band("top-bar", 0.0, 0.09, "#3b1717",
          state="dark reddish gradient background, single logo mark",
          role="header bar with Netflix wordmark logo at left"),
    _band("continue-button", 0.29, 0.35, "#d22f26", role="primary CTA button", x0=0.37, x1=0.63),
    _band("page-background", 0.09, 0.86, "#321213",
          state="empty dark gradient with subtle texture, form centered"),
    _band("footer", 0.86, 1.0, "#161616", role="footer band"),
]


def test_the_real_login_bands_yield_the_measured_gradient():
    assert grad({"components": _LOGIN}) == "linear-gradient(180deg, #3b1717 0%, #161616 100%)"


def test_a_narrow_element_never_becomes_a_stop():
    """The CTA is #d22f26 and sits between the stops — it is not a full-bleed band."""
    assert "#d22f26" not in (grad({"components": _LOGIN}) or "")


def test_the_stops_are_ordered_by_VERTICAL_position_not_declaration_order():
    shuffled = [_LOGIN[3], _LOGIN[2], _LOGIN[1], _LOGIN[0]]
    assert grad({"components": shuffled}) == grad({"components": _LOGIN})


# --- the two narrowings, each with its real false positive --------------------------------

def test_a_luminance_difference_ALONE_is_not_a_gradient():
    """The 1759-screen over-fire: bands differ, but nothing says the surface is a gradient."""
    plain = [_band("top-nav-bar", 0.0, 0.08, "#000000"),
             _band("page", 0.08, 1.0, "#141414")]
    assert grad({"components": plain}) is None


def test_a_hero_band_is_a_PHOTO_not_the_surface():
    """`shows` reported #ffffff for its hero; `movies` #504f4d. Both are imagery."""
    for ident in ("hero-billboard", "hero-background-collage", "featured-artwork",
                  "poster-rail", "video-canvas", "banner-image"):
        bands = [_band("page-background", 0.1, 1.0, "#141414", state="dark gradient"),
                 _band(ident, 0.0, 0.6, "#ffffff", role="full-bleed featured artwork")]
        assert "#ffffff" not in (grad({"components": bands}) or ""), ident


def test_one_colour_across_every_band_is_not_a_gradient():
    same = [_band("top-bar", 0.0, 0.09, "#141414", state="flat gradient-free band"),
            _band("page-background", 0.09, 1.0, "#141414", state="dark gradient")]
    assert grad({"components": same}) is None


def test_junk_is_inert():
    assert grad({}) is None
    assert grad({"components": [None, "x", {}]}) is None
    assert grad({"components": [_band("p", 0.0, 1.0, "not-a-hex", state="gradient")]}) is None


# --- end to end through the resolver ---------------------------------------------------------

def _design(screen_name, bands):
    return {"design_system": {}, "screens": [{"name": screen_name, "components": bands}]}


def test_the_resolver_returns_a_background_gradient_not_a_flat_colour():
    surf = _screen_surface_bg(_design("login", _LOGIN), {"name": "login"})
    assert surf == {"prop": "background",
                    "value": "linear-gradient(180deg, #3b1717 0%, #161616 100%)"}


def test_the_style_attribute_uses_the_background_shorthand():
    surf = _screen_surface_bg(_design("login", _LOGIN), {"name": "login"})
    attr = _surf_style_attr_526(surf)
    assert "background: 'linear-gradient(180deg, #3b1717 0%, #161616 100%)'" in attr
    assert "backgroundColor" not in attr


def test_a_screen_with_no_gradient_evidence_still_gets_todays_flat_colour():
    """Byte-identical where the measurement does not claim a gradient."""
    flat = [_band("page-background", 0.0, 1.0, "#141414")]
    surf = _screen_surface_bg(_design("browse_home", flat), {"name": "browse_home"})
    assert surf == {"prop": "backgroundColor", "value": "#141414"}


def test_an_authored_surfaces_entry_still_wins():
    """Branch (a) is the analyst's explicit authority — #602 must not pre-empt it."""
    d = _design("login", _LOGIN)
    d["design_system"] = {"material": {"surfaces": {"login": {"color": "#000000"}}}}
    surf = _screen_surface_bg(d, {"name": "login"})
    assert surf == {"prop": "backgroundColor", "value": "#000000"}


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
