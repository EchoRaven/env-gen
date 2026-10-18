r"""#1203nw: an icon can fail for its GEOMETRY, not only its colour.

`#1203n0`/`#1203nv` ask whether CSS colour can reach a staged icon loaded through
`<img>`/`url()`. This asks whether the file has a usable coordinate system at all. Both arise
the same way: the staging pipeline lifts SVG fragments out of the real product's page, where
the page's own CSS supplied what the fragment leaves out.

MEASURED WITH REAL CHROMIUM -- a 3px circle in a 48x48 `<img>` slot on #121212, bright pixels
over the whole slot:

    with a viewBox          img 48x48     784 of 2304 bright   34.0%  -> a normal icon
    no viewBox              img 48x48      12 of 2304 bright    0.5%  -> a speck
    no viewBox, no w/h      img 300x150    12 of 51200 bright   0.0%  -> breaks the layout

Without a viewBox an SVG has no coordinate mapping, so sizing the ELEMENT does not scale the
CONTENT -- 68x less ink than the same glyph with one -- and with no width/height either the
`<img>` falls back to the SVG default of 300x150.

POPULATION, deduped per (file, reference): 23 rows for "no viewBox and no width" in 14 runs
and 8 for "renders nothing" in 5 runs, four of the affected runs modern (tiktok-web-r166,
r169, r177, r179). The "renders nothing" files are
`<svg style="position:absolute;width:0;height:0" id="svg-sprite-container"></svg>` -- a 0x0
sprite HOST scraped from the page and staged as if it were a glyph.

★ ONE CLASS WAS A DETECTOR ERROR OF MINE AND IS DELIBERATELY ABSENT. "A single shape with a
short path" looked like a placeholder and flagged 155 files, until I read one:
netflix-local-r45's `chevron-right.svg` is `<path d="m9 18 6-6-6-6"/>`, a correct lucide
chevron. A simple glyph IS one short path, so the shape of the drawing says nothing about its
quality. A test below pins that it is not reported.
"""
import tempfile
import unittest
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    unrenderable_img_icons_1203nw as unrenderable,
)

_GOOD = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="24" '
         'height="24"><path d="M4 4h16v16H4z"/></svg>')
_NO_VB_NO_W = ('<svg xmlns="http://www.w3.org/2000/svg" class="css-1guk65o">'
               '<circle cx="3" cy="3" r="2" fill="#FFFFFF"/></svg>')
_NO_VB_WITH_W = ('<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24">'
                 '<circle cx="3" cy="3" r="2" fill="#FFFFFF"/></svg>')
_SPRITE_HOST = ('<svg xmlns="http://www.w3.org/2000/svg" '
                'style="position:absolute;width:0;height:0" id="svg-sprite-container">'
                '</svg>')
_LUCIDE_CHEVRON = ('<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
                   'viewBox="0 0 24 24" fill="none" stroke="currentColor">'
                   '<path d="m9 18 6-6-6-6"/></svg>')


class _FE(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.fe = Path(self._tmp.name) / "frontend"
        (self.fe / "src").mkdir(parents=True)
        (self.fe / "public" / "assets" / "icons").mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def icon(self, name, body):
        (self.fe / "public" / "assets" / "icons" / name).write_text(body, encoding="utf-8")

    def second_copy(self, name, body):
        d = self.fe / "public" / "img"
        d.mkdir(parents=True, exist_ok=True)
        (d / name).write_text(body, encoding="utf-8")

    def src(self, name, body):
        (self.fe / "src" / name).write_text(body, encoding="utf-8")


class TheGeometryFailuresAreReported(_FE):
    def test_no_viewbox_and_no_width(self):
        self.icon("dot.svg", _NO_VB_NO_W)
        self.src("Pane.jsx", '<img src="/assets/icons/dot.svg"/>')
        got = unrenderable(self.fe)
        self.assertEqual(len(got), 1, got)
        self.assertIn("no viewBox and no width", got[0])
        self.assertIn("300x150", got[0])

    def test_a_sprite_host_renders_nothing(self):
        self.icon("icon_0065272a.svg", _SPRITE_HOST)
        self.src("LoginPage.jsx", '<img src="/assets/icons/icon_0065272a.svg"/>')
        got = unrenderable(self.fe)
        self.assertEqual(len(got), 1, got)
        self.assertIn("renders nothing", got[0])

    def test_no_viewbox_but_sized_says_the_content_does_not_scale(self):
        """0 referenced instances in the corpus, so this branch is labelled rather than
        evidenced (#647) -- but it is the same viewBox test and must say the right thing."""
        self.icon("sized.svg", _NO_VB_WITH_W)
        self.src("Pane.jsx", '<img src="/assets/icons/sized.svg"/>')
        got = unrenderable(self.fe)
        self.assertEqual(len(got), 1, got)
        self.assertIn("cannot be", got[0].replace("drawing cannot", "cannot be"))
        self.assertIn("0.5%", got[0])

    def test_the_row_names_the_file_and_the_reference(self):
        self.icon("dot.svg", _NO_VB_NO_W)
        self.src("EmptyChatPane.jsx", '<img src="/assets/icons/dot.svg"/>')
        got = unrenderable(self.fe)
        self.assertTrue(got[0].startswith("EmptyChatPane.jsx -> /assets/icons/dot.svg"), got)

    def test_a_css_url_reference_counts(self):
        self.icon("dot.svg", _NO_VB_NO_W)
        self.src("app.css", ".x{background-image:url('/assets/icons/dot.svg')}")
        self.assertEqual(len(unrenderable(self.fe)), 1)


class AWellFormedIconIsSilent(_FE):
    def test_a_viewbox_is_enough(self):
        self.icon("ok.svg", _GOOD)
        self.src("Nav.jsx", '<img src="/assets/icons/ok.svg"/>')
        self.assertEqual(unrenderable(self.fe), [])

    def test_a_simple_glyph_is_not_a_placeholder(self):
        """★ The class that was my own detector error: a correct lucide chevron is one short
        path, so path complexity says nothing about quality."""
        self.icon("chevron-right.svg", _LUCIDE_CHEVRON)
        self.src("Nav.jsx", '<img src="/assets/icons/chevron-right.svg"/>')
        self.assertEqual(unrenderable(self.fe), [])

    def test_an_inline_jsx_icon_is_not_a_reference(self):
        self.icon("dot.svg", _NO_VB_NO_W)
        self.src("Nav.jsx", "const nav=[{icon:Icons.Dot}];")
        self.assertEqual(unrenderable(self.fe), [])

    def test_a_reference_to_nothing_staged_says_nothing(self):
        """#883: an unreadable file is not evidence of a broken geometry."""
        self.src("Nav.jsx", '<img src="/assets/icons/absent.svg"/>')
        self.assertEqual(unrenderable(self.fe), [])


class AmbiguityIsSilence(_FE):
    """#883, as #1203n0 states it for the same channel: a bare basename served from two
    folders cannot say which one the page loads."""

    def test_disagreeing_copies_say_nothing(self):
        self.icon("bell.svg", _NO_VB_NO_W)
        self.second_copy("bell.svg", _GOOD)
        self.src("Nav.jsx", '<img src="bell.svg"/>')
        self.assertEqual(unrenderable(self.fe), [])

    def test_agreeing_copies_are_reported(self):
        self.icon("bell.svg", _NO_VB_NO_W)
        self.second_copy("bell.svg", _NO_VB_NO_W)
        self.src("Nav.jsx", '<img src="bell.svg"/>')
        self.assertEqual(len(unrenderable(self.fe)), 1)

    def test_a_full_path_resolves_past_the_ambiguity(self):
        self.icon("bell.svg", _NO_VB_NO_W)
        self.second_copy("bell.svg", _GOOD)
        self.src("Nav.jsx", '<img src="/assets/icons/bell.svg"/>')
        self.assertEqual(len(unrenderable(self.fe)), 1)


class ItSurvivesAMissingTree(_FE):
    def test_no_src_dir(self):
        import shutil
        shutil.rmtree(self.fe / "src")
        self.assertEqual(unrenderable(self.fe), [])

    def test_no_public_dir(self):
        import shutil
        shutil.rmtree(self.fe / "public")
        self.assertEqual(unrenderable(self.fe), [])

    def test_a_nonexistent_frontend(self):
        self.assertEqual(unrenderable(Path("/nope/frontend")), [])


class TheHealPipelineAsksTheQuestion(unittest.TestCase):
    """A detector nobody calls is the gap it exists to close."""

    @staticmethod
    def _calls(tree):
        """Try nodes whose body CALLS the detector — not merely imports it.

        ★ The first version of this test searched the try body's AST dump for the NAME, and a
        mutation replacing `unrenderable_img_icons_1203nw(fe)` with `[]` came back MISSED:
        the `from ... import` line still carries the name, so the assertion passed on the
        import alone. A detector that is imported and never called is the exact gap this
        ticket exists to close, so the test has to look for a Call.
        """
        import ast
        out = []
        for n in ast.walk(tree):
            if not isinstance(n, ast.Try):
                continue
            for sub in ast.walk(ast.Module(body=n.body, type_ignores=[])):
                if isinstance(sub, ast.Call) and getattr(
                        sub.func, "id", getattr(sub.func, "attr", "")
                ) == "unrenderable_img_icons_1203nw":
                    out.append(n)
                    break
        return out

    def test_it_is_actually_called(self):
        import ast
        import inspect
        from env_generator.llm_generator.multi_agent.runtime import heal_pipeline as HP
        self.assertTrue(self._calls(ast.parse(inspect.getsource(HP))),
                        "the heal pipeline imports it but never calls it")

    def test_its_failure_cannot_silence_its_neighbour(self):
        import ast
        import inspect
        from env_generator.llm_generator.multi_agent.runtime import heal_pipeline as HP
        holders = self._calls(ast.parse(inspect.getsource(HP)))
        self.assertTrue(holders)
        node = min(holders, key=lambda n: (n.end_lineno or 0) - n.lineno)
        body = ast.dump(ast.Module(body=node.body, type_ignores=[]))
        self.assertNotIn("invisible_img_icons_1203n0", body,
                         "it shares a try with #1203n0, so one failing silences the other")
        self.assertTrue(node.handlers, "the call is not guarded at all (#1201)")

    def test_the_message_carries_the_measurement(self):
        import ast
        import inspect
        from env_generator.llm_generator.multi_agent.runtime import heal_pipeline as HP
        tree = ast.parse(inspect.getsource(HP))
        emitted = [n.value for n in ast.walk(tree)
                   if isinstance(n, ast.Constant) and isinstance(n.value, str)
                   and "#1203nw" in n.value]
        self.assertTrue(emitted, "the #1203nw message is gone")
        joined = " ".join(emitted)
        self.assertIn("300x150", joined)
        self.assertIn("viewBox", joined)

    def test_the_cut_declares_itself(self):
        """#1034: the message lists at most six rows."""
        import ast
        import inspect
        from env_generator.llm_generator.multi_agent.runtime import heal_pipeline as HP
        src = inspect.getsource(HP)
        self.assertIn("more unrenderable icon reference(s) not listed", src)


if __name__ == "__main__":
    unittest.main()
