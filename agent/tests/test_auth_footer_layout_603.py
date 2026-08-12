r"""#603: the auth footer's width and column count are measurements too.

After #594 (the card panel) and #602 (the surface gradient), `footer` is what is left of
`login`'s deviation clusters — 48 of its 282 — and the complaints are STRUCTURAL, not copy:

    "implementation has a small centered footer; reference is a full-width 4-column footer"
    "Footer: 2-column layout missing … links"

The template hard-coded `mx-auto w-full max-w-4xl` (at 1280px that is x 0.15–0.85) and
`grid-cols-2 … sm:grid-cols-4`. The measurement disagrees, consistently: over the **143** login
screens carrying footer regions the x-span median is **0.000 → 1.000 (the full frame)** and
**139 of 143** declare exactly **4** column regions.

No measurement — 4 of those 143, and every app generated without design input — keeps the exact
strings the template used before, so output there is byte-identical.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _FOOTER_BOX_DEFAULT_603,
    _FOOTER_GRID_DEFAULT_603,
    _auth_footer_classes_603 as classes,
    _auth_footer_layout_603 as layout,
)


def _reg(id_, x0, x1, y0=0.9, y1=1.0):
    return {"id": id_, "role": "", "region": [x0, y0, x1, y1]}


# the real r142 `login` footer measurement
_FOOTER = [
    _reg("footer-divider", 0.0, 1.0, 0.86, 0.88),
    _reg("footer-contact", 0.1, 0.5, 0.88, 0.93),
    _reg("footer-links-col1", 0.10, 0.28),
    _reg("footer-links-col2", 0.30, 0.50),
    _reg("footer-links-col3", 0.50, 0.70),
    _reg("footer-links-col4", 0.70, 0.92),
]


def _design(regions, name="login"):
    return {"screens": [{"name": name, "regions": regions}]}


# --- the measurement ---------------------------------------------------------------------

def test_the_real_login_footer_is_full_width_with_four_columns():
    assert layout(_design(_FOOTER)) == {"full_width": True, "cols": 4}


def test_an_inset_footer_stays_inset():
    inset = [_reg("footer-links-col1", 0.30, 0.45), _reg("footer-links-col2", 0.55, 0.70)]
    assert layout(_design(inset)) == {"full_width": False, "cols": 2}


def test_a_single_column_footer_does_not_claim_a_grid():
    one = [_reg("footer-links", 0.0, 1.0)]
    assert layout(_design(one)) == {"full_width": True, "cols": 0}


def test_a_screen_with_no_footer_regions_yields_None():
    assert layout(_design([_reg("top-bar", 0.0, 1.0, 0.0, 0.08)])) is None


def test_a_non_login_screen_is_not_consulted():
    assert layout(_design(_FOOTER, name="browse_home")) is None


def test_junk_is_inert():
    assert layout(None) is None
    assert layout({}) is None
    assert layout(_design([None, "x", {}])) is None
    assert layout({"screens": [{"name": "login", "regions": [{"id": "footer-x"}]}]}) is None


# --- the classes it drives ------------------------------------------------------------------

def test_the_measured_footer_goes_full_width_with_four_columns():
    c = classes(_design(_FOOTER))
    assert "max-w-4xl" not in c["__CLS_FOOTER_BOX__"]
    assert c["__CLS_FOOTER_BOX__"].startswith("w-full")
    assert c["__CLS_FOOTER_GRID__"] == "grid grid-cols-2 sm:grid-cols-4"


def test_a_measured_three_column_footer_gets_three():
    three = [_reg("footer-links-col1", 0.0, 0.3), _reg("footer-links-col2", 0.35, 0.6),
             _reg("footer-links-col3", 0.65, 1.0)]
    assert classes(_design(three))["__CLS_FOOTER_GRID__"] == "grid grid-cols-2 sm:grid-cols-3"


def test_the_column_count_is_capped():
    many = [_reg(f"footer-links-col{i}", i / 9, (i + 1) / 9) for i in range(9)]
    assert classes(_design(many))["__CLS_FOOTER_GRID__"].endswith("sm:grid-cols-6")


def test_an_unmeasured_design_keeps_the_templates_own_strings():
    c = classes({})
    assert c["__CLS_FOOTER_BOX__"] == _FOOTER_BOX_DEFAULT_603 == "mx-auto w-full max-w-4xl px-6 pb-10"
    assert c["__CLS_FOOTER_GRID__"] == _FOOTER_GRID_DEFAULT_603 == "grid grid-cols-2 sm:grid-cols-4"


def test_an_inset_measurement_keeps_the_centered_box():
    inset = [_reg("footer-links-col1", 0.30, 0.45), _reg("footer-links-col2", 0.55, 0.70)]
    assert classes(_design(inset))["__CLS_FOOTER_BOX__"] == _FOOTER_BOX_DEFAULT_603


# --- the wiring ---------------------------------------------------------------------------------

def test_no_placeholder_can_survive_into_the_emitted_page():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import frontend_scaffold as fs
    src = inspect.getsource(fs._auth_page_src_540)
    assert "_auth_footer_classes_603(design)" in src
    # the placeholder exists in exactly two places: the template, and the dict that
    # substitutes it — so no other render path can emit it unsubstituted
    mod = inspect.getsource(fs)
    assert mod.count("__CLS_FOOTER_BOX__") == 2
    assert mod.count("__CLS_FOOTER_GRID__") == 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
