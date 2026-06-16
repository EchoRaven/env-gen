"""Guard: a table re-registered via the FLAT-MAP contract-tool schema
(``{column: "type string"}``) must project ALL its columns — with correct
types + FKs — into the ORM and the DDL, not collapse to an id-only table.

Root cause this guards (youtube run's 500s + chain 404s): the contract tools
``registryhub_register_table`` / ``registryhub_update_table_schema`` advertise a
flat-map schema, ``register_table`` stored it verbatim, and
``database_scaffold._columns_of`` only understood ``{"columns":[...]}`` — so a
flat-map table became an id-only ORM model + DDL with every other column
silently dropped. The fix normalizes ANY accepted shape to ONE canonical
``{"columns":[...]}`` at the write boundary (and ``_columns_of`` tolerates the
raw flat map as defense in depth).

Domain-neutral: column names are arbitrary examples, not load-bearing.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from multi_agent.runtime.database_scaffold import (  # noqa: E402
    _columns_of,
    normalize_table_schema,
    render_schema_sql,
)
from multi_agent.runtime.backend_skeleton import render_models  # noqa: E402


# A flat-map schema as the contract tools advertise it: ``{col: "type string"}``
# with modifiers inline in the type string. Arbitrary domain.
_FLAT_MAP = {
    "id": "serial primary key",
    "title": "text",
    "channel_id": "integer references channels(id)",
    "views": "integer",
}


def _hub(td: str):
    # PR 5: table surface lives on SchemaHub (== RegistryHub instance).
    return HubRegistry(Path(td)).schema_hub


class TestNormalizer(unittest.TestCase):
    def test_flat_map_normalizes_to_canonical_columns(self):
        canon = normalize_table_schema(_FLAT_MAP)
        self.assertIn("columns", canon)
        by_name = {c["name"]: c for c in canon["columns"]}
        self.assertEqual(set(by_name), {"id", "title", "channel_id", "views"})
        # Inline modifiers promoted to structured flags (so the ORM renderer
        # — which keys PK/FK off the flags — projects them faithfully).
        self.assertTrue(by_name["id"].get("primary_key"))
        self.assertEqual(by_name["channel_id"].get("references"), "channels(id)")
        # Full type string is preserved verbatim for the DDL renderer.
        self.assertIn("references channels(id)", by_name["channel_id"]["type"])

    def test_columns_list_form_passes_through_unchanged(self):
        cols = [{"name": "id", "type": "integer"}, {"name": "x", "type": "text"}]
        canon = normalize_table_schema({"columns": cols})
        # Idempotent: canonical input round-trips structurally equal.
        self.assertEqual(canon, {"columns": cols})

    def test_bare_list_form_wrapped(self):
        cols = [{"name": "id", "type": "integer"}]
        self.assertEqual(normalize_table_schema(cols), {"columns": cols})

    def test_columns_of_tolerates_raw_flat_map_store_row(self):
        # Defense in depth: a row that bypassed the write boundary and holds a
        # raw flat-map schema still yields all its columns via _columns_of.
        row = {"name": "videos", "schema": dict(_FLAT_MAP)}
        names = {c["name"] for c in _columns_of(row)}
        self.assertEqual(names, {"id", "title", "channel_id", "views"})


class TestFlatMapProjects(unittest.TestCase):
    def _register_flat(self, hub, name="videos"):
        return hub.register_table(
            name=name, schema=dict(_FLAT_MAP),
            provider="backend", agent="backend",
        )

    def test_flat_map_register_then_ddl_has_all_columns_and_fk(self):
        with tempfile.TemporaryDirectory() as td:
            hub = _hub(td)
            self._register_flat(hub)
            tables = hub.list_tables()
            ddl = render_schema_sql(tables)
            # All four columns present (NOT just id).
            for col in ("id", "title", "channel_id", "views"):
                self.assertIn(f'"{col}"', ddl,
                              msg=f"DDL dropped column {col!r}:\n{ddl}")
            # FK preserved into the DDL (inline ``references`` survives).
            self.assertRegex(ddl, r"references\s+channels\s*\(\s*id\s*\)")

    def test_flat_map_register_then_orm_has_all_columns_and_fk(self):
        with tempfile.TemporaryDirectory() as td:
            hub = _hub(td)
            self._register_flat(hub)
            tables = hub.list_tables()
            models_py = render_models(tables)
            # The model class exists with every business column (NOT id-only).
            self.assertIn("title = Column(", models_py)
            self.assertIn("channel_id = Column(", models_py)
            self.assertIn("views = Column(", models_py)
            # FK projected onto the ORM column.
            self.assertIn('ForeignKey("channels.id")', models_py)

    def test_columns_list_form_still_projects_no_regression(self):
        with tempfile.TemporaryDirectory() as td:
            hub = _hub(td)
            hub.register_table(
                name="videos",
                schema={"columns": [
                    {"name": "id", "type": "serial", "primary_key": True},
                    {"name": "title", "type": "text"},
                    # Inline FK in the type — the form the DDL renderer honors
                    # (the canonical/kickoff path carries FKs this way too).
                    {"name": "channel_id", "type": "integer references channels(id)"},
                    {"name": "views", "type": "integer"},
                ]},
                provider="backend", agent="backend",
            )
            ddl = render_schema_sql(hub.list_tables())
            for col in ("id", "title", "channel_id", "views"):
                self.assertIn(f'"{col}"', ddl)
            self.assertRegex(ddl, r"references\s+channels\s*\(\s*id\s*\)")

    def test_flat_map_update_table_schema_round_trips(self):
        with tempfile.TemporaryDirectory() as td:
            hub = _hub(td)
            hub.register_table(
                name="videos",
                schema={"id": "serial primary key", "title": "text"},
                provider="backend", agent="backend",
            )
            # Evolve via the flat-map update tool path (adds two columns).
            hub.update_table_schema("videos", dict(_FLAT_MAP), agent="backend")
            stored = hub.get_table("videos")
            # Stored shape is canonical, and ALL columns survive the round-trip.
            self.assertIn("columns", stored["schema"])
            names = {c["name"] for c in stored["schema"]["columns"]}
            self.assertEqual(names, {"id", "title", "channel_id", "views"})
            ddl = render_schema_sql(hub.list_tables())
            for col in ("id", "title", "channel_id", "views"):
                self.assertIn(f'"{col}"', ddl)


if __name__ == "__main__":
    unittest.main()
