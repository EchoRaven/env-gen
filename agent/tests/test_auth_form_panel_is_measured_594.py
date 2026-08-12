r"""#594: the auth form's card panel is a MEASUREMENT, not a constant.

`login` is the single most frequent per-screen fidelity blocker in the arc — below 0.65 in **29
of 40** scored runs, mean **0.593** (next worst: browse_by_languages 27/40, player 20/40,
title_detail 20/40). Clustering its 282 judge deviations by theme:

    background/gradient 49 | footer 48 | card/border 42 | get help 39 | register-link 35

`card/border` is third, and unlike the others it has a hard structural signal behind it: of the
45 `login` screens in `design_system.json`, **39 declare no card/panel region at all**. Their
region roles are header bar / heading / secondary line / labeled input / CTA button / help link
— nothing enclosing them. The reference form sits straight on the page surface; the template
wrapped it in `rounded-md border-white/10 bg-black/20` unconditionally.

Two things were checked first and are NOT the cause, recorded so nobody re-chases them:
  * the chrome slots are filled — the reCAPTCHA line is present in 42/43 delivered LoginPages
    (an earlier count of 0/43 was a bad regex: the framework deliberately words it "not a bot"
    with no product literal), `<footer>` 43/43, brand header 43/43, footer links median 6;
  * `Get Help` is present in only 28/43, but score with vs without is 0.592 vs 0.596 — nothing.

Degrades to identical behaviour: `None` (no design, or no login screen measured) keeps the
panel, the same convention `_auth_page_classes` already follows for the palette.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _auth_form_panel_measured as measured,
    _auth_page_classes,
)

_ROLES_NO_PANEL = [
    {"role": "header bar with brand wordmark logo at left"},
    {"role": "primary page heading for sign-in form"},
    {"role": "secondary supporting text under heading"},
    {"role": "labeled text input field for email/mobile"},
    {"role": "primary CTA button spanning form width"},
    {"role": "expandable help link with chevron"},
]
_DARK = {"palette": {"bg": "#141414", "accent": "#E50914"}}


def _design(screens, **extra):
    return {**_DARK, "screens": screens, **extra}


# --- the predicate ------------------------------------------------------------------------------

def test_the_measured_login_screen_reports_no_panel():
    d = _design([{"name": "login", "regions": _ROLES_NO_PANEL}])
    assert measured(d) is False


def test_a_measured_panel_is_honoured():
    d = _design([{"name": "login", "regions": _ROLES_NO_PANEL
                  + [{"role": "bordered card containing the form"}]}])
    assert measured(d) is True


def test_the_id_field_is_read_too():
    d = _design([{"name": "login", "regions": [{"id": "signin_panel", "role": ""}]}])
    assert measured(d) is True


def test_no_measurement_at_all_is_None_not_False():
    """The difference that keeps a design-less env byte-identical."""
    assert measured(None) is None
    assert measured({}) is None
    assert measured(_design([])) is None
    assert measured(_design([{"name": "browse_home", "regions": []}])) is None


def test_a_signup_screen_does_not_answer_for_login():
    """#546's own split: register surfaces are excluded from the login predicate."""
    assert measured(_design([{"name": "signup", "regions": _ROLES_NO_PANEL}])) is None


def test_the_components_key_is_accepted_as_well_as_regions():
    d = _design([{"name": "login", "components": _ROLES_NO_PANEL}])
    assert measured(d) is False


def test_junk_regions_do_not_crash():
    assert measured(_design([{"name": "login", "regions": [None, "x", {}]}])) is False


# --- the class it drives --------------------------------------------------------------------------

def test_the_panel_classes_are_dropped_when_nothing_encloses_the_form():
    cls = _auth_page_classes(_design([{"name": "login", "regions": _ROLES_NO_PANEL}]))
    assert cls["__CLS_CARD__"] == ""


def test_the_panel_survives_when_the_reference_has_one():
    cls = _auth_page_classes(_design([{"name": "login", "regions": _ROLES_NO_PANEL
                                       + [{"role": "card panel around form"}]}]))
    assert "bg-black/20" in cls["__CLS_CARD__"]


def test_an_unmeasured_design_keeps_todays_panel():
    cls = _auth_page_classes(_DARK)
    assert "bg-black/20" in cls["__CLS_CARD__"]


def test_a_design_LESS_env_is_untouched():
    """No palette at all -> the light constant table, never reached by #594."""
    cls = _auth_page_classes({})
    assert cls["__CLS_CARD__"], cls


def test_everything_else_about_the_page_is_unchanged():
    d = _design([{"name": "login", "regions": _ROLES_NO_PANEL}])
    cls = _auth_page_classes(d)
    assert cls["__CLS_PAGE__"] == "bg-bg"
    assert cls["__CLS_TITLE__"] == "text-white"
    assert "bg-accent" in cls["__CLS_SUBMIT__"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
