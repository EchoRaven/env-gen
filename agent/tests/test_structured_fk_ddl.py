"""Guard: a column that carries its foreign key as a STRUCTURED field
(``references`` / ``fk``, not inline in the ``type`` string) must render a
``REFERENCES`` constraint in the generated CREATE TABLE DDL.

Root cause this guards: ``database_scaffold._render_column`` emitted a FK only
when it was written INLINE in the column's ``type`` (``"integer references
users(id)"``). But kickoff_declare_table / ``normalize_columns`` / re-registered
flat-map tables produce the FK as a STRUCTURED field
(``{"name":"owner_id","type":"integer","references":"users(id)"}`` or ``{"fk":
"users.id"}`` or ``{"references":{"table":"users","column":"id"}}``). Those
structured FKs were silently dropped from the DDL → schemas missing real foreign
keys → no referential integrity. The ORM renderer
(``backend_skeleton._fk_target``) already read structured FKs; this guards DDL
parity.

Domain-neutral: ``owner_id``/``users``/``teams`` are arbitrary example names,
not load-bearing.
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.runtime.database_scaffold import (  # noqa: E402
    _structured_fk_ref,
    render_schema_sql,
)


def _widgets(*cols):
    return {"widgets": {"name": "widgets", "schema": {"columns": list(cols)}}}


def _widgets_block(ddl: str) -> str:
    """Slice out just the business ``widgets`` CREATE TABLE (so spine FKs like
    ``users.tenant_id REFERENCES tenants`` can't satisfy an assertion)."""
    i = ddl.index('CREATE TABLE IF NOT EXISTS "widgets"')
    return ddl[i:]


class TestStructuredFkExtraction(unittest.TestCase):
    def test_references_string_table_paren_col(self):
        self.assertEqual(_structured_fk_ref({"references": "users(id)"}), ("users", "id"))

    def test_references_string_dotted(self):
        self.assertEqual(_structured_fk_ref({"references": "users.id"}), ("users", "id"))

    def test_fk_field_dotted(self):
        self.assertEqual(_structured_fk_ref({"fk": "users.id"}), ("users", "id"))

    def test_references_nested_dict(self):
        self.assertEqual(
            _structured_fk_ref({"references": {"table": "teams", "column": "id"}}),
            ("teams", "id"),
        )

    def test_bare_table_defaults_to_id(self):
        self.assertEqual(_structured_fk_ref({"fk": "orgs"}), ("orgs", "id"))

    def test_no_fk_returns_none(self):
        self.assertIsNone(_structured_fk_ref({"type": "integer"}))

    def test_inline_in_type_is_not_treated_as_structured(self):
        # Inline FK lives in the type string, NOT a structured field → None here
        # (the inline render path owns it; this keeps the two from double-emitting).
        self.assertIsNone(_structured_fk_ref({"type": "integer references users(id)"}))


class TestStructuredFkDDL(unittest.TestCase):
    def test_structured_references_renders_fk(self):
        ddl = render_schema_sql(_widgets(
            {"name": "id", "type": "serial", "primary_key": True},
            {"name": "owner_id", "type": "integer", "references": "users(id)"},
        ))
        block = _widgets_block(ddl)
        self.assertIn('"owner_id"', block)
        # FK constraint emitted (quoting is incidental — match the REFERENCES + target).
        self.assertRegex(
            block, r'"owner_id"[^,]*REFERENCES\s+"?users"?\s*\(\s*"?id"?\s*\)',
            msg=f"structured FK dropped from DDL:\n{block}",
        )

    def test_structured_fk_field_renders_fk(self):
        ddl = render_schema_sql(_widgets(
            {"name": "id", "type": "serial", "primary_key": True},
            {"name": "parent_id", "type": "integer", "fk": "users.id"},
        ))
        block = _widgets_block(ddl)
        self.assertRegex(
            block, r'"parent_id"[^,]*REFERENCES\s+"?users"?\s*\(\s*"?id"?\s*\)',
            msg=f"structured ``fk`` field dropped from DDL:\n{block}",
        )

    def test_structured_nested_dict_renders_fk(self):
        ddl = render_schema_sql(_widgets(
            {"name": "id", "type": "serial", "primary_key": True},
            {"name": "team_id", "type": "integer",
             "references": {"table": "teams", "column": "id"}},
        ))
        block = _widgets_block(ddl)
        self.assertRegex(
            block, r'"team_id"[^,]*REFERENCES\s+"?teams"?\s*\(\s*"?id"?\s*\)',
            msg=f"nested-dict structured FK dropped from DDL:\n{block}",
        )

    def test_inline_in_type_still_renders_no_regression(self):
        ddl = render_schema_sql(_widgets(
            {"name": "id", "type": "serial", "primary_key": True},
            {"name": "channel_id", "type": "integer references channels(id)"},
        ))
        block = _widgets_block(ddl)
        self.assertRegex(block, r"references\s+channels\s*\(\s*id\s*\)")

    def test_no_double_emit_when_inline_and_structured_agree(self):
        # A column may carry the FK both inline AND structured (the flat-map
        # normalizer does exactly this). Only ONE REFERENCES clause must appear.
        ddl = render_schema_sql(_widgets(
            {"name": "id", "type": "serial", "primary_key": True},
            {"name": "channel_id", "type": "integer references channels(id)",
             "references": "channels(id)"},
        ))
        block = _widgets_block(ddl)
        # Count REFERENCES on the channel_id line only.
        line = next(l for l in block.splitlines() if '"channel_id"' in l)
        self.assertEqual(len(re.findall(r"references", line, re.IGNORECASE)), 1,
                         msg=f"double-emitted FK on:\n{line}")

    def test_column_without_fk_renders_none(self):
        ddl = render_schema_sql(_widgets(
            {"name": "id", "type": "serial", "primary_key": True},
            {"name": "count", "type": "integer"},
        ))
        block = _widgets_block(ddl)
        count_line = next(l for l in block.splitlines() if '"count"' in l)
        self.assertNotRegex(count_line, r"references", )


if __name__ == "__main__":
    unittest.main()
