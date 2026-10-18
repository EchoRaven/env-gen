r"""#1203od: the route guard ate the page name, and the gate read the guard.

`_placeholder_route_blockers_1202w` blocks a delivery whose App.jsx routes a page whose NAME
says it is a placeholder (`PlaceholderPage`, `DummyToGetRegistryList`, four corpus runs shipped
one live). It read routes with `element=\{\s*<(\w+)`, which captures the FIRST identifier after
`element={` -- and in `element={<RequireAuth><BrowsePage/></RequireAuth>}` that is the guard.

MEASURED over the 102 delivered App.jsx files: the naive read sees 1114 component names, the
wrapper-aware read sees 1527. 31 runs gain names and the shortfall is not marginal --
netflix-local-r35 routes 30 pages and the check examined 5, r41 5 of 28, r8 5 of 26 -- and every
one of those runs is netflix. The check was correct on the product it was written for and nearly
blind on another, which is the generality bar, not a nicety.

★ `_route_element` IN THE SAME MODULE HAS DONE THIS CORRECTLY SINCE IT WAS WRITTEN -- its
docstring says "the PAGE, not the guard". So this is #1032's rule applied rather than a new
idea: the module that owns route parsing owns this question, and the gate stops hand-rolling a
narrower regex beside a correct one.

★ IT CHANGES NO VERDICT ON TODAY'S CORPUS, and that belongs in the open: the junk vocabulary
matches 0 of the 1114 names the gate saw and 0 of the 413 it was missing. The four runs carrying
a junk-named component carry it as an UNROUTED file (`NoopProbeDoNotUse`), which #1202hp drops at
the producer. This closes a blind spot; the tests that pin the blind spot are the load-bearing
half, and they are written against synthetic App.jsx files for exactly that reason.

★ AND ONE MISATTRIBUTION I CAUGHT BEFORE IT BECAME A CLAIM. 27 `route ... not wired in App.jsx`
lines sit in three runs that route pages behind wrappers, and the #146 drift path at
`_audit_ui_page` is wrapper-blind too, so it looked like the live damage. It is not: r38's
`/login` is wired BARE (`element={<LoginPage`) and was complained about anyway, so those lines
come from ticks before App.jsx held its routes. Recorded here so nobody re-derives it as
evidence.
"""
import inspect
import re
import unittest
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime import deliverability as D
from env_generator.llm_generator.multi_agent.runtime.frontend_audit import (
    routed_page_components_1203od as rpc,
)

_NAIVE = re.compile(r"element=\{\s*<(\w+)")


class TheReaderReturnsThePageNotTheGuard(unittest.TestCase):
    def test_a_bare_element(self):
        self.assertEqual(rpc('<Route path="/" element={<Home />} />'), (["Home"], "read"))

    def test_a_guard_wrapping_the_page(self):
        src = '<Route path="/b" element={<RequireAuth><BrowsePage/></RequireAuth>} />'
        self.assertEqual(rpc(src), (["BrowsePage"], "read"))
        self.assertEqual(_NAIVE.findall(src), ["RequireAuth"],
                         "the naive regex stopped returning the guard, so this test no "
                         "longer exercises the blind spot it was written for")

    def test_two_nested_wrappers(self):
        self.assertEqual(
            rpc('<Route path="/b" element={<Layout><RequireAuth><Deep/></RequireAuth></Layout>} />'),
            (["Deep"], "read"))

    def test_an_unknown_wrapper_is_handled_too(self):
        """The corpus uses names the shared list does not carry (`Protected`, `Authed`,
        `CatalogProtected`), so taking the INNERMOST name is what makes this general."""
        self.assertEqual(
            rpc('<Route path="/b" element={<CatalogProtected><Browse/></CatalogProtected>} />'),
            (["Browse"], "read"))

    def test_a_suspense_fallback_does_not_become_the_page(self):
        self.assertEqual(
            rpc('<Route path="/b" element={<Suspense fallback={<Spin/>}><Real/></Suspense>} />'),
            (["Real"], "read"))

    def test_several_routes_are_all_returned(self):
        names, state = rpc('<Route path="/a" element={<A/>}/>'
                           '<Route path="/b" element={<Guard><B/></Guard>}/>')
        self.assertEqual((names, state), (["A", "B"], "read"))


class TheThreeStatesAreDistinguished(unittest.TestCase):
    def test_an_app_with_no_router_is_not_unchecked(self):
        """googlemaps-r15's App.jsx renders its own markup and declares no `<Route`. "No
        routed pages" is the TRUE answer there, so it must not announce."""
        self.assertEqual(rpc('<div>single page app</div>'), ([], "no-routes"))

    def test_a_route_that_yields_no_component_is_unchecked(self):
        """#883: this file DOES declare routes and none gave a name, so the check looked at
        nothing and may not read as clean."""
        self.assertEqual(rpc('<Route path="/x" />'), ([], "unparsed"))

    def test_garbage_is_unchecked_not_clean(self):
        self.assertEqual(rpc(None), ([], "unparsed"))


class _Tree(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.app = Path(self._tmp.name) / "app"
        self.src = self.app / "frontend" / "src"
        self.src.mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def app_jsx(self, body):
        (self.src / "App.jsx").write_text(body, encoding="utf-8")


class TheGateSeesThroughTheGuard(_Tree):
    def test_a_placeholder_page_behind_a_guard_is_blocked(self):
        """The blind spot, stated as one assertion."""
        self.app_jsx('<Route path="/x" element={<RequireAuth><PlaceholderPage/></RequireAuth>} />')
        rows = D._placeholder_route_blockers_1202w(self.app)
        self.assertEqual(len(rows), 1, rows)
        self.assertIn("PlaceholderPage", rows[0])

    def test_a_bare_placeholder_page_is_still_blocked(self):
        self.app_jsx('<Route path="/x" element={<DummyPage/>} />')
        self.assertTrue(D._placeholder_route_blockers_1202w(self.app))

    def test_a_real_page_behind_a_guard_is_silent(self):
        self.app_jsx('<Route path="/b" element={<RequireAuth><BrowsePage/></RequireAuth>} />')
        self.assertEqual(D._placeholder_route_blockers_1202w(self.app), [])

    def test_a_junk_named_WRAPPER_is_not_the_finding(self):
        """Narrow on purpose, and the same convention `_route_element` set: the question is
        what the user LANDS ON. `TodoGuard` is not a page, and reporting it would hand the
        lane a finding about its own route plumbing."""
        self.app_jsx('<Route path="/x" element={<TodoGuard><BrowsePage/></TodoGuard>} />')
        self.assertEqual(D._placeholder_route_blockers_1202w(self.app), [])

    def test_a_junk_page_inside_a_junk_named_wrapper_is_still_blocked(self):
        self.app_jsx('<Route path="/x" element={<TodoGuard><DummyPage/></TodoGuard>} />')
        self.assertTrue(D._placeholder_route_blockers_1202w(self.app))


class AnUncheckedAppSaysSo(_Tree):
    def _said(self, fn):
        said = []
        orig = D._gate_absent_792
        D._gate_absent_792 = lambda *a, **k: said.append(a)
        try:
            fn()
        finally:
            D._gate_absent_792 = orig
        return said

    def test_a_frontend_with_no_app_jsx_announces(self):
        said = self._said(lambda: D._placeholder_route_blockers_1202w(self.app))
        self.assertTrue(said, "a scaffolded frontend with no router was scored clean in "
                              "silence")

    def test_a_tree_with_no_frontend_src_stays_quiet(self):
        """★ The precondition that keeps the announcement informative: the gate also runs on
        ticks BEFORE the frontend is scaffolded, and a line that fires on every run says
        nothing."""
        import shutil
        shutil.rmtree(self.src)
        said = self._said(lambda: D._placeholder_route_blockers_1202w(self.app))
        self.assertEqual(said, [], "it announces on every pre-scaffold tick")

    def test_routes_that_parse_to_nothing_announce(self):
        self.app_jsx('<Routes><Route path="/x" /></Routes>')
        said = self._said(lambda: D._placeholder_route_blockers_1202w(self.app))
        self.assertTrue(said)

    def test_a_single_page_app_is_clean_without_announcing(self):
        self.app_jsx('export default function App() { return <div>hi</div>; }')
        said = self._said(lambda: D._placeholder_route_blockers_1202w(self.app))
        self.assertEqual(said, [])
        self.assertEqual(D._placeholder_route_blockers_1202w(self.app), [])


class OneOwnerForRouteParsing(unittest.TestCase):
    """#1032: the gate must not carry its own route-element regex beside the module that
    owns the question."""

    def test_the_gate_no_longer_hand_rolls_the_read(self):
        src = inspect.getsource(D._placeholder_route_blockers_1202w)
        self.assertIn("routed_page_components_1203od", src)
        self.assertNotIn("element=\\{\\s*<(\\w+)", src)

    def test_the_reader_shares_the_wrapper_list_rather_than_copying_it(self):
        from env_generator.llm_generator.multi_agent.runtime import frontend_audit as FA
        src = inspect.getsource(FA.routed_page_components_1203od)
        self.assertIn("_ROUTE_WRAPPERS", src)
        self.assertNotIn("ProtectedRoute", src)


class WhatTheCorpusSays(unittest.TestCase):
    """Named runs only: the worst blind run, a healthy one, and the router-less one."""

    @classmethod
    def setUpClass(cls):
        cls.corpus = Path(__file__).resolve().parents[2] / "generated"
        if not cls.corpus.is_dir():
            raise unittest.SkipTest("no generated/ corpus on this machine")

    def _app_jsx(self, run):
        p = self.corpus / run / "app" / "frontend" / "src" / "App.jsx"
        return p.read_text(encoding="utf-8", errors="ignore") if p.is_file() else None

    def test_the_worst_blind_run_gains_its_pages(self):
        src = self._app_jsx("netflix-local-r35")
        if src is None:
            self.skipTest("netflix-local-r35 is not on this disk")
        names, state = rpc(src)
        self.assertEqual(state, "read")
        self.assertGreaterEqual(len(names), 25,
                                "r35 routes 30 pages; the reader found %d" % len(names))
        self.assertLessEqual(len(set(_NAIVE.findall(src))), 8,
                             "the naive regex stopped under-reading r35, so the measured "
                             "shortfall no longer exists")

    def test_a_tiktok_run_is_unaffected(self):
        """The check was already right where it was written; the fix must not move it."""
        src = self._app_jsx("tiktok-web-r191")
        if src is None:
            self.skipTest("tiktok-web-r191 is not on this disk")
        names, _ = rpc(src)
        self.assertEqual(sorted(names), sorted(set(_NAIVE.findall(src))))

    def test_the_router_less_run_reads_as_no_routes(self):
        src = self._app_jsx("googlemaps-r15")
        if src is None:
            self.skipTest("googlemaps-r15 is not on this disk")
        self.assertEqual(rpc(src), ([], "no-routes"))

    def test_no_delivered_run_is_blocked_by_the_widening(self):
        """Honest about what this does today: 0 junk names anywhere, so every delivered run
        stays silent. If one starts firing, read it -- it is a real placeholder route that
        was hidden behind a guard."""
        checked = 0
        for run in ("netflix-local-r35", "netflix-local-r41", "netflix-local-r8",
                    "tiktok-web-r190", "tiktok-web-r191"):
            app = self.corpus / run / "app"
            if not (app / "frontend" / "src" / "App.jsx").is_file():
                continue
            checked += 1
            with self.subTest(run=run):
                self.assertEqual(D._placeholder_route_blockers_1202w(app), [])
        if not checked:
            self.skipTest("none of the named runs is on this disk")


if __name__ == "__main__":
    unittest.main()
