"""FIX #214 — the route_projector's read serializer must not assume a ``*_at``
column holds a datetime; a STRING value must pass through, not 500.

r16 live: GET /api/messages 500'd —
``main.py:468 in <listcomp> AttributeError: 'str' object has no attribute
'isoformat'``. The projected read serialized ``r.created_at.isoformat()`` guarded
only by truthiness, but ``created_at`` was a STRING (the value arrived/stored as
text), so ``.isoformat()`` blew up → every call to that projected read 500'd →
business_chain + ui_flow could never pass → delivery churned to the wall. The
lane's own hand-written handler already guarded with ``isinstance(x, str)``; the
projected one must be equally defensive. Env-agnostic: any projected read over a
datetime column whose value is a string (TEXT column, pre-serialized seed, etc.).
"""

import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.route_projector import _serialize_expr  # noqa: E402


class _Row:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _eval(cols, row):
    expr = _serialize_expr("r", cols)
    return eval(expr, {"r": row})  # noqa: S307 - controlled test input


def test_string_created_at_passes_through_no_crash():
    # THE r16 bug: created_at is a str → must NOT raise, must return the string.
    out = _eval(["id", "created_at"], _Row(id=1, created_at="2026-07-18T00:00:00"))
    assert out["created_at"] == "2026-07-18T00:00:00"


def test_datetime_created_at_is_isoformatted():
    dt = datetime(2026, 7, 18, 12, 30, 0)
    out = _eval(["id", "created_at"], _Row(id=1, created_at=dt))
    assert out["created_at"] == dt.isoformat()


def test_none_at_is_none():
    out = _eval(["updated_at"], _Row(updated_at=None))
    assert out["updated_at"] is None


def test_non_at_columns_untouched():
    out = _eval(["id", "text"], _Row(id=7, text="hello"))
    assert out == {"id": 7, "text": "hello"}


def test_password_hash_never_serialized():
    out = _eval(["id", "password_hash"], _Row(id=1, password_hash="secret"))
    assert "password_hash" not in out
