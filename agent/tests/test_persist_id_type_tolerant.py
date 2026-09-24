"""FIX #122 — the write-persist readback matches ids TYPE-TOLERANTLY
(instagram-core-di run-41 M4 STUCK, 2026-07-09 18:3x; run-35 same class).

POST /api/messages returned {"item":{"id":3}} (int); the lane's GET handler
stringifies every value ({"id":"3",...}) — live probe confirmed the row IS in
the readback. validation_runner's containment check used type-STRICT equality
(r.get("id") == new_id → "3" == 3 → False), so a correctly-persisting app was
reported 'write not persisted' and business_writes_persist wedged the run to the
STUCK wall. Ids must compare as strings (the platform already treats "8"/8 as
the same id everywhere else — chain placeholder substitution stringifies).
ENV-AGNOSTIC + LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.validation_runner import _id_in_rows  # noqa: E402


def test_string_id_matches_int_new_id():
    assert _id_in_rows(3, [{"id": "3", "content": "x"}]) is True     # run-41's exact shape


def test_int_id_matches_string_new_id():
    assert _id_in_rows("8", [{"id": 8}]) is True


def test_same_type_still_matches():
    assert _id_in_rows(5, [{"id": 5}]) is True
    assert _id_in_rows("a-b", [{"id": "a-b"}]) is True


def test_absent_id_still_fails():
    assert _id_in_rows(3, [{"id": "4"}, {"id": 5}]) is False
    assert _id_in_rows(3, []) is False
    assert _id_in_rows(3, [{"no_id": 1}, "not-a-dict"]) is False


def test_none_never_matches():
    assert _id_in_rows(None, [{"id": None}]) is False
