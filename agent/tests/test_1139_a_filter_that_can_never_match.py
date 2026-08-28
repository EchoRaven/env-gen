"""#1139: r8 delivered an endpoint whose filter cannot match a single seeded row.

netflix-local-r8 delivered release 1.0.0 on the DEFAULT budget, boots, authenticates, and
serves 24 real rows on /api/titles/trending and /api/search. `/api/titles/top10` returns an
empty collection forever:

    custom_routes.py:125   SELECT ... FROM titles t WHERE t.top10_rank IS NOT NULL ...
    models.py:62           top10_rank = Column(Text)
    effective seed         no row carries a top10_rank value at all

Measured live on one token: trending 24 rows, search 24 rows, top10 0 rows.

DELIBERATELY NOT "the response was empty". `/api/my-list` is empty for a freshly registered
user and is not a defect — it filters by `user_id`, so it is never reported here. What is
reported is a filter no seeded row could satisfy, which nothing ships on purpose. That
narrowness is what makes it safe to state as fact, and it is EVIDENCE, not a verdict (#1023):
returned in the gate result and logged, never added to `failed_checks`.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from multi_agent.runtime.delivery_gate import never_matching_filters_1139 as detect  # noqa: E402

TOP10_ROUTE = '''
from sqlalchemy import text
@router.get("/api/titles/top10")
def list_top10_titles(db=None, user=None):
    rows = db.execute(text("""
        SELECT to_jsonb(t) AS item FROM titles t
        WHERE t.top10_rank IS NOT NULL
        ORDER BY t.top10_rank ASC LIMIT 10
    """)).mappings().all()
    return {"items": [dict(r["item"]) for r in rows]}
'''

MYLIST_ROUTE = '''
@router.get("/api/my-list")
def list_my_list(db=None, user=None):
    user_id = _current_user_id(user)
    return {"items": db.query(MyList).filter(MyList.user_id == user_id).all()}
'''


def _project(routes: str, seed: dict, dataset: dict | None = None):
    root = Path(tempfile.mkdtemp())
    be = root / "app" / "backend"
    be.mkdir(parents=True)
    (be / "custom_routes.py").write_text(routes, encoding="utf-8")
    (be / "seed_data.json").write_text(json.dumps(seed), encoding="utf-8")
    if dataset is not None:
        (be / "seed_dataset.json").write_text(json.dumps(dataset), encoding="utf-8")
    return str(root)


class TheR8Defect(unittest.TestCase):

    def test_a_filter_no_seeded_row_can_satisfy_is_reported(self):
        p = _project(TOP10_ROUTE, {"users": [{"id": 1}]},
                     {"titles": [{"id": 1, "name": "Backrooms"}]})
        hits = detect(p)
        self.assertEqual([h["column"] for h in hits], ["top10_rank"])
        self.assertIn("cannot match", hits[0]["detail"])

    def test_it_goes_quiet_once_the_column_is_seeded(self):
        p = _project(TOP10_ROUTE, {"users": [{"id": 1}]},
                     {"titles": [{"id": 1, "name": "Backrooms", "top10_rank": "1"}]})
        self.assertEqual(detect(p), [])

    def test_a_column_present_but_empty_everywhere_still_counts(self):
        p = _project(TOP10_ROUTE, {"users": [{"id": 1}]},
                     {"titles": [{"id": 1, "top10_rank": None},
                                 {"id": 2, "top10_rank": ""}]})
        self.assertEqual([h["column"] for h in detect(p)], ["top10_rank"])


class ItMustNotCryWolf(unittest.TestCase):
    """A finding that fires on a legitimately-empty collection would be worse than silence."""

    def test_a_user_scoped_route_is_never_reported(self):
        """/api/my-list is empty for a new user and is NOT a defect."""
        p = _project(MYLIST_ROUTE, {"users": [{"id": 1}]})
        self.assertEqual(detect(p), [])

    def test_no_seed_at_all_says_nothing(self):
        """Nothing to judge against — silence, not a guess."""
        p = _project(TOP10_ROUTE, {})
        self.assertEqual(detect(p), [])

    def test_a_missing_backend_says_nothing(self):
        self.assertEqual(detect(tempfile.mkdtemp()), [])
        self.assertEqual(detect(None), [])
        self.assertEqual(detect("/no/such/path"), [])


class ItIsEvidenceNotAVerdict(unittest.TestCase):

    def test_the_gate_reports_it_without_blocking(self):
        src = (ROOT / "env_generator" / "llm_generator" / "multi_agent" / "runtime"
               / "delivery_gate.py").read_text(encoding="utf-8")
        self.assertIn('"never_matching_filters": never_matching_filters_1139(', src)
        # Exact, and no fixed-size source slice (#943): collect every check name the gate
        # ever appends and assert this one is not among them.
        import re as _re
        appended = _re.findall(r'failed_checks\.append\(\s*"([^"]+)"', src)
        self.assertTrue(appended, "sanity: the gate does append check names")
        self.assertNotIn("never_matching_filters", appended)


if __name__ == "__main__":
    unittest.main()
