"""#1126: the walk checked that login WORKED, never where it LANDED.

The step is named "auth flow stores a token + navigates into the app". The check behind it
was `navigated = not any(seg in path for seg in _AUTH_ROUTE_SEGS)` -- true for ANY path that
is not /login, /signup, /signin or /register, the site root included.

netflix-local-r1 shipped `LoginPage.jsx` doing `window.location.href = '/'` while `App.jsx`
routes `/` to `<LandingPage />` -- the signed-OUT marketing page, "Sign In" still in its
header. Token stored, /auth/login 200, `navigated` True: the walk passed a login that put
the user back where they started. A human found it by opening the app.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from multi_agent.runtime.test_user_runner import (  # noqa: E402
    _landed_in_the_app_1126, _LOGIN_AFFORDANCE_JS,
)


class TheDefectItWasWrittenFor(unittest.TestCase):

    def test_the_netflix_shape_is_not_landed(self):
        """token stored, left /login, arrived at the signed-out landing page."""
        self.assertFalse(_landed_in_the_app_1126("/", "/login", login_affordance=True))

    def test_returning_to_the_page_we_came_from_is_not_landing_either(self):
        self.assertFalse(
            _landed_in_the_app_1126("/login", "/login", login_affordance=True))


class ItMustNotCryWolf(unittest.TestCase):
    """#504 and r81 both record a working app re-wired because this harness false-alarmed."""

    def test_a_root_landing_with_no_login_affordance_passes(self):
        """The Twitter shape: `/` is the landing page signed out and the feed signed in."""
        self.assertTrue(_landed_in_the_app_1126("/", "/login", login_affordance=False))

    def test_a_real_destination_passes_even_if_something_matched(self):
        """A footer link or a closing modal on /browse is not proof of anything."""
        self.assertTrue(_landed_in_the_app_1126("/browse", "/login", login_affordance=True))

    def test_a_trailing_slash_is_the_same_place(self):
        self.assertFalse(_landed_in_the_app_1126("/", "/login", login_affordance=True))
        self.assertTrue(_landed_in_the_app_1126("/browse/", "/login", login_affordance=True))

    def test_both_signals_are_required(self):
        """Neither alone fails the step."""
        self.assertTrue(_landed_in_the_app_1126("/", "/login", login_affordance=False))
        self.assertTrue(_landed_in_the_app_1126("/feed", "/login", login_affordance=True))


class TheProbeMatchesTheRealPage(unittest.TestCase):
    """The predicate is worthless if it cannot see the control netflix actually renders."""

    def test_the_regex_matches_the_landing_controls(self):
        import re
        want = re.compile(r"^(sign ?in|log ?in|sign ?up)$", re.I)
        # exactly what LandingPage.jsx renders
        self.assertTrue(want.match("Sign In"))
        self.assertTrue(want.match("Log in"))
        # ...and what an authenticated header renders, which must NOT match
        for benign in ("Sign Out", "Log out", "Profile", "Get Started ›", "Settings"):
            self.assertIsNone(want.match(benign), benign)

    def test_the_probe_reads_password_fields_and_controls(self):
        self.assertIn("input[type=password]", _LOGIN_AFFORDANCE_JS)
        self.assertIn("getBoundingClientRect", _LOGIN_AFFORDANCE_JS)


if __name__ == "__main__":
    unittest.main()
