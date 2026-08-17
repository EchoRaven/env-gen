"""#396 (audit Prong C, the #393 root): the ORM renderer (backend_skeleton) keys
nullable/pk/unique/FK off STRUCTURED column flags, while the DDL renderer (database_scaffold)
honours modifiers embedded in the `type` string. The LLM routinely emits the constraint
inline in a STRUCTURED column dict ({"name":"name","type":"text not null"}). Inline-modifier
promotion used to run only for the flat-map shape, so for the canonical {"columns":[...]}
shape the ORM Column stayed nullable while the DDL emitted NOT NULL — an ORM/DDL divergence
that caused the intermittent NotNullViolation (#393), plus phantom-id PKs and dropped inline
FKs. The fix promotes inline modifiers at the single `_columns_of` chokepoint both renderers
use. This DB-free parity test locks it: for each inline constraint, the ORM and DDL agree.
"""
from env_generator.llm_generator.multi_agent.runtime.database_scaffold import (
    _promote_inline_modifiers, _columns_of, _render_column as ddl_render_column)
from env_generator.llm_generator.multi_agent.runtime.backend_skeleton import (
    _render_column as orm_render_column)


def _rendered(col):
    """Render one column through BOTH renderers exactly as the pipeline does — via the
    inline-modifier promotion _columns_of now applies — and return (orm_line, ddl_line)."""
    promoted = _promote_inline_modifiers(dict(col))
    return orm_render_column(dict(promoted)) or "", ddl_render_column("t", dict(promoted)) or ""


def test_not_null_parity():
    orm, ddl = _rendered({"name": "name", "type": "text not null"})
    assert "nullable=False" in orm, orm
    assert "NOT NULL" in ddl.upper(), ddl


def test_primary_key_parity():
    orm, ddl = _rendered({"name": "id", "type": "integer primary key"})
    assert "primary_key=True" in orm, orm
    assert "PRIMARY KEY" in ddl.upper(), ddl


def test_unique_parity():
    orm, ddl = _rendered({"name": "email", "type": "text unique"})
    assert "unique=True" in orm, orm
    assert "UNIQUE" in ddl.upper(), ddl


def test_references_parity():
    orm, ddl = _rendered({"name": "user_id", "type": "integer references users(id)"})
    assert "ForeignKey" in orm, orm
    assert "REFERENCES" in ddl.upper(), ddl


def test_plain_column_nullable_in_both():
    orm, ddl = _rendered({"name": "bio", "type": "text"})
    assert "nullable=False" not in orm
    assert "NOT NULL" not in ddl.upper()


def test_no_double_emit_when_already_structured():
    # a column with BOTH the inline modifier and the structured flag must emit once
    orm, ddl = _rendered({"name": "name", "type": "text not null", "not_null": True})
    assert ddl.upper().count("NOT NULL") == 1, ddl
    assert "nullable=False" in orm


def test_columns_of_promotes_canonical_columns_shape():
    cols = _columns_of({"schema": {"columns": [{"name": "name", "type": "text not null"}]}})
    assert cols[0].get("not_null") is True
    cols2 = _columns_of({"columns": [{"name": "id", "type": "int primary key"}]})
    assert cols2[0].get("primary_key") is True


def test_promote_is_copy_on_write_and_idempotent():
    src = {"name": "name", "type": "text not null"}
    out = _promote_inline_modifiers(src)
    assert "not_null" not in src            # caller's dict not mutated
    assert out.get("not_null") is True
    assert _promote_inline_modifiers(out) == out  # idempotent


# ---------------------------------------------------------------------------
# #497 (netflix r67, live): the DDL scaffolder's #407 heuristic gives a NOT-NULL
# no-default timestamp/date/time/bool column an UNAMBIGUOUS DB default
# (now()/CURRENT_DATE/CURRENT_TIME/false), but it synthesized that at DDL-render time
# only — the ORM Column emitted NO server_default, so models.py and 01_init.sql
# DIVERGED on created_at. That forced every create handler to hand-set
# created_at=datetime.utcnow(); any path that omitted it 400'd
# ``null value in column "created_at"`` and wedged business_chain. #497 mirrors the
# heuristic in the ORM renderer so BOTH agree and an omitting insert is safe.
# ---------------------------------------------------------------------------

def test_created_at_timestamp_default_parity_497():
    orm, ddl = _rendered({"name": "created_at", "type": "timestamp", "not_null": True})
    assert "server_default=_sa_text('now()')" in orm, orm
    assert "default=datetime.utcnow" in orm, orm
    assert "DEFAULT NOW()" in ddl.upper(), ddl


def test_created_at_timestamptz_default_parity_497():
    orm, ddl = _rendered({"name": "created_at", "type": "TIMESTAMPTZ", "nullable": False})
    assert "server_default=_sa_text('now()')" in orm, orm
    assert "DEFAULT NOW()" in ddl.upper(), ddl


def test_notnull_bool_default_parity_497():
    orm, ddl = _rendered({"name": "is_active", "type": "boolean", "not_null": True})
    assert "server_default=_sa_text('false')" in orm, orm
    assert "DEFAULT FALSE" in ddl.upper(), ddl


def test_notnull_date_default_parity_497():
    # CURRENT_DATE must be a SQL function server_default, NOT a quoted string literal.
    orm, ddl = _rendered({"name": "starts_on", "type": "date", "not_null": True})
    assert "server_default=_sa_text('current_date')" in orm, orm
    assert "'CURRENT_DATE'" not in orm, orm
    assert "CURRENT_DATE" in ddl.upper(), ddl


def test_nullable_timestamp_gets_no_synth_default_497():
    orm, ddl = _rendered({"name": "seen_at", "type": "timestamp"})
    assert "server_default" not in orm, orm
    assert "DEFAULT" not in ddl.upper(), ddl


def test_notnull_text_stays_required_no_invented_default_497():
    # text has no universal safe default — a required name/email must stay required.
    orm, ddl = _rendered({"name": "title", "type": "text", "not_null": True})
    assert "nullable=False" in orm, orm
    assert "server_default" not in orm, orm
    assert "DEFAULT" not in ddl.upper(), ddl


def test_notnull_pk_timestamp_excluded_from_synth_497():
    orm, _ = _rendered({"name": "id", "type": "timestamp", "primary_key": True})
    assert "server_default=_sa_text('now()')" not in orm, orm


def test_explicit_default_still_wins_over_synth_497():
    # a column that already carries an explicit default is untouched by the synth path.
    orm, ddl = _rendered({"name": "status", "type": "text", "not_null": True, "default": "active"})
    assert "default='active'" in orm or 'default="active"' in orm, orm
    assert "DEFAULT" in ddl.upper(), ddl


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
