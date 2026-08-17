"""Audit rank-4 (complete _coerce_body + global DataError->400): extends the #395 create-only
scalar coercion. (a) Boolean columns now coerce a bool-ish string ("true"/"1"/"on" ...) or
1/0 to a real bool; (b) coercion runs up-front so it covers PUT/PATCH updates too, not just
create; (c) a value that STILL can't fit the column type (a bad datetime) is re-raised as
DataError from the write handler and mapped to 400 by a global handler — instead of the
catch-all 500 that lands in no chain's expect list and wedges business_chain.
"""
import re

from sqlalchemy import Boolean, Integer, Numeric, String

from env_generator.llm_generator.multi_agent.runtime.backend_skeleton import render_skeleton_main
from env_generator.llm_generator.multi_agent.runtime.backend_scaffold import _INTEGRITY_HANDLER

_TABLES = {
    "users": {"columns": [
        {"name": "id", "type": "integer", "primary_key": True},
        {"name": "is_active", "type": "boolean not null"}]},
    "ratings": {"columns": [
        {"name": "id", "type": "integer", "primary_key": True},
        {"name": "value", "type": "integer not null"},
        {"name": "liked", "type": "boolean"},
        {"name": "watched_at", "type": "timestamp"}]},
}
_EPS = [{"method": "POST", "path": "/api/ratings", "auth_required": True},
        {"method": "PATCH", "path": "/api/ratings/{id}", "auth_required": True},
        {"method": "PUT", "path": "/api/users/{id}", "auth_required": True}]

_SRC = render_skeleton_main(_EPS, _TABLES)


def _coerce():
    m = re.search(r"\ndef _coerce_body\(cls, valid\):.*?\n    return out\n", _SRC, re.S)
    assert m, "could not extract _coerce_body from generated main.py"
    ns = {}
    exec(m.group(0), ns)
    return ns["_coerce_body"]


class _Col:
    def __init__(self, t):
        self.type = t


class _Model:
    class __table__:
        columns = {"flag": _Col(Boolean()), "value": _Col(Integer()),
                   "title": _Col(String()), "score": _Col(Numeric())}


def test_generated_main_compiles():
    compile(_SRC, "main.py", "exec")


# ---- (a) Boolean coercion --------------------------------------------------------------
def test_bool_string_true_variants():
    for s in ("true", "True", "1", "yes", "on", "t"):
        assert _coerce()(_Model, {"flag": s})["flag"] is True, s


def test_bool_string_false_variants():
    for s in ("false", "False", "0", "no", "off", "f"):
        assert _coerce()(_Model, {"flag": s})["flag"] is False, s


def test_bool_int_coerced():
    assert _coerce()(_Model, {"flag": 1})["flag"] is True
    assert _coerce()(_Model, {"flag": 0})["flag"] is False


def test_real_bool_untouched_in_bool_column():
    assert _coerce()(_Model, {"flag": True})["flag"] is True


def test_bool_into_non_bool_column_not_mangled():
    # regression of #395's test_none_and_bool_untouched: a bool in a String/Int col is left
    out = _coerce()(_Model, {"title": True, "value": True})
    assert out["title"] is True and out["value"] is True


def test_unparseable_bool_string_left_for_dataerror():
    # not a recognised bool token -> left as-is (the global DataError->400 handler catches it)
    assert _coerce()(_Model, {"flag": "maybe"})["flag"] == "maybe"


def test_int_coercion_still_works():
    assert _coerce()(_Model, {"value": "up"})["value"] == 0
    assert _coerce()(_Model, {"value": "4"})["value"] == 4


# ---- (b) coercion covers create AND update ---------------------------------------------
def test_coercion_runs_for_every_write_handler():
    # POST + PATCH + PUT = 3 write handlers, each with an up-front _coerce_body
    assert _SRC.count("valid = _coerce_body(") == 3, _SRC.count("valid = _coerce_body(")


# ---- (c) DataError -> 400 wiring -------------------------------------------------------
def test_handlers_reraise_dataerror_before_generic_500():
    assert "from sqlalchemy.exc import IntegrityError, DataError" in _SRC
    # in each write handler the DataError re-raise must appear before the catch-all 500
    de = _SRC.index("except DataError:")
    ex = _SRC.index("except Exception as _exc:")
    assert de < ex, "DataError branch must precede the catch-all Exception branch"


def test_global_dataerror_handler_present():
    assert "_framework_data_error_handler" in _INTEGRITY_HANDLER
    assert "status_code=400" in _INTEGRITY_HANDLER


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
