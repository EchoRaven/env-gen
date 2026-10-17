r"""#1203mv: the one route shape #1202sd refuses to rewrite was also the one nothing reported.

`repair_frontend_unmatchable_routes_1202sd` declines a `<Route path>` carrying a query string,
and for a good reason it writes down itself: #1202iy's rewrite is actively harmful there --
r79's `/?comments=1&video=:id` would become `/:id`, a top-level dynamic route shadowing
/explore, /login and every other static path. Its comment ends "Left alone, loudly unfixed."

Nothing was loud. `_sub` returned the match unchanged, the path went into no list, and the
caller -- which already reports `repaired` and (since #1203f6) `refused` -- had nothing to
report. That is the same silence #1203f6 had to fix one branch over in the same function.

MEASURED over the 3267 delivered frontend .jsx on disk: three runs ship one, and one of them
is modern.

    tiktok-web-r35   <Route path="/?comments=true">
    tiktok-web-r74   <Route path="/?comments=1">
    tiktok-web-r163  <Route path="/?comments=:video_id">     <- r150+

A query string is not part of a route path, so each of these matches that literal spelling and
nothing else: the comments deep-link is a page no URL reaches -- the exact consequence #1202iy
went looking for, in the one shape its repair deliberately will not touch. The lane is the only
one who can fix it, and it can only fix what it is told.
"""
import ast
import inspect
import unittest

from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    repair_frontend_unmatchable_routes_1202sd as repair,
)


def _fe(tmp, app_jsx, extra=None):
    src = tmp / "src"
    src.mkdir(parents=True, exist_ok=True)
    (src / "App.jsx").write_text(app_jsx)
    for name, text in (extra or {}).items():
        (src / name).write_text(text)
    return tmp


class TheQueryStringRouteIsReported(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_r163s_route_is_named(self):
        fe = _fe(self.tmp, '<Route path="/?comments=:video_id" element={<C/>}/>')
        left = repair(fe)["left_1203mv"]
        self.assertEqual(len(left), 1)
        self.assertIn("/?comments=:video_id", left[0])

    def test_it_names_the_file_too(self):
        """The lane's router is split across files (#1202sd already had to learn that)."""
        fe = _fe(self.tmp, "<div/>",
                 {"Router.jsx": '<Route path="/?comments=1" element={<C/>}/>'})
        left = repair(fe)["left_1203mv"]
        self.assertEqual(len(left), 1)
        self.assertIn("Router.jsx", left[0])

    def test_the_ampersand_shape_is_reported(self):
        """r79's, the one the comment cites as the reason not to rewrite."""
        fe = _fe(self.tmp, '<Route path="/?comments=1&video=:id" element={<C/>}/>')
        self.assertEqual(len(repair(fe)["left_1203mv"]), 1)

    def test_every_corpus_spelling_is_reported(self):
        for path in ("/?comments=true", "/?comments=1", "/?comments=:video_id"):
            with self.subTest(path=path):
                import tempfile
                from pathlib import Path
                with tempfile.TemporaryDirectory() as d:
                    fe = _fe(Path(d), '<Route path="%s" element={<C/>}/>' % path)
                    self.assertEqual(len(repair(fe)["left_1203mv"]), 1)


class ReportingItDoesNotStartRewritingIt(unittest.TestCase):
    """r79 is why: `/?comments=1&video=:id` -> `/:id` shadows every static path."""

    def setUp(self):
        import tempfile
        from pathlib import Path
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_the_file_is_left_byte_for_byte(self):
        text = '<Route path="/?comments=:video_id" element={<C/>}/>'
        fe = _fe(self.tmp, text)
        repair(fe)
        self.assertEqual((self.tmp / "src" / "App.jsx").read_text(), text)

    def test_it_is_not_counted_as_a_repair(self):
        fe = _fe(self.tmp, '<Route path="/?comments=:video_id" element={<C/>}/>')
        r = repair(fe)
        self.assertEqual(r["routes"], 0)
        self.assertEqual(list(r["repaired"]), [])


class TheRewritableShapeIsStillRewrittenAndNotReportedAsLeft(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_at_username_still_repaired(self):
        fe = _fe(self.tmp, '<Route path="/@:username" element={<P/>}/>')
        r = repair(fe)
        self.assertEqual(r["routes"], 1)
        self.assertEqual(list(r["left_1203mv"]), [])
        self.assertIn('path="/:username"', (self.tmp / "src" / "App.jsx").read_text())

    def test_a_clean_router_reports_an_empty_list_not_a_missing_key(self):
        fe = _fe(self.tmp, '<Route path="/explore" element={<E/>}/>')
        self.assertEqual(list(repair(fe)["left_1203mv"]), [])


class TheCallerSaysIt(unittest.TestCase):
    """#1203f6: the announcement must sit in the statement that reads the key."""

    def _warning_reading(self, key):
        from env_generator.llm_generator.multi_agent.runtime import heal_pipeline
        tree = ast.parse(inspect.getsource(heal_pipeline))
        for node in ast.walk(tree):
            if not isinstance(node, ast.For):
                continue
            if key not in ast.dump(node.iter):
                continue
            for inner in ast.walk(node):
                if isinstance(inner, ast.Call) and getattr(inner.func, "attr", "") == "warning":
                    for a in inner.args:
                        if isinstance(a, ast.Constant) and isinstance(a.value, str):
                            return a.value
        return None

    def test_the_heal_pipeline_warns_about_what_it_left(self):
        self.assertIsNotNone(self._warning_reading("left_1203mv"),
                             "nothing announces the paths #1202sd declined")

    def test_the_warning_says_the_page_is_unreachable(self):
        self.assertIn("unreachable", self._warning_reading("left_1203mv"))

    def test_the_warning_tells_the_lane_what_to_do_instead(self):
        txt = self._warning_reading("left_1203mv")
        self.assertIn("useSearchParams", txt)

    def test_it_says_why_the_framework_will_not_do_it(self):
        """Otherwise the next reader 'fixes' it and ships r79's shadowing route."""
        txt = self._warning_reading("left_1203mv")
        self.assertIn("shadows", txt)


if __name__ == "__main__":
    unittest.main()
