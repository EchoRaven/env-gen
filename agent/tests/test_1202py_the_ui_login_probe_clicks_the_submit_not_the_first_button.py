"""#1202py: the UI login probe must click the form's submit, not the first button on the page.

A comma selector matches in document order, so `.first` of "button[type=submit], form button,
button" clicked tiktok-r126's nav button and reported "submit sent NO /auth request" for a login
the browser test-user completed five minutes later."""
import asyncio
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime.test_user_runner import _click_primary

# The page, in document order: a nav button, a "Use QR code" button, then the form's submit.
_DOM = [("button", {"type": "button"}, "Log in (nav)"),
        ("button", {"type": "button"}, "Use QR code"),
        ("button", {"type": "submit"}, "Sign in")]


class _Loc:
    def __init__(self, page, matches):
        self.page, self.matches = page, matches

    @property
    def first(self):
        return _Loc(self.page, self.matches[:1])

    async def count(self):
        return len(self.matches)

    async def is_visible(self):
        return bool(self.matches)

    async def click(self, timeout=None):
        self.page.clicked.append(self.matches[0][2])


class _Page:
    def __init__(self):
        self.clicked = []

    def locator(self, sel):
        def m(el, one):
            one = one.strip()
            if one == "button[type=submit]":
                return el[1].get("type") == "submit"
            if one == "button[type=button]":
                return el[1].get("type") == "button"
            if one == "button":
                return True
            return False                      # no <form> in this DOM
        return _Loc(self, [el for el in _DOM if any(m(el, s) for s in sel.split(","))])


def test_the_submit_is_clicked_even_when_other_buttons_come_first():
    p = _Page()
    assert asyncio.run(_click_primary(p)) is True
    assert p.clicked == ["Sign in"]


def test_the_old_union_selector_would_have_clicked_the_nav_button():
    p = _Page()
    asyncio.run(p.locator("button[type=submit], form button, button").first.click())
    assert p.clicked == ["Log in (nav)"]


def test_the_validation_probe_uses_the_runner_rule():
    src = Path("env_generator/llm_generator/multi_agent/runtime/test_user_validation.py").read_text()
    assert '"button[type=submit], form button, button").first.click()' not in src
    assert "_click_primary" in src
