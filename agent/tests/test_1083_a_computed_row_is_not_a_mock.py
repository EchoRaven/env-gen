'''#1083 — "a list containing a dict literal" is not the same as "hardcoded mock rows".

#173's mock-row rule flags any `[{...}]` return. Its own docstring says what it means by that:

    a list whose elements include a dict/object literal (hardcoded MOCK rows —
    [{"id": "dep_1", "line": "A"}])

Every value in that example is a CONSTANT. The implementation never checked, so a COMPUTED
row matched too. gmrun7 (`2of3-forcedeliver`) ships:

    dist = math.sqrt(...) * 111
    duration_mins = int(dist * 10) if mode == "transit" else int(dist * 5)
    return {"items": [{"mode": mode, "distance_km": round(dist, 2),
                       "duration_mins": duration_mins,
                       "steps": [{"instruction": f"Head towards destination using {mode}", ...}]}],
            "total": 1}

Nothing there is hardcoded — every field derives from the query parameters — and directions
are COMPUTED, so "query the real seeded table(s)" is advice the endpoint cannot take. It is a
HARD blocker (`deliverability_placeholder_stub_handler`, 726 occurrences across 201 run logs)
on a correct handler, in a run that had to be force-delivered.

Measured across the 83 generated backends: of the returns carrying a dict literal inside a
list, **87 have at least one dynamic value and 5 are entirely constant**. The premise "dict
literal ⇒ hardcoded" is wrong far more often than right here. Requiring the rows to be
constant makes the rule strictly NARROWER — the 5 genuine fixtures still flag, and exactly
one of the corpus's four current blockers changes: the false one.
'''
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import mkdtemp

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime.backend_audit import stub_handler_blockers  # noqa: E402

_HEAD = """from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
import math
from database import get_db
router = APIRouter()
"""

_COMPUTED = '''
@router.get("/api/directions")
def get_directions(origin_lat: float = Query(0.0), dest_lat: float = Query(0.0),
                   mode: str = Query("transit"), db: Session = Depends(get_db)):
    dist = math.sqrt((dest_lat - origin_lat) ** 2) * 111
    duration_mins = int(dist * 10) if mode == "transit" else int(dist * 5)
    return {"items": [{"mode": mode, "distance_km": round(dist, 2),
                       "duration_mins": duration_mins,
                       "steps": [{"instruction": f"Head towards destination using {mode}",
                                  "distance_km": round(dist, 2)}]}],
            "total": 1}
'''

_MOCK = '''
@router.get("/api/transit/departures")
def get_departures(db: Session = Depends(get_db)):
    return {"items": [{"id": "dep_1", "line": "A", "time": "5 min"},
                      {"id": "dep_2", "line": "B", "time": "9 min"}]}
'''

_EMPTY = '''
@router.get("/api/messages")
def get_messages(db: Session = Depends(get_db)):
    return {"items": []}
'''

_REAL = '''
@router.get("/api/stops")
def get_stops(db: Session = Depends(get_db)):
    rows = db.execute(text("SELECT * FROM stops")).mappings().all()
    return {"items": [dict(r) for r in rows]}
'''


def _backend(body: str) -> Path:
    root = Path(mkdtemp())
    be = root / "backend"
    be.mkdir()
    (be / "custom_routes.py").write_text(_HEAD + body, encoding="utf-8")
    return root


class AComputedRowIsNotAMock(unittest.TestCase):

    def test_gmrun7_directions_is_not_a_placeholder(self):
        self.assertEqual(stub_handler_blockers(_backend(_COMPUTED)), [])


class TheGenuineStubsStillBlock(unittest.TestCase):
    """Narrower, not weaker — the shapes #173 was built for are untouched."""

    def test_the_docstrings_own_mock_row_example_still_blocks(self):
        out = stub_handler_blockers(_backend(_MOCK))
        self.assertTrue(out, "hardcoded mock rows stopped blocking")
        self.assertIn("get_departures", out[0])

    def test_an_empty_collection_still_blocks(self):
        out = stub_handler_blockers(_backend(_EMPTY))
        self.assertTrue(out, "the classic {'items': []} stub stopped blocking")

    def test_a_db_reading_handler_never_blocked_and_still_does_not(self):
        self.assertEqual(stub_handler_blockers(_backend(_REAL)), [])


class TheRowPredicateItself(unittest.TestCase):

    def _p(self, expr: str) -> bool:
        import ast
        from multi_agent.runtime.backend_audit import _placeholder_collection_literal
        return _placeholder_collection_literal(ast.parse(expr, mode="eval").body)

    def test_constant_rows_are_placeholders(self):
        self.assertTrue(self._p('[{"id": "dep_1", "line": "A"}]'))
        self.assertTrue(self._p('{"items": [{"a": 1}]}'))
        self.assertTrue(self._p("[]"))
        self.assertTrue(self._p('{"items": []}'))

    def test_a_dynamic_value_anywhere_in_the_row_disqualifies_it(self):
        self.assertFalse(self._p('[{"mode": mode}]'))
        self.assertFalse(self._p('[{"d": round(dist, 2)}]'))
        self.assertFalse(self._p('[{"s": f"to {mode}"}]'))
        self.assertFalse(self._p('[{"nested": [{"i": instruction}]}]'))

    def test_a_dynamic_sibling_element_disqualifies_the_list(self):
        self.assertFalse(self._p('[{"a": 1}, extra_row]'))

    def test_scalar_and_comprehension_lists_are_still_not_placeholders(self):
        self.assertFalse(self._p('["driving", "walking"]'))
        self.assertFalse(self._p('{"items": [dict(r) for r in rows]}'))


if __name__ == "__main__":
    unittest.main()
