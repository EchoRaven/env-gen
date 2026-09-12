"""#1202le: the chain-isolation flip must respect a materials-PUBLIC table.

#1202io refuses the contradiction `visibility: public` + `owner_scoped_reads: True` at the
`register_table` write boundary -- "direct opposites ... every reader of this record must see
one answer". The chain-isolation block in `register_verification_chain` writes through
`self._tables.update` and never passed under that guard. Same contradiction, second producing
site -- the same second writer #1202kv had to be taught to announce itself.

tiktok-r119 is the cost, and its own ledger is the evidence: `videos` carries
`visibility: public` AND `owner_scoped_reads_set_by_chain_1202kv:
'tenant_auth_content_access_flow'` -- the provenance key added that morning is how the flip was
identified as the writer.

The damage chain is four links and ends nowhere:
  1. the chain's cross-user denial step flips `videos` owner-scoped;
  2. backend_audit's public-content exemption (#1202gd/#1202hm) needs materials-public AND not
     owner-scoped, so the flip withdraws it;
  3. the audit reports `unscoped owner read: GET /api/videos returns every row of videos to ANY
     caller` -- against a public feed;
  4. that blocker is minted as `deliverability_other:<prose>`, a DYNAMIC name no `_GATE_OWNER`
     key can match, so delivery declines with "NO remediation owner" and NOTHING is dispatched.
The orchestrator saw through it and still could not act: "Materials declare videos PUBLIC
content, so do NOT scope feed reads to caller". Corpus-wide, "NO remediation owner" appears in
20 runs over 21 days and `deliverability_other` has essentially one subtype -- `unscoped owner
read`, 376 occurrences.

WHAT IS VERIFIED: a materials-public table is NOT flipped and the refusal is announced naming
both repairs; a materials-SILENT table is still flipped (unchanged); a materials-`owner` table
is still flipped; the flip's existing provenance/announcement (#1202kv) is untouched for the
cases that still flip; and an already-scoped table is left alone.

WHAT IS NOT: a weakening of the leak check. A table the materials call public is one whose rows
are MEANT to be visible -- #320's whole case. Where the materials say nothing, this changes
nothing.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "env_generator" / "llm_generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime.registryhub import RegistryHub  # noqa: E402

_LOGGER = "multi_agent.runtime.registryhub"
_DENIAL = [
    {"method": "POST", "path": "/auth/register",
     "body": {"email": "a@example.com", "password": "Pw1!xyz"},
     "save": {"token": "access_token"}, "expect": [200, 201]},
    {"method": "GET", "path": "/api/videos/1", "auth": "token", "expect": [403, 404]},
]


class TheMaterialsDecide(unittest.TestCase):

    def setUp(self):
        self.hub = Path(tempfile.mkdtemp(prefix="le_"))
        self.rh = RegistryHub(self.hub)

    def tearDown(self):
        shutil.rmtree(self.hub, ignore_errors=True)

    def _table(self, **md):
        self.rh.register_table(name="videos", schema={"columns": [
            {"name": "id", "type": "integer", "primary_key": True},
            {"name": "author_id", "type": "integer", "references": "users.id"}]},
            agent="backend", status="implemented", **md)

    def _chain(self, name="tenant_auth_content_access_flow"):
        self.rh.register_verification_chain(name=name, steps=_DENIAL, agent="backend")

    def _osr(self):
        return ((self.rh.list_tables().get("videos") or {}).get("metadata") or {}
                ).get("owner_scoped_reads")

    def test_a_materials_public_table_is_NOT_flipped(self):
        """★ r119's `videos`."""
        self._table(visibility="public", owner_scoped_reads=False)
        self._chain()
        self.assertIsNot(self._osr(), True)

    def test_the_refusal_is_announced_with_both_repairs(self):
        self._table(visibility="public", owner_scoped_reads=False)
        with self.assertLogs(_LOGGER, level="WARNING") as cm:
            self._chain()
        said = "\n".join(cm.output)
        self.assertIn("#1202le", said)
        self.assertIn("tenant_auth_content_access_flow", said)
        self.assertIn("correct the materials", said)
        self.assertIn("drop that step", said)

    def test_a_materials_silent_table_is_still_flipped(self):
        """★ Narrowness: #320's bargain where the materials say nothing is untouched."""
        self._table(owner_scoped_reads=False)
        self._chain()
        self.assertIs(self._osr(), True)

    def test_a_materials_owner_table_is_still_flipped(self):
        self._table(visibility="owner", owner_scoped_reads=False)
        self._chain()
        self.assertIs(self._osr(), True)

    def test_the_1202kv_provenance_still_lands_when_it_does_flip(self):
        """The announcement added that morning must survive this refusal being added."""
        self._table(owner_scoped_reads=False)
        self._chain(name="some_isolation_chain")
        md = (self.rh.list_tables().get("videos") or {}).get("metadata") or {}
        self.assertEqual(md.get("owner_scoped_reads_set_by_chain_1202kv"),
                         "some_isolation_chain")

    def test_an_already_scoped_table_is_untouched(self):
        self._table(owner_scoped_reads=True)
        self._chain()
        self.assertIs(self._osr(), True)


if __name__ == "__main__":
    unittest.main()
