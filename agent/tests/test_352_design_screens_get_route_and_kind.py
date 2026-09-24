"""#352 (step A): give every measured screen a deterministic route + kind.

`missing_design_screen_pages` skips any screen whose route is missing:

    route = str(s.get("route") or "").strip()
    if not route.startswith("/") or norm in seen_routes:
        continue

and `design_system.json` carries NO `route` and NO `kind` on any screen in any
run -- its keys are name / reference / layout / layout_metrics / components. So
11 of 11 screens were skipped and the #225 seeding NEVER fired:
`grep -c "#225 registered design-screen"` over r91/r92/r93/r94 = 0, 0, 0, 0.

Cause: the run takes the AGENT path, and `build_design_analyst_briefing` never
asks for route/kind -- those fields exist only in the single-shot FALLBACK
prompt, optional even there -- and nothing backfills them.

Two collateral effects this also fixes:

  * `visual_fidelity.load_screen_classifications` returns {} every run, so FIX
    #132's authoritative reference->route map degrades to filename guessing --
    which is where the 10-entry social `_ROUTE_KEYWORDS` catalog does its damage
    (it forces requires_auth on any Google-Maps `*search*` reference).
  * `kind` is currently guessed by an overlay NAME regex, which demoted r92's
    `login_modal` to advisory and left the blocking set EMPTY -- the direct
    cause of "PASSED: all 0 screens >= 0.65".

Derivation, both halves deterministic:

  route -- from `reference_spec.json`'s authoritative `route_hint`, matched by
  TOKEN OVERLAP because the analyst names screens after reference FILENAMES
  (`explore_grid`, `profile_own`) while the spec uses logical names (`explore`,
  `profile`). Exact-name matching resolves only 2 of 11. Assignment is
  greedy-by-score with deterministic tie-breaking and each route claimed once.

  kind -- a screen the spec gives a route_hint IS reachable by URL, so it is a
  `page`. Only a screen no route can be assigned to is an `overlay`. This is a
  better rule than the name regex: login_modal's route_hint is `/login`.

Geometry was considered and rejected: `layout_metrics` measures the whole
screenshot (login_modal is 2840x1596, same as the pages), so it cannot
discriminate an overlay.
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

# The REAL r93 pairing: analyst screen names vs spec names/routes.
DESIGN = ["explore_grid", "following_suggested_creators", "friends_suggested_creators",
          "fyp_feed_comments_panel", "fyp_feed_logged_out", "live_discover",
          "login_modal", "messages_dm_empty", "notifications_activity",
          "profile_own", "settings_more_menu"]
SPEC = [("fyp_feed", "/"), ("fyp_comments", "/?comments=1"), ("login_modal", "/login"),
        ("signup", "/signup"), ("explore", "/explore"), ("following", "/following"),
        ("friends", "/friends"), ("live_discover", "/live"), ("messages", "/messages"),
        ("activity", "/activity"), ("profile", "/@:username"),
        ("settings_more", "/settings")]


def _assign(design=None, spec=None):
    from multi_agent.runtime.design_prep import assign_screen_routes
    return assign_screen_routes(
        [{"name": n} for n in (design if design is not None else DESIGN)],
        [{"name": n, "route_hint": r} for n, r in (spec if spec is not None else SPEC)])


class EveryMeasuredScreenGetsARoute(unittest.TestCase):

    def test_all_eleven_r93_screens_resolve(self):
        got = _assign()
        self.assertEqual(len(got), len(DESIGN))
        unrouted = [n for n, v in got.items() if not str(v.get("route") or "").startswith("/")]
        self.assertEqual(unrouted, [])

    def test_filename_style_names_match_logical_spec_names(self):
        got = _assign()
        self.assertEqual(got["explore_grid"]["route"], "/explore")
        self.assertEqual(got["profile_own"]["route"], "/@:username")
        self.assertEqual(got["notifications_activity"]["route"], "/activity")
        self.assertEqual(got["settings_more_menu"]["route"], "/settings")

    def test_the_ambiguous_fyp_pair_is_split_correctly(self):
        """fyp_feed_comments_panel and fyp_feed_logged_out both overlap fyp_feed
        and fyp_comments; each route may be claimed once."""
        got = _assign()
        self.assertEqual(got["fyp_feed_comments_panel"]["route"], "/?comments=1")
        self.assertEqual(got["fyp_feed_logged_out"]["route"], "/")

    def test_no_route_is_assigned_twice(self):
        routes = [v["route"] for v in _assign().values()]
        self.assertEqual(len(routes), len(set(routes)))

    def test_assignment_is_deterministic(self):
        self.assertEqual(_assign(), _assign())


class KindComesFromReachabilityNotFromTheFilename(unittest.TestCase):

    def test_a_routed_modal_is_a_page_not_an_overlay(self):
        """r92 demoted login_modal to advisory and left the blocking set empty."""
        self.assertEqual(_assign()["login_modal"]["kind"], "page")

    def test_every_r93_screen_is_a_page_except_the_feed_state(self):
        """This originally asserted all 11 are pages. That expectation was MINE
        and it was wrong: fyp_comments' route_hint is `/?comments=1`, a query on
        the feed's own path -- the comments panel opening OVER `/`, not a second
        page. #355 makes the path part decide, so exactly one screen here is a
        state. Scaffolding it as a page emitted `<Route path="/?comments=1">`,
        which can never match."""
        got = _assign()
        pages = {n for n, v in got.items() if v["kind"] == "page"}
        overlays = {n for n, v in got.items() if v["kind"] == "overlay"}
        self.assertEqual(overlays, {"fyp_feed_comments_panel"})
        self.assertEqual(len(pages), len(DESIGN) - 1)

    def test_an_unroutable_screen_is_an_overlay(self):
        got = _assign(design=["search_flyout"], spec=[("explore", "/explore")])
        self.assertEqual(got["search_flyout"]["kind"], "overlay")


class DegenerateInputs(unittest.TestCase):

    def test_no_spec_falls_back_to_a_slug(self):
        got = _assign(design=["explore_grid"], spec=[])
        self.assertTrue(got["explore_grid"]["route"].startswith("/"))

    def test_empty_design_returns_empty(self):
        self.assertEqual(_assign(design=[], spec=SPEC), {})

    def test_more_screens_than_routes_still_routes_everything(self):
        got = _assign(design=["a_page", "b_page", "c_page"], spec=[("a", "/a")])
        self.assertEqual(len([v for v in got.values() if v["route"].startswith("/")]), 3)


if __name__ == "__main__":
    unittest.main()
