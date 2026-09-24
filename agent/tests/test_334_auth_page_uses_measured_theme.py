"""#334: the framework-projected auth page must use the MEASURED theme.

`_AUTH_PAGE_TEMPLATE` is a fixed LIGHT design — `bg-zinc-50`, `bg-white`,
`border-zinc-200/300`, `text-zinc-900`, `bg-blue-600` — and the auth branch of
`_project_page_component` ignored the `design` argument the function already
accepts (and that its caller already passes).

Two consequences, both measured:

1. It ships the wrong app. r93's delivered
   `app/frontend/src/pages/LoginPage.jsx` contains `bg-zinc-50`, `bg-white`
   and `bg-blue-600` — a white card with a blue button — against a reference
   login that is black with the brand red #FE2C55.

2. It fights another framework pass. Auth pages are re-projected on EVERY
   orchestrator tick (`_is_auth_page(...) or not target.exists()`), and the
   #209 darkify pass re-darkens them right after. r92 logged
   "14 swaps across 2 files ... ['src/pages/LoginPage.jsx',
   'src/pages/SignupPage.jsx']" **57 times** in one run. The framework was the
   only author on both sides of that loop.

The fix is not to stop projecting the page — the lane does ship dead logins,
which is why the template exists — but to project it in the measured palette,
so there is nothing left to darken and the shipped page matches the reference.

Generality: with no design system the output is unchanged (a neutral light
form), so envs that run without design input behave exactly as before.
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# A measured dark reference (the shape `_palette_of` reads).
DARK = {"palette": {"bg": "#000000", "accent": "#fe2c55"},
        "theme": {"default": "dark"}}

LIGHT_LITERALS = ("bg-zinc-50", "bg-white", "bg-blue-600", "bg-blue-700",
                  "text-zinc-900", "border-zinc-200", "border-zinc-300",
                  "text-blue-600")


def _render(design):
    from multi_agent.runtime.frontend_scaffold import _project_page_component
    page = {"name": "LoginPage", "route": "/login", "component": "LoginPage"}
    return _project_page_component("LoginPage", page, design=design)


class MeasuredThemeReachesTheAuthPage(unittest.TestCase):

    def test_no_hardcoded_light_utility_survives_a_measured_design(self):
        out = _render(DARK)
        leaked = [lit for lit in LIGHT_LITERALS if lit in out]
        self.assertEqual(
            leaked, [],
            f"hardcoded light utilities survived the measured theme: {leaked}")

    def test_it_uses_the_measured_tokens(self):
        """render_measured_tailwind_theme emits `bg` and `accent` tokens, so the
        page must consume them (bg-bg / bg-accent) rather than literals."""
        out = _render(DARK)
        self.assertIn("bg-bg", out)
        self.assertIn("accent", out)

    def test_darkify_pass_finds_nothing_left_to_swap(self):
        """The r92 thrash loop: the darkify pass rewrites light-neutral
        utilities. With the measured theme projected there is no such utility,
        so the two passes stop fighting."""
        out = _render(DARK)
        self.assertIsNone(
            re.search(r"\b(?:bg|text|border)-(?:zinc|slate|gray)-(?:50|100|200|300)\b", out),
            "a light-neutral utility remains for the darkify pass to swap")


class NoDesignInputIsUnchanged(unittest.TestCase):
    """Envs generated without design input must behave exactly as before."""

    def test_without_a_design_the_page_still_renders_a_light_form(self):
        out = _render(None)
        self.assertIn("bg-zinc-50", out)

    def test_empty_palette_is_treated_as_no_design(self):
        out = _render({"palette": {}})
        self.assertIn("bg-zinc-50", out)


class TheAuthPageStaysFunctional(unittest.TestCase):
    """The template exists because lanes ship dead logins — styling it must not
    cost the functionality."""

    def _assert_functional(self, out):
        self.assertIn("type=\"password\"", out)
        self.assertIn("type=\"email\"", out)
        self.assertIn("/auth/login", out)
        self.assertIn("/auth/register", out)
        self.assertIn("access_token", out)

    def test_functional_with_a_measured_design(self):
        self._assert_functional(_render(DARK))

    def test_functional_without_a_design(self):
        self._assert_functional(_render(None))


if __name__ == "__main__":
    unittest.main()
