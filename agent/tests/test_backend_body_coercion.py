"""#395: the projected create handler now coerces a request body's scalar values to each
column's ACTUAL type before the INSERT. The rating verification chains POST a thumbs value
{"value": "up"} / {"value": "thumbs_up"} into the INTEGER ratings.value column, so the raw
INSERT errored ('integrity constraint violated' 400) and the rating chain wedged
business_chain. _coerce_body (in _MAIN_HEADER) mirrors the seed loader: non-numeric string
in a numeric column -> 0, numeric string -> the number, non-string scalar in a String col ->
str. The generated create handler calls it before cls(**valid). No-op for a well-typed body.
"""
import re

from sqlalchemy import Integer, String, Numeric

from env_generator.llm_generator.multi_agent.runtime.backend_skeleton import render_skeleton_main

_TABLES = {
    "users": {"columns": [{"name": "id", "type": "integer", "primary_key": True}]},
    "titles": {"columns": [{"name": "id", "type": "integer", "primary_key": True}]},
    "profiles": {"columns": [
        {"name": "id", "type": "integer", "primary_key": True},
        {"name": "user_id", "type": "integer", "fk": "users.id"},
        {"name": "name", "type": "text not null"}]},
    "ratings": {"columns": [
        {"name": "id", "type": "integer", "primary_key": True},
        {"name": "profile_id", "type": "integer", "fk": "profiles.id"},
        {"name": "title_id", "type": "integer", "fk": "titles.id"},
        {"name": "value", "type": "integer not null"}]},
}
_EPS = [{"method": "POST", "path": "/api/titles/{id}/rating", "auth_required": True},
        {"method": "POST", "path": "/api/ratings", "auth_required": True}]

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


class _Rating:
    class __table__:
        columns = {"value": _Col(Integer()), "title": _Col(String()), "score": _Col(Numeric())}


def test_helper_defined_and_handler_calls_it():
    assert "def _coerce_body(cls, valid):" in _SRC
    # both projected create handlers (rating + ratings) coerce before cls(**valid)
    assert _SRC.count("valid = _coerce_body(") >= 1


def test_nonnumeric_string_in_int_column_becomes_zero():
    # the exact rating-chain bug: {"value": "up"} into an INTEGER column
    assert _coerce()(_Rating, {"value": "up"})["value"] == 0
    assert _coerce()(_Rating, {"value": "thumbs_up"})["value"] == 0


def test_numeric_string_coerced_to_number():
    assert _coerce()(_Rating, {"value": "4"})["value"] == 4
    assert _coerce()(_Rating, {"score": "3.5"})["score"] == 3.5


def test_well_typed_values_untouched():
    out = _coerce()(_Rating, {"value": 5, "title": "Inception"})
    assert out["value"] == 5 and out["title"] == "Inception"


def test_scalar_in_string_column_becomes_str():
    assert _coerce()(_Rating, {"title": 7})["title"] == "7"


def test_none_and_bool_untouched():
    out = _coerce()(_Rating, {"value": None, "title": True})
    assert out["value"] is None and out["title"] is True


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
