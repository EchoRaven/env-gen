r"""#1203nq: the frontend had already fixed 38% of these, and the check reported them as 404s.

`missing_static_assets_1203g9` lists absolute asset paths the frontend references that are not
on disk under `public/`, and the consumer's instruction was "Add the file or stop referencing
it". A lane routinely does a THIRD thing: it keeps the invented name and adds a literal remap
table to a file that IS staged. `remapped_seed_media_1203m3` exists for exactly that question
-- "{missing_path: staged_target} for each path the FRONTEND already rewrites" -- and it was
wired to the SEED side only (`#1202zf`). `#1203g9` never asked it.

MEASURED over the 73 rows `#1203g9` produces in the delivered trees of 12 runs: **28 (38%) are
keys in a resolving remap table**, and four runs are essentially all remap -- tiktok-web-r166
5 of 5, r172 4 of 4, r182 6 of 6, r169 13 of 14. r172's reads

    /assets/real_videos/khaby.lame__7663376464665906452.mp4
        -> /assets/real_videos/khaby.lame__7661681676719869214.mp4

the same-creator repoint `#1203np`'s task recommends, done by the lane unprompted. The other
eight runs annotate 0, including both googlemaps runs whose 36 missing icons are this
finding's strongest genuine case.

ANNOTATED, NEVER DROPPED, which is `#1203m3`'s own rule carried across: the predicate proves a
mapping EXISTS, not that every caller goes through it (r172 applies its map in `getForYouFeed`
and nowhere else). Dropping the row is the direction that masks a failure.

Why it matters beyond tidiness: `#1202zf` filed a P1 at delivery ordering "Fix the SEED ROW,
not the page" and `#1203m3`'s docstring records that for r166 "that run's entire P1 was false".
This is the same false instruction on the frontend side.
"""
import inspect
import json
import tempfile
import unittest
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime import scaffolder as SC
from env_generator.llm_generator.multi_agent.runtime.frontend_audit import (
    missing_static_assets_1203g9 as det,
)

_REMAPPED = "/assets/videos/invented.mp4"
_ORPHAN = "/assets/videos/orphan.mp4"
_GHOSTKEY = "/assets/videos/ghostkey.mp4"
_STAGED = "/assets/real_videos/real__7661681676719869214.mp4"


def _tree(root: Path, remap_target=_STAGED):
    pub = root / "app" / "frontend" / "public" / "assets" / "real_videos"
    pub.mkdir(parents=True)
    (pub / "real__7661681676719869214.mp4").write_bytes(b"x")
    (pub / "real__7650863317510147349.mp4").write_bytes(b"x")
    src = root / "app" / "frontend" / "src" / "services"
    src.mkdir(parents=True)
    (src / "api.js").write_text(
        "const CARD = '%s';\n"
        "const OTHER = '%s';\n"
        "const GHOST = '%s';\n"
        "export const stagedReplacements = {\n"
        "  '%s': '%s',\n"
        "  '%s': '/assets/real_videos/does_not_exist.mp4',\n"
        "};\n" % (_REMAPPED, _ORPHAN, _GHOSTKEY, _REMAPPED, remap_target, _GHOSTKEY),
        encoding="utf-8")
    return root / "app"


def _rows(app):
    return {r.split(" (referenced by ")[0]: r for r in det(app)}


class TheRemapIsNamed(unittest.TestCase):
    def test_a_remapped_row_says_so_and_names_the_target(self):
        with tempfile.TemporaryDirectory() as d:
            row = _rows(_tree(Path(d)))[_REMAPPED]
            self.assertIn("ALREADY REMAPS", row)
            self.assertIn(_STAGED, row)

    def test_it_carries_the_1203m3_caveat(self):
        """A mapping existing does not prove every caller goes through it."""
        with tempfile.TemporaryDirectory() as d:
            row = _rows(_tree(Path(d)))[_REMAPPED]
            self.assertIn("does not prove every caller goes through it", row)

    def test_the_row_is_annotated_not_dropped(self):
        """Dropping is the direction that masks a failure."""
        with tempfile.TemporaryDirectory() as d:
            self.assertIn(_REMAPPED, _rows(_tree(Path(d))))


class TheOtherRowsAreLeftAlone(unittest.TestCase):
    def test_a_reference_with_no_remap_is_not_annotated(self):
        with tempfile.TemporaryDirectory() as d:
            row = _rows(_tree(Path(d)))[_ORPHAN]
            self.assertNotIn("ALREADY REMAPS", row)

    def test_a_remap_whose_target_is_absent_is_not_annotated(self):
        """#1203m3's tight predicate: the VALUE has to resolve on disk. 'Appears as a key'
        alone would overmatch, and annotating a mapping that points nowhere would soften a
        row that is a genuine 404 twice over."""
        with tempfile.TemporaryDirectory() as d:
            row = _rows(_tree(Path(d)))[_GHOSTKEY]
            self.assertNotIn("ALREADY REMAPS", row)

    def test_a_remap_to_a_file_that_is_also_missing_keeps_the_row_plain(self):
        with tempfile.TemporaryDirectory() as d:
            app = _tree(Path(d), remap_target="/assets/real_videos/nope.mp4")
            self.assertNotIn("ALREADY REMAPS", _rows(app)[_REMAPPED])


class AFailedLookupSaysSoRatherThanReadingClean(unittest.TestCase):
    """#883 -- an empty default here would mean "no remap exists", and the ratchet failed the
    first draft of this patch for exactly that. The third state is `None`, and every row has
    to carry it: an unanswered question must not look like a confirmed 404."""

    def setUp(self):
        from env_generator.llm_generator.multi_agent.runtime import frontend_scaffold as FS
        self._real = FS.remapped_seed_media_1203m3

        def boom(*a, **k):
            raise RuntimeError("remap reader exploded")

        FS.remapped_seed_media_1203m3 = boom
        self._FS = FS

    def tearDown(self):
        self._FS.remapped_seed_media_1203m3 = self._real

    def test_every_row_says_the_question_was_not_answered(self):
        with tempfile.TemporaryDirectory() as d:
            rows = _rows(_tree(Path(d)))
            self.assertTrue(rows)
            for ref, row in rows.items():
                with self.subTest(ref=ref):
                    self.assertIn("could NOT check whether the frontend remaps this", row)
                    self.assertIn("UNCONFIRMED", row)

    def test_no_row_claims_a_remap_it_could_not_read(self):
        with tempfile.TemporaryDirectory() as d:
            for row in _rows(_tree(Path(d))).values():
                self.assertNotIn("ALREADY REMAPS", row)

    def test_the_rows_are_still_produced(self):
        """Fail-closed on the annotation, never on the finding."""
        with tempfile.TemporaryDirectory() as d:
            self.assertIn(_REMAPPED, _rows(_tree(Path(d))))


class TheInventoryStillTravels(unittest.TestCase):
    """#1203gi's three-example inventory is what makes the row actionable; the annotation is
    added beside it, never instead of it."""

    def test_both_halves_are_in_the_annotated_row(self):
        with tempfile.TemporaryDirectory() as d:
            row = _rows(_tree(Path(d)))[_REMAPPED]
            self.assertIn("real .mp4 exist under", row)
            self.assertIn("ALREADY REMAPS", row)

    def test_the_referencing_file_is_still_named(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIn("referenced by api.js", _rows(_tree(Path(d)))[_REMAPPED])


class TheConsumerOffersTheThirdFix(unittest.TestCase):
    """"Add the file or stop referencing it" named two fixes while 38% of rows had taken a
    third. Read the emitted strings of the scaffolder block, docstring excluded."""

    def _warning_text(self):
        import ast
        tree = ast.parse(inspect.getsource(SC))
        best = None
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            if "#1203g9 %d asset path(s)" in node.value:
                best = node.value
        self.assertIsNotNone(best, "the #1203g9 warning string is gone")
        return best

    def test_it_names_the_remap_option(self):
        self.assertIn("remap it to one that IS staged", self._warning_text())

    def test_it_keeps_the_two_it_already_had(self):
        t = self._warning_text()
        self.assertIn("Add the file", t)
        self.assertIn("stop referencing it", t)

    def test_it_tells_the_reader_what_the_annotation_means(self):
        self.assertIn("ALREADY REMAPS", self._warning_text())


class WhatTheCorpusSays(unittest.TestCase):
    """The measurement the change rests on. Skips where the tree is absent."""

    @classmethod
    def setUpClass(cls):
        cls.corpus = Path(__file__).resolve().parents[2] / "generated"
        if not cls.corpus.is_dir():
            raise unittest.SkipTest("no generated/ corpus on this machine")

    def test_some_rows_are_annotated_and_some_are_not(self):
        """Non-vacuity in both directions: an annotation that fired on everything, or on
        nothing, would pass the unit tests above and still be wrong about the corpus."""
        ann = plain = 0
        for app in sorted(self.corpus.glob("*/app")):
            for r in det(app):
                if "ALREADY REMAPS" in r:
                    ann += 1
                else:
                    plain += 1
        if ann + plain == 0:
            self.skipTest("no rows on this disk")
        self.assertGreater(ann, 0, "nothing is annotated -- the remap lookup is not running")
        self.assertGreater(plain, 0, "everything is annotated -- the predicate is too loose")

    def test_the_googlemaps_icons_stay_unannotated(self):
        """The negative control that matters: those missing icons are real 404s with no
        remap, and softening them is the failure this must not cause."""
        for app in sorted(self.corpus.glob("googlemaps*/app")):
            rows = [r for r in det(app) if "/assets/icons/" in r]
            if not rows:
                continue
            with self.subTest(run=app.parent.name):
                self.assertFalse([r for r in rows if "ALREADY REMAPS" in r])


if __name__ == "__main__":
    unittest.main()
