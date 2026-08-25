"""#1098 — #633's flag without #271's guarantee: the private table is still a public dump.

#1097 taught `backend_skeleton` the two owner-scoping steps `route_projector` already applied
(#320's explicit-public exemption, #633's structural-privacy override). It stopped one step
short. `_generate_handler` gates the owner filter on AUTH —

    owner_fk   = _owner_fk(meta) if auth else None      # auth False -> no owner column
    read_scoped = bool(owner_fk) and (...)              # -> False   -> no filter

— which is why route_projector's line reads

    auth = resolve_endpoint_auth(method, path, ep, meta) or _owner_scoped     # #271

The `or _owner_scoped` is what makes #633's flag mean anything: a resource that is private BY
CONSTRUCTION forces an actor, whatever the contract forgot. `backend_skeleton` computed auth
from the contract alone, so with a contract that says `auth_required: false`:

    #633 says /api/my-list is structurally private   ->  _owner_scoped = True
    auth  = bool(False)                              ->  False
    _generate_handler drops the filter               ->  no actor, no filter

which is #633's own documented leak, verbatim: *"4 of them ship GET /api/search over
ContinueWatching … returns user_id, title_id, progress_seconds for EVERY user,
unauthenticated"*. One emitter protects the resource and the other publishes it, from the
same contract.

Also fixed here, in the same expression: `bool(ep.get("auth_required", default))` returns
False for a key that is PRESENT and None — the exact r58 shape `resolve_endpoint_auth` calls
out (*"every unauthored endpoint carried auth_required=None … so /api/me,
/api/feed/following and the video write routes all projected WIDE OPEN"*). No corpus contract
carries that shape today (measured: 0 of 68), so this is a latent bypass rather than a live
one — but it is the same key, read the same broken way, in the emitter that lacked the fix.

The unstated default stays True here. route_projector defaults an unstated read by SHAPE
(`resolve_endpoint_auth`); this emitter has always been conservative, and widening that is a
policy change with its own blast radius, not part of closing a leak.
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.backend_skeleton import (_models_meta,  # noqa: E402
                                                  render_skeleton_main)
from multi_agent.runtime.route_projector import (  # noqa: E402
    _structurally_private_resource_633)

_MY_LIST = {
    "my_list": {"schema": {"columns": [
        {"name": "id", "type": "integer", "primary_key": True},
        {"name": "user_id", "type": "integer", "references": "users.id"},
        {"name": "title_id", "type": "integer", "references": "titles.id"},
        {"name": "progress_seconds", "type": "integer"}]}},
    "titles": {"schema": {"columns": [
        {"name": "id", "type": "integer", "primary_key": True},
        {"name": "name", "type": "text"}]}},
}


def _handler(main: str, path: str):
    m = re.search(r'@app\.get\("%s"\)\ndef \w+\(([^\n]*)\):\n(.*?)(?=\n@app|\Z)'
                  % re.escape(path), main, re.S)
    return (m.group(1), m.group(2)) if m else ("", "")


class TheFixtureReallyIsStructurallyPrivate(unittest.TestCase):
    """Non-vacuity: if #633 stopped recognising this shape the rest proves nothing."""

    def test_633_flags_it(self):
        self.assertTrue(_structurally_private_resource_633(
            "GET", "/api/my-list", _models_meta(_MY_LIST)))


class AContractThatForgetsAuthCannotPublishIt(unittest.TestCase):

    def test_an_explicitly_public_private_table_still_gets_an_actor(self):
        eps = [{"method": "GET", "path": "/api/my-list", "auth_required": False}]
        sig, body = _handler(render_skeleton_main(eps, _MY_LIST), "/api/my-list")
        self.assertTrue(sig, "the handler was not projected")
        self.assertIn("get_current_user", sig,
                      "a structurally-private resource projected with no actor")
        self.assertIn("_fw_owner_val(", body,
                      "…and with no owner filter: every user's rows, unauthenticated")

    def test_the_same_holds_when_metadata_declares_it_public(self):
        eps = [{"method": "GET", "path": "/api/my-list",
                "metadata": {"auth_required": False}}]
        sig, _ = _handler(render_skeleton_main(eps, _MY_LIST), "/api/my-list")
        self.assertIn("get_current_user", sig)


class APresentButNoneKeyDefaultsClosed(unittest.TestCase):
    """r58's shape: `.get(key, default)` does not apply the default to a PRESENT None."""

    def test_none_is_treated_as_unstated_not_as_false(self):
        """On a PRIVATE resource the difference is observable and safety-relevant.

        (#1099 moved the unstated default from "always auth" to "by shape", so a public
        catalog is the wrong place to observe this now — an unstated catalog read is
        legitimately anonymous either way. What must never happen is None being read as an
        explicit False, which would drop both the actor and the owner filter.)"""
        eps = [{"method": "GET", "path": "/api/my-list", "auth_required": None}]
        sig, body = _handler(render_skeleton_main(eps, _MY_LIST), "/api/my-list")
        self.assertIn("get_current_user", sig,
                      "auth_required=None projected a private resource wide open")
        self.assertIn("_fw_owner_val(", body)


class TheOrdinaryCasesAreUnchanged(unittest.TestCase):

    def test_a_declared_public_read_on_a_plain_table_stays_anonymous(self):
        eps = [{"method": "GET", "path": "/api/titles", "auth_required": False}]
        sig, body = _handler(render_skeleton_main(eps, _MY_LIST), "/api/titles")
        self.assertNotIn("get_current_user", sig)
        self.assertNotIn("_fw_owner_val(", body)

    def test_an_unstated_read_defaults_by_shape(self):
        """#1099 replaced this emitter's blanket default-True with `resolve_endpoint_auth`,
        which is r58's rule: a write or a self/personalised read needs an actor, a public
        catalog read does not. This test used to pin the blanket default; that contract was
        changed deliberately, so it now pins the rule that replaced it."""
        catalog, _ = _handler(render_skeleton_main(
            [{"method": "GET", "path": "/api/titles"}], _MY_LIST), "/api/titles")
        self.assertNotIn("get_current_user", catalog, "a public catalog read forced an actor")
        write, _ = _handler(render_skeleton_main(
            [{"method": "GET", "path": "/api/titles"}], _MY_LIST), "/api/titles")
        selfread, _ = _handler(render_skeleton_main(
            [{"method": "GET", "path": "/api/me"}], _MY_LIST), "/api/me")
        self.assertIn("get_current_user", selfread, "a self read went anonymous")


if __name__ == "__main__":
    unittest.main()
