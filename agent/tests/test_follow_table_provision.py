"""Guard: FIX #204 — provision the user→user `follows` join so the follow button works.

r12 live: business_chain walled on `POST /api/users/3/follow → 404`. Root: #196
deliberately EXCLUDED user→USER verbs (dual-role FKs), so no `follows` table was
provisioned; the lane didn't model one either; and a follow-404 is a
business_chain failure (not a stub_handler), so #201's "declare the table"
remediation never fires → the follow button never works.

Verified: the projector ALREADY serves POST /api/users/{id}/follow correctly
when a `follows` table with follower_id + followed_id (both → users) exists —
_target_fk picks followed_id (∈ _TARGET_FK_NAMES) for the path user,
_owner_fk picks follower_id for the caller. So provisioning that table closes
the last interaction endpoint. Like/save (user→content) stay via #196.
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
from multi_agent.runtime import route_projector as rp  # noqa: E402


def _ep(method, path):
    return {"method": method, "path": path}


_USERS = {"name": "users", "schema": {"columns": [
    {"name": "id", "primary_key": True, "type": "integer"}]}}


class FollowProvisionTests(unittest.TestCase):
    def test_follow_provisions_follows_dual_user_fk(self):
        out = interaction_tables_to_provision(
            [_ep("POST", "/api/users/{id}/follow")], {"users": _USERS})
        follows = [t for t in out if t["name"] == "follows"]
        self.assertEqual(len(follows), 1)
        cols = {c["name"]: c.get("references") for c in follows[0]["schema"]["columns"]}
        self.assertEqual(cols.get("follower_id"), "users.id")
        self.assertEqual(cols.get("followed_id"), "users.id")

    def test_existing_follows_table_skips(self):
        follows = {"name": "follows", "schema": {"columns": [
            {"name": "id", "primary_key": True, "type": "integer"},
            {"name": "follower_id", "references": "users.id", "type": "integer"},
            {"name": "followed_id", "references": "users.id", "type": "integer"}]}}
        out = interaction_tables_to_provision(
            [_ep("POST", "/api/users/{id}/follow")],
            {"users": _USERS, "follows": follows})
        self.assertEqual([t for t in out if t["name"] == "follows"], [])

    def test_unfollow_shares_follows_no_dup(self):
        out = interaction_tables_to_provision(
            [_ep("POST", "/api/users/{id}/follow"),
             _ep("POST", "/api/users/{id}/unfollow")], {"users": _USERS})
        self.assertEqual(len([t for t in out if t["name"] == "follows"]), 1)

    def test_content_verbs_unaffected(self):
        # like/save on a content parent still provision their own tables
        videos = {"name": "videos", "schema": {"columns": [
            {"name": "id", "primary_key": True, "type": "text"}]}}
        out = interaction_tables_to_provision(
            [_ep("POST", "/api/videos/{id}/like"),
             _ep("POST", "/api/users/{id}/follow")],
            {"users": _USERS, "videos": videos})
        names = {t["name"] for t in out}
        self.assertIn("likes", names)
        self.assertIn("follows", names)

    def test_projector_serves_provisioned_follows(self):
        out = interaction_tables_to_provision(
            [_ep("POST", "/api/users/{id}/follow")], {"users": _USERS})
        tables = {"users": _USERS}
        for t in out:
            tables[t["name"]] = t
        models = {}
        for name, tb in tables.items():
            cols = [c["name"] for c in tb["schema"]["columns"]]
            fks = {c["name"]: str(c.get("references", "")).split(".")[0]
                   for c in tb["schema"]["columns"] if c.get("references")}
            models[name] = {"cls": name.title().replace("_", ""), "cols": cols, "fks": fks}
        h = rp._generate_handler("POST", "/api/users/{id}/follow", True, models, 0)
        self.assertNotIn("not implemented", h)
        self.assertIn('valid["followed_id"] = _parent.id', h)
        self.assertIn("_fw_owner_val(Follow", h)


if __name__ == "__main__":
    unittest.main()
