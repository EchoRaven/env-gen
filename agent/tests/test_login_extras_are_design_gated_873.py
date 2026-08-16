r"""#873: the login template hardcoded two lines the design never asked for.

Found by re-auditing my own deferral. Item 187 recorded the invented login links as "not fixed"
because *"removing it may break a registration chain"*. **That justification is false**, and the
corpus says so flatly: 3813 chains across 140 runs register over the **API** (`/register`, 4431
steps) and **not one** navigates via a UI link; 151 test-user/log files reference it zero times.

What the template actually hardcodes, ungated:

    "This page is protected to verify you are not a bot. Learn more."      <- cosmetic
    "Questions? Contact support"                                          <- cosmetic
    "New here? Create an account"                                         <- FUNCTIONAL

★ **#540 already established the rule for this very template** — *"no product literals — every
copy string is read from the spec"* — and these two escaped it. #454/#443/#445/#652 all gate on
the design's own enumeration; this one gated nothing. The judge reports them as invented on login
in **38 of the 51 runs** in the `nav order/extra` class.

★ **The register toggle is deliberately left alone.** The judge flags it too, but it is the only
UI path into register mode — `isRegister` has no other trigger — so dropping it would delete a
capability to win pixels. Functional vs cosmetic is the line the rest of the file respects, and it
is why deferring was right even though my stated reason for it was wrong.
"""
import inspect

import pytest

from env_generator.llm_generator.multi_agent.runtime import frontend_scaffold as fs


def _d(*roles, screen="login"):
    return {"screens": [{"name": screen,
                         "components": [{"role": r, "id": r.replace(" ", "-")} for r in roles]}]}


def test_the_helper_exists():
    """Non-vacuity."""
    assert set(fs._auth_extras_873(_d("email field"))) == {"__EXTRA_NOTICE__", "__EXTRA_SUPPORT__"}


def test_a_described_login_without_the_signals_gets_neither():
    out = fs._auth_extras_873(_d("email field", "password field", "submit button"))
    assert out["__EXTRA_NOTICE__"] == "" and out["__EXTRA_SUPPORT__"] == ""


@pytest.mark.parametrize("role", ["recaptcha disclaimer", "bot verification notice",
                                  "captcha", "protected notice"])
def test_an_enumerated_notice_is_emitted(role):
    assert "not a bot" in fs._auth_extras_873(_d("email field", role))["__EXTRA_NOTICE__"]


@pytest.mark.parametrize("role", ["help link", "contact support link", "faq link"])
def test_an_enumerated_support_link_is_emitted(role):
    assert "Contact support" in fs._auth_extras_873(_d("email field", role))["__EXTRA_SUPPORT__"]


def test_the_two_are_independent():
    out = fs._auth_extras_873(_d("recaptcha disclaimer"))
    assert "not a bot" in out["__EXTRA_NOTICE__"] and out["__EXTRA_SUPPORT__"] == ""


@pytest.mark.parametrize("design", [None, {}, {"screens": []},
                                    {"screens": [{"name": "browse", "components": [{"role": "x"}]}]},
                                    {"screens": [{"name": "login"}]},
                                    {"screens": [{"name": "login", "components": []}]}])
def test_no_information_is_not_information_saying_no(design):
    """★ The correction that #540's own test forced. Its contract is explicit — *"when the spec
    carries none of these signals the caller keeps the existing template (byte-identical)"* — and
    `test_540_byte_identical_without_spec` asserts the notice survives a spec-less route.

    My first cut returned empty strings whenever nothing matched, which silently reinterprets an
    ABSENT design as a design that REJECTED the lines. Only a design that actually describes the
    auth screen gets to withhold them. Same distinction #864 draws between "cannot confirm" and
    "confirmed empty"."""
    out = fs._auth_extras_873(design)
    assert "not a bot" in out["__EXTRA_NOTICE__"]
    assert "Contact support" in out["__EXTRA_SUPPORT__"]


def test_the_fallback_class_map_keeps_them_too():
    """The design-less path has no information either, so it must follow the same rule."""
    m = fs._AUTH_CLASSES_LIGHT
    assert "not a bot" in m["__EXTRA_NOTICE__"]
    assert "Contact support" in m["__EXTRA_SUPPORT__"]


def test_the_register_toggle_is_untouched():
    """★ Functional, not cosmetic: `isRegister` has no other trigger."""
    src = inspect.getsource(fs)
    assert "New here? Create an account" in src
    assert "setIsRegister(!isRegister)" in src


def test_the_placeholders_are_substituted_not_shipped():
    """A placeholder that reaches the browser is worse than the line it replaced."""
    src = inspect.getsource(fs)
    assert "__EXTRA_NOTICE__" in src and "__EXTRA_SUPPORT__" in src
    assert '"__EXTRA_NOTICE__": ' in src and '"__EXTRA_SUPPORT__": ' in src
    assert "**_auth_extras_873(design)" in src


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
