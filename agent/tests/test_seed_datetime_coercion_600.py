r"""#600: the seed loader's coercion table had no datetime branch.

#599 filled required columns type-directedly but had to DECLINE timestamps: the emitted
`_coerce_row` handled String/Integer/Numeric and nothing else, so handing a `DateTime` column an
ISO string risked a driver-level bind failure. Its residue was 108 required columns, **every one
a timestamp**, of which 5 are genuinely `DateTime, nullable=False` with no default in the
delivered models — 5 more tables that ship EMPTY, for the same reason `ratings` and `episodes`
did in r134.

Two halves, in this order:
  * the loader learns to parse ISO-8601 (with `Z`), and DROPS the key on anything unparseable so
    a bad value can never take the whole row down with it — the failure mode #599 exists to stop;
  * `_seed_required_fallback` may then fill a required timestamp.
"""
import py_compile
import tempfile

import pytest

from env_generator.llm_generator.multi_agent.runtime.backend_skeleton import (
    _SEED_OMIT,
    _build_seed_rows,
    _seed_required_fallback as fallback,
    render_seed_data,
)

_ID = {"name": "id", "type": "int", "primary_key": True}


def _emit(**cols_by_table):
    return render_seed_data({t: {"columns": c} for t, c in cols_by_table.items()})


# --- the loader half ------------------------------------------------------------------------

@pytest.fixture(scope="module")
def src():
    return _emit(ratings=[_ID, {"name": "value", "type": "text", "nullable": False},
                          {"name": "created_at", "type": "timestamp", "nullable": False}])


def test_the_emitted_loader_still_compiles(src):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(src)
    py_compile.compile(f.name, doraise=True)


def test_the_datetime_branch_exists_and_is_typed(src):
    assert "DateTime as _SADT" in src and "Date as _SADate" in src
    assert "_is_dt = isinstance(ctype, (_SADT, _SADate))" in src


def test_it_only_touches_a_STRING_value(src):
    """A real `datetime` object must pass through untouched."""
    assert "elif _is_dt and isinstance(v, str):" in src


def test_an_unparseable_timestamp_drops_the_KEY_not_the_ROW(src):
    """The whole point of #599 — a bad cell must never cost the row."""
    i = src.index("_is_dt and isinstance(v, str)")
    window = src[i:src.index("return out", i)]
    assert "out.pop(k, None)" in window
    assert "except Exception:" in window
    assert "raise" not in window


def test_the_Z_suffix_is_accepted(src):
    assert "replace('Z', '+00:00')" in src


def test_the_flag_defaults_false_when_the_type_cannot_be_read(src):
    assert "_is_int = _is_num = _is_str = _is_dt = False" in src


def test_the_parse_matches_what_the_fallback_emits():
    """Guard the pair: whatever #599 writes, the loader must be able to read."""
    from datetime import datetime
    v = fallback("DateTime", 3)
    assert isinstance(v, str)
    assert datetime.fromisoformat(v.strip().replace("Z", "+00:00"))


# --- the fallback half -----------------------------------------------------------------------

def test_a_required_timestamp_is_now_filled():
    seed, *_ = _build_seed_rows({
        "titles": {"columns": [_ID, {"name": "name", "type": "text", "nullable": False},
                               {"name": "created_at", "type": "timestamp",
                                "nullable": False}]}})
    rows = seed["titles"]
    assert rows and all(isinstance(r.get("created_at"), str) for r in rows), rows


def test_it_is_deterministic_and_ordering_is_stable():
    a = [fallback("DateTime", i) for i in range(6)]
    b = [fallback("DateTime", i) for i in range(6)]
    assert a == b
    assert a == sorted(a), a          # monotonic, so ORDER BY the column is meaningful


def test_a_NULLABLE_timestamp_is_still_left_to_the_database():
    seed, *_ = _build_seed_rows({
        "titles": {"columns": [_ID, {"name": "name", "type": "text", "nullable": False},
                               {"name": "created_at", "type": "timestamp"}]}})
    assert all("created_at" not in r for r in seed["titles"])


def test_a_timestamp_with_a_server_default_is_still_left_alone():
    seed, *_ = _build_seed_rows({
        "titles": {"columns": [_ID, {"name": "name", "type": "text", "nullable": False},
                               {"name": "created_at", "type": "timestamp",
                                "nullable": False, "server_default": "now()"}]}})
    assert all("created_at" not in r for r in seed["titles"])


def test_the_other_declined_types_are_unchanged():
    assert fallback(None, 0) is _SEED_OMIT
    assert fallback("SomeCustomType", 0) is _SEED_OMIT


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
