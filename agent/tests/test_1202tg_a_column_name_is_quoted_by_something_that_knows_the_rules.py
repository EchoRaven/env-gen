r"""#1202tg: a column name becomes a Python string literal, so it must be quoted properly.

`_serialize_expr` builds the dict literal every projected read returns. It interpolated the
column name RAW into three places — the dict key, the `getattr` argument, and (for `*_at`) a
real attribute access. Found by rendering the skeleton over adversarial contracts, which is
the same codegen stress-audit that produced FIX #214 and FIX #216 for this generator.

Two failures, and the second is the worse one:

    a"b      -> `"a"b": getattr(r, "a"b", None)`   SyntaxError. The app never imports.
    a-b_at   -> `r.a-b_at.isoformat()`             PARSES, and is a SUBTRACTION. NameError at
                                                   request time, so the projected read 500s —
                                                   precisely the outcome FIX #214 exists to
                                                   stop, reached by another road.

`json.dumps` emits a valid Python string literal for any `str`, and the `_at` branch now uses
`getattr` throughout, so no identifier is required anywhere.

HOW LIKELY: the corpus carries 2,009 table/column names, of which 3 are non-identifiers —
`suggested-creators`, `continue-watching` (twice), all TABLE names, no quotes. So this is
hardening, not a live incident, and it is recorded as such. It is worth doing because nothing
upstream validates the name and the cost of being wrong is total: a backend that cannot be
imported, or a read that 500s on every call.

WHAT MUST NOT CHANGE: FIX #214's properties. A `*_at` that holds a string passes through, a
missing attribute yields None rather than raising, and `password_hash` is never serialised.

LOCAL-ONLY (gitignored)."""
from __future__ import annotations

import ast
import datetime
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.runtime.route_projector import _serialize_expr  # noqa: E402


def _eval(expr, row):
    return eval(expr, {"getattr": getattr, "hasattr": hasattr}, {"r": row})


class _Row:
    pass


@pytest.mark.parametrize("cols", [
    [],
    ["id"],
    ["id", "title"],
    ["id", "created_at"],
    ["id", "a-b"],                 # the shape the corpus actually has, one level down
    ["id", 'a"b'],                 # SyntaxError before this fix
    ["id", "a-b_at"],              # parsed as a subtraction before this fix
    ["id", "class"],
    ["id", "a'b"],
    ["id", "a\\b"],
    ["id", "naïve_at"],
])
def test_every_name_yields_valid_python(cols):
    ast.parse("x = " + _serialize_expr("r", cols))


def test_the_quote_case_round_trips_to_the_right_key():
    row = _Row()
    setattr(row, 'a"b', 7)
    row.id = 1
    got = _eval(_serialize_expr("r", ["id", 'a"b']), row)
    assert got == {"id": 1, 'a"b': 7}


def test_the_dashed_at_column_reads_rather_than_subtracts():
    """`r.a-b_at` parsed fine and computed the wrong thing. The value must come back."""
    row = _Row()
    row.id = 1
    setattr(row, "a-b_at", datetime.datetime(2026, 9, 23, 1, 2, 3))
    got = _eval(_serialize_expr("r", ["id", "a-b_at"]), row)
    assert got["a-b_at"] == "2026-09-23T01:02:03"


def test_fix_214_still_holds_a_string_passes_through():
    row = _Row()
    row.id = 1
    row.created_at = "already a string"
    got = _eval(_serialize_expr("r", ["id", "created_at"]), row)
    assert got["created_at"] == "already a string"


def test_a_datetime_is_still_isoformatted():
    row = _Row()
    row.id = 1
    row.created_at = datetime.datetime(2026, 9, 23, 1, 2, 3)
    got = _eval(_serialize_expr("r", ["id", "created_at"]), row)
    assert got["created_at"] == "2026-09-23T01:02:03"


def test_a_missing_attribute_is_none_not_an_error():
    row = _Row()
    row.id = 1
    got = _eval(_serialize_expr("r", ["id", "title"]), row)
    assert got["title"] is None


def test_password_hash_is_still_never_serialised():
    expr = _serialize_expr("r", ["id", "password_hash", "title"])
    assert "password_hash" not in expr


def test_the_name_is_not_interpolated_raw_any_more():
    """The rule, not the instance: a bare `"{c}"` in this function is how it comes back."""
    import inspect
    src = inspect.getsource(_serialize_expr)
    body = src[src.index("parts = []"):]
    assert '"{c}"' not in body, "the column name is being interpolated raw again"
    assert "{_lit}" in body
