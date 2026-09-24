"""Contract completeness: a large app's backend lane often registers many business
ENDPOINTS but tables for only a few resources. The unbacked resources project to
valid-shape STUB handlers -> the synthesized business_chain create/list/read cycle
wedges -> STUCK-ABORT (live youtube 2026-06-20: 20 business endpoints, 1 table).

synthesize_missing_tables derives a backing table for every creatable COLLECTION
resource (param-less POST /api/<col>) that has no registered table, using EXACTLY
synthesize_default_chain's predicate so the table side and the chain side agree by
construction (no nested resources, no action verbs like POST /api/videos/{id}/like).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.runtime.database_scaffold import (  # noqa: E402
    synthesize_missing_tables)


def _ep(path, method="POST", kind=None, request=None):
    e = {"path": path, "method": method}
    if kind:
        e["metadata"] = {"kind": kind}
    if request is not None:
        e["schema"] = {"request": request}
    return e


def _derived(tables):
    return sorted(k for k, v in tables.items()
                  if isinstance(v, dict) and (v.get("metadata") or {}).get("derived"))


def _cols(t):
    return {c["name"]: c for c in t["schema"]["columns"]}


class SynthesizeMissingTablesTests(unittest.TestCase):
    def test_missing_collection_resource_gets_table(self):
        out = synthesize_missing_tables({}, [_ep("/api/videos")])
        self.assertEqual(_derived(out), ["videos"])
        cols = _cols(out["videos"])
        self.assertTrue(cols["id"]["primary_key"])
        self.assertEqual(cols["user_id"]["references"], "users.id")

    def test_request_schema_fields_become_columns(self):
        # registryhub stores request as a flat {field: "str"|"int?"|...} map.
        out = synthesize_missing_tables({}, [_ep(
            "/api/posts", request={
                "title": "str", "views": "int", "public": "bool"})])
        cols = _cols(out["posts"])
        self.assertEqual(cols["title"]["type"], "text")
        self.assertEqual(cols["views"]["type"], "int")
        self.assertEqual(cols["public"]["type"], "bool")

    def test_existing_table_not_overridden(self):
        existing = {"videos": {"name": "videos",
                               "schema": {"columns": [{"name": "id", "type": "int"}]}}}
        out = synthesize_missing_tables(existing, [_ep("/api/videos")])
        self.assertEqual(_derived(out), [])  # untouched
        self.assertIs(out["videos"], existing["videos"])

    def test_action_verb_endpoint_skipped(self):
        # POST /api/videos/{id}/like is an action, not a collection -> no 'like' table.
        out = synthesize_missing_tables({}, [_ep("/api/videos/{videoId}/like")])
        self.assertEqual(_derived(out), [])

    def test_nested_resource_skipped(self):
        # parametrized path -> not a param-less collection -> skipped (agrees w/ chain).
        out = synthesize_missing_tables({}, [_ep("/api/videos/{videoId}/comments")])
        self.assertEqual(_derived(out), [])

    def test_non_post_skipped(self):
        out = synthesize_missing_tables({}, [_ep("/api/videos", method="GET")])
        self.assertEqual(_derived(out), [])

    def test_fixed_kind_skipped(self):
        out = synthesize_missing_tables({}, [_ep("/api/sessions", kind="auth")])
        self.assertEqual(_derived(out), [])

    def test_spine_resource_skipped(self):
        out = synthesize_missing_tables({}, [_ep("/api/users"), _ep("/api/tenants")])
        self.assertEqual(_derived(out), [])

    def test_non_api_skipped(self):
        out = synthesize_missing_tables({}, [_ep("/videos")])
        self.assertEqual(_derived(out), [])

    def test_idempotent(self):
        eps = [_ep("/api/videos"), _ep("/api/playlists")]
        once = synthesize_missing_tables({}, eps)
        twice = synthesize_missing_tables(once, eps)
        self.assertEqual(sorted(once), sorted(twice))
        self.assertEqual(_derived(once), ["playlists", "videos"])


if __name__ == "__main__":
    unittest.main()
