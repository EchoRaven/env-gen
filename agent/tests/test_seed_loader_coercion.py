"""#388: the generated seed loader's _coerce_nested_for_string_cols coerced list/dict→JSON
and string→number, but NOT int/float→str for a String/Text column. So the embedded _SEED
fallback (and any dataset/lane seed) that put an INT in the TEXT maturity_rating column
made postgres reject the row ('type text but expression is of type integer'), the per-row
savepoint rolled back EVERY title, and the catalog shipped empty → GET /api/titles [] →
POST /api/titles/1/rating 404 → business_chain STUCK abort (netflix r13). The fix adds the
int/float→str branch, applied to every seed source at insert time (render_seed_data emits
`cls(**_coerce_nested_for_string_cols(...))`).
"""
import re

from env_generator.llm_generator.multi_agent.runtime.backend_skeleton import render_seed_data
from sqlalchemy import String, Text, Integer, Numeric


def _load_coerce():
    tables = {"titles": {"columns": [
        {"name": "id", "type": "integer", "primary_key": True},
        {"name": "name", "type": "text"},
        {"name": "maturity_rating", "type": "text"},
        {"name": "view_count", "type": "integer"},
        {"name": "rating", "type": "numeric"},
    ]}}
    src = render_seed_data(tables)
    assert "_is_str = isinstance(ctype, _SAStr)" in src and "out[k] = str(v)" in src
    m = re.search(r"def _coerce_nested_for_string_cols\(cls, vals\):.*?\n    return out\n",
                  src, re.S)
    assert m, "could not extract _coerce_nested_for_string_cols from generated loader"
    ns = {"json": __import__("json")}
    exec(m.group(0), ns)
    return ns["_coerce_nested_for_string_cols"]


_coerce = _load_coerce()


class _Col:
    def __init__(self, t):
        self.type = t


class _Cls:
    class __table__:
        columns = {
            "maturity_rating": _Col(Text()),
            "title": _Col(String(255)),
            "view_count": _Col(Integer()),
            "rating": _Col(Numeric()),
        }


def test_int_in_text_column_coerced_to_str():
    # the exact r13 bug: TEXT maturity_rating seeded with an int
    assert _coerce(_Cls, {"maturity_rating": 3})["maturity_rating"] == "3"


def test_float_in_string_column_coerced_to_str():
    assert _coerce(_Cls, {"title": 4.5})["title"] == "4.5"


def test_string_in_int_column_still_coerced_to_int():
    # #213 regression must still hold
    assert _coerce(_Cls, {"view_count": "5"})["view_count"] == 5


def test_correct_types_untouched():
    out = _coerce(_Cls, {"maturity_rating": "PG-13", "view_count": 10, "rating": 4.2})
    assert out["maturity_rating"] == "PG-13"
    assert out["view_count"] == 10
    assert out["rating"] == 4.2


def test_none_and_bool_untouched():
    out = _coerce(_Cls, {"maturity_rating": None, "view_count": True})
    assert out["maturity_rating"] is None and out["view_count"] is True


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
