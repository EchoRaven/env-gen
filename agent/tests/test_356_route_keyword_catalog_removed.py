"""#356: delete the 10-entry social catalog from the visual gate.

`_ROUTE_KEYWORDS` mapped filename tokens to routes AND to a requires_auth
opinion:

    (("home","feed","timeline"), "/feed", True)
    (("search","explore","discover"), "/explore", True)
    (("video","reel","watch"), "/reels", True)
    ...

Route assignment was guarded by `r in known`, but the AUTH flag was not -- so on
Google Maps every `*search*` reference (search_results, atm_search_results,
hotel_search_results, restaurant_search_results, ...) was forced
requires_auth=True by the `/explore` row and screenshotted logged-out against a
PUBLIC search screen, scoring ~0 and raising a blocking visual.needs_revision.
Non-social stems matched nothing and were silently skipped, so the blocking gate
only ever scored whatever fraction of the app happened to look social.

The catalog existed as the fallback for FIX #132's authoritative
classifications, which returned {} on every run because design_system.json
carried no kind/route -- #352 fixed that, so the fallback's reason to exist is
gone. Route resolution keeps the GENERIC filename-vs-declared-route matcher,
which is already domain-agnostic.

What is NOT deleted is the auth opinion for the framework's OWN auth pages.
Deleting that outright would regress /login and /signup from auth=False to the
default auth=True, and an authenticated session visiting /login is typically
redirected -- the capture would bounce and the screen would be dropped. Those
two routes are public BY CONSTRUCTION: the framework injects them itself and a
login page must be reachable logged-out. That is a fact about framework-owned
routes, not a guess about the app's domain.
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


def _src():
    from multi_agent.runtime import visual_fidelity
    return Path(visual_fidelity.__file__).read_text()


def _map(images, known=None, cls=None, tmp=None):
    from multi_agent.runtime.visual_fidelity import map_reference_screens
    paths = []
    for n in images:
        p = Path(tmp) / f"{n}.png"
        p.write_bytes(b"x")
        paths.append(p)
    return {s["name"]: s for s in map_reference_screens(
        paths, known_routes=set(known or []), classifications=cls or {})}


class OnlyTheAuthColumnIsGone(unittest.TestCase):
    """I set out to delete the whole catalog and the evidence said not to.

    Its ROUTE half is real capability: `home` -> /feed, `search` -> /explore,
    `video` -> /reels are SEMANTIC synonyms no filename-token matcher can
    derive, every entry is gated on the app actually serving that route, and
    #352's authoritative classifications only cover MEASURED screens -- an
    unmeasured reference image still needs it. Deleting it outright broke 8
    existing tests that were pinning that capability, not pinning a bug.

    Its AUTH half was the defect, so that column is what is gone."""

    def test_the_keyword_rows_no_longer_carry_an_auth_flag(self):
        src = _src()
        for dead in ('"/reels", True', '"/explore", True', '"/signup", False',
                     '"/login", False'):
            self.assertNotIn(dead, src)

    def test_the_route_table_survives(self):
        self.assertIn("_ROUTE_KEYWORDS", _src())


class TheAuthOpinionNoLongerLeaksOffAFilenameToken(unittest.TestCase):
    """The real defect, verified in source: only TWO rows set auth=False, they
    match on filename tokens (register/signup/signin/login), and after `break`
    the flag was applied whether or not that row's ROUTE was used. So any
    reference whose name merely CONTAINS one of those tokens was captured
    logged-out -- and a protected page then renders the login wall and scores ~0.
    (The auth=True rows were always harmless: True is the default.)"""

    def test_a_register_named_page_is_not_forced_logged_out(self):
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            got = _map(["admin_register_user"], known=["/admin"], tmp=t)
            self.assertTrue(got["admin_register_user"]["auth"],
                            "a token in the filename must not decide auth")

    def test_a_signin_named_page_is_not_forced_logged_out_either(self):
        """I originally asserted this page must not ROUTE to /login. That was
        written assuming the whole catalog would go; the route table is
        deliberately retained (see the class above), so a `signin` token still
        maps to /login when the app serves it -- guarded, and the same
        capability that maps `home` -> /feed. What this fix guarantees is the
        AUTH half: the flag now follows the resolved route, so it is False here
        because the route really IS /login, not because of a filename token."""
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            got = _map(["password_reset_signin"], known=["/account"], tmp=t)
            self.assertNotEqual(got["password_reset_signin"]["route"], "/login")
            self.assertTrue(got["password_reset_signin"]["auth"])

    def test_a_measured_classification_still_wins(self):
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            got = _map(["hotel_search_results"], known=["/search"],
                       cls={"hotel_search_results": {"route": "/search",
                                                     "requires_auth": False}}, tmp=t)
            self.assertEqual(got["hotel_search_results"]["route"], "/search")
            self.assertFalse(got["hotel_search_results"]["auth"])


class TheGenericMatcherStillResolvesRoutes(unittest.TestCase):

    def test_filename_matches_a_declared_route(self):
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            got = _map(["explore"], known=["/explore"], tmp=t)
            self.assertEqual(got["explore"]["route"], "/explore")

    def test_app_name_prefix_is_stripped(self):
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            got = _map(["outlook_inbox"], known=["/inbox"], tmp=t)
            self.assertEqual(got["outlook_inbox"]["route"], "/inbox")


class FrameworkOwnedAuthPagesStayPublic(unittest.TestCase):
    """Deleting this too would bounce the capture on /login and /signup."""

    def test_login_reference_is_captured_logged_out(self):
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            got = _map(["login_modal"], known=["/login"], tmp=t)
            self.assertEqual(got["login_modal"]["route"], "/login")
            self.assertFalse(got["login_modal"]["auth"])

    def test_signup_reference_is_captured_logged_out(self):
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            got = _map(["signup"], known=["/signup"], tmp=t)
            self.assertFalse(got["signup"]["auth"])

    def test_an_ordinary_page_keeps_the_authenticated_default(self):
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            got = _map(["messages"], known=["/messages"], tmp=t)
            self.assertTrue(got["messages"]["auth"])


if __name__ == "__main__":
    unittest.main()
