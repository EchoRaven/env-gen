r"""#1202az: a contract table holding a primary key and nothing else, with data staged.

The projector is faithful — it materialises ORM + DDL from exactly what the contract
holds — so a table registered with only `id` becomes a one-column table, the staged rows
cannot land, and every consumer fails somewhere far from the cause.

netflix-r30 is the worked example and it cost the whole run:

    contract  titles = 1 column  ['id']          dataset: 60 rows x 12 fields
    r32       titles = 13 columns                same environment, two days later

    GET /api/genres/11/titles -> 404   x15, the id correctly SUBSTITUTED from the list
                                       endpoint — the lane derived genre names from title
                                       rows that had no genre column
    DELIVERY-GATE NO-CONVERGENCE ABORT after 148min, $930, nothing delivered

Not one of those symptoms names the cause, and the framework holds both halves the whole
time. 2 of 79 corpus runs carry it (r30 `titles`, tiktok-r81 `videos`) — rare, and each
one is a dead run.
"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

from multi_agent.runtime.backend_audit import (  # noqa: E402
    underspecified_tables_1202az)


def _cols(*names):
    return {"schema": {"columns": [{"name": n, "type": "text"} for n in names]}}


class UnderspecifiedTableTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="az1202_"))
        (self.root / "app" / "backend").mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def _dataset(self, obj):
        (self.root / "app" / "backend" / "seed_dataset.json").write_text(json.dumps(obj))

    def test_r30_shape_is_reported(self):
        self._dataset({"titles": [{"id": 1, "name": "A", "genre": "Drama",
                                   "kind": "movie", "year": "2020"}] * 60})
        found = underspecified_tables_1202az({"titles": _cols("id")}, self.root)
        self.assertEqual(len(found), 1)
        self.assertIn("titles", found[0])
        self.assertIn("60 staged row", found[0])

    def test_a_fully_registered_table_is_not_reported(self):
        """r32 is the control: same environment, same data, 13 columns, delivered."""
        self._dataset({"titles": [{"id": 1, "name": "A", "genre": "Drama"}] * 60})
        found = underspecified_tables_1202az(
            {"titles": _cols("id", "name", "genre")}, self.root)
        self.assertEqual(found, [])

    def test_a_single_column_table_with_no_staged_rows_is_not_a_finding(self):
        """Only the staged data can prove the table needs more than it declares.

        The dataset table here is `other` and the contract carries it, so #1202bf's
        missing-table branch stays quiet and this isolates the column property. The
        first version staged `other` WITHOUT contracting it, which #1202bf then
        correctly reported — the fixture, not the check, was ambiguous.
        """
        self._dataset({"other": [{"id": 1, "x": 2}]})
        self.assertEqual(
            underspecified_tables_1202az(
                {"titles": _cols("id"), "other": _cols("id", "x")}, self.root), [])

    def test_a_missing_dataset_is_not_an_error(self):
        self.assertEqual(
            underspecified_tables_1202az({"titles": _cols("id")}, self.root), [])

    def test_it_never_raises_on_junk(self):
        self._dataset({"titles": "not a list"})
        self.assertEqual(
            underspecified_tables_1202az({"titles": None}, self.root), [])


    def test_a_table_the_contract_does_not_have_at_all_is_reported(self):
        """#1202bf: the worse case, and invisible to the column check.

        That loop walks the CONTRACT, so a table the contract lacks entirely is never
        visited. tiktok-web-r46 and r83 each carry four contract tables — oauth_clients,
        oauth_authorization_codes, tenants, users, all framework infrastructure — and not
        one domain table, while the dataset holds 35 videos, 295 comments and 8 sounds.
        """
        self._dataset({"videos": [{"id": 1, "caption": "a"}] * 35,
                       "users": [{"id": 1}]})
        found = underspecified_tables_1202az({"users": _cols("id", "name")}, self.root)
        self.assertEqual(len(found), 1)
        self.assertIn("videos", found[0])
        self.assertIn("35 row", found[0])
        self.assertIn("NO such table", found[0])

    def test_a_dataset_table_that_the_contract_has_is_not_reported(self):
        """Non-vacuity for the new branch: presence in the contract is what clears it."""
        self._dataset({"videos": [{"id": 1, "caption": "a"}] * 35})
        self.assertEqual(
            underspecified_tables_1202az(
                {"videos": _cols("id", "caption")}, self.root), [])

    def test_an_empty_staged_table_is_not_a_finding(self):
        """Only staged ROWS prove the table is needed."""
        self._dataset({"videos": []})
        self.assertEqual(underspecified_tables_1202az({}, self.root), [])


if __name__ == "__main__":
    unittest.main()
