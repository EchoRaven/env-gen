r"""#653: the account chip's caret promised a menu that did not exist — and clicking it logged you out.

#457 moved logout onto the avatar chip because "streaming/media apps put logout in the avatar
menu, not a top-bar text button". That reasoning is right, but the menu was never built. What
shipped is a disclosure affordance (the caret) whose only behaviour is an immediate
`localStorage.clear()` + redirect to `/login`.

Measured over the 144 delivered frontends:

    61 carry the chip     61 of 61 render the caret     44 of them have NO menu state anywhere

So a user-agent that clicks the account chip to reach account actions — the obvious move, and
exactly what the caret invites — is silently signed out. `profile avatar dropdown` is also the
judge's 4th most-reported missing component (75).

Found while checking whether #506's blue-CTA fix held (it does — every "blue" note after r84 is
about the reference's avatar, not a CTA). Reading #443's emitter to understand those notes is
what surfaced the caret.

The disclosure is CSS-only — the projected TopNav imports no hooks — and opens on hover AND on
click/keyboard focus. The logout FUNCTION is preserved verbatim, just moved onto a menu item.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import _ref_nav_jsx as nav

_ROUTES = [("Home", "/"), ("Shows", "/shows"), ("Movies", "/movies"), ("Games", "/games")]
_LOGOUT = "localStorage.clear(); window.location.href = '/login'"


def _design(bg="#141414"):
    return {"design_system": {"palette": {"bg": bg, "accent": "#e50914"}},
            "screens": [{"components": [{"id": "primary-nav",
                                         "role": "horizontal primary nav: Home, Shows"}]}]}


def _jsx(design=None):
    return nav(_ROUTES, "#e50914", False, design=design if design is not None else _design())


def _chip(out):
    """The chip subtree, bounded by the NEXT construct — the utility cluster's close.

    Not `out.index("            </div>")`: 12 spaces + `</div>` is a substring of the menu's
    own 14-space close, so that boundary silently cuts the subtree in half.
    """
    i = out.index('<div className="relative group">')
    return out[i:out.index("          </span>\n", i)]


# --- the trap is gone ---------------------------------------------------------------------------

def test_the_chip_button_no_longer_logs_you_out_on_click():
    """The whole defect: the thing that looks like a menu opener signed you out."""
    chip = _chip(_jsx())
    opener = chip[chip.index("<button"):chip.index("</button>")]
    assert "onClick" not in opener
    assert _LOGOUT not in opener


def test_the_caret_now_actually_discloses_something():
    chip = _chip(_jsx())
    # #859: was `"\\u25BE" in chip` — the THIRD test in this suite asserting the caret's exact
    # spelling. #653's point is that the caret must DISCLOSE something, which the menu assertions
    # below cover; the glyph was never the subject. Three independent tests pinning one glyph is
    # how #782 survived 122 rounds, and this file is the third instance of it in one session.
    assert 'd="M6 9l6 6 6-6"' in chip, "the caret must be present and drawn"
    assert "\u25be" not in chip, "a typed caret is the #859 defect"
    assert 'role="menu"' in chip


def test_the_opener_announces_the_popup():
    assert 'aria-haspopup="menu"' in _chip(_jsx())


# --- the function is preserved, not dropped ------------------------------------------------------

def test_sign_out_is_still_reachable():
    """#457's intent was logout-in-the-avatar-menu; #653 finally provides the menu."""
    chip = _chip(_jsx())
    assert _LOGOUT in chip
    assert 'role="menuitem"' in chip
    assert "Sign out" in chip


def test_the_logout_action_is_byte_identical_to_the_one_it_replaces():
    """A behaviour change here would be a silent auth regression."""
    assert "onClick={() => { " + _LOGOUT + "; }}" in _chip(_jsx())


def test_the_logout_now_lives_on_the_menu_item_not_the_opener():
    chip = _chip(_jsx())
    assert chip.index('role="menu"') < chip.index(_LOGOUT)


# --- it opens without hooks ----------------------------------------------------------------------

def test_the_disclosure_is_css_only():
    """The projected TopNav imports no hooks; a useState menu would not compile."""
    chip = _chip(_jsx())
    for token in ("useState", "useEffect", "React.", "import "):
        assert token not in chip


def test_it_opens_on_click_and_keyboard_focus_not_only_hover():
    """A user-agent drives with clicks — hover-only would still be a dead affordance."""
    chip = _chip(_jsx())
    assert "group-hover:block" in chip
    assert "group-focus-within:block" in chip


def test_the_menu_is_closed_by_default():
    menu = _chip(_jsx())
    menu = menu[menu.index('role="menu"'):]
    assert "hidden" in menu[:menu.index(">")]


def test_the_opener_and_the_menu_share_a_group_container():
    """`group-hover` does nothing without the `group` class on a common ancestor."""
    chip = _chip(_jsx())
    assert chip.startswith('<div className="relative group">')


# --- the surface must be visible over the page ----------------------------------------------------

def test_the_menu_carries_its_own_background():
    """The nav sets none, so a transparent dropdown would paint over the page content."""
    assert "backgroundColor: '#141414'" in _chip(_jsx())


def test_the_background_comes_from_the_measured_palette():
    assert "backgroundColor: '#0b0b0b'" in _chip(_jsx(_design(bg="#0b0b0b")))


def test_a_design_with_no_palette_falls_back_to_the_frameworks_floor():
    d = {"screens": [{"components": [{"id": "primary-nav", "role": "horizontal primary nav: Home"}]}]}
    assert "backgroundColor: '#141414'" in _chip(_jsx(d))


def test_the_menu_is_layered_above_the_page():
    assert "z-50" in _chip(_jsx())


# --- shape ------------------------------------------------------------------------------------

def test_the_avatar_swatch_still_uses_the_resolved_accent():
    """#506 resolved the brand red; #653 must not disturb it."""
    assert "backgroundColor: '#e50914'" in _chip(_jsx())


def test_the_chip_markup_is_balanced():
    chip = _chip(_jsx())
    assert chip.count("<div") == chip.count("</div>") == 2
    assert chip.count("<button") == chip.count("</button>") == 2


def test_the_measurement_is_recorded():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import frontend_scaffold as fs
    flat = " ".join(inspect.getsource(fs._ref_nav_jsx).replace("#", " ").split())
    assert "61 carry this chip" in flat and "44 of them contain NO menu state" in flat


def test_457s_intent_is_credited_rather_than_reverted():
    """The next reader must see that #653 completes #457, not that it undoes it."""
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import frontend_scaffold as fs
    flat = " ".join(inspect.getsource(fs._ref_nav_jsx).split())
    assert "the menu was never built" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
