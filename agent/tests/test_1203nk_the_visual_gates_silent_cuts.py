r"""#1203nk: the visual gate's three component blocks were each capped, and none said so.

All three are PROSE WRITTEN FOR THE AGENT that has to reproduce the screen, so a withheld row
is a measurement the lane never receives and cannot know it is missing — #1034's harm in the
channel where it costs most.

    _spec_snippet          MEASURED SPEC rows from design/component_specs/<screen>.json   cap 12
    _copy_lines_797        REFERENCE COPY, verbatim strings from the design doc            cap 12
    _layout_geometry_lines LAYOUT GEOMETRY, #796's repair-round block                      cap 10

MEASURED on the MEASURED SPEC block, which was cutting all along: across 102 runs and 1412
screens it showed 15882 of 20407 components (78%), the cap bit on 961 screens (68%), and it
withheld 4525 components in total — median 4 per affected screen, up to 12. Nothing said so.

The other two had caps that never bit, because the design_analyst's wholesale rewrite left
2-4 components a screen. #1203ni restores the measured components that rewrite dropped
(r191's `fyp_feed_logged_out` goes 4 -> 19), so from this point they cut too — the same
composition that produced #1203nj one file over.

NO CAP IS RAISED. These are prompts; the bound is the point. What changes is that the lane can
tell there is more, and where to find it.
"""
import unittest

from env_generator.llm_generator.multi_agent.runtime.visual_fidelity import (
    _COPY_CHARS_1203NK as COPY_CHARS,
    _COPY_ROWS_1203NK as COPY_CAP,
    _LAYOUT_ROWS_1203NK as LAYOUT_CAP,
    _SURFACE_ROWS_1203NK as SURFACE_CAP,
    _copy_lines_797,
    _cut_row_1203nk,
    _layout_geometry_lines,
    _spec_snippet,
)


def _components(n, *, copy=False, region=True):
    out = []
    for i in range(n):
        c = {"name": "comp_%02d" % i, "id": "comp-%02d" % i,
             "background": "#0a0a0a", "accents": {"blue": "#65c9d1"},
             "state": "default"}
        if region:
            c["region"] = [0.0, i / max(n, 1), 1.0, (i + 1) / max(n, 1)]
            c["colors"] = {"bg": "#0a0a0a"}
        if copy:
            c["copy"] = "Sign in"
        out.append(c)
    return out


def _ds(n, **kw):
    return {"screens": [{"name": "s", "components": _components(n, **kw)}]}


class TheCutRowItself(unittest.TestCase):
    def test_nothing_cut_renders_nothing(self):
        self.assertEqual(_cut_row_1203nk(12, 12), [])
        self.assertEqual(_cut_row_1203nk(3, 12), [])

    def test_one_withheld_is_singular(self):
        row = _cut_row_1203nk(13, 12)[0]
        self.assertIn("+1 more measured component not shown", row)

    def test_many_withheld_names_the_number(self):
        self.assertIn("+9 more measured components not shown", _cut_row_1203nk(21, 12)[0])

    def test_it_says_where_the_rest_is(self):
        self.assertIn("design/component_specs/", _cut_row_1203nk(21, 12)[0])

    def test_hostile_totals_never_raise(self):
        for bad in (None, "x", object()):
            with self.subTest(total=repr(bad)):
                self.assertEqual(_cut_row_1203nk(bad, 12), [])


class TheMeasuredSpecBlockDeclaresItsCut(unittest.TestCase):
    """The block that was cutting all along: 4525 components withheld across the corpus."""

    def _snippet(self, n):
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            import pathlib
            cs = pathlib.Path(d) / "design" / "component_specs"
            cs.mkdir(parents=True)
            (cs / "s.json").write_text(json.dumps({"components": _components(n)}),
                                       encoding="utf-8")
            return _spec_snippet(d, "s")

    def test_a_corpus_sized_screen(self):
        """21 components is the top of the measured range."""
        out = self._snippet(21)
        self.assertIn("+%d more measured components not shown" % (21 - SURFACE_CAP), out)

    def test_the_median_affected_screen(self):
        out = self._snippet(SURFACE_CAP + 4)
        self.assertIn("+4 more measured components not shown", out)

    def test_a_screen_under_the_cap_is_unchanged(self):
        out = self._snippet(SURFACE_CAP)
        self.assertNotIn("not shown", out)
        self.assertIn("comp_00", out)
        self.assertIn("#0a0a0a", out)

    def test_it_still_shows_exactly_the_cap(self):
        out = self._snippet(21)
        shown = [ln for ln in out.split("\n") if ln.strip().startswith("· comp_")]
        self.assertEqual(len(shown), SURFACE_CAP)


class TheLayoutBlockDeclaresItsCut(unittest.TestCase):
    """#796's repair-round block. Its cap never bit until #1203ni restored the components."""

    def test_r191s_restored_screen(self):
        lines = _layout_geometry_lines(_ds(19), "s")
        self.assertTrue(any("+%d more" % (19 - LAYOUT_CAP) in ln for ln in lines), lines[-2:])

    def test_the_pre_1203ni_shape_is_unchanged(self):
        for n in (2, 3, 4, LAYOUT_CAP):
            with self.subTest(components=n):
                lines = _layout_geometry_lines(_ds(n), "s")
                self.assertFalse([ln for ln in lines if "not shown" in ln])

    def test_it_still_shows_exactly_the_cap(self):
        lines = _layout_geometry_lines(_ds(19), "s")
        shown = [ln for ln in lines if ln.strip().startswith("· comp-")]
        self.assertEqual(len(shown), LAYOUT_CAP)

    def test_a_component_without_a_region_does_not_consume_a_row(self):
        lines = _layout_geometry_lines(_ds(3, region=False), "s")
        self.assertFalse([ln for ln in lines if ln.strip().startswith("· comp-")])


class TheCopyBlockDeclaresItsCut(unittest.TestCase):
    def test_a_restored_screen_declares_what_it_did_not_examine(self):
        lines = _copy_lines_797(_ds(19, copy=True), "s")
        self.assertTrue(any("+%d more" % (19 - COPY_CAP) in ln for ln in lines), lines[-2:])

    def test_the_pre_1203ni_shape_is_unchanged(self):
        lines = _copy_lines_797(_ds(4, copy=True), "s")
        self.assertFalse([ln for ln in lines if "not shown" in ln])
        self.assertTrue(any("Sign in" in ln for ln in lines))

    def test_no_copy_means_no_block_at_all(self):
        self.assertEqual(_copy_lines_797(_ds(19, copy=False), "s"), [])


class TheVerbatimStringCutDeclaresItself(unittest.TestCase):
    """The block says "render these strings character for character" and then sliced the
    string at 120. MEASURED over the delivered design docs: 2366 components in 13 runs carry
    `copy` — median 28 characters, p90 142, max 322 — and 260 of them exceed 120. The lane was
    being told to reproduce exactly a string it had only the first 120 characters of."""

    def _lines(self, length):
        ds = {"screens": [{"name": "s", "components": [
            {"id": "c", "copy": "x" * length}]}]}
        return _copy_lines_797(ds, "s")

    def test_a_string_under_the_bound_is_untouched(self):
        for n in (7, 28, COPY_CHARS):
            with self.subTest(length=n):
                ln = self._lines(n)[1]
                self.assertNotIn("CUT at", ln)
                self.assertIn('"' + "x" * n + '"', ln)

    def test_the_p90_string_declares_its_cut(self):
        ln = self._lines(142)[1]
        self.assertIn("CUT at %d of 142 characters" % COPY_CHARS, ln)

    def test_the_longest_corpus_string(self):
        ln = self._lines(322)[1]
        self.assertIn("CUT at %d of 322 characters" % COPY_CHARS, ln)

    def test_it_tells_the_lane_not_to_treat_the_fragment_as_complete(self):
        ln = self._lines(200)[1]
        self.assertIn("do not render this fragment as the complete text", ln)

    def test_it_says_where_the_whole_string_is(self):
        ln = self._lines(200)[1]
        self.assertIn("design/design_system.json", ln)

    def test_the_bound_is_named_not_restated(self):
        self.assertEqual(COPY_CHARS, 120)


class TheCapsAreNamedAndUnchanged(unittest.TestCase):
    """#1032: read from the module, not restated. And the point of the ticket is that the
    bounds stay — these are prompts."""

    def test_the_three_caps(self):
        self.assertEqual((SURFACE_CAP, COPY_CAP, LAYOUT_CAP), (12, 12, 10))

    def test_no_literal_cap_survives_at_the_three_sites(self):
        """Only the COMPONENT-LIST slices. A first version flagged every integer slice and so
        caught `txt[:120]` as well -- which turned out to be a real defect of its own (the
        verbatim-copy cut below), but it is a different cut and belongs to a different
        assertion."""
        import ast
        import inspect
        from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as VF
        for fn in (_spec_snippet, _copy_lines_797, _layout_geometry_lines):
            with self.subTest(fn=fn.__name__):
                tree = ast.parse(inspect.getsource(fn).lstrip())
                for n in ast.walk(tree):
                    if not (isinstance(n, ast.Subscript)
                            and isinstance(n.slice, ast.Slice)):
                        continue
                    target = ast.unparse(n.value)
                    if not any(k in target for k in ("components", "comps", "_all1203nk")):
                        continue
                    up = n.slice.upper
                    if isinstance(up, ast.Constant) and isinstance(up.value, int):
                        self.fail("%s still slices components with a literal %r"
                                  % (fn.__name__, up.value))
        self.assertTrue(hasattr(VF, "_cut_row_1203nk"))

    def test_every_site_calls_the_one_renderer(self):
        import ast
        import inspect
        for fn in (_spec_snippet, _copy_lines_797, _layout_geometry_lines):
            with self.subTest(fn=fn.__name__):
                tree = ast.parse(inspect.getsource(fn).lstrip())
                calls = {n.func.id for n in ast.walk(tree)
                         if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
                self.assertIn("_cut_row_1203nk", calls)


if __name__ == "__main__":
    unittest.main()
