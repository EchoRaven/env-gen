"""Deterministic seed-data generator (2026-06-21): every business table gets
realistic, FK-valid demo rows on first boot so the generated app's UI isn't blank
(youtube run #22 shipped with empty business tables → blank home feed). Login-able
demo users use the framework's real auth hash.

LOCAL-ONLY (agent/tests/ gitignored).
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.runtime.backend_skeleton import (  # noqa: E402
    render_seed_data, _seed_password_hash, _seed_topo_order, _models_meta,
    _SEED_PASSWORD, _SEED_PASSWORD_SALT)
from multi_agent.runtime.seed_audit import detect_placeholder_score  # noqa: E402


def _col(name, **kw):
    d = {"name": name}
    d.update(kw)
    return d


_TABLES = {
    "channels": {"schema": {"columns": [
        _col("id", primary_key=True), _col("owner_id", type="int", references="users.id"),
        _col("name", type="text"), _col("handle", type="text"), _col("description", type="text"),
        _col("avatar_url", type="text")]}},
    "videos": {"schema": {"columns": [
        _col("id", primary_key=True), _col("channel_id", type="int", references="channels.id"),
        _col("title", type="text"), _col("description", type="text"),
        _col("thumbnail_url", type="text"), _col("views", type="int"), _col("kind", type="text")]}},
    "comments": {"schema": {"columns": [
        _col("id", primary_key=True), _col("video_id", type="int", references="videos.id"),
        _col("user_id", type="int", references="users.id"), _col("text", type="text")]}},
}


class SeedGeneratorTests(unittest.TestCase):
    def setUp(self):
        self.src = render_seed_data(_TABLES)
        # Anchored to the assignment's OWN line. The previous greedy DOTALL form
        # (r"_SEED = (\{.*\})\n") ran to the LAST "}\n" anywhere in the file, so any
        # later emitted line ending in "}" swallowed the whole loader and took all 11
        # tests down in setUp with an unrelated SyntaxError.
        _m = re.search(r"^_SEED = (\{.*\})$", self.src, re.M)
        assert _m, "_SEED assignment not found in the rendered loader"
        self.seed = __import__("ast").literal_eval(_m.group(1))
        self.order = __import__("ast").literal_eval(re.search(r"_ORDER = (\[.*?\])\n", self.src).group(1))

    def test_generates_valid_python(self):
        ast.parse(self.src)
        self.assertIn("def seed_if_empty", self.src)
        self.assertIn("db.query(cls).first() is not None", self.src)  # idempotent guard

    def test_password_hash_matches_framework_scheme(self):
        # MUST equal oauth_store: sha256(password + salt). A drift here breaks logins.
        expected = hashlib.sha256(
            (_SEED_PASSWORD + _SEED_PASSWORD_SALT).encode()).hexdigest()
        self.assertEqual(_seed_password_hash(), expected)
        self.assertEqual(self.seed["users"][0]["password_hash"], expected)

    def test_users_are_loginable_shape(self):
        u = self.seed["users"][0]
        self.assertIn("@example.com", u["email"])
        self.assertEqual(u["tenant_id"], "default")
        self.assertTrue(u["password_hash"])
        self.assertGreaterEqual(len(self.seed["users"]), 5)

    def test_fk_topo_order_parents_before_children(self):
        # users → channels → videos → comments
        self.assertLess(self.order.index("channels"), self.order.index("videos"))
        self.assertLess(self.order.index("videos"), self.order.index("comments"))

    def test_fk_columns_reference_existing_parent_ids(self):
        for v in self.seed["videos"]:
            self.assertIn(v["channel_id"], range(1, 7))  # channels has 6 rows
        for c in self.seed["comments"]:
            self.assertIn(c["video_id"], range(1, 7))
            self.assertIn(c["user_id"], range(1, 6))  # users has 5

    def test_no_placeholder_words(self):
        for t, rows in self.seed.items():
            self.assertLess(detect_placeholder_score(rows), 0.5,
                            f"{t} rows look placeholder-y")

    def test_realistic_values(self):
        v = self.seed["videos"][0]
        self.assertTrue(v["title"] and "test" not in v["title"].lower())
        # Seeded media is a self-contained data: URI, not an http(s) URL. The
        # generator used to emit https://picsum.photos/...: the sandbox cannot
        # reach it, so every page rendering a poster logged
        # net::ERR_TUNNEL_CONNECTION_FAILED, the console errors failed the
        # UI-evidence gate, and r161 died on it. A local /assets/ path would 404
        # for any row the staged pool misses — the same error in different
        # clothes. The property to pin is that it RESOLVES with no network.
        self.assertTrue(v["thumbnail_url"].startswith("data:image/"),
                        v["thumbnail_url"][:60])
        self.assertNotIn("picsum", v["thumbnail_url"])
        self.assertIsInstance(v["views"], int)

    def test_seed_values_are_domain_neutral(self):
        # GENERALITY: the seed must not inject video/music-platform vocabulary into
        # generic columns (kind/type/visibility/title) — it biases every generated app.
        v = self.seed["videos"][0]
        self.assertNotIn(v.get("kind"), ("video", "short"), "kind seeded with a youtube enum")
        titles = " ".join(str(r.get("title", "")) for r in self.seed["videos"])
        for biased in ("Sunrise Timelapse", "Behind the Scenes", "Calm Morning"):
            self.assertNotIn(biased, titles, "title pool is video-platform shaped")
        # but it still provides a real (non-null, non-placeholder) title so the UI fills
        self.assertTrue(v.get("title") and "test" not in v["title"].lower())

    def test_pk_and_timestamps_omitted(self):
        # PK is SERIAL, created_at is DB default → not in seed rows
        for rows in self.seed.values():
            for r in rows:
                self.assertNotIn("id", r)
                self.assertNotIn("created_at", r)

    def test_fk_matches_text_pk_parent(self):
        # a parent table with a TEXT primary key: the child FK must reference the parent's
        # actual string key, not an integer 1..N (which would type-mismatch / not exist).
        tables = {
            "workspaces": {"schema": {"columns": [
                _col("id", primary_key=True, type="text"), _col("name", type="text")]}},
            "boards": {"schema": {"columns": [
                _col("id", primary_key=True),
                _col("workspace_id", type="text", references="workspaces.id"),
                _col("title", type="text")]}},
        }
        src = render_seed_data(tables)
        # Same anchored form as setUp. The greedy DOTALL version that used to be here
        # runs to the LAST "}" anywhere in the file and swallows the rest of the
        # loader, so literal_eval died with an unrelated SyntaxError at line 2.
        _m = re.search(r"^_SEED = (\{.*\})$", src, re.M)
        assert _m, "_SEED assignment not found in the rendered loader"
        seed = ast.literal_eval(_m.group(1))
        # parent's text PK is seeded as a string (not omitted as a SERIAL)
        self.assertTrue(seed["workspaces"] and all(isinstance(w["id"], str) for w in seed["workspaces"]))
        parent_ids = {w["id"] for w in seed["workspaces"]}
        # every child FK references an existing parent string key
        for b in seed["boards"]:
            self.assertIsInstance(b["workspace_id"], str)
            self.assertIn(b["workspace_id"], parent_ids)

    def test_topo_handles_self_ref_and_cycle(self):
        meta = _models_meta({
            "a": {"schema": {"columns": [_col("id", primary_key=True),
                                         _col("parent_id", references="a.id"),
                                         _col("b_id", references="b.id")]}},
            "b": {"schema": {"columns": [_col("id", primary_key=True),
                                         _col("a_id", references="a.id")]}},
        })
        order = _seed_topo_order(meta)  # must terminate despite the a↔b cycle + self-ref
        self.assertTrue({"a", "b"} <= set(order))  # spine 'users' is also present
        self.assertEqual(len(order), len(set(order)))  # no dupes, terminated cleanly


if __name__ == "__main__":
    unittest.main()
