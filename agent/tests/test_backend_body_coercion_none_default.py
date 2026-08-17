"""#420 (netflix r14, live): an EXPLICIT None in a create body OVERRIDES the
column's DB default → NOT-NULL violation on INSERT. POST /api/my-list sent
created_at=None (a Pydantic optional field defaulting to None) →
'null value in column "created_at" violates not-null constraint', regressing
business_chain on re-validation despite DEFAULT now() in the DDL + server_default
on the ORM column. FIX: _coerce_body drops a None-valued key whose column can
supply its OWN value (server_default / Python default / autoincrement PK) so the
default/serial applies — the runtime twin of the #409 seed None-strip, on the
create/update handler path. A None for a column WITHOUT a default STAYS → the #411
IntegrityError handler 400s with the column name (not a silent drop).

Harness mirrors test_backend_body_coercion.py: extract the EMITTED _coerce_body
from the generated main.py and exercise it with fake columns that carry the
server_default/default/primary_key/autoincrement attributes real SQLAlchemy
columns have."""
import re

from sqlalchemy import Integer, String

from env_generator.llm_generator.multi_agent.runtime.backend_skeleton import render_skeleton_main

_TABLES = {
    "users": {"columns": [{"name": "id", "type": "integer", "primary_key": True}]},
    "titles": {"columns": [{"name": "id", "type": "integer", "primary_key": True}]},
    "my_list": {"columns": [
        {"name": "id", "type": "integer", "primary_key": True},
        {"name": "profile_id", "type": "integer", "fk": "users.id"},
        {"name": "title_id", "type": "integer", "fk": "titles.id"}]},
}
_EPS = [{"method": "POST", "path": "/api/my-list", "auth_required": True}]
_SRC = render_skeleton_main(_EPS, _TABLES)


def _coerce():
    m = re.search(r"\ndef _coerce_body\(cls, valid\):.*?\n    return out\n", _SRC, re.S)
    assert m, "could not extract _coerce_body from generated main.py"
    ns = {}
    exec(m.group(0), ns)
    return ns["_coerce_body"]


class _Col:
    def __init__(self, t, *, server_default=None, default=None,
                 primary_key=False, autoincrement=False):
        self.type = t
        self.server_default = server_default
        self.default = default
        self.primary_key = primary_key
        self.autoincrement = autoincrement


class _MyList:
    class __table__:
        columns = {
            # created_at: NOT-NULL timestamp with a DB default (the r14 bug column)
            "created_at": _Col(String(), server_default=object()),
            # serial PK
            "id": _Col(Integer(), primary_key=True, autoincrement=True),
            # a Python-side default column
            "status": _Col(String(), default="active"),
            # genuinely nullable optional — None is meaningful, keep it
            "note": _Col(String()),
            # required FK, no default — None must STAY (→ #411 400 with the column)
            "title_id": _Col(Integer()),
            # a normal typed field for the regression check
            "profile_id": _Col(Integer()),
        }


def test_none_stripped_when_column_has_server_default():
    out = _coerce()(_MyList, {"created_at": None, "profile_id": 3})
    assert "created_at" not in out, "None over a server_default column must be dropped"
    assert out["profile_id"] == 3


def test_none_stripped_for_autoincrement_pk():
    out = _coerce()(_MyList, {"id": None, "profile_id": 3})
    assert "id" not in out, "None over a serial PK must be dropped (let the sequence fill)"


def test_none_stripped_for_python_default():
    out = _coerce()(_MyList, {"status": None})
    assert "status" not in out


def test_none_kept_for_nullable_optional_no_default():
    out = _coerce()(_MyList, {"note": None})
    assert "note" in out and out["note"] is None, "a genuinely optional None is preserved"


def test_none_kept_for_required_no_default_column():
    # title_id is required (FK) with no default — keep None so the #411 IntegrityError
    # handler surfaces the column name, rather than silently dropping it.
    out = _coerce()(_MyList, {"title_id": None})
    assert "title_id" in out and out["title_id"] is None


def test_typed_coercion_still_works_alongside_none_strip():
    out = _coerce()(_MyList, {"created_at": None, "profile_id": "5"})
    assert "created_at" not in out
    assert out["profile_id"] == 5  # numeric string → int, unaffected by the None pass


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
