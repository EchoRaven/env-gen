r"""#1203ff: r157 delivered the same <Route> three times, and a framework repair made them.

The delivered `app/frontend/src/App.jsx` of tiktok-web-r157:

    <Route path="/:username" element={<ProfileOwnPage />} />
    <Route path="/:username" element={<ProfileOwnPage />} />
    <Route path="/:username" element={<ProfileOwnPage />} />

Its git history shows the mechanism across four commits:

    230bf8c  lane merge   /@:username  +  /:username
    6d2fb12  framework    /:username   +  /:username        <- #1202sd rewrote the unmatchable
    69574f7  lane merge   /@:username  +  /:username  x2    <- the lane re-added /@
    c2e022c  framework    /:username   x3                   <- #1202sd rewrote again

#1202sd rewrites a path React Router cannot match (`/@:username` compiles to a literal, so
the page is unreachable) and does not ask whether the path it produces is already there. Each
lane/framework cycle therefore leaves one more copy. Six rewrites in r157, three routes
shipped.

#1202sd IS NOT THE ONLY CAUSE, which is why this deduplicates the result rather than patching
that producer: r112 ships a duplicate with #1202sd never firing. Measured over the 177
delivered App.jsx on disk -- 12 carry duplicates, 19 redundant routes, and every one is a
byte-identical line, same path AND same element.

The guards matter more than the dedupe:

  * ONLY a complete single-line tag (`<Route ... />` on one line). 141 of the corpus's 2735
    `<Route>` tags span several lines, and a line-based pass would delete half of one.
  * ONLY a file with ONE `<Routes` block, because two routers could each legitimately carry
    `/:username`. No file on disk has two (0 of 182) -- this guard protects a case that does
    not occur yet, since a predicate true today is not a promise about tomorrow's code.
  * BYTE-IDENTICAL only, the same line `dedupe_identical_toplevel_blocks` already draws.
"""
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent))
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

from multi_agent.runtime import frontend_scaffold as fs        # noqa: E402
from multi_agent.runtime import path_routed_workspace as prw   # noqa: E402


def _fe(app_jsx, name="App.jsx"):
    """A frontend at the shape real runs have, so #1202cw's guard engages."""
    d = Path(tempfile.mkdtemp()) / "app" / "frontend"
    p = d / "src" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(app_jsx, encoding="utf-8")
    return d, p


def _router(*route_lines, routes_blocks=1):
    body = "\n".join("    %s" % r for r in route_lines)
    blocks = "".join("  <Routes>\n%s\n  </Routes>\n" % body for _ in range(routes_blocks))
    return ("import { Routes, Route } from 'react-router-dom';\n"
            "export default function App(){\n  return (\n%s  );\n}\n" % blocks)


R_USER = '<Route path="/:username" element={<ProfileOwnPage />} />'
R_UP = '<Route path="/upload" element={<UploadPage />} />'


def _reset():
    for b in prw._LANE_CLOBBERS_1202CW.values():
        b.clear()


class TheR157ShapeIsRepaired(unittest.TestCase):
    def setUp(self):
        _reset()

    def test_three_identical_routes_become_one(self):
        fe, p = _fe(_router(R_USER, R_USER, R_USER, R_UP))
        res = fs.dedupe_identical_routes_1203ff(fe)
        txt = p.read_text(encoding="utf-8")
        self.assertEqual(txt.count(R_USER), 1, txt)
        self.assertEqual(txt.count(R_UP), 1, "an unrelated route was removed")
        self.assertTrue(res.get("deduped"), res)

    def test_the_first_copy_is_the_one_kept(self):
        """React Router matches the first; keeping a later copy would change which one wins
        if they ever stopped being identical."""
        fe, p = _fe(_router(R_USER, R_UP, R_USER))
        fs.dedupe_identical_routes_1203ff(fe)
        # `<Routes>` also contains "<Route" — filter on the tag, not a substring of it.
        lines = [l.strip() for l in p.read_text(encoding="utf-8").split("\n")
                 if l.strip().startswith("<Route ")]
        self.assertEqual(lines, [R_USER, R_UP], lines)

    def test_a_file_with_no_duplicates_is_untouched(self):
        fe, p = _fe(_router(R_USER, R_UP))
        before = p.read_text(encoding="utf-8")
        res = fs.dedupe_identical_routes_1203ff(fe)
        self.assertEqual(p.read_text(encoding="utf-8"), before)
        self.assertFalse(res.get("deduped"), res)

    def test_the_write_is_declared_not_refused(self):
        fe, _p = _fe(_router(R_USER, R_USER))
        fs.dedupe_identical_routes_1203ff(fe)
        led = prw.lane_clobbers_1202cw()
        self.assertFalse(led["refused"], led["refused"])
        self.assertTrue(any("App.jsx" in k for k in led["declared"]), led)


class TheGuardsHold(unittest.TestCase):
    def setUp(self):
        _reset()

    def test_a_route_that_differs_at_all_is_kept(self):
        a = '<Route path="/:username" element={<ProfileOwnPage />} />'
        b = '<Route path="/:username" element={<OtherPage />} />'
        fe, p = _fe(_router(a, b))
        fs.dedupe_identical_routes_1203ff(fe)
        txt = p.read_text(encoding="utf-8")
        self.assertIn(a, txt)
        self.assertIn(b, txt, "a route with a DIFFERENT element was removed")

    def test_a_multi_line_route_tag_is_left_alone(self):
        """A line-based pass must not delete half a tag. 141 corpus tags span lines."""
        # The attributes START on the tag's own line and the tag closes on a LATER one. A
        # first line of bare `<Route` would not exercise the guard at all: the pattern needs
        # whitespace after `Route`, so even a loosened `^\s*<Route\s.*$` would skip it, and
        # the mutation that removes the `/>` anchor would stay green. That version of this
        # test proved nothing (#1202, a green test can prove nothing).
        multi = ('    <Route path="/:username"\n'
                 '      element={<ProfileOwnPage />}\n    />\n')
        app = ("import { Routes, Route } from 'react-router-dom';\n"
               "export default function App(){ return (\n  <Routes>\n"
               + multi + multi + "  </Routes>\n); }\n")
        fe, p = _fe(app)
        before = p.read_text(encoding="utf-8")
        res = fs.dedupe_identical_routes_1203ff(fe)
        self.assertEqual(p.read_text(encoding="utf-8"), before,
                         "a multi-line <Route> was edited by a line-based pass")
        self.assertFalse(res.get("deduped"), res)

    def test_two_routers_in_one_file_are_skipped_and_said(self):
        fe, p = _fe(_router(R_USER, routes_blocks=2))
        before = p.read_text(encoding="utf-8")
        res = fs.dedupe_identical_routes_1203ff(fe)
        self.assertEqual(p.read_text(encoding="utf-8"), before)
        self.assertTrue(res.get("skipped"), res)
        self.assertIn("<Routes>", str(res["skipped"][0]))

    def test_a_file_without_routes_is_not_read_for_nothing(self):
        fe, p = _fe("export default function Nav(){ return <nav/>; }\n", name="Nav.jsx")
        res = fs.dedupe_identical_routes_1203ff(fe)
        self.assertFalse(res.get("deduped"), res)
        self.assertFalse(res.get("skipped"), res)

    def test_a_missing_src_never_raises(self):
        d = Path(tempfile.mkdtemp()) / "app" / "frontend"
        d.mkdir(parents=True)
        res = fs.dedupe_identical_routes_1203ff(d)
        self.assertEqual(res.get("deduped"), [])
        self.assertNotIn("error", res)


class TheRefusalIsReported(unittest.TestCase):
    def setUp(self):
        _reset()

    def test_a_refused_write_reports_unwritten_and_claims_nothing(self):
        fe, _p = _fe(_router(R_USER, R_USER))
        real = fs._fw_write_1202cw
        fs._fw_write_1202cw = lambda *a, **k: False
        try:
            res = fs.dedupe_identical_routes_1203ff(fe)
        finally:
            fs._fw_write_1202cw = real
        self.assertFalse(res.get("deduped"), "claimed a dedupe it did not write: %r" % (res,))
        self.assertTrue(res.get("unwritten"), res)


class TheCallerAnnouncesIt(unittest.TestCase):
    def test_heal_pipeline_reads_every_negative_key(self):
        import ast
        p = (THIS_DIR.parent / "env_generator" / "llm_generator" / "multi_agent" / "runtime"
             / "heal_pipeline.py")
        tree = ast.parse(p.read_text(encoding="utf-8"))
        var = None
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                f = node.value.func
                if (getattr(f, "id", None) or getattr(f, "attr", None)) \
                        == "dedupe_identical_routes_1203ff":
                    var = node.targets[0].id
        self.assertIsNotNone(var, "nothing calls the dedupe")
        src = p.read_text(encoding="utf-8")
        for key in ("deduped", "unwritten", "skipped"):
            self.assertIn('%s.get("%s")' % (var, key), src,
                          "the caller never reads %r, so that outcome is silent" % key)


if __name__ == "__main__":
    unittest.main()
