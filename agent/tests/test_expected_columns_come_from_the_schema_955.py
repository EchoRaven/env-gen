r"""#955: expected columns were read from a key the registry does not use.

A registryhub table record is

    {"id": "titles", "name": "titles", "status": "implemented",
     "schema": {"columns": [{"name": "id", "type": "serial primary key"}, …]}}

and `extract_spec_tables` read `table["columns"]`, which is absent. So `expected_columns` was empty
for all 12 of r154's tables, and the caller's `if not expected_columns: continue` skipped the
comparison for every table in every run. **The column-level contract check has never executed.**

★ Found immediately after #954. Making the tables visible (4 → 12) changed nothing observable, so
I planted a drift — deleted `synopsis` from the SQL while the contract still declares it — and the
gate still reported `errors: 0`. A second blindness sitting behind the first only shows itself when
you demand the fixed check produce a finding.

With both fixed, against r154:

    clean            errors 0, warnings 0            (correct — r154 has no drift)
    synopsis removed errors 1: "SQL table `titles` missing registered columns: synopsis"
"""
import json
import pathlib

import pytest

from env_generator.llm_generator.multi_agent.runtime.delivery_gate import extract_spec_tables


def test_columns_under_schema_are_found():
    """★ THE fix — the shape the registry actually writes."""
    spec = {"tables": [{"name": "titles",
                        "schema": {"columns": [{"name": "id"}, {"name": "synopsis"}]}}]}
    assert extract_spec_tables(spec)["titles"] == {"id", "synopsis"}


def test_a_top_level_columns_key_still_wins():
    """Other producers may use the documented shape; it must keep working and take precedence."""
    spec = {"tables": [{"name": "t", "columns": [{"name": "a"}],
                        "schema": {"columns": [{"name": "b"}]}}]}
    assert extract_spec_tables(spec)["t"] == {"a"}


def test_a_dict_of_columns_still_works():
    spec = {"tables": {"t": {"columns": {"a": "int", "b": "text"}}}}
    assert extract_spec_tables(spec)["t"] == {"a", "b"}


def test_a_dict_under_schema_works_too():
    spec = {"tables": [{"name": "t", "schema": {"columns": {"a": "int"}}}]}
    assert extract_spec_tables(spec)["t"] == {"a"}


def test_a_table_with_no_columns_anywhere_is_empty_not_crashing():
    spec = {"tables": [{"name": "t"}, {"name": "u", "schema": {}}]}
    out = extract_spec_tables(spec)
    assert out.get("t", set()) == set() and out.get("u", set()) == set()


def test_the_real_registry_now_yields_columns_for_every_table():
    """★ Non-vacuity against the tree that exposed it: 12 tables, 12 with columns, 0 before."""
    p = (pathlib.Path(__file__).resolve().parents[1]
         / "generated/netflix-web-r154/shared/hubs/registryhub_tables.json")
    if not p.is_file():
        pytest.skip("r154 not on this box")
    hub = {k: v for k, v in json.loads(p.read_text()).items() if k != "_meta"}
    out = extract_spec_tables({"tables": list(hub.values())})
    assert len(out) == 12
    assert sum(1 for v in out.values() if v) == 12, {k: len(v) for k, v in out.items()}
    assert "synopsis" in out["titles"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
