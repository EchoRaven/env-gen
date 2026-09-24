r"""#1202th: a ui_page name becomes a JS identifier, so a leading digit must not survive.

`_pascal_case` turns a registered page name into the component identifier that is declared
and imported in the generated frontend:

    function <Comp>() …            src/pages/<Comp>.jsx
    import <Comp> from './pages/<Comp>.jsx'

A name beginning with a digit came through unchanged — `123page` stayed `123page`, not even
PascalCased, because the first character is not a letter to upper-case. `function 404Page()`
is not JavaScript, and esbuild fails the WHOLE build on it: the same total failure
`_RESERVED_APP_IDENTS` exists to prevent, recorded there as *"an agent registered a ui_page
named 'App' … the frontend build failed every cycle → run wedged on docker_up"*.

HOW LIKELY: the corpus holds 4,283 ui_page name/component values, 76 of them non-identifiers.
All 76 are hyphenated (`continue-watching_page` ×25, `my-list_page` ×22) or carry the
accumulated `page:ui:` prefix that `#1202ly` already fixed — none begins with a digit. So this
is hardening rather than a live incident. It is worth doing because `404_page` and
`2fa_setup_page` are ordinary names for a lane to choose, nothing upstream constrains them,
and the cost is that the frontend never builds.

The Python half of the generator has always done this: `backend_skeleton._attr_name` prefixes
`col_` for a leading digit, and says it is idempotent so applying it twice cannot double-
mangle. This is the same rule on the JS side.

LOCAL-ONLY (gitignored)."""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.runtime.frontend_scaffold import (  # noqa: E402
    _page_component_name, _pascal_case, _safe_import_alias)

_JS_IDENT = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")

_NAMES = [
    "login_page", "for_you", "my-list_page", "continue-watching_page",
    "suggested-creators_page",                      # the shapes the corpus really has
    "404_page", "2fa_setup_page", "123page", "0", "9lives-page",   # leading digit
    "", "   ", "@handle", "a b page", "view-活动", "a\"b", "a'b",
    "page:ui:root_for_you_page",                    # #1202ly's shape, still must render
]


@pytest.mark.parametrize("name", _NAMES)
def test_every_name_yields_a_valid_js_identifier(name):
    comp = _pascal_case(name)
    assert _JS_IDENT.match(comp), f"{name!r} -> {comp!r} is not a JS identifier"


@pytest.mark.parametrize("name", _NAMES)
def test_the_import_alias_is_valid_too(name):
    """The alias is the local binding in App.jsx; it must be an identifier as well."""
    assert _JS_IDENT.match(_safe_import_alias(_pascal_case(name)))


@pytest.mark.parametrize("name", _NAMES)
def test_the_page_component_name_path_agrees(name):
    """`_page_component_name` is what the projector actually calls."""
    assert _JS_IDENT.match(_page_component_name({"name": name}))


def test_a_leading_digit_is_prefixed_not_dropped():
    """Dropping it would collapse `404_page` and `page` onto one component."""
    assert _pascal_case("404_page") == "Page404Page"
    assert _pascal_case("404_page") != _pascal_case("page")


def test_it_is_idempotent():
    """`_attr_name` says why: the transform is applied at several stages, and must not
    double-mangle."""
    for name in _NAMES:
        once = _pascal_case(name)
        assert _pascal_case(once) == once, name


def test_ordinary_names_are_untouched():
    """Non-vacuity: the fix must not rename every page."""
    assert _pascal_case("login_page") == "LoginPage"
    assert _pascal_case("continue-watching_page") == "ContinueWatchingPage"
    assert _pascal_case("") == "Page"


def test_a_component_the_registration_already_supplies_still_wins():
    """`_page_component_name` prefers an explicit, already-valid component name."""
    assert _page_component_name({"name": "404_page", "component": "NotFound"}) == "NotFound"
    assert _page_component_name({"name": "404_page", "component": "9bad"}) == "Page404Page"
