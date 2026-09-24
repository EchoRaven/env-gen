"""#354 (FE-F5): a dead nav link that points at a REFERENCE screen must be built,
not deleted.

`dead_nav_link_remediation` has two branches: if the target is a declared
ui_page, "wire the missing route" (right); otherwise "CHEAPEST FIX FIRST: remove
this extra nav item". "Declared ui_page" is its only notion of in-scope.

But the sidebar the lane draws comes FROM the reference. A link to /explore or
/messages is not an "extra nav item" -- the reference shows those screens exist;
they are simply pages the contract has not scoped yet. Telling the lane the
cheapest fix is to delete them is how r93's App.jsx ended up wiring exactly
three routes (/login, /signup, /) against an 11-screen reference, and how r92
ended up with 11 `StubPage` routes. That is the mechanism behind "UI is not
similar enough".

#352 now assigns every measured screen a route, so there is a third, decisive
signal available: the target matches a MEASURED REFERENCE SCREEN. Then the fix
is to author that page.

The #278 case this must not regress is real: r61 stalled 81 minutes oscillating
on /shop and /upload, nav links the lane drew that the contract never declared
AND the reference never showed. Those still get "remove or repoint" -- the
cheap fix stays cheap for genuinely out-of-scope links.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _rem(target, declared=(), reference=()):
    from multi_agent.runtime.frontend_audit import dead_nav_link_remediation
    return dead_nav_link_remediation(
        target, "SidebarNavigation.jsx", set(declared),
        reference_routes=set(reference))


class AReferenceScreenIsBuiltNotDeleted(unittest.TestCase):

    def test_it_says_author_the_page(self):
        msg = _rem("/explore", declared=(), reference=("/explore", "/messages"))
        self.assertIn("author", msg.lower())

    def test_it_does_not_advise_removal(self):
        msg = _rem("/explore", declared=(), reference=("/explore",))
        self.assertNotIn("remove this extra nav item", msg)

    def test_it_names_the_reference_as_the_reason(self):
        msg = _rem("/messages", declared=(), reference=("/messages",))
        self.assertIn("reference", msg.lower())

    def test_query_and_hash_are_normalised_before_matching(self):
        msg = _rem("/explore?tab=all#top", declared=(), reference=("/explore",))
        self.assertIn("author", msg.lower())

    def test_trailing_slash_is_normalised(self):
        msg = _rem("/messages/", declared=(), reference=("/messages",))
        self.assertIn("author", msg.lower())


class TheDeclaredPageBranchIsUnchanged(unittest.TestCase):

    def test_declared_page_still_says_wire_the_route(self):
        msg = _rem("/explore", declared=("/explore",), reference=("/explore",))
        self.assertIn("Wire the missing route", msg)

    def test_declared_wins_over_reference(self):
        """A declared page needs its route wired, not authored from scratch."""
        msg = _rem("/explore", declared=("/explore",), reference=("/explore",))
        self.assertNotIn("author", msg.lower().split("wire")[0])


class TrulyOutOfScopeLinksKeepTheCheapFix(unittest.TestCase):
    """#278: r61 stalled 81 min oscillating on /shop and /upload."""

    def test_unknown_link_still_says_remove_or_repoint(self):
        msg = _rem("/shop", declared=(), reference=("/explore", "/messages"))
        self.assertIn("remove this extra nav item", msg)

    def test_no_reference_data_preserves_the_old_behaviour(self):
        msg = _rem("/shop", declared=(), reference=())
        self.assertIn("remove this extra nav item", msg)

    def test_backwards_compatible_without_the_new_argument(self):
        from multi_agent.runtime.frontend_audit import dead_nav_link_remediation
        msg = dead_nav_link_remediation("/shop", "Nav.jsx", set())
        self.assertIn("remove this extra nav item", msg)


class ReferenceRoutesComeFromTheMeasuredScreens(unittest.TestCase):

    def test_routes_are_read_from_the_design_system(self):
        import json
        import tempfile
        from multi_agent.runtime.frontend_audit import reference_screen_routes
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "design"
            d.mkdir()
            (d / "design_system.json").write_text(json.dumps({"screens": [
                {"name": "explore_grid", "route": "/explore", "kind": "page"},
                {"name": "search_flyout", "route": "/search-flyout", "kind": "overlay"},
            ]}))
            got = reference_screen_routes(tmp)
        self.assertIn("/explore", got)

    def test_overlays_are_not_pages_to_author(self):
        import json
        import tempfile
        from multi_agent.runtime.frontend_audit import reference_screen_routes
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "design"
            d.mkdir()
            (d / "design_system.json").write_text(json.dumps({"screens": [
                {"name": "search_flyout", "route": "/search-flyout", "kind": "overlay"},
            ]}))
            self.assertEqual(reference_screen_routes(tmp), set())

    def test_missing_design_system_is_empty_not_an_error(self):
        import tempfile
        from multi_agent.runtime.frontend_audit import reference_screen_routes
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(reference_screen_routes(tmp), set())


if __name__ == "__main__":
    unittest.main()
