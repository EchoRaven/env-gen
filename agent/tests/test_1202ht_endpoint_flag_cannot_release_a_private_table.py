"""#1202ht — `auth_required: false` on an endpoint emptied a private table onto the internet.

tiktok-web-r106, live, at 19:06:

    notifications.metadata = {'owner_scoped_reads': True, 'visibility': 'owner'}
    GET /api/notifications  schema.auth_required = False

    def _projected_get_api_notifications_15(db=Depends(get_db)):
        rows = db.query(Notification).limit(100).all()

The table is declared per-user-private TWICE — by the materials (`visibility: owner`) and by
the contract (`owner_scoped_reads: True`) — and the projector emitted an UNAUTHENTICATED,
UNFILTERED dump of it. No lane can fix that handler; the framework wrote it.

`#320`'s exemption is what clears the owner scoping, and it states its own premise:

    "UNSTATED reads on an owner-scoped table still force-auth + owner-scope (r58/#315 leak
     protection ...) — a strong model marks a genuinely-private list private and only sets
     =False on a real public feed"

r106 falsified that. Its lane was working through a run of unscoped-read blockers on `videos`
and set `auth_required: false` on `/api/notifications` too. The exemption exists for
OWNED-BUT-PUBLIC content (a TikTok feed, an IG grid); it must therefore require that the
content actually be public, rather than trusting an endpoint flag that answers a different
question — the same conflation #1202hf and #1202hq were written about.

This is the exact mirror of #1202hh. There, the materials' `public` declaration makes a SHAPE
heuristic stand down. Here, a `private` declaration — from the materials or the contract —
refuses an ENDPOINT flag. Both keep the rule that releasing a read needs agreement, and only
tightening happens on disagreement.
"""
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "env_generator" / "llm_generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime.backend_skeleton import render_skeleton_main


def _tables(owner_scoped=True, visibility="owner"):
    md = {}
    if owner_scoped is not None:
        md["owner_scoped_reads"] = owner_scoped
    if visibility:
        md["visibility"] = visibility
    return {
        "users": {"name": "users", "schema": {"columns": [
            {"name": "id", "type": "integer", "primary_key": True},
            {"name": "email", "type": "text"}]}},
        "notifications": {"name": "notifications", "metadata": md, "schema": {"columns": [
            {"name": "id", "type": "integer", "primary_key": True},
            {"name": "user_id", "type": "integer", "references": "users.id"},
            {"name": "text", "type": "text"}]}},
    }


def _handler(src, name="notifications"):
    keep, body = False, []
    for line in src.split("\n"):
        if "def _projected_get_api_%s" % name in line:
            keep = True
        elif keep and line.startswith("@app."):
            break
        if keep:
            body.append(line)
    return "\n".join(body)


_PUBLIC_EP = [{"method": "GET", "path": "/api/notifications",
               "schema": {"auth_required": False}, "metadata": {}}]


class APrivateTableRefusesTheEndpointFlag(unittest.TestCase):
    def test_the_r106_shape_is_not_served_unfiltered(self):
        body = _handler(render_skeleton_main(_PUBLIC_EP, _tables()))
        self.assertTrue(body, "the read was not projected at all")
        self.assertIn("_fw_owner_val", body,
                      "an unauthenticated dump of a table declared private twice:\n" + body)

    def test_it_still_requires_an_actor(self):
        """A scoped read without a caller is #271/#1098's silent-drop shape."""
        body = _handler(render_skeleton_main(_PUBLIC_EP, _tables()))
        self.assertIn("get_current_user", body, body)

    def test_the_contract_flag_alone_does_NOT_refuse(self):
        """A deliberate limit, not an oversight. #320's own case is a table that carries
        `owner_scoped_reads` (set for write ownership / the "my videos" view) whose FEED is
        public — r88/r89's wedge. With the materials silent those two are indistinguishable,
        and refusing here would re-open that wedge for every spec written before `visibility`
        existed, which is all of them bar the most recent. So the materials decide when they
        speak, and #320's bargain stands when they do not."""
        body = _handler(render_skeleton_main(_PUBLIC_EP,
                                             _tables(owner_scoped=True, visibility="")))
        self.assertNotIn("_fw_owner_val", body, body)

    def test_the_materials_declaration_alone_is_enough_to_refuse(self):
        """A lane that never set the flag, on a table the materials call per-user."""
        body = _handler(render_skeleton_main(_PUBLIC_EP,
                                             _tables(owner_scoped=None, visibility="owner")))
        self.assertIn("_fw_owner_val", body, body)


class ThePublicFeedExemptionStillWorks(unittest.TestCase):
    def test_320s_own_case_is_untouched(self):
        """#320 exists for owned-but-PUBLIC content — r88/r89's feed wedge. A table the
        materials declare public keeps the exemption, which is #1202hh's case."""
        tables = _tables(owner_scoped=None, visibility="public")
        tables["notifications"]["name"] = "notifications"
        body = _handler(render_skeleton_main(_PUBLIC_EP, tables))
        self.assertNotIn("_fw_owner_val", body, body)

    def test_an_undeclared_table_keeps_the_pre_1202ht_behaviour(self):
        """No materials verdict and no contract flag: #320's original bargain, unchanged."""
        body = _handler(render_skeleton_main(_PUBLIC_EP,
                                             _tables(owner_scoped=None, visibility="")))
        self.assertNotIn("_fw_owner_val", body, body)


if __name__ == "__main__":
    unittest.main()
