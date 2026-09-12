"""#1202kx: when the materials overrule a contract-public endpoint, SAY SO.

`#1202ht` is right that the materials decide: an endpoint flag cannot publish a table the
materials call per-user. It did that silently, and silence is why the same contract kept
coming back.

Measured across the corpus: `GET /api/notifications` is declared `auth_required=False` while
the materials call `notifications` owner-private in SEVEN runs -- r106, r108, r109, r111,
r115, r117, r118. Seven times the lane made the statement, seven times it was quietly
reversed, and nothing told it the two disagreed.

r117 shows what the silence bought. The framework guarded the route correctly -- a fresh
render of r117's own ledger is byte-identical to its deployed main.py, and that handler takes
`get_current_user` AND owner-filters. So the lane went around it from custom_routes.py:
appending ("GET", "/api/notifications") into `_FW_PUBLIC_API_1202KH`, a matching regex into
the public list, and re-registering its own unguarded handler via `add_api_route`. That served
owner-private rows to an anonymous caller, and the verifier caught it as `DENIAL-PROBE got
success` -- the `business_chain_failing` r117 died on. It is also the ONLY run in 130 that
mutates the framework's auth-policy data, which is what a lane does when it cannot see why it
is being refused.

WHAT IS VERIFIED: the demotion is announced, names both repairs and rejects the third; the
demotion itself still happens; a materials-silent table is NOT announced (#320's bargain is
untouched); a materials-PUBLIC table is not announced; and an already-private contract is not
announced, since nothing was overruled.

WHAT IS NOT: that announcing stops a lane from doing it anyway. It removes the excuse, not
the capability -- no framework-side enforcement of `_FW_PUBLIC_API_1202KH` is added here, and
at n=1 run the corpus does not justify one.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "env_generator" / "llm_generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime.backend_skeleton import render_skeleton_main  # noqa: E402

_LOGGER = "multi_agent.runtime.backend_skeleton"
_PUBLIC_EP = [{"method": "GET", "path": "/api/notifications",
               "schema": {"auth_required": False}, "metadata": {}}]
_PRIVATE_EP = [{"method": "GET", "path": "/api/notifications",
                "schema": {"auth_required": True}, "metadata": {}}]


def _tables(visibility="owner"):
    """r118's REAL notifications shape, not a three-column stand-in: the richer shape is what
    trips #633, and a toy table silently exercises a different path."""
    md = {}
    if visibility:
        md["visibility"] = visibility
    return {
        "users": {"name": "users", "schema": {"columns": [
            {"name": "id", "type": "integer", "primary_key": True},
            {"name": "email", "type": "text"}]}},
        "notifications": {"name": "notifications", "metadata": md, "schema": {"columns": [
            {"name": "id", "type": "integer", "primary_key": True},
            {"name": "user_id", "type": "integer", "references": "users.id"},
            {"name": "type", "type": "text"},
            {"name": "actor_user_id", "type": "integer", "references": "users.id"},
            {"name": "read_at", "type": "datetime"}]}},
    }


class TheDisagreementIsAnnounced(unittest.TestCase):

    def test_it_says_so(self):
        """★ The case: seven runs wrote this contract and never heard back."""
        with self.assertLogs(_LOGGER, level="WARNING") as cm:
            render_skeleton_main(_PUBLIC_EP, _tables())
        said = "\n".join(cm.output)
        self.assertIn("#1202kx", said)
        self.assertIn("/api/notifications", said)

    def test_it_names_both_repairs_and_rejects_the_third(self):
        with self.assertLogs(_LOGGER, level="WARNING") as cm:
            render_skeleton_main(_PUBLIC_EP, _tables())
        said = "\n".join(cm.output)
        self.assertIn("auth_required", said)
        self.assertIn("materials", said)
        # r117's actual move must be named as NOT a way out
        self.assertIn("public list", said)

    def test_the_demotion_itself_is_unchanged(self):
        """Announce-only: the materials still win and the route still gets an actor."""
        src = render_skeleton_main(_PUBLIC_EP, _tables())
        body, keep = [], False
        for line in src.split("\n"):
            if "def _projected_get_api_notifications" in line:
                keep = True
            elif keep and line.startswith("@app."):
                break
            if keep:
                body.append(line)
        body = "\n".join(body)
        self.assertIn("get_current_user", body, body)
        self.assertIn("_fw_owner_val", body, body)
        self.assertNotIn(("GET", "/api/notifications"),
                         _opened(src), "the route was published despite the materials")


def _opened(src):
    import re
    m = re.search(r"_FW_PUBLIC_API_1202KH = \[(.*?)\]", src, re.S)
    return set(re.findall(r"\('([A-Z]+)', '([^']+)'\)", m.group(1) if m else ""))


class ItStaysNarrow(unittest.TestCase):
    """#1202ht's limit and #320's bargain are not this fix's business."""

    def _no_kx(self, eps, tables):
        import logging
        with self.assertLogs(_LOGGER, level="WARNING") as cm:
            logging.getLogger(_LOGGER).warning("sentinel so assertLogs has a record")
            render_skeleton_main(eps, tables)
        return "#1202kx" not in "\n".join(cm.output)

    def test_a_materials_silent_table_is_not_announced(self):
        """Nothing was overruled: #320's bargain stands and there is nothing to report."""
        self.assertTrue(self._no_kx(_PUBLIC_EP, _tables(visibility="")))

    def test_a_materials_public_table_is_not_announced(self):
        self.assertTrue(self._no_kx(_PUBLIC_EP, _tables(visibility="public")))

    def test_an_already_private_contract_is_not_announced(self):
        """The contract and the materials AGREE -- announcing would be noise."""
        self.assertTrue(self._no_kx(_PRIVATE_EP, _tables(visibility="owner")))


if __name__ == "__main__":
    unittest.main()
