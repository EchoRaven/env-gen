r"""#1203mi: the icon that was positioned out of its own viewport.

The scraper lifts icons out of inline page markup and keeps the element's live inline
`style`. TikTok's tooltip arrow arrives with `position: absolute; bottom: 100%;` on its ROOT
`<svg>`, so its paths draw outside its own 14x14 viewport and the icon is EMPTY wherever the
app uses it. Real Chromium over a 64x64 canvas: 0 opaque pixels of 4096 as staged, 1105 with
`position` removed. Found by rendering every staged SVG in the corpus and asking which ones
put no ink anywhere -- `#1203ku`'s structural predicate cannot see this one, because the file
has real `<path>` elements.

Only `position` is dropped (#647): measured per declaration on that same file, dropping
`position` alone gives 1105 while dropping `bottom`, `left`, `transform` or `pointer-events`
alone each still gives 0.

The corpus bounds what this touches: 411 of 8978 staged SVGs declare `position` on the root,
but only THREE distinct filenames across 137 runs -- two are the empty sprite hosts #1203ku
already drops, so rendering all three before and after gives one improvement, two unchanged
and ZERO regressions.
"""
import ast
import inspect
import unittest

from env_generator.llm_generator.multi_agent.runtime import material_prep as MP

# The real staged bytes (generated/tiktok-web-r*/.../icons/icon_56b8c744.svg), 137 runs.
ARROW = (
    '<svg xmlns="http://www.w3.org/2000/svg" data-testid="tux-tooltip-arrow" '
    'fill="var(--tux-v2-color-ui-sheet-flat-3)" aria-hidden="true" width="14.66" '
    'height="14" viewBox="0 0 14 14" style="position: absolute; pointer-events: none; '
    'bottom: 100%; transform: rotate(180deg); left: 31.1719px;">'
    '<path fill="none" stroke="currentColor" d="M0,0 H14 L9.625,5 Q7,8 4.375,5 Z"></path>'
    '</svg>')

PLAIN = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
         '<path d="M4 4h16v16H4z"/></svg>')


class ThePredicateAsksAboutTheRoot(unittest.TestCase):
    def test_the_real_arrow_is_positioned(self):
        self.assertTrue(MP.svg_root_is_positioned_1203mi(ARROW))

    def test_a_normal_icon_is_not(self):
        self.assertFalse(MP.svg_root_is_positioned_1203mi(PLAIN))

    def test_non_svg_text_is_not(self):
        self.assertFalse(MP.svg_root_is_positioned_1203mi("not markup at all"))
        self.assertFalse(MP.svg_root_is_positioned_1203mi(""))
        self.assertFalse(MP.svg_root_is_positioned_1203mi(None))

    def test_a_positioned_CHILD_is_not_the_root(self):
        """The narrowing that matters: a child may legitimately be positioned."""
        src = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
               '<foreignObject><div style="position:absolute">x</div></foreignObject></svg>')
        self.assertFalse(MP.svg_root_is_positioned_1203mi(src))
        self.assertEqual(MP.strip_root_position_1203mi(src), src)

    def test_a_style_without_position_is_not(self):
        src = '<svg xmlns="http://www.w3.org/2000/svg" style="color:red" viewBox="0 0 2 2"/>'
        self.assertFalse(MP.svg_root_is_positioned_1203mi(src))


class TheRepairTakesOnlyThatDeclaration(unittest.TestCase):
    def test_position_is_gone_and_the_rest_is_kept(self):
        out = MP.strip_root_position_1203mi(ARROW)
        self.assertNotIn("position:", out.replace(" ", ""))
        for keep in ("pointer-events", "bottom: 100%", "transform: rotate(180deg)",
                     "left: 31.1719px"):
            self.assertIn(keep, out, "#1203mi dropped more than `position`: lost %r" % keep)

    def test_everything_outside_the_style_survives(self):
        out = MP.strip_root_position_1203mi(ARROW)
        for keep in ('viewBox="0 0 14 14"', 'width="14.66"', 'height="14"',
                     'data-testid="tux-tooltip-arrow"', "<path", "M0,0 H14"):
            self.assertIn(keep, out)

    def test_a_style_that_was_only_position_loses_the_attribute(self):
        src = ('<svg xmlns="http://www.w3.org/2000/svg" style="position:absolute" '
               'viewBox="0 0 2 2"><path d="M0,0 H2"/></svg>')
        out = MP.strip_root_position_1203mi(src)
        self.assertNotIn("style=", out, "an empty `style=\"\"` was left behind")
        self.assertIn('viewBox="0 0 2 2"', out)
        self.assertIn("<path", out)

    def test_it_is_idempotent(self):
        once = MP.strip_root_position_1203mi(ARROW)
        self.assertEqual(MP.strip_root_position_1203mi(once), once)

    def test_nothing_to_do_returns_the_input(self):
        self.assertEqual(MP.strip_root_position_1203mi(PLAIN), PLAIN)
        self.assertEqual(MP.strip_root_position_1203mi("x"), "x")


class ItComposesWithThe1203l6Repair(unittest.TestCase):
    """Both repairs edit the ROOT tag; a file can need both, so neither may eat the other."""

    NO_NS_POSITIONED = (
        '<svg data-testid="tux-tooltip-arrow" width="14.66" height="14" viewBox="0 0 14 14" '
        'style="position: absolute; bottom: 100%;"><path d="M0,0 H14"/></svg>')

    def test_the_file_needs_both(self):
        self.assertTrue(MP.svg_needs_namespace_1203l6(self.NO_NS_POSITIONED))
        self.assertTrue(MP.svg_root_is_positioned_1203mi(self.NO_NS_POSITIONED))

    def test_either_order_gives_the_same_bytes_and_both_repairs(self):
        a = MP.strip_root_position_1203mi(
            MP.add_svg_namespace_1203l6(self.NO_NS_POSITIONED))
        b = MP.add_svg_namespace_1203l6(
            MP.strip_root_position_1203mi(self.NO_NS_POSITIONED))
        self.assertEqual(a, b, "the two root-tag repairs are order-dependent")
        for out in (a, b):
            self.assertIn('xmlns="http://www.w3.org/2000/svg"', out)
            self.assertNotIn("position:", out.replace(" ", ""))
            self.assertIn("bottom: 100%", out)
            self.assertIn('viewBox="0 0 14 14"', out)
            self.assertIn("<path", out)

    def test_each_predicate_is_false_after_the_other_repair(self):
        """#1203l6's output must not look un-positioned, and mine must not lose the xmlns
        question -- the shape where one repair hides the other's case."""
        after_l6 = MP.add_svg_namespace_1203l6(self.NO_NS_POSITIONED)
        self.assertTrue(MP.svg_root_is_positioned_1203mi(after_l6),
                        "#1203l6's output no longer reads as positioned")
        after_mi = MP.strip_root_position_1203mi(self.NO_NS_POSITIONED)
        self.assertTrue(MP.svg_needs_namespace_1203l6(after_mi),
                        "#1203mi's output no longer reads as namespace-less")


class TheStagingSiteCallsBoth(unittest.TestCase):
    """Pinned on the CALL, not on source text -- a docstring quoting the name is not a use."""

    def _calls(self):
        tree = ast.parse(inspect.getsource(MP))
        return {n.func.id for n in ast.walk(tree)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}

    def test_both_repairs_are_invoked_in_the_module(self):
        names = self._calls()
        for want in ("add_svg_namespace_1203l6", "svg_needs_namespace_1203l6",
                     "strip_root_position_1203mi", "svg_root_is_positioned_1203mi"):
            self.assertIn(want, names, "%s is defined but never called (#1202w1)" % want)

    def test_the_write_is_guarded_by_either_repair_firing(self):
        """The repaired text is written when EITHER repair fired.

        An AST assertion, not `"... in getsource"`: a comment that quotes the condition
        would satisfy a text match while the code said something else.
        """
        tree = ast.parse(inspect.getsource(MP))
        flags = {"_did1203l6", "_did1203mi"}
        found = False
        for n in ast.walk(tree):
            if (isinstance(n, ast.If) and isinstance(n.test, ast.BoolOp)
                    and isinstance(n.test.op, ast.Or)
                    and {v.id for v in n.test.values
                         if isinstance(v, ast.Name)} == flags):
                # ...and that branch is what writes, while the else-branch copies.
                body = ast.dump(ast.Module(body=n.body, type_ignores=[]))
                orelse = ast.dump(ast.Module(body=n.orelse, type_ignores=[]))
                if "write_text" in body and "copy2" in orelse:
                    found = True
        self.assertTrue(found,
                        "no `if <l6 fired> or <mi fired>:` branch writes the repaired text "
                        "with the untouched copy in its else (#1203mi)")


if __name__ == "__main__":
    unittest.main()


class TheStagingRunAppliesBothRepairs(unittest.TestCase):
    """The hole mutation MI5 found: the two FUNCTIONS composing is not the same fact as the
    staging site asking both questions.

    `test_either_order_gives_the_same_bytes_and_both_repairs` passed while the staged write
    said `if (not _did1203l6) and svg_root_is_positioned_1203mi(...)`, i.e. a file needing
    both got only the namespace. So this drives the real `ingest_assets` over a real file.
    """

    SRC = ('<svg data-testid="tux-tooltip-arrow" width="14.66" height="14" '
           'viewBox="0 0 14 14" style="position: absolute; bottom: 100%;">'
           '<path d="M0,0 H14 L9.625,5 Q7,8 4.375,5 Z"/></svg>')

    def _stage(self, text):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td:
            src_dir = Path(td) / "assets" / "icons"
            src_dir.mkdir(parents=True)
            (src_dir / "arrow.svg").write_text(text, encoding="utf-8")
            stage = Path(td) / "stage"
            MP.ingest_assets(Path(td) / "assets", stage)
            out = stage / "icons" / "arrow.svg"
            self.assertTrue(out.is_file(), "the SVG was not staged at all")
            return out.read_text(encoding="utf-8")

    def test_a_file_needing_both_gets_both(self):
        staged = self._stage(self.SRC)
        self.assertIn('xmlns="http://www.w3.org/2000/svg"', staged,
                      "#1203l6's repair did not reach the staged copy")
        self.assertNotIn("position:", staged.replace(" ", ""),
                         "#1203mi's repair did not reach the staged copy — the two repairs "
                         "are not both applied at the staging write")
        self.assertIn("bottom: 100%", staged)
        self.assertIn('viewBox="0 0 14 14"', staged)

    def test_a_file_needing_only_position_still_gets_it(self):
        with_ns = self.SRC.replace(
            "<svg ", '<svg xmlns="http://www.w3.org/2000/svg" ', 1)
        staged = self._stage(with_ns)
        self.assertNotIn("position:", staged.replace(" ", ""))
        self.assertIn('xmlns="http://www.w3.org/2000/svg"', staged)

    def test_a_clean_file_is_staged_byte_for_byte(self):
        staged = self._stage(PLAIN)
        self.assertEqual(staged, PLAIN, "a file needing no repair was rewritten")
