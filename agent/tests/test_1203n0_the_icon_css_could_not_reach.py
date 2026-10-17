r"""#1203n0: #551's rule was only ever asked of the nav the FRAMEWORK emits.

#551, sharpened by #1203kw: "an SVG that paints its OWN default colour must not reach a themed
nav through <img>, because CSS cannot get inside the image." Both apply it to
`_nav_utility_icons`, the chrome the framework writes. Nothing asks it of the icon references
the LANE writes -- the same shape #1202iy -> #1202sd already had to fix once for routes.

r190 is the case. `src/components/LeftSidebar.jsx` declares its nav rows two ways:

    { label:'Shop',      icon: Icons.ShoppingBag }           # inline JSX  -> inherits colour
    { label:'For You',   img:'for-you_9be6781e.svg' }        # <img src>   -> cannot

and all six `img:` rows point at `fill="currentColor"` files. The visual judge then reported,
unprompted, "several implementation nav items have missing or inconsistent icon treatment",
naming For You, Following, LIVE and Profile -- exactly the `img:` rows.

MEASURED WITH REAL CHROMIUM on r190's own `following_eb9a6ec0.svg`, 48x48 on #121212 with
`color:#fff` set on both carriers:

    inline SVG   mean 66.2   max 255   bright(>200) 418    -> visible
    <img src>    mean 14.3   max  18   bright(>200)   0    -> all 2304 px background-dark

(The first attempt measured nothing, because its inline control used `fetch()` on a file://
page and CORS blocked it -- the "dark" reading was pure background. A contrast means nothing
until the control is proven alive.)

CORPUS: 52 runs reference a colourless staged SVG this way, 522 references in all (37 old, 15
modern; r35 71, netflix-r21 29, r190 8, r184 2 -- and r184 was a 3-of-4-milestone delivery).

HONEST LIMIT, stated because the obvious story is wrong: this does NOT explain the iconography
floor. Modern runs WITH such references average 0.491 and those WITHOUT average 0.509 -- a
0.018 difference with huge spread inside each group (r173 has 8 references and scores 0.676;
instagram-core-r176 has 8 and scores 0.309). The mechanism is real and costs score where it
happens; it is not the floor's cause.
"""
import json
import tempfile
import unittest
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    invisible_img_icons_1203n0 as invisible,
)

_COLOURLESS = ('<svg fill="currentColor" viewBox="0 0 48 48" '
               'xmlns="http://www.w3.org/2000/svg"><path d="M1 1h4v4H1z"/></svg>')
_OWN_COLOUR = ('<svg viewBox="0 0 48 48" xmlns="http://www.w3.org/2000/svg">'
               '<path fill="#FE2C55" d="M1 1h4v4H1z"/></svg>')
_MIXED = ('<svg fill="currentColor" viewBox="0 0 48 48" '
          'xmlns="http://www.w3.org/2000/svg"><path stroke="#25F4EE" d="M1 1h4v4H1z"/></svg>')


class _FE(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.fe = Path(self._d.name)
        (self.fe / "src" / "components").mkdir(parents=True)
        (self.fe / "public" / "assets" / "icons").mkdir(parents=True)
        self.addCleanup(self._d.cleanup)

    def icon(self, name, body=_COLOURLESS):
        (self.fe / "public" / "assets" / "icons" / name).write_text(body)

    def src(self, name, body):
        (self.fe / "src" / "components" / name).write_text(body)


class TheLanesOwnReferenceIsChecked(_FE):
    def test_r190s_img_field(self):
        """The exact shape: `img:'for-you_9be6781e.svg'` beside `icon:Icons.X`."""
        self.icon("for-you_9be6781e.svg")
        self.src("LeftSidebar.jsx",
                 "const nav=[{label:'For You',img:'for-you_9be6781e.svg'},"
                 "{label:'Shop',icon:Icons.ShoppingBag}];")
        out = invisible(self.fe)
        self.assertEqual(len(out), 1, out)
        self.assertIn("for-you_9be6781e.svg", out[0])
        self.assertIn("LeftSidebar.jsx", out[0])

    def test_an_img_tag(self):
        self.icon("bell.svg")
        self.src("Nav.jsx", '<img src="/assets/icons/bell.svg" alt="bell" />')
        self.assertEqual(len(invisible(self.fe)), 1)

    def test_a_css_url(self):
        self.icon("bell.svg")
        (self.fe / "src" / "app.css").write_text(
            ".bell{background-image:url('/assets/icons/bell.svg')}")
        self.assertEqual(len(invisible(self.fe)), 1)

    def test_several_files_each_report(self):
        for n in ("a.svg", "b.svg"):
            self.icon(n)
        self.src("A.jsx", '<img src="/assets/icons/a.svg"/>')
        self.src("B.jsx", '<img src="/assets/icons/b.svg"/>')
        self.assertEqual(len(invisible(self.fe)), 2)

    def test_the_same_reference_twice_in_one_file_reports_once(self):
        self.icon("a.svg")
        self.src("A.jsx", '<img src="/assets/icons/a.svg"/><img src="/assets/icons/a.svg"/>')
        self.assertEqual(len(invisible(self.fe)), 1)


class AnAssetWithItsOwnColoursKeepsTheImgChannel(_FE):
    """#1203kw's carve-out: #421 stays alive for a genuinely coloured mark."""

    def test_a_concrete_fill_is_not_reported(self):
        self.icon("logo.svg", _OWN_COLOUR)
        self.src("Nav.jsx", '<img src="/assets/icons/logo.svg"/>')
        self.assertEqual(invisible(self.fe), [])

    def test_currentcolor_plus_a_real_colour_is_not_reported(self):
        self.icon("mixed.svg", _MIXED)
        self.src("Nav.jsx", '<img src="/assets/icons/mixed.svg"/>')
        self.assertEqual(invisible(self.fe), [])

    def test_an_inline_jsx_icon_is_not_a_reference(self):
        """`icon: Icons.X` carries no .svg path at all."""
        self.icon("a.svg")
        self.src("Nav.jsx", "const nav=[{label:'Shop',icon:Icons.ShoppingBag}];")
        self.assertEqual(invisible(self.fe), [])

    def test_an_svg_with_no_colour_at_all_is_out_of_scope(self):
        """A fill-less SVG defaults to black, so it is invisible through <img> too -- but
        INLINING would not fix it either (there is no `currentColor` to inherit), so the
        remedy this reports does not apply and the finding would be misleading. Mutation N02
        removes the `currentColor` precondition and this is the case that catches it."""
        self.icon("plain.svg", '<svg viewBox="0 0 48 48" xmlns="http://www.w3.org/2000/svg">'
                               '<path d="M1 1h4v4H1z"/></svg>')
        self.src("Nav.jsx", '<img src="/assets/icons/plain.svg"/>')
        self.assertEqual(invisible(self.fe), [])

    def test_a_path_that_is_not_staged_says_nothing(self):
        """#883: an unreadable file is not evidence of invisibility."""
        self.src("Nav.jsx", '<img src="/assets/icons/absent.svg"/>')
        self.assertEqual(invisible(self.fe), [])

    def test_no_src_tree(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(invisible(Path(d)), [])


class TheReportReachesTheLane(unittest.TestCase):
    """#1139/#1203f6: a finding that only a function returns is not a finding."""

    def _warning(self):
        import ast
        import inspect
        from env_generator.llm_generator.multi_agent.runtime import heal_pipeline
        tree = ast.parse(inspect.getsource(heal_pipeline))
        for node in ast.walk(tree):
            if not isinstance(node, ast.For):
                continue
            if "_inv1203n0" not in ast.dump(node.iter):
                continue
            for inner in ast.walk(node):
                if isinstance(inner, ast.Call) and getattr(inner.func, "attr", "") == "warning":
                    for a in inner.args:
                        if isinstance(a, ast.Constant) and isinstance(a.value, str):
                            return a.value
        return None

    def test_the_heal_pipeline_announces_it(self):
        self.assertIsNotNone(self._warning(), "nothing reports the invisible icons")

    def test_it_says_the_icon_is_invisible_not_merely_wrong(self):
        self.assertIn("invisible", self._warning())

    def test_it_names_the_mechanism_not_just_the_symptom(self):
        """The mechanism is what makes the remedy obvious, so assert it rather than only the
        symptom word.

        Mutation N08 (first line -> "a staged icon with a colour problem") still passes here
        and that is the right outcome: it leaves `currentColor`, `<img>/url()`, the
        consequence and both remedies in place, so the sentence stays correct and actionable
        and only loses the word "only". Killing it would mean asserting one exact phrase,
        which is the brittle kind of test this repo has been bitten by. Recorded as a
        near-null mutant (#1203jr) instead of chased."""
        txt = self._warning()
        self.assertIn("currentColor", txt)
        self.assertIn("<img>", txt)

    def test_it_names_both_remedies(self):
        txt = self._warning()
        self.assertIn("INLINE", txt)
        self.assertIn("own colours", txt)

    def test_the_cut_list_declares_itself(self):
        """#1034: a capped list must say it was capped -- asserted on the GUARD, not on the
        sentence. Mutation N09 turned `if len(_inv1203n0) > 6:` into `if False:` and the
        text-in-source version of this test stayed green, which is the trap my own notes
        describe: a literal left in place feeds a text assertion."""
        import ast
        import inspect
        from env_generator.llm_generator.multi_agent.runtime import heal_pipeline
        tree = ast.parse(inspect.getsource(heal_pipeline))
        guards = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.If):
                continue
            dump = ast.dump(node.test)
            if "_inv1203n0" in dump and "Compare" in dump:
                said = [c for c in ast.walk(node)
                        if isinstance(c, ast.Call)
                        and getattr(c.func, "attr", "") == "warning"]
                guards.append(bool(said))
        self.assertTrue(guards, "no length guard over the invisible-icon list")
        self.assertTrue(all(guards), "the cap guard does not announce the cut")


if __name__ == "__main__":
    unittest.main()
