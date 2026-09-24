"""#1202hp — an agent's probe registration became a page, a route, and a delivery blocker.

tiktok-web-r106's ui_pages ledger carries, alongside its 13 real pages:

    key   __noop_monitor_do_not_use__
    {"id": "page:ui:__noop_monitor_do_not_use__", "route": "", "component": "",
     "apis_used": [], "status": "implemented", "metadata": {"notes": "noop? no"},
     "_updated_by": "orchestrator"}

The orchestrator AGENT wrote it while probing its own tool — `"notes": "noop? no"` is the
probe talking. The framework then took it at face value:

  * `frontend_page_projector` wrote `src/pages/NoopMonitorDoNotUse.jsx` and routed it in
    App.jsx as `/noop-monitor-do-not-use`;
  * `deliverability_frontend_fallback_page` blocked delivery — "route
    /noop-monitor-do-not-use renders a framework fallback page (`NoopMonitorDoNotUse`) —
    author the REAL page (reference layout, real fields, real controls)";
  * `deliverability_other` blocked again on the same file as a placeholder route;
  * `deliverability_ui_page_unwired x8` counted it first of the eight;
  * and a P0 task went to the frontend lane telling it to author a real page for something
    whose own name says DO NOT USE.

The framework already knows this class. `_tag_parked_probe_1202dw` does exactly this job for
ENDPOINTS, and its docstring records the same damage on that side: "the orchestrator agent
authored a P0 telling backend to write 'real DB-backed state/check logic' for
`GET /__noop_orchestrator_state_check__`, which the lane then went grepping app/backend for,
across runs." Its stated convention is a LEADING `__` segment. The page pipeline never got it.

Measured over the 145 runs with hub stores here: 41 (28%) carry `__`-prefixed probe
ENDPOINTS, so agents probe these registration tools constantly; 2 carry a probe UI PAGE
(netflix-local-r14's `noop_should_not_register`, r106's). Rare on the page side, but when it
lands it is an unwinnable blocker, and the fix is the framework's own existing convention
applied to the half that was missing.

Dropped at the PRODUCER, next to `drop_component_page_twins_1087`, rather than exempted in
each gate: if the projector never writes the file, there is no route for any reader to flag,
and the three separate checks above stop disagreeing about it without being touched.
"""
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "env_generator" / "llm_generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime.frontend_scaffold import drop_sentinel_pages_1202hp


def _pages():
    return {
        "__noop_monitor_do_not_use__": {"id": "page:ui:__noop_monitor_do_not_use__",
                                        "name": "__noop_monitor_do_not_use__",
                                        "route": "", "component": "",
                                        "metadata": {"notes": "noop? no"}},
        "fyp_feed_logged_out": {"id": "page:ui:fyp_feed_logged_out",
                                "name": "fyp_feed_logged_out", "route": "/",
                                "component": "FeedPage"},
        "explore_grid": {"id": "page:ui:explore_grid", "name": "explore_grid",
                         "route": "/explore", "component": "ExplorePage"},
    }


class SentinelPages(unittest.TestCase):
    def test_the_probe_page_is_dropped(self):
        kept = drop_sentinel_pages_1202hp(_pages())
        self.assertNotIn("__noop_monitor_do_not_use__", kept)

    def test_every_real_page_survives(self):
        kept = drop_sentinel_pages_1202hp(_pages())
        self.assertEqual(sorted(kept), ["explore_grid", "fyp_feed_logged_out"])

    def test_the_convention_is_a_LEADING_double_underscore(self):
        """#1202dw's wording, kept verbatim: `/api/__x` is app surface and is left alone. A
        single leading underscore is a naming style, not the framework's probe marker."""
        pages = {**_pages(),
                 "_drafts": {"name": "_drafts", "route": "/drafts"},
                 "my__weird__name": {"name": "my__weird__name", "route": "/w"}}
        kept = drop_sentinel_pages_1202hp(pages)
        self.assertIn("_drafts", kept)
        self.assertIn("my__weird__name", kept)

    def test_the_name_decides_when_the_key_does_not(self):
        """The ledger is keyed by name today, but the record carries its own `name` and a
        caller may hand this either shape — reading only the key would make the filter
        silently inert for the other one."""
        kept = drop_sentinel_pages_1202hp(
            {"page:ui:__probe__": {"name": "__probe__", "route": ""},
             "ok": {"name": "ok", "route": "/ok"}})
        self.assertEqual(list(kept), ["ok"])

    def test_a_hostile_store_never_raises_and_is_returned_unchanged(self):
        """This sits in the path that gives the app its pages — #1087's own rule: any fault
        returns the INPUT, not a substitute. Returning `{}` for a store that could not be
        read would be a silent empty default (#883) and would erase every page."""
        for bad in (None, {}, {"x": None}, {"y": "not-a-mapping"}, []):
            self.assertEqual(drop_sentinel_pages_1202hp(bad), bad)


if __name__ == "__main__":
    unittest.main()
