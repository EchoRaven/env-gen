"""#1202fj: chains must say whether the DATABASE is the one these models describe.

The compose file mounts app/database/init/01_init.sql at
/docker-entrypoint-initdb.d, and Postgres runs those scripts only on an EMPTY
volume -- with CREATE TABLE IF NOT EXISTS besides. So models that move after a
stack is up leave the live tables behind, and the projected handler, built from
the current models, SELECTs a column that does not exist:

    (psycopg.errors.UndefinedColumn) column "actor_name" does not exist

tiktok-r96 died on that twice. It reads as an application defect on a route
tagged FRAMEWORK-PROJECTED, and it sent me chasing a type-mismatch regression
that was not there (see the correction on a5030b03).

The drift is a WINDOW: measured directly against r96's live database right after
a `down -v && up`, models and schema agreed exactly.
"""
import sys
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent))
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

from multi_agent.runtime import seed_audit as sa  # noqa: E402

CE = (THIS_DIR.parent / "env_generator" / "llm_generator" / "multi_agent" / "runtime"
      / "chain_executor.py").read_text(encoding="utf-8")


class TestVerdict(unittest.TestCase):

    def setUp(self):
        self._live = sa.live_schema_1202fj
        self._models = None

    def tearDown(self):
        sa.live_schema_1202fj = self._live

    def _with(self, live, models, tmp=None):
        import types
        sa.live_schema_1202fj = lambda *a, **k: live
        d = Path(tmp or THIS_DIR)
        # a project dir with app/backend present, so the verdict reaches the model read
        import tempfile
        p = Path(tempfile.mkdtemp())
        (p / "app" / "backend").mkdir(parents=True)
        import multi_agent.runtime.route_projector as rp
        _orig = rp._orm_models
        rp._orm_models = lambda *a, **k: models
        try:
            return sa.schema_currency_1202fj(p)
        finally:
            rp._orm_models = _orig

    def test_a_matching_schema_is_current(self):
        got = self._with({"notifications": {"id", "user_id", "kind"}},
                         {"notifications": {"cols": ["id", "user_id", "kind"]}})
        self.assertEqual(got["verdict"], "current")

    def test_a_missing_column_is_drift_and_is_named(self):
        """The direction that 500s: models declare it, the live table lacks it."""
        got = self._with({"notifications": {"id", "user_id"}},
                         {"notifications": {"cols": ["id", "user_id", "actor_name"]}})
        self.assertEqual(got["verdict"], "drifted")
        self.assertIn("notifications.actor_name", got["detail"])
        self.assertIn("down -v", got["detail"])

    def test_extra_live_columns_are_not_drift(self):
        """A column the models dropped harms no read."""
        got = self._with({"notifications": {"id", "user_id", "legacy"}},
                         {"notifications": {"cols": ["id", "user_id"]}})
        self.assertEqual(got["verdict"], "current")

    def test_a_table_absent_entirely_is_not_this_check(self):
        """#952 owns declared-but-unmounted; this one owns column drift."""
        got = self._with({"other": {"id"}},
                         {"notifications": {"cols": ["id", "actor_name"]}})
        self.assertEqual(got["verdict"], "current")

    def test_an_unreadable_database_claims_neither_verdict(self):
        got = self._with({}, {"notifications": {"cols": ["id"]}})
        self.assertEqual(got["verdict"], "unknown")
        self.assertIn("could not be read", got["detail"])

    def test_it_never_raises(self):
        for bad in (None, 42, object()):
            self.assertIn(sa.schema_currency_1202fj(bad)["verdict"],
                          ("current", "drifted", "unknown"))


class TestWiring(unittest.TestCase):

    def test_it_is_measured_before_any_chain_is_judged(self):
        # Anchored on the ASSIGNMENT, not on how the callable is spelled: the import had
        # to become function-local (three tests compile this file standalone), which
        # renamed the call and broke a literal-matching version of this assertion.
        measured = CE.index("_schema_1202fj = _sc1202fj(project_dir)")
        judged = CE.index("results = [execute_chain(", measured - 6000)
        self.assertLess(measured, judged)

    def test_the_drift_reaches_the_list_the_lane_reads(self):
        """A verdict in a dict nothing reads is the shape #1202ex's wiring commit was about."""
        self.assertIn('broken.insert(0, "[schema currency #1202fj] "', CE)

    def test_it_leads_the_build_currency_line(self):
        """A missing column 500s every read of it -- louder than a maybe-stale image."""
        self.assertLess(CE.index('"[schema currency #1202fj] "'),
                        CE.index('"[build currency #1202ex] These verdicts'))

    def test_the_verdict_reaches_the_caller(self):
        self.assertIn('"schema_currency_1202fj": _schema_1202fj', CE)


if __name__ == "__main__":
    unittest.main()
