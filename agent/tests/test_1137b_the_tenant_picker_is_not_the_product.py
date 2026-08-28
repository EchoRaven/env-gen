"""#1137b: `/tenants` satisfies #1137's rule and is still the wrong place to land.

netflix-local-r5 DELIVERED with `window.location.href = '/tenants'`. By #1137's rule that is
correct — a route that requires auth, not the signed-out root — and as a product landing it is
wrong. r5's route order is:

    /login, /signup, /tenants, /profiles, /, /browse, /catalog, /search

The tenant picker is there because the FRAMEWORK supports multi-tenancy, not because the
product has anything on it. Skipping that category makes r5 choose `/profiles`, which for this
product is also what the real thing does after sign-in.

Generic, not Netflix-shaped: `/tenants`, `/admin`, `/oauth`, `/health`, `/debug` are infra
surfaces in any generated app. And a platform page is still preferred over `/` — the front
door is the defect #1137 exists to prevent.
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

from multi_agent.runtime.frontend_scaffold import _post_auth_dest_1137 as dest  # noqa: E402

# exactly what netflix-local-r5 shipped
R5 = [("Sign in", "/login"), ("Sign up", "/signup"), ("Tenants", "/tenants"),
      ("Profiles", "/profiles"), ("Home", "/"), ("Browse", "/browse")]


class TheDeliveredRunWouldNowLandProperly(unittest.TestCase):

    def test_r5_chooses_profiles_over_the_tenant_picker(self):
        self.assertEqual(dest(R5), "/profiles")

    def test_platform_surfaces_are_skipped_generally(self):
        for infra in ("/tenants", "/tenant/pick", "/admin", "/oauth/consent",
                      "/health", "/debug/state", "/_internal"):
            self.assertEqual(dest([("x", infra), ("Feed", "/feed")]), "/feed", infra)


class TheFallbacksStayOrdered(unittest.TestCase):
    """A platform page is still better than the signed-out front door."""

    def test_a_platform_page_beats_the_root(self):
        self.assertEqual(dest([("Tenants", "/tenants")]), "/tenants")

    def test_auth_routes_are_never_chosen_even_as_fallback(self):
        self.assertEqual(dest([("Sign in", "/login"), ("Sign up", "/signup")]), "/")

    def test_no_routes_keeps_todays_behaviour(self):
        for empty in ([], None, [("x", "  ")]):
            self.assertEqual(dest(empty), "/")

    def test_the_root_is_never_the_destination(self):
        self.assertEqual(dest([("Home", "/"), ("Browse", "/browse")]), "/browse")

    def test_malformed_input_does_not_raise(self):
        for bad in ("nope", [("one",)], [None], 7):
            self.assertEqual(dest(bad), "/")


if __name__ == "__main__":
    unittest.main()
