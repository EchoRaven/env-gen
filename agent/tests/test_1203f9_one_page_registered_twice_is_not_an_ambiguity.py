r"""#1203f9: `login` and `login_page` on one route is ONE page, and the resolver dropped it.

`_page_name_by_route_1202fo` maps a route to the ui_page registered on it so that #1202fq can
retire a stale failure with a fresh walk recorded under a different spelling. When two names
claim one route it drops the route -- "two pages on one route: never guess" -- which is the
right answer to two pages and the wrong answer to one page registered twice.

#237 settled which is which, 100 lines earlier IN THIS FILE. `_flow_key` exists because
"`explore` / `explore_page` / `explore_screen` are the SAME user journey ... a verifier record
under either spelling satisfies the flow". `_index_ui_flow_records` keys every record through
it. This resolver was the one place that never asked.

MEASURED over the registries on disk, reading `route` the way the code does (not `path`, which
holds a SOURCE FILE in 946 records and is not a route at all -- a first pass that conflated
them inflated nothing and deflated nothing, but it was the wrong column):

    34 routes in 20 runs carry two names
    26 of them differ ONLY by the #237 suffix (search/search_page, profile/profile_page,
       reels/reels_page, home_feed/home_feed_page ...)        <- dropped for no reason
     8 are genuinely different (search_page/search_results, auth_login/login,
       for_you_page/fyp_feed, login_modal/login_page)          <- must keep dropping

So #1202fq's supersede fell back to the record's own spelling on 26 routes: the latch it
removes, reinstated for three quarters of the ambiguous routes it was meant to cover.
instagram run79 is the pair where it cost something visible -- `/login` held
`ui_flow:login` SUCCESS beside `ui_flow:login_page` FAILURE, two keys, the stale one still
"the newest word on its flow".

The fix asks `_flow_key`, so it introduces no judgement of its own: either the framework
already treats the two spellings as one journey, or they stay dropped.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "env_generator" / "llm_generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime import flow_coverage as FC          # noqa: E402
from multi_agent.runtime.delivery_gate import (              # noqa: E402
    _ui_evidence_breadth_739)


class _Reg:
    def __init__(self, pages):
        self._p = pages

    def list_ui_pages(self):
        return self._p


class _Hubs:
    def __init__(self, pages):
        self.registryhub = _Reg(pages)


def _pages(*pairs):
    """(name, route) ... as the registry stores them."""
    return {n: {"name": n, "route": r, "component": n.title().replace("_", "")}
            for n, r in pairs}


def _rec(flow, status, at, url=None):
    meta = {"check": "ui_flow", "flow": flow}
    if url:
        meta["url"] = url
    return {"name": "validation:ui_flow:%s" % flow, "status": status,
            "metadata": meta, "recorded_at": at}


class TheSuffixPairResolves(unittest.TestCase):
    def test_the_corpus_shape_is_no_longer_dropped(self):
        m = FC._page_name_by_route_1202fo(
            _Hubs(_pages(("login", "/login"), ("login_page", "/login"))))
        self.assertEqual(m.get("/login"), "login",
                         "one page registered twice was dropped as ambiguous: %r" % (m,))

    def test_the_canonical_spelling_wins_regardless_of_registry_order(self):
        for pairs in ((("login_page", "/login"), ("login", "/login")),
                      (("login", "/login"), ("login_page", "/login"))):
            m = FC._page_name_by_route_1202fo(_Hubs(_pages(*pairs)))
            self.assertEqual(m.get("/login"), "login", pairs)

    def test_a_canonical_name_that_is_not_registered_is_never_invented(self):
        """The value becomes a supersede key; a key no record carries retires nothing."""
        m = FC._page_name_by_route_1202fo(
            _Hubs(_pages(("explore_grid_page", "/explore"),
                         ("explore_grid_screen", "/explore"))))
        self.assertIn(m.get("/explore"), ("explore_grid_page", "explore_grid_screen"), m)
        self.assertNotEqual(m.get("/explore"), "explore_grid",
                            "invented a page name nothing is registered under")

    def test_the_three_suffix_spellings_still_collapse(self):
        m = FC._page_name_by_route_1202fo(
            _Hubs(_pages(("explore", "/explore"), ("explore_page", "/explore"),
                         ("explore_screen", "/explore"))))
        self.assertEqual(m.get("/explore"), "explore", m)


class TwoPagesAreStillNeverGuessed(unittest.TestCase):
    def test_genuinely_different_names_still_drop(self):
        for a, b in (("search_page", "search_results"), ("auth_login", "login"),
                     ("for_you_page", "fyp_feed"), ("login_modal", "login_page")):
            m = FC._page_name_by_route_1202fo(_Hubs(_pages((a, "/x"), (b, "/x"))))
            self.assertNotIn("/x", m,
                             "guessed between two different pages %r/%r: %r" % (a, b, m))

    def test_a_suffix_pair_mixed_with_a_third_name_still_drops(self):
        m = FC._page_name_by_route_1202fo(
            _Hubs(_pages(("login", "/login"), ("login_page", "/login"),
                         ("auth_login", "/login"))))
        self.assertNotIn("/login", m,
                         "a real second page must not be lost in the suffix pair: %r" % (m,))

    def test_one_name_on_one_route_is_untouched(self):
        m = FC._page_name_by_route_1202fo(
            _Hubs(_pages(("live_discover", "/live"), ("explore", "/explore"))))
        self.assertEqual(m, {"/live": "live_discover", "/explore": "explore"})


class TheKindIsNotCollapsedWithTheTarget(unittest.TestCase):
    """The canonicaliser runs on the TARGET only. Merging `ui_smoke:login` into
    `ui_flow:login` would let one kind of evidence answer for another, which is the thing
    #830's `_UI_SMOKE_EVIDENCE_CHECKS` split exists to keep separate."""

    def _rec_kind(self, kind, target, status, at):
        return {"name": "validation:%s:%s" % (kind, target), "status": status,
                "metadata": {"check": kind, "flow": target}, "recorded_at": at}

    def test_a_passing_smoke_does_not_retire_a_failing_flow(self):
        recs = [self._rec_kind("ui_flow", "login_page", "failure", 1000.0),
                self._rec_kind("ui_smoke", "login", "success", 9000.0)]
        b = _ui_evidence_breadth_739(recs)
        self.assertEqual(b["failed_records"], 1,
                         "a ui_smoke pass answered for a ui_flow failure")

    def test_the_two_spellings_of_one_kind_do_merge(self):
        recs = [self._rec_kind("ui_flow", "login_page", "failure", 1000.0),
                self._rec_kind("ui_flow", "login", "success", 9000.0)]
        b = _ui_evidence_breadth_739(recs)
        self.assertEqual(b["failed_records"], 0,
                         "the suffix spellings did not merge without the map: %r"
                         % (b.get("pages_failed"),))


class TheLatchActuallyOpens(unittest.TestCase):
    """End to end, in the shape instagram run79 shipped: the point is the GATE, not the map."""

    def test_a_fresh_pass_under_the_suffix_spelling_retires_the_stale_failure(self):
        m = FC._page_name_by_route_1202fo(
            _Hubs(_pages(("login", "/login"), ("login_page", "/login"))))
        recs = [_rec("login_page", "failure", 1000.0),
                _rec("login", "success", 9000.0, "http://localhost:8081/login")]
        b = _ui_evidence_breadth_739(recs, page_by_route=m)
        self.assertEqual(b["failed_records"], 0,
                         "the stale failure still blocks: %r" % (b.get("pages_failed"),))

    def test_a_newer_failure_under_either_spelling_still_blocks(self):
        m = FC._page_name_by_route_1202fo(
            _Hubs(_pages(("login", "/login"), ("login_page", "/login"))))
        recs = [_rec("login", "success", 1000.0),
                _rec("login_page", "failure", 9000.0, "http://localhost:8081/login")]
        b = _ui_evidence_breadth_739(recs, page_by_route=m)
        self.assertEqual(b["failed_records"], 1,
                         "collapsing the spellings must not blunt the gate")

    def test_two_real_pages_keep_their_separate_verdicts(self):
        m = FC._page_name_by_route_1202fo(
            _Hubs(_pages(("auth_login", "/login"), ("login", "/login"))))
        recs = [_rec("auth_login", "failure", 1000.0),
                _rec("login", "success", 9000.0, "http://localhost:8081/login")]
        b = _ui_evidence_breadth_739(recs, page_by_route=m)
        self.assertEqual(b["failed_records"], 1,
                         "a different page's pass must not answer for this one")


if __name__ == "__main__":
    unittest.main()
