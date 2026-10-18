r"""#1203nm: the DDL creates `"metadata.visibility"`, and the detector's `\w+` cannot see a dot.

`ddl_behind_models_1202xk` answers "which columns does models.py map that the init DDL never
creates". It read each CREATE TABLE body line with ``[\"']?(\w+)[\"']?\s+\S``, which fails
outright on

        "metadata.visibility" TEXT

-- `(\w+)` stops at the dot and the next character is not whitespace. So the column was missing
from the DDL's set while models.py maps it (#216 keeps the DB name in the `Column()` first
argument: `metadata_visibility = Column('metadata.visibility', String)`), and the detector
reported a column THE DDL CREATES as one the DDL never creates.

MEASURED, both ends:
  * SOURCE -- 3 lines. Of the corpus's 9,578 CREATE TABLE body lines, 294 did not parse: 291
    SQL comments (not columns, and they must stay unparsed) and exactly 3 quoted dotted names
    (tiktok-web-r166 ×2, tiktok-web-r180 ×1).
  * CONSEQUENCE -- 66% of a ledger. `metadata.visibility` is reported 175 times and 122 of
    `logs/ddl_behind_models_1202xk.jsonl`'s 185 lines report nothing else, because the detector
    re-runs on every scaffold pass.
  * NON-REGRESSION -- old and new verdicts differ on those 3 lines and agree on the other
    9,575; the delivered sweep goes 4 affected runs → 2, and the 2 are googlemaps-r16 and
    tiktok-web-r107, the pair the function's own docstring names.

Found by reading r190's `ddl_behind_models_1202xk.jsonl` (53 lines) while asking whether
#1203nd's "the database was older than these models" condition fires for real. It does -- and
the loudest thing in its ledger was this.
"""
import json
import tempfile
import unittest
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime.database_scaffold import (
    ddl_behind_models_1202xk,
    ddl_column_name_1203nm,
)


class TheDottedNameIsReadNow(unittest.TestCase):
    def test_the_corpus_shape(self):
        self.assertEqual(ddl_column_name_1203nm('"metadata.visibility" TEXT'),
                         "metadata.visibility")

    def test_a_single_quoted_dotted_name(self):
        self.assertEqual(ddl_column_name_1203nm("'a.b' INTEGER"), "a.b")

    def test_more_than_one_dot(self):
        self.assertEqual(ddl_column_name_1203nm('"a.b.c" TEXT'), "a.b.c")


class EveryShapeThatAlreadyWorkedStillDoes(unittest.TestCase):
    def test_a_bare_name(self):
        self.assertEqual(ddl_column_name_1203nm("user_id INTEGER NOT NULL"), "user_id")

    def test_a_quoted_plain_name(self):
        self.assertEqual(ddl_column_name_1203nm('"name" TEXT'), "name")

    def test_the_name_is_lowercased(self):
        self.assertEqual(ddl_column_name_1203nm('"Metadata.Visibility" TEXT'),
                         "metadata.visibility")
        self.assertEqual(ddl_column_name_1203nm("Created_At TIMESTAMP"), "created_at")

    def test_a_serial_pk(self):
        self.assertEqual(ddl_column_name_1203nm('"id" SERIAL PRIMARY KEY'), "id")


class ItStillRefusesWhatIsNotAColumn(unittest.TestCase):
    """291 of the 294 lines the old pattern could not parse are SQL comments. A fix that made
    them parse would trade 3 false negatives for 291 false positives."""

    def test_a_sql_comment(self):
        self.assertEqual(ddl_column_name_1203nm("-- the lane wrote this table by hand"), "")

    def test_a_comment_that_mentions_a_column(self):
        self.assertEqual(ddl_column_name_1203nm("-- metadata.visibility is a JSON path"), "")

    def test_an_unbalanced_quote(self):
        """The old pattern's optional quotes let `\"name` match with no closing quote."""
        self.assertEqual(ddl_column_name_1203nm('"metadata.visibility TEXT'), "")

    def test_a_name_with_no_type_on_the_line(self):
        self.assertEqual(ddl_column_name_1203nm('"metadata.visibility"'), "")
        self.assertEqual(ddl_column_name_1203nm("user_id"), "")

    def test_empty_and_none(self):
        self.assertEqual(ddl_column_name_1203nm(""), "")
        self.assertEqual(ddl_column_name_1203nm(None), "")


def _tree(root: Path, ddl: str, models: str) -> Path:
    (root / "app" / "backend").mkdir(parents=True)
    (root / "app" / "database" / "init").mkdir(parents=True)
    (root / "app" / "database" / "init" / "01_init.sql").write_text(ddl, encoding="utf-8")
    (root / "app" / "backend" / "models.py").write_text(models, encoding="utf-8")
    return root


_DDL_WITH_DOT = '''CREATE TABLE videos (
    "id" SERIAL PRIMARY KEY,
    "title" TEXT,
    -- the lane flattened a JSON path into a column name
    "metadata.visibility" TEXT
);
'''

_MODELS_WITH_DOT = '''from sqlalchemy import Column, Integer, String


class Video(Base):
    __tablename__ = "videos"
    id = Column(Integer, primary_key=True)
    title = Column(String)
    metadata_visibility = Column('metadata.visibility', String)
'''


class TheDetectorEndToEnd(unittest.TestCase):
    def test_a_dotted_column_the_ddl_creates_is_no_longer_reported(self):
        with tempfile.TemporaryDirectory() as d:
            root = _tree(Path(d), _DDL_WITH_DOT, _MODELS_WITH_DOT)
            self.assertEqual(ddl_behind_models_1202xk(root), [])

    def test_a_column_the_ddl_really_lacks_is_still_reported(self):
        """Non-regression, and non-vacuity for the test above: the same tree minus the DDL
        line must still fire, or the assertion above would pass for the wrong reason."""
        with tempfile.TemporaryDirectory() as d:
            ddl = _DDL_WITH_DOT.replace('    "metadata.visibility" TEXT\n', '')
            ddl = ddl.replace('"title" TEXT,', '"title" TEXT')
            root = _tree(Path(d), ddl, _MODELS_WITH_DOT)
            got = ddl_behind_models_1202xk(root)
            self.assertEqual(got, ["videos: metadata.visibility"])

    def test_the_comment_line_is_not_read_as_a_column(self):
        """If the comment parsed, the DDL set would gain a phantom and a REAL missing column
        could be masked by it. Drive it from the models side: a model mapping only the two
        real columns must report nothing, and one mapping a third must report exactly that."""
        with tempfile.TemporaryDirectory() as d:
            models = _MODELS_WITH_DOT.replace(
                "    metadata_visibility = Column('metadata.visibility', String)\n",
                "    metadata_visibility = Column('metadata.visibility', String)\n"
                "    caption = Column(String)\n")
            root = _tree(Path(d), _DDL_WITH_DOT, models)
            self.assertEqual(ddl_behind_models_1202xk(root), ["videos: caption"])


class TheTableNameAndTheAlterAreDeliberatelyUnchanged(unittest.TestCase):
    """#647 -- the same `\\w+` sits in the CREATE TABLE table name and the ALTER ... ADD COLUMN
    pattern, and the corpus has 0 dotted table names and 0 dotted names among 532
    ALTER ... ADD COLUMN statements. Asserted as BEHAVIOUR, not as a source literal (#943): a
    dotted table name must land in the silent "a table the DDL never creates at all is a
    different class" branch rather than being reported as a wholly-missing table."""

    def test_a_dotted_table_name_is_skipped_not_reported(self):
        ddl = 'CREATE TABLE "public.videos" (\n    "id" SERIAL PRIMARY KEY\n);\n'
        models = ('class Video(Base):\n'
                  '    __tablename__ = "public.videos"\n'
                  '    id = Column(Integer, primary_key=True)\n'
                  '    title = Column(String)\n')
        with tempfile.TemporaryDirectory() as d:
            root = _tree(Path(d), ddl, models)
            self.assertEqual(ddl_behind_models_1202xk(root), [])

    def test_an_alter_add_column_still_counts_as_created(self):
        ddl = (_DDL_WITH_DOT
               + 'ALTER TABLE videos ADD COLUMN IF NOT EXISTS caption TEXT;\n')
        models = _MODELS_WITH_DOT.replace(
            "    metadata_visibility = Column('metadata.visibility', String)\n",
            "    metadata_visibility = Column('metadata.visibility', String)\n"
            "    caption = Column(String)\n")
        with tempfile.TemporaryDirectory() as d:
            root = _tree(Path(d), ddl, models)
            self.assertEqual(ddl_behind_models_1202xk(root), [])


class WhatTheCorpusSays(unittest.TestCase):
    """The measurements the docstring rests on, re-run against the tree if it is here. These
    skip rather than fail on a machine without `generated/` -- the unit tests above carry the
    contract."""

    @classmethod
    def setUpClass(cls):
        cls.corpus = Path(__file__).resolve().parents[2] / "generated"
        if not cls.corpus.is_dir():
            raise unittest.SkipTest("no generated/ corpus on this machine")

    def test_no_run_reports_a_dotted_column_any_more(self):
        offenders = []
        for d in sorted(self.corpus.glob("*/")):
            for row in ddl_behind_models_1202xk(d):
                if ":" in row and "." in row.split(":", 1)[1]:
                    offenders.append((d.name, row))
        self.assertEqual(offenders, [])

    def test_the_two_genuinely_affected_runs_still_report(self):
        """The real signal, preserved. Each is skipped if that run is no longer on disk."""
        for run, want_substr in (("googlemaps-r16", "places:"),
                                 ("tiktok-web-r107", "videos: metadata")):
            d = self.corpus / run
            if not (d / "app" / "backend" / "models.py").is_file():
                continue
            with self.subTest(run=run):
                rows = ddl_behind_models_1202xk(d)
                self.assertTrue(any(want_substr in r for r in rows),
                                "%s stopped reporting: %r" % (run, rows))

    def test_the_ledger_this_came_from_is_real(self):
        """Non-vacuity for the 66% claim: the ledger exists and its dominant entry was the
        dotted name. Reads the recorded lines, which the fix does not rewrite."""
        dotted = total = 0
        for f in self.corpus.glob("*/logs/ddl_behind_models_1202xk.jsonl"):
            for ln in f.read_text(encoding="utf-8", errors="ignore").splitlines():
                try:
                    row = json.loads(ln)
                except Exception:
                    continue
                cols = []
                for t in row.get("tables") or []:
                    if ":" in t:
                        cols += [c.strip() for c in t.split(":", 1)[1].split(";")]
                if not cols:
                    continue
                total += 1
                if all("." in c for c in cols):
                    dotted += 1
        if not total:
            self.skipTest("no ledger lines recorded in this corpus")
        self.assertGreater(dotted * 2, total,
                           "the dotted name was not the ledger's dominant entry: "
                           "%d of %d" % (dotted, total))


if __name__ == "__main__":
    unittest.main()
