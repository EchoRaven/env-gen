r"""#1203ny: the visual gate scores a blank capture as a design mismatch.

The gate captures each mapped screen and scores it against its reference. Handed an empty
page, an LLM judge returns a MIDDLING similarity -- r163's and r180's `explore_grid` land in
the same band as a page that rendered and merely looks different -- so nothing in the record
says "nothing rendered" and the lane reads a styling note where the page is gone.

FOUND BY MEASURING THE OUTCOME rather than by reading code: edge density (the share of pixels
differing from a neighbour) over every staged reference and its paired capture. 264 pairs in
30 runs, ratio median 0.864, p10 0.131 -- and 18 pairs in 8 runs between 0.016 and 0.087:

    tiktok-web-r163  explore_grid                 ref 16.44%  cap 0.27%  ratio 0.016
    tiktok-web-r180  explore_grid                 ref 16.44%  cap 0.27%  ratio 0.016
    googlemaps-gmrun3 home_map_biking_satellite   ref 31.06%  cap 1.69%  ratio 0.054

★ WHY IT IS A RATIO, AND WHY A THRESHOLD CANNOT WORK. `messages_dm_empty`'s reference inks
0.52% because an empty inbox IS mostly background, so any absolute floor low enough to clear
it would clear a dead page too. Against its OWN reference that screen reads 0.587 and 8.262
and stays silent, while `explore_grid` reads 0.016. The same comparison makes the check
theme-independent: a dark page and a light page both have text, and both lack it when nothing
rendered.

Reports only. Whether a blank capture is a dead page, a mid-rebuild shot or a 404 is not
decidable from the pixels, and #655b/#75a already refund a capture taken while the app was
unreachable.
"""
import tempfile
import unittest
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime.visual_fidelity import (
    _BLANK_RATIO_1203NY,
    _REF_HAS_CONTENT_1203NY,
    _edge_density_1203ny,
    blank_captures_1203ny as blank,
)


def _png(path, kind):
    """`solid` inks ~0% edges, `busy` inks a lot, `sparse` a little."""
    from PIL import Image, ImageDraw
    im = Image.new("L", (240, 160), 20)
    d = ImageDraw.Draw(im)
    if kind == "busy":
        for x in range(0, 240, 3):
            d.line([(x, 0), (x, 160)], fill=230)
    elif kind == "sparse":
        d.line([(0, 80), (240, 80)], fill=230)
    im.save(path)


class _Tree(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.run = Path(self._tmp.name) / "run"
        self.refs = self.run / "design" / "references"
        self.caps = self.run / "design" / "visual_gate"
        self.refs.mkdir(parents=True)
        self.caps.mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def pair(self, name, ref_kind, cap_kind):
        _png(self.refs / (name + ".png"), ref_kind)
        _png(self.caps / (name + ".png"), cap_kind)


class TheBlankCaptureIsNamed(_Tree):
    def test_a_blank_capture_against_a_busy_reference_is_reported(self):
        self.pair("explore_grid", "busy", "solid")
        got = blank(self.run)
        self.assertEqual(len(got), 1, got)
        self.assertIn("explore_grid", got[0])
        self.assertIn("looks EMPTY", got[0])

    def test_the_row_carries_both_densities_and_the_ratio(self):
        self.pair("explore_grid", "busy", "solid")
        row = blank(self.run)[0]
        self.assertIn("ratio", row)
        self.assertIn("of the page against", row)
        self.assertIn("0.864", row)      # the corpus median, for scale

    def test_several_screens_are_all_named(self):
        self.pair("a", "busy", "solid")
        self.pair("b", "busy", "solid")
        self.assertEqual(len(blank(self.run)), 2)


class AHealthyCaptureIsSilent(_Tree):
    def test_a_busy_capture_is_not_reported(self):
        self.pair("explore_grid", "busy", "busy")
        self.assertEqual(blank(self.run), [])

    def test_a_capture_above_the_ratio_is_not_reported(self):
        """p10 of the healthy population is 0.131, well above the 0.10 line."""
        self.pair("explore_grid", "busy", "sparse")
        rows = blank(self.run)
        er = _edge_density_1203ny(self.refs / "explore_grid.png")
        ec = _edge_density_1203ny(self.caps / "explore_grid.png")
        if ec / er >= _BLANK_RATIO_1203NY:
            self.assertEqual(rows, [], "ratio %.3f should be silent" % (ec / er))
        else:
            self.assertEqual(len(rows), 1)


class AnEmptyStateScreenIsSilent(_Tree):
    """★ The case that forces the ratio. `messages_dm_empty`'s reference inks 0.52% in every
    run that stages it, so an absolute floor low enough to clear it would clear a dead page
    too."""

    def test_both_sides_near_blank_is_not_reported(self):
        self.pair("messages_dm_empty", "solid", "solid")
        self.assertEqual(blank(self.run), [])

    def test_a_thin_reference_is_below_the_content_floor(self):
        self.pair("messages_dm_empty", "sparse", "solid")
        er = _edge_density_1203ny(self.refs / "messages_dm_empty.png")
        self.assertLess(er, _REF_HAS_CONTENT_1203NY,
                        "the sparse fixture is no longer below the content floor, so this "
                        "test stopped exercising the empty-state carve-out")
        self.assertEqual(blank(self.run), [])


class ItSurvivesWhatIsNotThere(_Tree):
    def test_a_reference_with_no_capture_is_skipped(self):
        _png(self.refs / "explore_grid.png", "busy")
        self.assertEqual(blank(self.run), [])

    def test_a_missing_directory_returns_empty(self):
        import shutil
        shutil.rmtree(self.caps)
        self.assertEqual(blank(self.run), [])

    def test_a_nonexistent_run(self):
        self.assertEqual(blank(Path("/nope/run")), [])

    def test_an_unreadable_png_is_skipped_not_guessed(self):
        (self.refs / "broken.png").write_bytes(b"not a png")
        (self.caps / "broken.png").write_bytes(b"not a png")
        self.assertEqual(blank(self.run), [])
        self.assertEqual(_edge_density_1203ny(self.refs / "broken.png"), -1.0)


class TheConstantsCarryTheirMeasurement(unittest.TestCase):
    def test_the_ratio_sits_between_the_populations(self):
        """0.10 lies in the empty band between the healthy p10 (0.131) and the worst blank
        (0.087). Asserting the ordering, not the number, so a future re-measurement can move
        it without this test going stale for the wrong reason."""
        self.assertLess(0.087, _BLANK_RATIO_1203NY)
        self.assertLess(_BLANK_RATIO_1203NY, 0.131)

    def test_the_content_floor_clears_every_flagged_reference(self):
        """Every flagged reference inks at least 8.42%; the empty state inks 0.52%."""
        self.assertLess(0.52, _REF_HAS_CONTENT_1203NY)
        self.assertLess(_REF_HAS_CONTENT_1203NY, 8.42)


class TheGateAsksTheQuestion(unittest.TestCase):
    """A detector nobody calls is the gap it exists to close."""

    @staticmethod
    def _tries():
        import ast
        import inspect
        from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as VF
        tree = ast.parse(inspect.getsource(VF))
        out = []
        for n in ast.walk(tree):
            if not isinstance(n, ast.Try):
                continue
            for sub in ast.walk(ast.Module(body=n.body, type_ignores=[])):
                if isinstance(sub, ast.Call) and getattr(
                        sub.func, "id", getattr(sub.func, "attr", "")
                ) == "blank_captures_1203ny":
                    out.append(n)
                    break
        return out

    def test_the_gate_calls_it(self):
        self.assertTrue(self._tries(), "the visual gate never calls it")

    def test_it_is_guarded_on_its_own(self):
        tries = self._tries()
        node = min(tries, key=lambda n: (n.end_lineno or 0) - n.lineno)
        self.assertTrue(node.handlers, "the call is unguarded (#1201)")
        import ast
        body = ast.dump(ast.Module(body=node.body, type_ignores=[]))
        self.assertNotIn("record_screen_coverage_1202w4", body,
                         "it shares a try with the coverage line, so one failing silences "
                         "the other")

    def test_the_cut_declares_itself(self):
        import inspect
        from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as VF
        self.assertIn("more blank capture(s) not listed", inspect.getsource(VF))


class WhatTheCorpusSays(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus = Path(__file__).resolve().parents[2] / "generated"
        if not cls.corpus.is_dir():
            raise unittest.SkipTest("no generated/ corpus on this machine")

    # NAMED RUNS ONLY, not a corpus sweep. The first version globbed every run and took 93
    # seconds of the suite to re-derive numbers that are already recorded in the docstring;
    # four runs make the same two assertions in under four.
    _MEASURED = ("tiktok-web-r163", "tiktok-web-r180")
    _HEALTHY = ("tiktok-web-r179", "tiktok-web-r191")

    def _rows(self, run):
        d = self.corpus / run
        if not (d / "design" / "visual_gate").is_dir():
            return None
        return blank(d)

    def test_it_fires_on_the_measured_runs(self):
        checked = 0
        for run in self._MEASURED:
            rows = self._rows(run)
            if rows is None:
                continue
            checked += 1
            with self.subTest(run=run):
                self.assertGreater(len(rows), 0,
                                   "%s was measured at 4 blank captures and now reports "
                                   "none" % run)
        if not checked:
            self.skipTest("neither measured run is on this disk")

    def test_it_stays_silent_on_the_healthy_ones(self):
        checked = 0
        for run in self._HEALTHY:
            rows = self._rows(run)
            if rows is None:
                continue
            checked += 1
            with self.subTest(run=run):
                self.assertEqual(rows, [],
                                 "a healthy run started reporting, so the ratio or the "
                                 "content floor no longer separates the populations")
        if not checked:
            self.skipTest("neither healthy run is on this disk")

    def test_the_empty_state_screen_is_never_reported(self):
        """The carve-out on real data: `messages_dm_empty`'s reference inks 0.52%."""
        checked = 0
        for run in self._MEASURED + self._HEALTHY:
            d = self.corpus / run
            if not (d / "design" / "references" / "messages_dm_empty.png").is_file():
                continue
            checked += 1
            with self.subTest(run=run):
                self.assertFalse([r for r in (blank(d) or []) if "messages_dm_empty" in r])
        if not checked:
            self.skipTest("the empty-state screen is not staged on this disk")


if __name__ == "__main__":
    unittest.main()
