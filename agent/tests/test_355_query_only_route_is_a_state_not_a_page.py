"""#355: a screen whose route only adds a QUERY to an existing route is a state.

Found by running the whole seeding chain end-to-end on the real r93 design
system: with #352's routes in place the chain registers 10 ui_pages and wires 11
routes (r93 actually shipped 3), but one of them was

    <Route path="/?comments=1" ... />

React Router matches a path pattern against the PATHNAME only, so a pattern
containing `?` can never match -- that is a dead route, and dead routes are
exactly what the #238 nav gate exists to catch.

The reference spec is not wrong: fyp_comments really does live at
`/?comments=1`. It is a STATE of the feed -- the comments panel opens over `/` --
not a separate page. #352's rule ("the spec gave it a route_hint, so it is a
page") is right for `/explore` and wrong here.

So the path part decides: if a screen's route, stripped of query and fragment,
duplicates a route another screen already claims, it is an overlay/state of that
route rather than a second page. Its route keeps the query so the visual gate
can still navigate to it; it just stops being scaffolded as its own page.
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


def _assign(design, spec):
    from multi_agent.runtime.design_prep import assign_screen_routes
    return assign_screen_routes([{"name": n} for n in design],
                                [{"name": n, "route_hint": r} for n, r in spec])


R93_SPEC = [("fyp_feed", "/"), ("fyp_comments", "/?comments=1"),
            ("explore", "/explore"), ("login_modal", "/login")]
R93_DESIGN = ["fyp_feed_logged_out", "fyp_feed_comments_panel",
              "explore_grid", "login_modal"]


class AQueryOnlyVariantIsAState(unittest.TestCase):

    def test_the_comments_panel_is_not_a_second_page(self):
        got = _assign(R93_DESIGN, R93_SPEC)
        self.assertEqual(got["fyp_feed_comments_panel"]["kind"], "overlay")

    def test_the_feed_itself_stays_a_page(self):
        got = _assign(R93_DESIGN, R93_SPEC)
        self.assertEqual(got["fyp_feed_logged_out"]["kind"], "page")
        self.assertEqual(got["fyp_feed_logged_out"]["route"], "/")

    def test_the_query_route_is_kept_for_navigation(self):
        """The visual gate still needs to be able to open the panel."""
        got = _assign(R93_DESIGN, R93_SPEC)
        self.assertEqual(got["fyp_feed_comments_panel"]["route"], "/?comments=1")

    def test_distinct_paths_are_both_pages(self):
        got = _assign(R93_DESIGN, R93_SPEC)
        self.assertEqual(got["explore_grid"]["kind"], "page")
        self.assertEqual(got["login_modal"]["kind"], "page")


class NoDeadRouteReachesTheScaffold(unittest.TestCase):
    """The end-to-end symptom: `path="/?comments=1"` can never match."""

    def test_no_seeded_page_route_contains_a_query(self):
        from multi_agent.runtime.frontend_scaffold import missing_design_screen_pages
        got = _assign(R93_DESIGN, R93_SPEC)
        ds = {"screens": [{"name": n, "route": v["route"], "kind": v["kind"]}
                          for n, v in got.items()]}
        for spec in missing_design_screen_pages(ds, [], []):
            self.assertNotIn("?", spec["route"])
            self.assertNotIn("#", spec["route"])

    def test_the_feed_page_is_still_seeded(self):
        from multi_agent.runtime.frontend_scaffold import missing_design_screen_pages
        got = _assign(R93_DESIGN, R93_SPEC)
        ds = {"screens": [{"name": n, "route": v["route"], "kind": v["kind"]}
                          for n, v in got.items()]}
        routes = {s["route"] for s in missing_design_screen_pages(ds, [], [])}
        self.assertIn("/", routes)
        self.assertIn("/explore", routes)


class FragmentsAreTreatedTheSameWay(unittest.TestCase):

    def test_hash_only_variant_is_a_state(self):
        got = _assign(["home", "home_modal"],
                      [("home", "/"), ("home_open", "/#open")])
        kinds = {v["kind"] for v in got.values()}
        self.assertIn("overlay", kinds)


if __name__ == "__main__":
    unittest.main()
