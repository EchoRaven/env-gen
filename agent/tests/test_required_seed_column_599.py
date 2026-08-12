r"""#599: a NOT NULL column the seed omits does not lose a FIELD — it loses the whole TABLE.

`_seed_cell` omits any column it has no naming rule for, and the loader then drops the entire
row on the NOT NULL — silently, by design. seed_data.py's own header says so:

    "a dropped seed row (FK to a missing parent, uncovered NOT NULL, wrong ...) ...
     _seed_dbg prints the dropped row's exception to stderr when FW_DEBUG is set."

Measured over the 1196 seeded tables in the arc: **204** columns are NOT NULL with no default of
any kind and are never set. Top offenders: `ratings.value` x80, `episodes.season` x34,
`genres.slug` x15. **4 survive into r134+**, and r134 is one of the three
*** MULTI-MILESTONE VALIDATED *** runs — it ships

    ratings   value  Text    NOT NULL,  seed rows are {profile_id, title_id}   -> table EMPTY
    episodes  season Integer NOT NULL,  never seeded                           -> table EMPTY

A required column has no naming rule precisely because it is domain-specific, so the fallback is
type-directed — the same thing `_fw_fill_required_defaults` already does for a request body on
the API path. It is only ever reached where the alternative is a dropped row.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime.backend_skeleton import (
    _SEED_OMIT,
    _build_seed_rows,
    _seed_required_fallback as fallback,
)


def _tables(**cols_by_table):
    return {t: {"columns": cols} for t, cols in cols_by_table.items()}


_ID = {"name": "id", "type": "int", "primary_key": True}
_TITLES = [_ID, {"name": "name", "type": "text", "nullable": False}]
_FK = {"name": "title_id", "type": "int", "references": "titles.id", "nullable": False}


def _widget(extra):
    """A table only reaches the seed when it hangs off the graph — mirror the real shape."""
    seed, *_ = _build_seed_rows(_tables(widgets=[_ID, _FK, extra], titles=_TITLES))
    return seed["widgets"]


# --- the fallback itself -----------------------------------------------------------------

def test_it_fills_the_types_it_can():
    assert fallback("Integer", 0) == 1
    assert fallback("Text", 0) and isinstance(fallback("Text", 0), str)
    assert fallback("Boolean", 0) is True and fallback("Boolean", 1) is False
    assert fallback("Float", 2) == 3
    assert fallback("JSON", 0) == {}


def test_it_declines_the_types_it_cannot_fill_safely():
    """A timestamp goes through the loader's own coercion path — leave it alone."""
    assert fallback("DateTime", 0) is _SEED_OMIT
    assert fallback("Date", 0) is _SEED_OMIT
    assert fallback(None, 0) is _SEED_OMIT
    assert fallback("SomeCustomType", 0) is _SEED_OMIT


def test_it_is_deterministic():
    assert fallback("Integer", 3) == fallback("Integer", 3)
    assert fallback("Text", 3) == fallback("Text", 3)


# --- the r134 rows, rebuilt ----------------------------------------------------------------

def test_the_r134_ratings_row_now_carries_its_required_value():
    """`value Text NOT NULL` — the column that emptied the table."""
    seed, *_ = _build_seed_rows(_tables(ratings=[
        _ID,
        {"name": "title_id", "type": "int", "references": "titles.id", "nullable": False},
        {"name": "value", "type": "text", "nullable": False},
    ], titles=[_ID, {"name": "name", "type": "text", "nullable": False}]))
    rows = seed["ratings"]
    assert rows and all("value" in r and r["value"] not in (None, "") for r in rows), rows


def test_the_r134_episodes_row_now_carries_its_required_season():
    seed, *_ = _build_seed_rows(_tables(episodes=[
        _ID,
        {"name": "title_id", "type": "int", "references": "titles.id", "nullable": False},
        {"name": "season", "type": "int", "nullable": False},
    ], titles=[_ID, {"name": "name", "type": "text", "nullable": False}]))
    assert all(isinstance(r.get("season"), int) for r in seed["episodes"]), seed["episodes"]


# --- what must not change -------------------------------------------------------------------

def test_a_NULLABLE_column_with_no_rule_is_still_omitted():
    """The fallback must not start inventing data for columns that may be NULL."""
    rows = _widget({"name": "mystery_field", "type": "text", "nullable": True})
    assert all("mystery_field" not in r for r in rows), rows


def test_a_required_column_with_a_DEFAULT_is_left_to_the_default():
    rows = _widget({"name": "flavour", "type": "text", "nullable": False,
                    "default": "vanilla"})
    assert all("flavour" not in r for r in rows), rows


def test_a_required_column_with_a_SERVER_default_is_left_alone():
    rows = _widget({"name": "made_at", "type": "timestamp", "nullable": False,
                    "server_default": "now()"})
    assert all("made_at" not in r for r in rows), rows


def test_a_column_a_naming_rule_already_covers_keeps_its_realistic_value():
    """The fallback is a LAST resort — `name` must still get a real title, not a type stub."""
    names = [r["name"] for r in _widget({"name": "name", "type": "text",
                                         "nullable": False})]
    assert len(set(names)) > 1, names          # varied, from the people/title pools


def test_the_primary_key_is_never_treated_as_required():
    """A PK is SERIAL — filling it would fight the sequence sync (Fix #56)."""
    rows = _widget({"name": "label", "type": "text"})
    assert all("id" not in r for r in rows), rows


def test_the_required_set_is_carried_on_the_meta():
    from env_generator.llm_generator.multi_agent.runtime.backend_skeleton import _models_meta
    meta = _models_meta(_tables(ratings=[
        _ID, {"name": "value", "type": "text", "nullable": False},
        {"name": "note", "type": "text", "nullable": True}]))
    assert meta["ratings"]["required"] == ["value"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
