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


class ItSeesEveryProductsSpelling(_FE):
    r"""#1203n4: the first pattern required `<img src=` / `url(` / `img:` immediately before
    the path, which is tiktok's spelling. instagram writes its whole icon set as a JSX
    template literal behind a prefix variable:

        icon={`${I}Home_b0d6db24.svg`}      src={`${I}Save_fd444e40.svg`}

    so the shipped detector reported 0 for instagram-core-r174/175/176 while all 47 of their
    staged icons load exactly that way -- and 0 for tiktok-web-r185 too, a full-delivery run
    with 12. A quoted `.svg` PATH can only be an image-style load: an inline icon is a JSX
    component and never names a file.
    """

    def test_instagrams_template_literal_with_a_prefix_variable(self):
        self.icon("Home_b0d6db24.svg")
        self.src("CollapsedLeftNav.jsx",
                 "const I='/assets/icons/';\n"
                 "export default () => <NavItem icon={`${I}Home_b0d6db24.svg`} />;")
        out = invisible(self.fe)
        self.assertEqual(len(out), 1, out)
        self.assertIn("Home_b0d6db24.svg", out[0])

    def test_a_src_prop_on_a_custom_component(self):
        self.icon("Save_fd444e40.svg")
        self.src("Icon.jsx", "const P='/assets/icons/';\n<Glyph src={`${P}Save_fd444e40.svg`} />")
        self.assertEqual(len(invisible(self.fe)), 1)

    def test_a_bare_basename_resolves_against_everything_served(self):
        self.icon("bell.svg")
        self.src("Nav.jsx", "const n='bell.svg';")
        self.assertEqual(len(invisible(self.fe)), 1)

    def test_an_icon_staged_outside_assets_icons(self):
        """Products stage icons in different folders; the index is over `public/**`."""
        p = self.fe / "public" / "img"
        p.mkdir(parents=True, exist_ok=True)
        (p / "logo.svg").write_text(_COLOURLESS)
        self.src("Nav.jsx", '<img src="/img/logo.svg" />')
        self.assertEqual(len(invisible(self.fe)), 1)

    def test_the_original_precise_forms_still_match(self):
        self.icon("a.svg")
        self.src("A.jsx", '<img src="/assets/icons/a.svg"/>')
        self.assertEqual(len(invisible(self.fe)), 1)

    def test_a_name_that_is_not_served_says_nothing(self):
        self.src("Nav.jsx", "const n = `${I}not_staged_anywhere.svg`;")
        self.assertEqual(invisible(self.fe), [])


class ADuplicatedBasenameIsAnAmbiguityNotAVerdict(_FE):
    """#883 / #1203n4: 27 runs serve the SAME basename from two folders (115 names in all --
    `bell.svg`, `plus.svg`, `info.svg`...). A bare reference cannot say which one loads."""

    def _second_copy(self, name, body):
        d = self.fe / "public" / "img"
        d.mkdir(parents=True, exist_ok=True)
        (d / name).write_text(body)

    def test_both_copies_colourless_is_reported(self):
        self.icon("bell.svg", _COLOURLESS)
        self._second_copy("bell.svg", _COLOURLESS)
        self.src("Nav.jsx", "const n=`${I}bell.svg`;")
        self.assertEqual(len(invisible(self.fe)), 1)

    def test_copies_that_disagree_say_nothing(self):
        self.icon("bell.svg", _COLOURLESS)
        self._second_copy("bell.svg", _OWN_COLOUR)
        self.src("Nav.jsx", "const n=`${I}bell.svg`;")
        self.assertEqual(invisible(self.fe), [],
                         "an ambiguous basename must not be turned into a verdict")

    def test_a_full_path_beats_the_index(self):
        """The reference names the coloured copy explicitly -- no report."""
        self.icon("bell.svg", _COLOURLESS)
        self._second_copy("bell.svg", _OWN_COLOUR)
        self.src("Nav.jsx", '<img src="/img/bell.svg" />')
        self.assertEqual(invisible(self.fe), [])

    def test_a_full_path_to_the_colourless_copy_is_reported(self):
        self.icon("bell.svg", _COLOURLESS)
        self._second_copy("bell.svg", _OWN_COLOUR)
        self.src("Nav.jsx", '<img src="/assets/icons/bell.svg" />')
        self.assertEqual(len(invisible(self.fe)), 1)


class AnSvgThatDeclaresItsOwnColourIsSelfColoured(_FE):
    """#1203nx: `fill="currentColor"` resolves against the element's OWN `color`, and these
    scraped fragments routinely carry one on the root `<svg>`. CSS never needs to reach
    inside, so #1203kw's carve-out applies and the row was a false positive.

    MEASURED BY RENDERED INK -- 124 referenced icons of six modern runs in real Chromium,
    48x48 `<img>` on #121212, ink = pixels brighter than 60: 78 render under 1% of the slot
    and 77 of those were already reported, but 21 reported rows ink 55-56%. Every one of the
    21 declares a concrete own `color`.

    ★ `var()` IS THE LINE. `notice-list-item_9628e7c7` declares
    `color="var(--ui-shape-text-1-on-primary)"` and inks 0.00%: no stylesheet reaches an
    `<img>` document, so the custom property is undefined, the declaration is invalid and
    `color` falls back to black. Validated on the rendered set, the carve-out removes 21
    false positives and loses 0 true positives.
    """

    def test_a_concrete_own_colour_is_not_reported(self):
        self.icon("like.svg", '<svg fill="currentColor" color="rgba(255, 255, 255, .9)" '
                              'viewBox="0 0 48 48"><path d="M4 4h16v16H4z"/></svg>')
        self.src("TikTokUI.jsx", '<img src="/assets/icons/like.svg"/>')
        self.assertEqual(invisible(self.fe), [])

    def test_an_own_colour_in_a_style_attribute_counts(self):
        self.icon("like.svg", '<svg fill="currentColor" style="color:#ffffff" '
                              'viewBox="0 0 48 48"><path d="M4 4h16v16H4z"/></svg>')
        self.src("Nav.jsx", '<img src="/assets/icons/like.svg"/>')
        self.assertEqual(invisible(self.fe), [])

    def test_a_var_colour_IS_still_reported(self):
        """The case that keeps this from being a loophole -- measured at 0.00% ink."""
        self.icon("notice.svg", '<svg fill="currentColor" viewBox="0 0 48 48" '
                                'color="var(--ui-shape-text-1-on-primary)">'
                                '<path d="M4 4h16v16H4z"/></svg>')
        self.src("Nav.jsx", '<img src="/assets/icons/notice.svg"/>')
        got = invisible(self.fe)
        self.assertEqual(got, ["Nav.jsx -> /assets/icons/notice.svg (currentColor)"], got)

    def test_a_var_colour_in_a_style_attribute_is_still_reported(self):
        self.icon("notice.svg", '<svg fill="currentColor" viewBox="0 0 48 48" '
                                'style="color:var(--x)"><path d="M4 4h16v16H4z"/></svg>')
        self.src("Nav.jsx", '<img src="/assets/icons/notice.svg"/>')
        self.assertEqual(len(invisible(self.fe)), 1)

    def test_colour_keywords_that_resolve_to_nothing_are_still_reported(self):
        for val in ("inherit", "currentColor", "unset", "initial", "revert"):
            with self.subTest(value=val):
                self.icon("k.svg", '<svg fill="currentColor" viewBox="0 0 48 48" '
                                   'color="%s"><path d="M4 4h16v16H4z"/></svg>' % val)
                self.src("Nav.jsx", '<img src="/assets/icons/k.svg"/>')
                self.assertEqual(len(invisible(self.fe)), 1, val)

    def test_an_own_colour_does_not_rescue_a_no_paint_icon(self):
        """A `color` declaration only matters because `currentColor` reads it. An SVG that
        names no paint at all is black regardless, so #1203nv's row must survive."""
        self.icon("plain.svg", '<svg viewBox="0 0 48 48" color="#ffffff">'
                               '<path d="M1 1h4v4H1z"/></svg>')
        self.src("Nav.jsx", '<img src="/assets/icons/plain.svg"/>')
        got = invisible(self.fe)
        self.assertEqual(got, ["Nav.jsx -> /assets/icons/plain.svg (no paint at all)"], got)


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

    def test_an_outline_icon_IS_reported_1203nv(self):
        """`fill="none" stroke="currentColor"` is the single commonest icon idiom, and
        `none`/`transparent`/`inherit` are skipped precisely so it still counts as
        colourless. A mutation that stops skipping them (NV5) made this whole family read as
        "carries its own colours" and nothing in the file noticed -- the skip list had no
        test of its own."""
        self.icon("outline.svg",
                  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor">'
                  '<path d="M4 4h16v16H4z"/></svg>')
        self.src("Nav.jsx", '<img src="/assets/icons/outline.svg"/>')
        got = invisible(self.fe)
        self.assertEqual(got, ["Nav.jsx -> /assets/icons/outline.svg (currentColor)"], got)

    def test_fill_none_alone_does_not_make_an_icon_colourless(self):
        """Non-vacuity for the skip list: `none` must be ignored as a PAINT, not treated as
        evidence of colourlessness. An icon whose only tokens are `none` and a real colour
        carries its own colour."""
        self.icon("halfnone.svg",
                  '<svg viewBox="0 0 24 24" fill="none" stroke="#ff2d55">'
                  '<path d="M4 4h16v16H4z"/></svg>')
        self.src("Nav.jsx", '<img src="/assets/icons/halfnone.svg"/>')
        self.assertEqual(invisible(self.fe), [])

    def test_an_inline_jsx_icon_is_not_a_reference(self):
        """`icon: Icons.X` carries no .svg path at all."""
        self.icon("a.svg")
        self.src("Nav.jsx", "const nav=[{label:'Shop',icon:Icons.ShoppingBag}];")
        self.assertEqual(invisible(self.fe), [])

    def test_an_svg_with_no_colour_at_all_IS_in_scope_1203nv(self):
        """#1203nv REVERSED THIS, and measured the reason the old criterion gave.

        It asserted a fill-less SVG is out of scope because "INLINING would not fix it
        either (there is no `currentColor` to inherit), so the remedy this reports does not
        apply". MEASURED WITH REAL CHROMIUM, the same method #1203n0 itself used -- 48x48 on
        #121212, mean brightness over all 2304 px:

            no-paint, INLINED under CSS `fill:#fff`   mean 151.3  bright 1296  -> visible
            currentColor, INLINED under `fill`+`color` mean 151.3  bright 1296  -> visible
            no-paint, INLINED under `color:#fff` only  mean   7.9  bright    0  -> invisible
            currentColor, INLINED under `color` only   mean 151.3  bright 1296  -> visible

        So inlining DOES fix it -- the CSS `fill` property applies to a shape with no `fill`
        presentation attribute, no `currentColor` required. The old reason was wrong about
        the mechanism. What it had a real kernel of is the ASYMMETRY on the last two lines:
        the usual idiom (inline and set `color`) fixes a currentColor icon and not a
        no-paint one, which is why the row now names its mechanism and the heal message
        gives the remedy per mechanism.

        Population: 328 rows in 11 runs, two of them modern (tiktok-web-r169, r177).
        """
        self.icon("plain.svg", '<svg viewBox="0 0 48 48" xmlns="http://www.w3.org/2000/svg">'
                               '<path d="M1 1h4v4H1z"/></svg>')
        self.src("Nav.jsx", '<img src="/assets/icons/plain.svg"/>')
        got = invisible(self.fe)
        self.assertEqual(got, ["Nav.jsx -> /assets/icons/plain.svg (no paint at all)"], got)

    def test_the_row_names_its_mechanism_1203nv(self):
        """The two mechanisms need different remedies, so a reader must be able to tell them
        apart without opening the file."""
        self.icon("cc.svg", '<svg viewBox="0 0 48 48"><path fill="currentColor" '
                            'd="M1 1h4v4H1z"/></svg>')
        self.src("Nav.jsx", '<img src="/assets/icons/cc.svg"/>')
        got = invisible(self.fe)
        self.assertEqual(got, ["Nav.jsx -> /assets/icons/cc.svg (currentColor)"], got)

    def test_a_path_that_is_not_staged_says_nothing(self):
        """#883: an unreadable file is not evidence of invisibility."""
        self.src("Nav.jsx", '<img src="/assets/icons/absent.svg"/>')
        self.assertEqual(invisible(self.fe), [])

    def test_a_staged_but_UNREADABLE_file_says_nothing_either_1203p0(self):
        """#1203p0: the OTHER half of #883 here, and it had no test.

        `test_a_path_that_is_not_staged_says_nothing` above covers the path that resolves to
        nothing -- the basename index has no entry, so the read never happens. A file that IS
        in the index and then fails to read is a different branch: `_one_colourless_1203n4`
        returns `None` there, deliberately, because "could not read it" is not "it takes a
        colour from CSS". Nothing asserted that, so changing the `except` to `return False`
        passed the whole suite while silently reclassifying every unreadable icon as coloured
        -- i.e. no longer reported. Found by writing fresh mutations against the CURRENT shape
        of this code rather than re-aiming the ones written before #1203nv/#1203nx rewrote it.

        The index is built by `pub.rglob("*.svg")` with no `is_file()` filter, so a DIRECTORY
        named like an icon is the deterministic way to make the read raise -- no chmod, no
        platform assumptions.
        """
        (self.fe / "public" / "assets" / "icons" / "dir_shaped.svg").mkdir()
        self.src("Nav.jsx", '<img src="/assets/icons/dir_shaped.svg"/>')
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
