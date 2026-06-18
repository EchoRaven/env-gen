"""Guard: generated DB schema is referentially type-consistent by construction
(PROPOSAL #3). youtube run #16: `channels.id` was text while every `*.channel_id`
FK was integer → `CREATE TABLE videos` aborted (incompatible FK types) → postgres
exit 3 → docker_up FAIL → no delivery.

Two layers:
  L1 (backend_skeleton._reconcile_fk_types_in_map / render_models): coerce FK type
     conflicts toward the majority referencing-FK type in the ORM itself.
  L3 (database_scaffold._ddl_type_from_introspect): the DDL backstop — emit the PK
     clause for ANY pk type, and render an FK with the referenced PK's type.

The framework `tenants.id TEXT PRIMARY KEY` (referenced only by text `tenant_id`)
must NEVER be coerced — exemption by construction (uniform type / spine target).
"""

import sys
import unittest
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.database_scaffold import (  # noqa: E402
    _ddl_type_from_introspect, _ddl_base_type,
)
from multi_agent.runtime.backend_skeleton import (  # noqa: E402
    _reconcile_fk_types_in_map, _fk_type_category, render_models,
)


class L3DdlTypeTests(unittest.TestCase):
    """database_scaffold._ddl_type_from_introspect — the DDL backstop."""

    def test_integer_pk_is_serial(self):
        self.assertEqual(
            _ddl_type_from_introspect({"name": "id", "type": "INTEGER", "pk": True}, {}),
            "serial primary key")

    def test_non_integer_pk_keeps_primary_key_clause(self):
        # Bug 1: a text/uuid PK must NOT lose its `primary key`.
        self.assertEqual(
            _ddl_type_from_introspect({"name": "id", "type": "VARCHAR", "pk": True}, {}),
            "text primary key")
        self.assertEqual(
            _ddl_type_from_introspect({"name": "id", "type": "UUID", "pk": True}, {}),
            "uuid primary key")

    def test_fk_type_follows_referenced_pk(self):
        # Bug 2: FK column type = the referenced PK's type, not always integer.
        pk = {"channels": "integer", "tenants": "text"}
        self.assertEqual(
            _ddl_type_from_introspect({"name": "channel_id", "type": "INTEGER", "fk": "channels.id"}, pk),
            "integer references channels(id) on delete cascade")
        self.assertEqual(
            _ddl_type_from_introspect({"name": "tenant_id", "type": "VARCHAR", "fk": "tenants.id"}, pk),
            "text references tenants(id) on delete cascade")

    def test_fk_unknown_target_defaults_integer(self):
        self.assertEqual(
            _ddl_type_from_introspect({"name": "x_id", "type": "INTEGER", "fk": "x.id"}, {}),
            "integer references x(id) on delete cascade")

    def test_plain_columns_unchanged(self):
        self.assertEqual(_ddl_type_from_introspect({"name": "n", "type": "TEXT"}, {}), "text")
        self.assertEqual(_ddl_type_from_introspect({"name": "f", "type": "BOOLEAN"}, {}), "boolean default false")
        self.assertEqual(_ddl_type_from_introspect({"name": "c", "type": "DATETIME"}, {}), "timestamptz default now()")


class L1ReconcileTests(unittest.TestCase):
    """backend_skeleton._reconcile_fk_types_in_map — the ORM-level (runtime-truth) fix."""

    def test_channels_id_coerced_to_integer_fk_majority(self):
        by_name = {
            "channels": [{"name": "id", "type": "text", "primary_key": True},
                         {"name": "name", "type": "text"}],
            "videos": [{"name": "id", "type": "integer", "primary_key": True},
                       {"name": "channel_id", "type": "integer", "references": "channels.id"}],
        }
        _reconcile_fk_types_in_map(by_name)
        ch_id = next(c for c in by_name["channels"] if c["name"] == "id")
        self.assertEqual(_fk_type_category(ch_id["type"]), "integer")  # text -> integer
        self.assertTrue(ch_id.get("primary_key"))

    def test_uniform_text_pk_is_left_intact(self):
        # A business table whose id is text AND all FKs to it are text → consistent
        # → must NOT be coerced (the tenants-style exemption, generalized).
        by_name = {
            "orgs": [{"name": "id", "type": "text", "primary_key": True}],
            "members": [{"name": "id", "type": "integer", "primary_key": True},
                        {"name": "org_id", "type": "text", "references": "orgs.id"}],
        }
        _reconcile_fk_types_in_map(by_name)
        org_id = next(c for c in by_name["orgs"] if c["name"] == "id")
        self.assertEqual(_fk_type_category(org_id["type"]), "text")  # untouched

    def test_fk_to_spine_target_is_skipped(self):
        # FK targeting users/tenants (not in the app-table map) → skipped, so the
        # framework tenants.id TEXT PK exemption holds by construction.
        by_name = {
            "channels": [{"name": "id", "type": "integer", "primary_key": True},
                         {"name": "tenant_id", "type": "text", "references": "tenants.id"},
                         {"name": "user_id", "type": "integer", "references": "users.id"}],
        }
        before = [dict(c) for c in by_name["channels"]]
        _reconcile_fk_types_in_map(by_name)
        self.assertEqual(by_name["channels"], before)  # nothing coerced

    def test_render_models_end_to_end_tenants_intact(self):
        # The reviewer-required regression: a framework text-PK table is left intact
        # while the conflicting business id is fixed.
        tables = {
            "channels": {"name": "channels", "columns": [
                {"name": "id", "type": "text", "primary_key": True},
                {"name": "tenant_id", "type": "text", "references": "tenants.id"}]},
            "videos": {"name": "videos", "columns": [
                {"name": "id", "type": "integer", "primary_key": True},
                {"name": "channel_id", "type": "integer", "references": "channels.id"}]},
        }
        src = render_models(tables)
        # channels.id fixed to Integer; the spine Tenant.id stays Text; channels FK
        # to tenants stays Text (text->text, never coerced).
        import re
        self.assertRegex(src, r"class Channel\b[\s\S]*?id = Column\(Integer, primary_key=True\)")
        self.assertRegex(src, r"class Tenant\b[\s\S]*?id = Column\(Text")
        self.assertIn('tenant_id = Column(Text, ForeignKey("tenants.id")', src)


if __name__ == "__main__":
    unittest.main()
