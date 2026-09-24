"""Guard: FIX #196 — provision missing association tables for interaction actions.

r6 verified root: schema had a `likes` INTEGER COUNTER column on videos/comments
but NO join table, yet the lane registered POST /api/videos/{id}/like → the
projector's #124 404s the action (no model to insert into) → business_chain
wedges → 75-min no-convergence abort. The like BUTTON 404s (non-functional →
violates the no-placeholder bar).

Verified fix boundary: the route_projector needs NO change — _resource_model
resolves 'like'→a `likes` model, _target_fk binds video_id, _owner_fk binds
user_id, and it inserts. So provisioning the join table (named to match the
action segment) makes the EXISTING machinery handle the endpoint end-to-end.
Scope: user→content verbs (like/save/favorite/bookmark/...); follow/subscribe/
block (user→user, dual-role FKs) are EXCLUDED as ambiguous and left as-is.
"""

import sys
import unittest
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.backend_skeleton import (  # noqa: E402
    interaction_tables_to_provision,
)


def _ep(method, path):
    return {"method": method, "path": path}


def _tbl(name, cols):
    return {"name": name, "schema": {"columns": cols}}


_USERS = _tbl("users", [{"name": "id", "primary_key": True, "type": "text"}])
_VIDEOS = _tbl("videos", [{"name": "id", "primary_key": True, "type": "text"},
                          {"name": "likes", "type": "integer"}])


class DetectionTests(unittest.TestCase):
    def test_like_action_with_no_join_table_provisions(self):
        eps = [_ep("POST", "/api/videos/{id}/like")]
        tables = {"users": _USERS, "videos": _VIDEOS}
        out = interaction_tables_to_provision(eps, tables)
        self.assertEqual(len(out), 1)
        t = out[0]
        self.assertEqual(t["name"], "likes")
        colnames = {c["name"] for c in t["schema"]["columns"]}
        self.assertIn("user_id", colnames)
        self.assertIn("video_id", colnames)
        self.assertTrue(any(c.get("primary_key") for c in t["schema"]["columns"]))
        # FKs point at the right parents
        fk = {c["name"]: c.get("references") for c in t["schema"]["columns"]}
        self.assertEqual(fk["user_id"], "users.id")
        self.assertEqual(fk["video_id"], "videos.id")

    def test_existing_join_table_skips(self):
        eps = [_ep("POST", "/api/videos/{id}/like")]
        likes = _tbl("likes", [{"name": "id", "primary_key": True, "type": "text"},
                               {"name": "user_id", "references": "users.id", "type": "text"},
                               {"name": "video_id", "references": "videos.id", "type": "text"}])
        tables = {"users": _USERS, "videos": _VIDEOS, "likes": likes}
        self.assertEqual(interaction_tables_to_provision(eps, tables), [])

    def test_parent_prefixed_join_table_skips_no_duplicate(self):
        # the lane modeled `video_likes` (descriptive) — #196 must NOT provision a
        # duplicate `likes`. #196 provisions IFF #198 can't resolve an existing
        # join; video_likes is exactly what #198 resolves, so skip.
        eps = [_ep("POST", "/api/videos/{id}/like")]
        vl = _tbl("video_likes", [
            {"name": "id", "primary_key": True, "type": "integer"},
            {"name": "user_id", "references": "users.id", "type": "integer"},
            {"name": "video_id", "references": "videos.id", "type": "text"}])
        tables = {"users": _USERS, "videos": _VIDEOS, "video_likes": vl}
        self.assertEqual(interaction_tables_to_provision(eps, tables), [])

    def test_comments_content_table_is_not_mistaken_for_like_join(self):
        # comments has user_id + video_id FKs too, but it's a CONTENT table, not a
        # like join — its name doesn't contain the verb → still provision `likes`.
        eps = [_ep("POST", "/api/videos/{id}/like")]
        comments = _tbl("comments", [
            {"name": "id", "primary_key": True, "type": "integer"},
            {"name": "user_id", "references": "users.id", "type": "integer"},
            {"name": "video_id", "references": "videos.id", "type": "text"},
            {"name": "text", "type": "text"}])
        tables = {"users": _USERS, "videos": _VIDEOS, "comments": comments}
        out = interaction_tables_to_provision(eps, tables)
        self.assertEqual([t["name"] for t in out], ["likes"])

    def test_counter_column_named_likes_does_not_count_as_join_table(self):
        # videos.likes is an INT counter — NOT a join table; must still provision.
        eps = [_ep("POST", "/api/videos/{id}/like")]
        tables = {"users": _USERS, "videos": _VIDEOS}
        out = interaction_tables_to_provision(eps, tables)
        self.assertEqual(len(out), 1)

    def test_follow_user_to_user_provisions_follows(self):
        # #204: follow is no longer excluded — it provisions a self-referential
        # `follows` (follower_id + followed_id → users), NOT a content-verb table.
        eps = [_ep("POST", "/api/users/{id}/follow")]
        out = interaction_tables_to_provision(eps, {"users": _USERS})
        self.assertEqual([t["name"] for t in out], ["follows"])
        cols = {c["name"] for c in out[0]["schema"]["columns"]}
        self.assertIn("follower_id", cols)
        self.assertIn("followed_id", cols)

    def test_multi_parent_like_single_table_both_fks(self):
        eps = [_ep("POST", "/api/videos/{id}/like"),
               _ep("POST", "/api/comments/{id}/like")]
        comments = _tbl("comments", [{"name": "id", "primary_key": True, "type": "text"}])
        tables = {"users": _USERS, "videos": _VIDEOS, "comments": comments}
        out = interaction_tables_to_provision(eps, tables)
        self.assertEqual(len(out), 1)  # one `likes` table
        cols = {c["name"] for c in out[0]["schema"]["columns"]}
        self.assertIn("video_id", cols)
        self.assertIn("comment_id", cols)

    def test_save_and_like_two_tables(self):
        eps = [_ep("POST", "/api/videos/{id}/like"),
               _ep("POST", "/api/videos/{id}/save")]
        tables = {"users": _USERS, "videos": _VIDEOS}
        out = interaction_tables_to_provision(eps, tables)
        self.assertEqual({t["name"] for t in out}, {"likes", "saves"})

    def test_no_interaction_endpoints_is_empty(self):
        eps = [_ep("GET", "/api/videos"), _ep("POST", "/api/videos")]
        tables = {"users": _USERS, "videos": _VIDEOS}
        self.assertEqual(interaction_tables_to_provision(eps, tables), [])

    def test_unlike_shares_the_like_table_no_dup(self):
        eps = [_ep("POST", "/api/videos/{id}/like"),
               _ep("POST", "/api/videos/{id}/unlike")]
        tables = {"users": _USERS, "videos": _VIDEOS}
        out = interaction_tables_to_provision(eps, tables)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["name"], "likes")

    def test_unknown_parent_table_skipped(self):
        # action on a resource with no table → can't wire the FK, skip
        eps = [_ep("POST", "/api/widgets/{id}/like")]
        tables = {"users": _USERS, "videos": _VIDEOS}
        self.assertEqual(interaction_tables_to_provision(eps, tables), [])


class ProjectionEndToEndTests(unittest.TestCase):
    """The whole point: once the table is provisioned, the EXISTING projector
    resolves the action segment and emits a REAL insert handler (no 404)."""

    def _models_from(self, tables):
        models = {}
        for name, t in tables.items():
            cols = [c["name"] for c in t["schema"]["columns"]]
            fks = {c["name"]: str(c.get("references", "")).split(".")[0]
                   for c in t["schema"]["columns"] if c.get("references")}
            cls = "".join(w.capitalize() for w in name.rstrip("s").split("_")) or name
            models[name] = {"cls": cls, "cols": cols, "fks": fks}
        return models

    def test_provisioned_table_yields_real_insert_handler(self):
        from multi_agent.runtime import route_projector as rp
        eps = [_ep("POST", "/api/videos/{id}/like")]
        tables = {"users": _USERS, "videos": _VIDEOS}
        for spec in interaction_tables_to_provision(eps, tables):
            tables[spec["name"]] = spec
        models = self._models_from(tables)
        # the action segment resolves to the provisioned model
        res = rp._resource_model("/api/videos/{id}/like", models)
        self.assertIsNotNone(res)
        self.assertEqual(res[0], "likes")
        handler = rp._generate_handler(
            "POST", "/api/videos/{id}/like", True, models, 0)
        # a real insert — NOT the #124 "action endpoint not implemented" 404
        self.assertNotIn("not implemented by the projection", handler)
        self.assertIn('valid["video_id"] = _parent.id', handler)
        self.assertIn("_fw_owner_val(Like", handler)
        self.assertIn("db.add(obj)", handler)

    def test_skeleton_write_includes_provisioned_model(self):
        import tempfile
        from multi_agent.runtime.backend_skeleton import (
            write_backend_skeleton, render_models)
        eps = [{"method": "POST", "path": "/api/videos/{id}/like",
                "auth_required": True}]
        tables = {"videos": {"name": "videos", "schema": {"columns": [
            {"name": "id", "primary_key": True, "type": "text"}]}}}
        td = Path(tempfile.mkdtemp())
        write_backend_skeleton(td, eps, tables)
        models_src = (td / "app" / "backend" / "models.py").read_text()
        self.assertIn("class Like", models_src)
        self.assertIn("video_id", models_src)


if __name__ == "__main__":
    unittest.main()
