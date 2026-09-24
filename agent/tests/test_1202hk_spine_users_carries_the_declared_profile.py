"""#1202hk — the framework's spine `users` must hold the user the MATERIALS describe.

r103's reference spec declares `users` with 11 fields:

    id, username, display_name, email, password_hash, avatar, bio, followers, following,
    likes, verified

The registered contract table has 6 — the tenancy/identity spine — and `render_schema_sql`
skips any contract table named `users` because the spine owns it. Measured across that run's
entities, the loss is concentrated exactly there: `users` loses 8 of 11 and `comments` loses 2
denormalised display fields, while `videos` (13/13), `notifications` (7/7), `conversations`
(5/5), `live_rooms` (6/6), `sounds`, `categories`, `follows`, `video_likes` and `video_saves`
lose nothing at all.

Nobody is wrong locally. The lane's kickoff draft does not declare `users` (the framework owns
it), the spine SQL is fixed by construction, and the materials describe the product's real
user. But the lane is handed BOTH the contract and the materials, and a TikTok video card
cannot render without `@username` and an avatar — so it wrote raw SQL against the fields the
materials describe:

    SELECT * FROM users WHERE lower(username) = :username        (custom_routes.py:194)

and got `UndefinedColumn: column u.username does not exist`, which is in r103's final gate as
`business_chain_failing`. `users` is framework-owned, so no lane can fix it — the iron law
this repo keeps re-learning.

The DDL half ALREADY does this -- `render_schema_sql` emits
`ALTER TABLE "users" ADD COLUMN IF NOT EXISTS "verified" BOOLEAN;` for every
registered `users` column beyond the spine, and `render_models` merges them onto the
ORM. It has simply never had anything to add, because the REGISTERED table never
carried them. So only the kickoff half is missing. The columns are additive: the spine's
own six are untouched (the OAuth AS keys on them), and an EXISTING volume — where
`CREATE TABLE IF NOT EXISTS` is a no-op and is why a schema change never reaches a live
database — picks them up on the next start.

Only spine tables are treated this way. An ordinary table's schema belongs to the lane, which
can extend it through `update_table_schema`; a mismatch there is not the framework's to fix.
"""
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "env_generator" / "llm_generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime.database_scaffold import render_schema_sql
from multi_agent.runtime.backend_skeleton import render_models


def _users(cols):
    return {"name": "users", "schema": {"columns": cols}}


_SPINE_ONLY = [{"name": "id", "type": "integer", "primary_key": True},
               {"name": "email", "type": "text"},
               {"name": "name", "type": "text"},
               {"name": "password_hash", "type": "text"},
               {"name": "tenant_id", "type": "text"},
               {"name": "created_at", "type": "timestamp"}]

_WITH_PROFILE = _SPINE_ONLY + [{"name": "username", "type": "text"},
                               {"name": "avatar", "type": "text"},
                               {"name": "followers", "type": "integer"},
                               {"name": "verified", "type": "boolean"}]


class SpineUsersDDL(unittest.TestCase):
    def test_declared_profile_columns_are_added_to_the_spine(self):
        sql = render_schema_sql({"users": _users(_WITH_PROFILE)})
        for col in ("username", "avatar", "followers", "verified"):
            self.assertIn('ADD COLUMN IF NOT EXISTS "%s"' % col, sql,
                          "`users.%s` is declared but never created:\n%s" % (col, sql[-1500:]))

    def test_the_spine_columns_are_never_re_added(self):
        """The OAuth AS keys on these; re-adding them is at best noise and at worst a type
        conflict with the CREATE TABLE above."""
        sql = render_schema_sql({"users": _users(_WITH_PROFILE)})
        for col in ("id", "email", "password_hash", "tenant_id", "created_at", "name"):
            self.assertNotIn('ADD COLUMN IF NOT EXISTS "%s"' % col, sql, col)

    def test_a_spine_only_users_changes_nothing(self):
        """Every run generated before this must render byte-identically."""
        sql = render_schema_sql({"users": _users(_SPINE_ONLY)})
        self.assertNotIn("ADD COLUMN IF NOT EXISTS", sql)

    def test_no_users_table_at_all_changes_nothing(self):
        sql = render_schema_sql({"videos": {"name": "videos", "schema": {"columns": [
            {"name": "id", "type": "integer", "primary_key": True},
            {"name": "caption", "type": "text"}]}}})
        self.assertNotIn("ADD COLUMN IF NOT EXISTS", sql)

    def test_the_orm_agrees_with_the_ddl(self):
        """#197/#1022's standing hazard: the ORM and the DDL are rendered by different code
        and have diverged before. A column in one and not the other is a 500 on every read."""
        src = render_models({"users": _users(_WITH_PROFILE)})
        for col in ("username", "avatar", "followers", "verified"):
            self.assertIn(col, src, col)


if __name__ == "__main__":
    unittest.main()


sys.path.insert(0, str(Path(__file__).resolve().parent))


def _decisions_with_a_spine_users():
    """r103's shape: the draft declares `users` with the tenancy/identity columns only."""
    import copy
    from test_kickoff_run_kickoff import _all_clean_decisions
    decs = copy.deepcopy(_all_clean_decisions())
    for d in decs:
        if d.get("section") == "backend":
            d["content"]["data_model"]["tables"].append({
                "name": "users",
                "columns": [{"name": "id", "type": "integer"},
                            {"name": "email", "type": "text"},
                            {"name": "password_hash", "type": "text"}]})
    return decs


def _registered_users(entities):
    import json
    import tempfile
    from test_kickoff_run_kickoff import ATTENDEES, _mock_hubs
    from multi_agent.runtime.kickoff.run_kickoff import finalize_kickoff, try_synthesize
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "shared").mkdir(parents=True)
        (root / "design").mkdir(parents=True)
        (root / "design" / "reference_spec.json").write_text(
            json.dumps({"entities": entities}), encoding="utf-8")
        hubs = _mock_hubs(decisions=_decisions_with_a_spine_users())
        hubs.base_dir = str(root)          # production: HubRegistry(output_dir).base_dir IS the run root
        handle = {"meeting_id": "page_meeting_1", "milestone_index": 1,
                  "expected_attendees": ATTENDEES}
        synthesis = try_synthesize(hubs, handle)
        assert synthesis["status"] == "ready", synthesis
        finalize_kickoff(hubs, handle, synthesis)
        for c in hubs.schema_hub.register_table.call_args_list:
            if c.kwargs.get("name") == "users":
                return [x.get("name") for x in
                        ((c.kwargs.get("schema") or {}).get("columns") or [])]
    return None


class SpineUsersRegistration(unittest.TestCase):
    def test_the_declared_profile_reaches_the_registered_table(self):
        cols = _registered_users([{"name": "users", "fields": [
            "id", "username", "display_name", "email", "password_hash", "avatar",
            "bio", "followers", "following", "likes", "verified"]}])
        self.assertIsNotNone(cols, "no users table was registered at all")
        for f in ("username", "display_name", "avatar", "bio", "followers", "verified"):
            self.assertIn(f, cols, "%s never reached the contract: %r" % (f, cols))

    def test_the_drafts_own_columns_survive_and_are_not_duplicated(self):
        cols = _registered_users([{"name": "users", "fields": ["id", "email", "username"]}])
        for f in ("id", "email", "password_hash"):
            self.assertIn(f, cols, cols)
        self.assertEqual(len(cols), len(set(cols)), cols)

    def test_no_declaration_registers_exactly_as_before(self):
        cols = _registered_users([{"name": "videos", "fields": ["id", "caption"]}])
        self.assertEqual(cols, ["id", "email", "password_hash"], cols)
