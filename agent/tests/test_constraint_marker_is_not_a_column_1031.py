r"""#1031: `__unique__` reached the DDL as a COLUMN and postgres refused the file.

The generated `01_init.sql` carried:

    ALTER TABLE "users" ADD COLUMN IF NOT EXISTS "__unique__" (email, tenant_id);

`ERROR: syntax error at or near "(" at character 59` -> initdb aborts -> the database never
starts -> every service behind it is unreachable.

The contract spelled a table constraint as `{"name": "__unique__", "type": "(email,
tenant_id)"}` — keyword as a MARKER NAME, column list in the TYPE. `_is_constraint_pseudo_
column` only knew the keyword-IN-the-name form (`_CONSTRAINT_NAME_RE` matches
`UNIQUE (a, b)`), so this entry was not recognised as a constraint, fell through to the
ordinary column path in `_spine_extra_column_alters`, and was emitted as a column.

This is #997's class exactly — "a token that means something to a contract author and nothing
to postgres" — and its FIFTH member, after #969 (`nullable`), #988 (`?`), #989
(`default_now`) and #1022's FK-type mismatch. #997 wrote "there is no reason to think the list
is complete." It has now been right twice.

★ HOW IT STAYED INVISIBLE, which is the part worth remembering: postgres runs
`/docker-entrypoint-initdb.d/*` ONLY on an empty data dir. r173's database came up at
**20:08:59** and this line was written at **21:28:28** — 80 minutes later — so r173 never
executed it and its log has zero SQL errors. It surfaced only when #1030 exported the run as a
DTAP env and cold-booted it. A DTAP task cold-boots a fresh VM every time, so it would have
hit this on every single task.

Three layers, because the producer fix alone does not cover artifacts already on disk:
  1. `_is_constraint_pseudo_column` recognises the marker  -> the column path skips it
  2. `_render_table_constraint` RENDERS it properly        -> the constraint is kept, not lost
  3. `_ddl_invariants_997` refuses the emitted shape       -> any other producer is caught too
  and `tools/dtap_env_export.sanitize_init_sql` repairs already-written SQL at export.
"""
import re
import sys
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime.database_scaffold import (
    _SPINE_USERS_COLUMNS, _ddl_invariants_997, _is_constraint_pseudo_column,
    _render_table_constraint, _spine_extra_column_alters)

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from dtap_env_export import sanitize_init_sql  # noqa: E402

_MARKER = {"name": "__unique__", "type": "(email, tenant_id)"}


# --- 1. the detector ---------------------------------------------------------------------------

def test_the_marker_spelling_is_recognised():
    assert _is_constraint_pseudo_column(_MARKER) is True


@pytest.mark.parametrize("name", ["__unique__", "__primary_key__", "__primarykey__",
                                  "__foreign_key__", "__check__", "__index__",
                                  "__UNIQUE__", "__ Unique __"])
def test_every_marker_keyword_is_recognised(name):
    assert _is_constraint_pseudo_column({"name": name, "type": "(a, b)"}) is True


@pytest.mark.parametrize("name", ["__dunder_field__", "user__name", "__init__", "email"])
def test_an_ordinary_column_is_not_mistaken_for_one(name):
    """Specificity matters more than sensitivity here: a false positive silently DROPS a real
    column, which is worse than the bug being fixed."""
    assert _is_constraint_pseudo_column({"name": name, "type": "text"}) is False


def test_the_keyword_in_name_form_still_works():
    assert _is_constraint_pseudo_column({"name": "UNIQUE (a, b)"}) is True
    assert _is_constraint_pseudo_column({"name": "constraint foo"}) is True


# --- 2. it is rendered, not merely dropped -------------------------------------------------------

def test_the_marker_renders_as_a_real_constraint():
    """The contract asked for a UNIQUE and we can honour it exactly — dropping it would be a
    silent loss of an integrity guarantee."""
    assert _render_table_constraint(_MARKER) == '    UNIQUE ("email", "tenant_id")'


def test_a_primary_key_marker_renders_too():
    out = _render_table_constraint({"name": "__primary_key__", "type": "(a, b)"})
    assert out == '    PRIMARY KEY ("a", "b")'


def test_a_marker_without_a_column_list_is_skipped_not_guessed():
    assert _render_table_constraint({"name": "__check__", "type": "x > 0"}) is None
    assert _render_table_constraint({"name": "__unique__", "type": "text"}) is None


def test_the_keyword_in_name_rendering_is_unchanged():
    assert _render_table_constraint({"name": "UNIQUE (a, b)"}) == '    UNIQUE ("a", "b")'


# --- 3. the ALTER path no longer emits it ---------------------------------------------------------

def test_the_spine_alter_skips_the_marker_and_keeps_real_columns():
    out = _spine_extra_column_alters(
        "users", [_MARKER, {"name": "username", "type": "text"}], _SPINE_USERS_COLUMNS)
    assert out == ['ALTER TABLE "users" ADD COLUMN IF NOT EXISTS "username" TEXT;']


def test_the_control_is_the_shipped_line():
    """Planted control: the exact SQL r173 wrote must be refused by the net."""
    bad = 'ALTER TABLE "users" ADD COLUMN IF NOT EXISTS "__unique__" (email, tenant_id);'
    with pytest.raises(ValueError) as e:
        _ddl_invariants_997(bad)
    assert "#1031" in str(e.value)


def test_a_healthy_file_with_a_real_constraint_still_passes():
    _ddl_invariants_997('CREATE TABLE "t" (\n  "id" SERIAL PRIMARY KEY,\n'
                        '  UNIQUE ("a", "b")\n);\n')


# --- 4. artifacts already on disk are repaired at export -------------------------------------------

def test_export_repairs_the_line_and_says_so():
    bad = 'ALTER TABLE "users" ADD COLUMN IF NOT EXISTS "__unique__" (email, tenant_id);\n'
    fixed, notes = sanitize_init_sql(bad)
    assert "ADD CONSTRAINT" in fixed and "UNIQUE (email, tenant_id)" in fixed
    assert "ADD COLUMN" not in fixed
    assert notes and "users" in notes[0]


def test_the_repaired_sql_passes_the_net():
    bad = 'ALTER TABLE "users" ADD COLUMN IF NOT EXISTS "__unique__" (email, tenant_id);\n'
    fixed, _ = sanitize_init_sql(bad)
    _ddl_invariants_997(fixed)          # must not raise


def test_repair_is_idempotent_and_quiet_on_clean_sql():
    clean = 'CREATE TABLE "t" ("id" SERIAL PRIMARY KEY);\n'
    out, notes = sanitize_init_sql(clean)
    assert out == clean and notes == []
    once, _ = sanitize_init_sql(
        'ALTER TABLE "users" ADD COLUMN IF NOT EXISTS "__unique__" (a, b);\n')
    twice, notes2 = sanitize_init_sql(once)
    assert twice == once and notes2 == []


def test_the_repair_does_not_touch_ordinary_alters():
    keep = 'ALTER TABLE "users" ADD COLUMN IF NOT EXISTS "username" TEXT;\n'
    out, notes = sanitize_init_sql(keep)
    assert out == keep and notes == []


# --- the premise -------------------------------------------------------------------------------

def test_the_shipped_artifact_is_the_motivating_case():
    """If r173's DDL is ever regenerated clean, this file's story is historical — but the
    guards above should still hold, so only this test needs revisiting."""
    p = (Path(__file__).resolve().parents[1] / "generated" / "netflix-web-r173"
         / "app" / "database" / "init" / "01_init.sql")
    if not p.is_file():
        pytest.skip("r173 artifact not present")
    assert "__unique__" in p.read_text(encoding="utf-8"), (
        "the motivating artifact no longer carries the marker")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
