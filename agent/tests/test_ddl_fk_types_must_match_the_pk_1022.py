r"""#1022: FIX #197 never once took effect, so the DDL shipped FKs postgres cannot implement.

#197 reconciles FK column types against the PK they reference, and says so at its call site
in ``render_schema_sql``:

    # The reconciler mutates the col dicts in place; _columns_of returns
    # those same dicts below, so the rendered types match the ORM by construction.

**That premise is false.** ``_columns_of()`` builds FRESH dicts on every call, so the
reconciler mutated throwaway copies and the render loop then called ``_columns_of(table)``
again and got unreconciled ones. ``render_models`` does it correctly — it renders from
``by_name`` itself (backend_skeleton:421) — so the ORM was reconciled and the DDL was not,
which is exactly the divergence #197 exists to prevent. Wrapped in ``except Exception: pass``,
so a hard failure would have been invisible too.

Measured end-to-end on the real renderers, with netflix r172's contract:

    models.py     Profile.id         = Column(String, …uuid4)
                  MyList.profile_id  = Column(String, ForeignKey("profiles.id"))
    01_init.sql   "profiles"."id"          SERIAL PRIMARY KEY
                  "my_list"."profile_id"   uuid references profiles(id)
    initdb        foreign key constraint "my_list_profile_id_fkey" cannot be implemented
                  DETAIL: Key columns "profile_id" and "id" are of incompatible types:
                          uuid and integer                      -> postgres exits

One unbootable file produced FIVE separate P0 tasks in r172 — postgres exits -> backend
health check times out -> frontend container missing -> compose "reports success but starts
no services" -> port 3000 serves backend 404 — which is #197's own predicted
"docker_up wedges every cycle … -> 75-min wall".

Three defects, one area:

  1. the reconciliation never reached the DDL (mutated discarded copies)
  2. ``_FK_RE`` could not see a QUOTED reference — `REFERENCES "users" ("id")` returned None,
     so those columns were skipped entirely. r122 shipped
     `"user_id" TEXT REFERENCES "users" ("id")` against an integer `users.id`.
  3. ``_set_col_base_category`` rebuilt the clause from two captured groups and dropped
     whatever followed, so coercing `… ON DELETE CASCADE` silently lost the cascade. Harmless
     while (1) kept it dead; live the moment it works.

The net is #997's, whose docstring predicted this: *"a FOURTH spelling gets caught when the
DDL is rendered, not by a container failing to boot an hour later … there is no reason to
think the list is complete."* An FK/PK type mismatch is that fourth member — the first that
is not a spelling. Validated against every generated DDL on disk: **1 of 159 flagged**, and
that one (r122) is a true positive.
"""
import glob
import os
import re

import pytest

from env_generator.llm_generator.multi_agent.runtime.backend_skeleton import (
    _fk_target, _set_col_base_category, render_models)
from env_generator.llm_generator.multi_agent.runtime.database_scaffold import (
    _columns_of, _ddl_column_types_1022, _ddl_invariants_997, _fk_type_conflicts_1022,
    render_schema_sql)


def _r172_tables():
    """netflix r172's shape: a uuid FK onto a SERIAL PK."""
    return {
        "profiles": {"name": "profiles", "columns": [
            {"name": "id", "type": "SERIAL", "primary_key": True}]},
        "titles": {"name": "titles", "columns": [
            {"name": "id", "type": "SERIAL", "primary_key": True}]},
        "my_list": {"name": "my_list", "columns": [
            {"name": "id", "type": "UUID", "primary_key": True},
            {"name": "profile_id", "type": "uuid references profiles(id) on delete cascade"},
            {"name": "title_id", "type": "integer references titles(id) on delete cascade"}]},
    }


def _table_block(sql, name):
    m = re.search(r'CREATE TABLE IF NOT EXISTS "%s"[^;]*;' % re.escape(name), sql)
    assert m, f"{name} not found in rendered DDL"
    return m.group(0)


# --- the defect ------------------------------------------------------------------------------

def test_the_rendered_ddl_has_no_fk_type_conflict():
    """The whole point: r172's contract must render a DDL postgres can boot."""
    assert _fk_type_conflicts_1022(render_schema_sql(_r172_tables())) == []


def test_the_false_premise_is_pinned():
    """`_columns_of` returns FRESH dicts — the reason #197 was a no-op. If this ever starts
    returning the same objects, the fix is merely redundant, not wrong; but the comment that
    claimed it was always false."""
    t = {"name": "x", "columns": [{"name": "c", "type": "uuid references y(id)"}]}
    a, b = _columns_of(t), _columns_of(t)
    assert a[0] is not b[0]
    assert a[0] is not t["columns"][0]


def test_the_control_is_the_pre_fix_render():
    """Planted control: re-derive the columns the way the pre-fix loop did and show the
    conflict comes straight back. Without this, the tests above would also pass on a build
    where reconciliation happened to be unnecessary."""
    from env_generator.llm_generator.multi_agent.runtime.backend_skeleton import (
        _reconcile_fk_types_in_map)
    tables = _r172_tables()
    recon = {str(n).lower(): _columns_of(t) for n, t in tables.items()}
    _reconcile_fk_types_in_map(recon)
    # pre-fix: the loop threw `recon` away and called _columns_of(table) again
    pre_fix = {str(n).lower(): _columns_of(t) for n, t in tables.items()}
    assert pre_fix["my_list"][1]["type"].startswith("uuid"), "control not reproducing"
    assert pre_fix["profiles"][0]["type"].upper() == "SERIAL"
    # reconciled view disagrees with it — that disagreement WAS the shipped bug
    assert recon["profiles"][0]["type"] != pre_fix["profiles"][0]["type"]


def _orm_class_block(orm, cls):
    """The body of ONE model class. A `.*?` across the whole file happily matches a LATER
    class's column and reports agreement that is not there — this test failed that way first."""
    m = re.search(r"^class %s\(Base\):\n(.*?)(?=^class |\Z)" % re.escape(cls),
                  orm, re.S | re.M)
    assert m, f"class {cls} not found in rendered models"
    return m.group(1)


def test_the_ddl_and_the_orm_agree():
    """#197's actual goal. The ORM was already reconciled; the DDL now is too."""
    ddl, orm = render_schema_sql(_r172_tables()), render_models(_r172_tables())
    ddl_pk = _ddl_column_types_1022(ddl)["profiles"]["id"][0]
    ddl_is_int = bool(re.search(r"\b(serial|int)", ddl_pk, re.I))
    orm_is_int = bool(re.search(r"\bid = Column\(Integer",
                                _orm_class_block(orm, "Profile")))
    assert ddl_is_int == orm_is_int, (
        f"DDL profiles.id is {ddl_pk!r} but the ORM's Profile.id disagrees")


def test_the_agreement_check_cannot_span_classes():
    """Control for the helper above: a Profile block that is uuid must NOT be satisfied by an
    Integer id belonging to the next class."""
    fake = ("class Profile(Base):\n    id = Column(String, primary_key=True)\n\n"
            "class Title(Base):\n    id = Column(Integer, primary_key=True)\n")
    assert "Integer" not in _orm_class_block(fake, "Profile")


# --- (2) quoted references -------------------------------------------------------------------

@pytest.mark.parametrize("type_text,expected", [
    ("uuid references profiles(id) on delete cascade", "profiles.id"),
    ('TEXT REFERENCES "users" ("id") ON DELETE CASCADE', "users.id"),
    ('integer REFERENCES "users"("id")', "users.id"),
    ("integer REFERENCES users(id)", "users.id"),
    ("TEXT REFERENCES users (id)", "users.id"),
    ("integer references titles.id", "titles.id"),
    ("text", None),
])
def test_fk_target_reads_quoted_and_bare_forms(type_text, expected):
    assert _fk_target({"type": type_text}) == expected


def test_a_quoted_spine_fk_is_coerced():
    """r122's exact shape: TEXT onto the integer `users.id` spine PK."""
    tables = {"profiles": {"name": "profiles", "columns": [
        {"name": "id", "type": "SERIAL", "primary_key": True},
        {"name": "user_id", "type": 'TEXT REFERENCES "users" ("id") ON DELETE CASCADE'}]}}
    block = _table_block(render_schema_sql(tables), "profiles")
    assert re.search(r'"user_id"\s+integer\b', block, re.I), block


# --- (3) the trailing clause survives ----------------------------------------------------------

def test_on_delete_cascade_survives_coercion():
    col = {"name": "user_id", "type": 'TEXT REFERENCES "users" ("id") ON DELETE CASCADE'}
    _set_col_base_category(col, "integer")
    assert col["type"].lower().startswith('integer references "users"("id")')
    assert "on delete cascade" in col["type"].lower(), (
        "the cascade was dropped — a parent delete would raise instead of cascading")


def test_a_reference_with_no_tail_gains_no_trailing_space():
    col = {"name": "user_id", "type": "TEXT REFERENCES users(id)"}
    _set_col_base_category(col, "integer")
    assert col["type"] == 'integer references "users"("id")'


def test_a_structured_fk_column_is_still_overwritten_bare():
    """The documented behaviour for the non-inline branch is unchanged."""
    col = {"name": "user_id", "type": "TEXT", "fk": "users.id"}
    _set_col_base_category(col, "integer")
    assert col["type"] == "integer"


# --- the net ------------------------------------------------------------------------------------

def test_the_net_flags_a_real_mismatch():
    bad = ('CREATE TABLE IF NOT EXISTS "profiles" (\n    "id" SERIAL PRIMARY KEY\n);\n'
           'CREATE TABLE IF NOT EXISTS "my_list" (\n'
           '    "id" SERIAL PRIMARY KEY,\n'
           '    "profile_id" uuid references profiles(id)\n);\n')
    assert _fk_type_conflicts_1022(bad) == [
        ("my_list", "profile_id", "uuid", "profiles.id", "integer")]
    with pytest.raises(ValueError) as e:
        _ddl_invariants_997(bad)
    msg = str(e.value)
    assert "#1022" in msg and "my_list.profile_id" in msg and "profiles.id" in msg, msg


def test_the_net_passes_matching_types():
    good = ('CREATE TABLE IF NOT EXISTS "profiles" (\n    "id" SERIAL PRIMARY KEY\n);\n'
            'CREATE TABLE IF NOT EXISTS "my_list" (\n'
            '    "id" SERIAL PRIMARY KEY,\n'
            '    "profile_id" integer references profiles(id)\n);\n')
    assert _fk_type_conflicts_1022(good) == []
    _ddl_invariants_997(good)


def test_an_unresolvable_target_is_not_flagged():
    """A reference to a table this file does not create cannot be judged — stay quiet rather
    than block a run on a guess."""
    ddl = ('CREATE TABLE IF NOT EXISTS "a" (\n    "id" SERIAL PRIMARY KEY,\n'
           '    "ext_id" uuid references somewhere_else(id)\n);\n')
    assert _fk_type_conflicts_1022(ddl) == []


def test_table_constraint_lines_are_not_read_as_columns():
    ddl = ('CREATE TABLE IF NOT EXISTS "t" (\n    "id" SERIAL PRIMARY KEY,\n'
           '    "a" integer,\n    PRIMARY KEY ("id"),\n'
           '    FOREIGN KEY ("a") REFERENCES other(id),\n    UNIQUE ("a")\n);\n')
    cols = _ddl_column_types_1022(ddl)["t"]
    assert set(cols) == {"id", "a"}, cols


def test_the_parser_has_a_denominator():
    """A parser that sees no tables reports every file clean — items 366/381/391/398/414."""
    parsed = _ddl_column_types_1022(render_schema_sql(_r172_tables()))
    assert len(parsed) >= 4, parsed
    assert "my_list" in parsed and "profile_id" in parsed["my_list"]


def test_the_real_renderer_output_is_clean():
    _ddl_invariants_997(render_schema_sql(_r172_tables()))


# --- false-positive control over the real corpus ------------------------------------------------

def test_the_net_does_not_flag_the_generated_corpus():
    """Validated on real artifacts before being trusted: over every generated `01_init.sql`
    on disk, only r122 flags, and r122 declares
    `"user_id" TEXT REFERENCES "users" ("id")` against `users.id SERIAL` — unbootable, so a
    true positive. Skips when the corpus is absent (a fresh checkout)."""
    root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "generated")
    files = sorted(glob.glob(os.path.join(root, "*", "app", "database", "init", "01_init.sql")))
    if len(files) < 20:
        pytest.skip(f"generated corpus not present ({len(files)} files)")
    flagged, parsed_any = {}, 0
    for f in files:
        try:
            ddl = open(f, encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        if _ddl_column_types_1022(ddl):
            parsed_any += 1
        c = _fk_type_conflicts_1022(ddl)
        if c:
            flagged[os.path.basename(os.path.dirname(os.path.dirname(
                os.path.dirname(os.path.dirname(f)))))] = c
    assert parsed_any == len(files), (
        f"the parser saw no tables in {len(files) - parsed_any} file(s) — a blind zero")
    assert set(flagged) <= {"netflix-web-r122"}, (
        f"unexpected flags (candidate false positives): {sorted(flagged)}")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
