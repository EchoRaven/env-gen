r"""#1203nl: `#1203kz` reported a missing field without saying the run never asked for it.

`#1203b7` states the general rule in design_prep's own words: "34 corpus runs adopt a donor,
so every design-prep fix has this hole until it is closed HERE — at the copy, which is the one
place an inherited doc enters a run." The deterministic fixes DO close it — `#1203kv` (asset
fields), `#1203l0` (layout metrics, dataset), `#1203nh`/`#1203ni` (the measured components) all
run in `complete_design_system`, which runs on an adopted document.

ONE FIELD CANNOT BE CLOSED THAT WAY: `copy`. A verbatim string has to be read off the
reference image, which is the design_analyst's vision pass — and adoption's own log line says
it is "skipping the design_analyst spawn".

MEASURED:
  * 79 corpus logs carry the adoption line, and EVERY run from r178 to r191 adopted. The
    analyst was last actually spawned around r91-r95.
  * r185..r191's documents carry the SAME 35 components, with byte-identical (screen, id)
    pairs in r185, r189 and r191 — one historical rewrite, frozen and inherited.
  * `#1203kz`'s warning fires in 6 of 6 modern runs ("NOT ONE of 35 components carries a
    verbatim `copy` string"), which is TRUE and silent about the reason a reader needs.

So the warning now names it: the document was ADOPTED from <donor>, the analyst was not
spawned, no deterministic pass can fill `copy`, and `ENVGEN_DESIGN_PREP_REUSE=0` forces a real
one. Without that, a reader goes after a prompt that was never issued.
"""
import ast
import inspect
import json
import logging
import pathlib
import tempfile
import unittest

from env_generator.llm_generator.multi_agent.runtime.design_prep import (
    _ADOPTED_FROM_1203NL,
    _stamp_adopted_from_1203nl as stamp,
    adopt_design_prep_1202hj,
    adopted_from_1203nl as read_donor,
    complete_design_system,
)


class _Cap(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


class _Caught:
    def __enter__(self):
        self.log = logging.getLogger("Orchestrator")
        self.h = _Cap()
        self.old = self.log.level
        self.log.addHandler(self.h)
        self.log.setLevel(logging.WARNING)
        return self.h

    def __exit__(self, *a):
        self.log.removeHandler(self.h)
        self.log.setLevel(self.old)
        return False


def _ds():
    return {"screens": [{"name": "s", "components": [
        {"id": "c", "region": [0, 0, 1, 1], "colors": {"bg": "#000000"}}]}],
        "assets": [], "dataset": []}


class TheStampRoundTrips(unittest.TestCase):
    def test_it_records_and_reads_back(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(read_donor(d), "")
            stamp(d, "/data/x/generated/tiktok-web-r189")
            self.assertEqual(read_donor(d), "tiktok-web-r189")

    def test_it_records_the_run_NAME_not_the_path(self):
        with tempfile.TemporaryDirectory() as d:
            stamp(d, "/some/long/path/generated/netflix-local-r30")
            self.assertEqual(read_donor(d), "netflix-local-r30")

    def test_it_also_records_that_the_analyst_did_not_run(self):
        with tempfile.TemporaryDirectory() as d:
            stamp(d, "generated/tiktok-web-r189")
            rec = json.loads((pathlib.Path(d) / "design" / _ADOPTED_FROM_1203NL)
                             .read_text(encoding="utf-8"))
            self.assertIs(rec["analyst_spawned"], False)
            self.assertEqual(rec["donor"], "tiktok-web-r189")

    def test_an_unstamped_run_reads_empty(self):
        with tempfile.TemporaryDirectory() as d:
            (pathlib.Path(d) / "design").mkdir()
            self.assertEqual(read_donor(d), "")

    def test_unreadable_and_hostile_never_raise(self):
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "design"
            p.mkdir()
            (p / _ADOPTED_FROM_1203NL).write_text("{not json", encoding="utf-8")
            self.assertEqual(read_donor(d), "")
        for bad in ("/nonexistent", None, 7):
            with self.subTest(out=repr(bad)):
                self.assertEqual(read_donor(bad), "")
        for bad in (None, 7):
            with self.subTest(donor=repr(bad)):
                stamp("/nonexistent/also", bad)       # must not raise


class TheAdoptionStampsItself(unittest.TestCase):
    """#1139: the writer and the reader are both needed, and the write must be at the copy —
    #1203b7's "the one place an inherited doc enters a run"."""

    def test_adoption_calls_the_stamp(self):
        tree = ast.parse(inspect.getsource(adopt_design_prep_1202hj).lstrip())
        names = [n.func.id for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
        self.assertIn("_stamp_adopted_from_1203nl", names)

    def test_it_stamps_after_the_copy_and_the_scrub(self):
        src = inspect.getsource(adopt_design_prep_1202hj)
        self.assertLess(src.index("shutil.copy2"), src.index("_stamp_adopted_from_1203nl"))
        self.assertLess(src.index("_scrub_adopted_design_system_1203b7"),
                        src.index("_stamp_adopted_from_1203nl"))

    def test_a_real_adoption_stamps_the_donor(self):
        with tempfile.TemporaryDirectory() as donor, tempfile.TemporaryDirectory() as out:
            dd = pathlib.Path(donor) / "design"
            dd.mkdir(parents=True)
            (dd / "design_system.json").write_text(json.dumps(_ds()), encoding="utf-8")
            ok = adopt_design_prep_1202hj(donor, out, "x", {})
            self.assertTrue(ok)
            self.assertEqual(read_donor(out), pathlib.Path(donor).name)


class TheWarningNamesTheReason(unittest.TestCase):
    def _warn(self, adopted):
        with tempfile.TemporaryDirectory() as d:
            if adopted:
                stamp(d, "generated/tiktok-web-r189")
            with _Caught() as cap:
                complete_design_system(_ds(), {}, d)
            return [l for l in cap.lines if "NOT ONE of" in l]

    def test_an_adopted_document_says_the_run_never_asked(self):
        lines = self._warn(True)
        self.assertEqual(len(lines), 1, lines)
        self.assertIn("THIS RUN NEVER ASKED", lines[0])
        self.assertIn("tiktok-web-r189", lines[0])
        self.assertIn("design_analyst was not spawned", lines[0])

    def test_it_names_the_lever(self):
        self.assertIn("ENVGEN_DESIGN_PREP_REUSE=0", self._warn(True)[0])

    def test_it_says_no_deterministic_pass_can_fill_it(self):
        self.assertIn("no deterministic pass can fill it", self._warn(True)[0])

    def test_a_freshly_measured_document_gets_no_such_clause(self):
        lines = self._warn(False)
        self.assertEqual(len(lines), 1, lines)
        self.assertNotIn("THIS RUN NEVER ASKED", lines[0])
        self.assertNotIn("ADOPTED", lines[0])

    def test_the_original_sentence_survives_in_both_cases(self):
        for adopted in (False, True):
            with self.subTest(adopted=adopted):
                ln = self._warn(adopted)[0]
                self.assertIn("carries a verbatim `copy` string", ln)
                self.assertIn("#797", ln)
                self.assertIn("#1203kz", ln)


if __name__ == "__main__":
    unittest.main()
