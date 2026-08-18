r"""#954: the contract check could not see a quoted table name, so it saw a third of the schema.

    CREATE TABLE IF NOT EXISTS tenants (      the framework's spine   → matched
    CREATE TABLE IF NOT EXISTS "titles" (     every lane-authored one → invisible

`([a-zA-Z_][\w]*)` does not admit a leading quote. Across the corpus: **1132 quoted CREATE TABLEs
against 564 unquoted, in 141 runs.** r154 reports `expected_tables=12, sql_tables=4`, and the four
are exactly the spine's (`tenants`, `users`, `oauth_clients`, `oauth_authorization_codes`) — its
`contract_alignment.errors` is empty because the comparison never saw the other eight.

★ Found by constructing a real `HubRegistry` and running the real `validate_delivery_gate` against
r154, rather than by reading the checker. Four synthetic integration runs and 6427 unit tests never
touched it, because a fixture writes whatever SQL the fixture author writes — and I would have
written it unquoted, like the framework does.

★★ The column loop in the same function already strips quotes (`first.strip('"')`). The knowledge
was inside the function, one loop below the line that lacked it.

★★★ NOT extended to `extract_backend_sql_refs`, on measurement rather than instinct: backend SQL is
23454 unquoted against 62 quoted (0.26%). Changing a regex that fires 23k times to catch 62 cases
risks more than it repairs.
"""
import pathlib

import pytest

from env_generator.llm_generator.multi_agent.delivery.contract_extract import extract_sql_tables


def _sql(tmp_path, text):
    d = tmp_path / "init"
    d.mkdir(parents=True)
    (d / "01_init.sql").write_text(text, encoding="utf-8")
    return tmp_path


_QUOTED = '''
CREATE TABLE IF NOT EXISTS "titles" (
    "id" SERIAL PRIMARY KEY,
    "name" TEXT,
    "year" TEXT
);
CREATE TABLE IF NOT EXISTS tenants (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL
);
'''


def test_a_quoted_table_is_seen(tmp_path):
    t = extract_sql_tables(_sql(tmp_path, _QUOTED))
    assert set(t) == {"titles", "tenants"}


def test_the_quotes_are_stripped_from_the_name(tmp_path):
    """`"titles"` must key as `titles`, or every downstream comparison misses by a quote."""
    assert '"titles"' not in extract_sql_tables(_sql(tmp_path, _QUOTED))


def test_columns_still_parse_for_a_quoted_table(tmp_path):
    t = extract_sql_tables(_sql(tmp_path, _QUOTED))
    assert {"id", "name", "year"} <= t["titles"]


def test_the_unquoted_form_still_works(tmp_path):
    """The framework's own spine is unquoted and must not regress."""
    assert "tenants" in extract_sql_tables(_sql(tmp_path, _QUOTED))


def test_a_schema_qualified_name_resolves_to_the_table(tmp_path):
    t = extract_sql_tables(_sql(tmp_path, 'CREATE TABLE public."items" (\n  "id" INT\n);\n'))
    assert set(t) == {"items"}


def test_a_schema_qualified_unquoted_name_too(tmp_path):
    t = extract_sql_tables(_sql(tmp_path, "CREATE TABLE public.items (\n  id INT\n);\n"))
    assert set(t) == {"items"}


def test_the_real_r154_schema_reads_all_twelve():
    """★ Non-vacuity against the tree that exposed this. 12 declared, 12 in SQL, 4 before."""
    d = pathlib.Path(__file__).resolve().parents[1] / "generated/netflix-web-r154/app/database"
    if not d.is_dir():
        pytest.skip("r154 not on this box")
    t = extract_sql_tables(d)
    assert len(t) == 12, sorted(t)
    assert {"titles", "episodes", "my_list", "ratings"} <= set(t)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
