r"""#1203nz: several screens, one rendering, and a separate score for each.

The visual gate captures every mapped screen and scores it against its own reference. When
two captures are BYTE IDENTICAL the judge still returns a score per screen, so all but one of
those scores describes pixels belonging to a different screen -- and nothing says so.

MEASURED over the 30 runs holding gate captures: 11 groups in 7 runs, 2 to 5 screens each,
19 screens scored against another screen's pixels. gmrun3 and gmrun4 each judge FIVE as one
image (`account_menu`, `home_map`, `home_map_biking_satellite`, `hotel_detail_overview`,
`layers_menu`); instagram-r174 three; tiktok-r180 two.

★ THE JUDGING IS EVIDENCED, AND MY FIRST READING OF THAT WAS WRONG. Reading
`gate_state.json`'s `_best_by_screen` made five of the seven runs look unjudged -- that field
is simply absent from the older state shape. `visual_gate/history/` is the record that
survives (146, 103, 123, 35, 29, 48 and 8 entries), and in EVERY one of the 11 groups at
least two colliding screens have a history entry with the same hash. The collision is scored,
not merely captured.

TWO CAUSES WITH DIFFERENT OWNERS, so the row names which:
  * a THEME pair (`login_dark` ≡ `login_light`, 1 group) means FIX #141's three emulation
    strategies were all inert on that app. #141's own words give the cost -- the dark
    reference "was judged against LIGHT pixels and structurally capped ~0.3; a blocking
    screen that can never pass ran every visual window to the 3600s anchor". #141 made the
    capture try harder and never checked the outcome.
  * DISTINCT screens (10 groups) means several routes render the same page: an overlay that
    never opened, or paths falling through to `*`.
"""
import tempfile
import unittest
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime.visual_fidelity import (
    identical_captures_1203nz as dup,
)


def _png(path, shade):
    from PIL import Image
    Image.new("L", (40, 30), shade).save(path)


class _Gate(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.run = Path(self._tmp.name) / "run"
        self.caps = self.run / "design" / "visual_gate"
        self.caps.mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def shot(self, name, shade):
        _png(self.caps / (name + ".png"), shade)


class TheCollisionIsNamed(_Gate):
    def test_two_distinct_screens_sharing_a_capture(self):
        self.shot("account_menu", 10)
        self.shot("layers_menu", 10)
        got = dup(self.run)
        self.assertEqual(len(got), 1, got)
        self.assertIn("account_menu + layers_menu", got[0])
        self.assertIn("judged as 2 screens", got[0])

    def test_it_counts_how_many_scores_are_about_other_pixels(self):
        for n in ("account_menu", "home_map", "layers_menu", "hotel_detail_overview"):
            self.shot(n, 10)
        got = dup(self.run)
        self.assertEqual(len(got), 1, got)
        self.assertIn("judged as 4 screens", got[0])
        self.assertIn("so 3 of those scores", got[0])

    def test_two_separate_collisions_are_two_rows(self):
        self.shot("a1", 10)
        self.shot("a2", 10)
        self.shot("b1", 200)
        self.shot("b2", 200)
        self.assertEqual(len(dup(self.run)), 2)

    def test_the_row_says_what_the_cause_might_be(self):
        self.shot("create_modal", 10)
        self.shot("home_feed", 10)
        row = dup(self.run)[0]
        self.assertIn("overlay that never opened", row)


class TheThemePairIsItsOwnCause(_Gate):
    def test_identical_theme_variants_name_fix_141(self):
        self.shot("login_dark", 10)
        self.shot("login_light", 10)
        got = dup(self.run)
        self.assertEqual(len(got), 1, got)
        self.assertIn("#141", got[0])
        self.assertIn("emulation", got[0])

    def test_it_does_not_read_as_a_distinct_screen_collision(self):
        self.shot("login_dark", 10)
        self.shot("login_light", 10)
        self.assertNotIn("judged as 2 screens", dup(self.run)[0])

    def test_two_different_screens_that_merely_carry_a_theme_token(self):
        """`feed_dark` and `profile_dark` are not a theme PAIR of one screen -- the stems
        differ -- so this is the distinct-screen cause, not #141's."""
        self.shot("feed_dark", 10)
        self.shot("profile_dark", 10)
        row = dup(self.run)[0]
        self.assertIn("judged as 2 screens", row)
        self.assertNotIn("#141", row)


class DistinctCapturesAreSilent(_Gate):
    def test_different_pixels_are_not_reported(self):
        self.shot("account_menu", 10)
        self.shot("layers_menu", 200)
        self.assertEqual(dup(self.run), [])

    def test_a_single_capture_is_not_a_collision(self):
        self.shot("only", 10)
        self.assertEqual(dup(self.run), [])

    def test_the_frameworks_own_NOT_CAPTURED_marker_is_excluded(self):
        """`explore_grid.NOT-CAPTURED.png` is the gate saying it never captured; two of
        those are identical by construction and are not a collision."""
        _png(self.caps / "explore_grid.NOT-CAPTURED.png", 10)
        _png(self.caps / "live_discover.NOT-CAPTURED.png", 10)
        self.assertEqual(dup(self.run), [])

    def test_a_real_capture_colliding_with_nothing_but_a_marker(self):
        _png(self.caps / "explore_grid.NOT-CAPTURED.png", 10)
        self.shot("live_discover", 10)
        self.assertEqual(dup(self.run), [])


class ItSurvivesWhatIsNotThere(_Gate):
    def test_no_gate_directory(self):
        import shutil
        shutil.rmtree(self.caps)
        self.assertEqual(dup(self.run), [])

    def test_a_nonexistent_run(self):
        self.assertEqual(dup(Path("/nope/run")), [])

    def test_an_unreadable_file_is_skipped(self):
        (self.caps / "broken.png").write_bytes(b"not a png")
        self.shot("a", 10)
        self.shot("b", 10)
        got = dup(self.run)
        self.assertEqual(len(got), 1, got)
        self.assertNotIn("broken", got[0])


class TheGateAsksTheQuestion(unittest.TestCase):
    @staticmethod
    def _tries():
        import ast
        import inspect
        from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as VF
        out = []
        for n in ast.walk(ast.parse(inspect.getsource(VF))):
            if not isinstance(n, ast.Try):
                continue
            for sub in ast.walk(ast.Module(body=n.body, type_ignores=[])):
                if isinstance(sub, ast.Call) and getattr(
                        sub.func, "id", getattr(sub.func, "attr", "")
                ) == "identical_captures_1203nz":
                    out.append(n)
                    break
        return out

    def test_the_gate_calls_it(self):
        self.assertTrue(self._tries(), "the visual gate never calls it")

    def test_it_is_guarded_on_its_own(self):
        import ast
        node = min(self._tries(), key=lambda n: (n.end_lineno or 0) - n.lineno)
        self.assertTrue(node.handlers, "unguarded (#1201)")
        body = ast.dump(ast.Module(body=node.body, type_ignores=[]))
        self.assertNotIn("blank_captures_1203ny", body,
                         "it shares a try with #1203ny, so one failing silences the other")

    def test_the_cut_declares_itself(self):
        import inspect
        from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as VF
        self.assertIn("more identical-capture group(s) not listed", inspect.getsource(VF))


class WhatTheCorpusSays(unittest.TestCase):
    """Named runs only -- the measured cases and two healthy controls."""

    _MEASURED = ("instagram-core-r174", "instagram-core-r176", "tiktok-web-r180")
    _HEALTHY = ("tiktok-web-r190", "tiktok-web-r191")

    @classmethod
    def setUpClass(cls):
        cls.corpus = Path(__file__).resolve().parents[2] / "generated"
        if not cls.corpus.is_dir():
            raise unittest.SkipTest("no generated/ corpus on this machine")

    def test_it_fires_on_the_measured_runs(self):
        checked = 0
        for run in self._MEASURED:
            d = self.corpus / run
            if not (d / "design" / "visual_gate").is_dir():
                continue
            checked += 1
            with self.subTest(run=run):
                self.assertGreater(len(dup(d)), 0,
                                   "%s was measured with a collision and now reports none"
                                   % run)
        if not checked:
            self.skipTest("no measured run on this disk")

    def test_it_stays_silent_on_the_healthy_ones(self):
        checked = 0
        for run in self._HEALTHY:
            d = self.corpus / run
            if not (d / "design" / "visual_gate").is_dir():
                continue
            checked += 1
            with self.subTest(run=run):
                self.assertEqual(dup(d), [])
        if not checked:
            self.skipTest("no healthy run on this disk")

    def test_the_judging_of_a_collision_is_evidenced(self):
        """The claim my first reading got wrong: `gate_state.json`'s `_best_by_screen` is
        absent from the older shape, so the history directory is what proves the colliding
        screens were scored."""
        import hashlib
        import re
        for run in self._MEASURED:
            caps = self.corpus / run / "design" / "visual_gate"
            hist = caps / "history"
            if not hist.is_dir():
                continue
            rows = dup(caps.parent.parent)
            if not rows:
                continue
            names = set(re.findall(r"[\w.-]+", rows[0].split(":")[0]))
            byscreen = {}
            for f in hist.glob("*.png"):
                m = re.match(r"\d+_(.+)\.png$", f.name)
                if m and m.group(1) in names:
                    byscreen.setdefault(m.group(1), set()).add(
                        hashlib.md5(f.read_bytes()).hexdigest())
            with self.subTest(run=run):
                self.assertGreaterEqual(
                    len(byscreen), 2,
                    "fewer than two colliding screens have a history entry in %s, so the "
                    "'scored, not merely captured' claim no longer holds there" % run)


if __name__ == "__main__":
    unittest.main()
