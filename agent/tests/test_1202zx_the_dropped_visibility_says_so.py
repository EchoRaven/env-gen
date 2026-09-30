r"""#1202zx: the registry dropped an unreadable `visibility` and told only the log.

#1202vr is right to drop it: `VISIBILITY_VERDICTS_1202vr` is `{"public", "owner"}`, measured
vocabulary — across the corpus the materials declare `public` (135) and `owner` (221) and nothing
else, while the hub additionally held `private` (2) and one `text`, neither of which any reader
understands. The value is moved to `visibility_unreadable_1202vr` and a warning goes to the logger.

WHAT THE SILENCE COST, in #1202vr's own words beside the code: with the verdict dropped,
`_declared_public_content_1202hh` is False, `_structurally_private_resource_633` decides alone,
`auth = auth or _owner_scoped` puts `Depends(get_current_user)` on `GET /api/feed/for-you`, and
r137's front page answered 401 to a logged-out visitor. #1202kx exists to tell a lane which of the
two legitimate fixes to apply and fires only on `public` vs `owner`, so it did not fire — 0 times
in that run. "With no path it could take", the lane reached into `_FW_PUBLIC_API_1202KH` from
custom_routes.py and the run abandoned at 81 minutes and $190 on `deliverability_guard_tampering`.

So the one fact that would have redirected that lane existed, and reached a logger and a stored
marker — neither of which a lane reads in the turn it registers. `register_table` returns the
table dict and `registryhub_register_table` hands it back as its `ToolResult(data=...)`, exactly
like `register_endpoint`, whose #731 comment states the reasoning: "A note on the RETURN closes it
inside one tool call ... the agent finds out while it can still act."

Additive: the drop, the stored record, the logger line and every other reader are unchanged.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (_AGENT, os.path.join(_AGENT, "env_generator", "llm_generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime.registryhub import RegistryHub  # noqa: E402

_NOTE = "_visibility_dropped_1202zx"


class TheDroppedVerdictIsAnnounced(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="zx_"))
        self.rh = RegistryHub(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _reg(self, vis="text", name="videos"):
        kw = {"visibility": vis} if vis is not None else {}
        return self.rh.register_table(
            name, schema={"columns": [{"name": "id", "type": "int"}]},
            provider="backend", agent="backend", status="implemented", **kw)

    # ── the note ──────────────────────────────────────────────────────────────

    def test_an_unreadable_verdict_is_reported_to_the_caller(self):
        out = self._reg("text")
        self.assertIn(_NOTE, out, sorted(out))
        self.assertIn("text", out[_NOTE])

    def test_the_note_names_the_only_verdicts_that_are_read(self):
        n = self._reg("text")[_NOTE]
        self.assertIn("public", n)
        self.assertIn("owner", n)

    def test_the_note_says_what_to_do(self):
        """★ #1202kx could not fire here, so this is the only thing standing between the lane and
        the guess it made in r137."""
        n = self._reg("text")[_NOTE]
        self.assertIn("Re-register", n)
        self.assertIn("read by people who did not write them", n)

    def test_the_note_names_the_401_consequence(self):
        """Knowing the value was dropped is not enough — the lane has to know the shape then
        decides alone and its landing page will refuse a visitor."""
        n = self._reg("text")[_NOTE]
        self.assertIn("401", n)
        self.assertIn("SHAPE", n)

    def test_the_note_closes_the_door_r137_took(self):
        n = self._reg("text")[_NOTE]
        self.assertIn("custom_routes.py", n)
        self.assertIn("blocker", n)

    def test_private_is_reported_too(self):
        """The corpus holds `private` in 2 runs — plausible-looking and still not read."""
        self.assertIn(_NOTE, self._reg("private"))

    # ── what must not change ──────────────────────────────────────────────────

    def test_the_registration_still_stands_and_keeps_the_value(self):
        self._reg("text")
        rec = self.rh.get_table("videos")
        self.assertTrue(rec, self.rh.list_tables())
        md = rec.get("metadata") or {}
        self.assertNotIn("visibility", md, md)
        self.assertEqual(md.get("visibility_unreadable_1202vr"), "text")

    def test_the_note_is_not_persisted(self):
        """★ Serialised, not top-level: #1202zw's test made exactly that mistake and a leak into
        `metadata` left it green."""
        self._reg("text")
        blob = json.dumps(self.rh.list_tables(), default=str)
        self.assertNotIn(_NOTE, blob, blob[:400])

    def test_a_readable_verdict_is_silent(self):
        for vis in ("public", "owner", "PUBLIC"):
            out = self._reg(vis, name="t_%s" % vis.lower())
            self.assertNotIn(_NOTE, out, (vis, sorted(out)))

    def test_no_visibility_at_all_is_silent(self):
        self.assertNotIn(_NOTE, self._reg(None, name="quiet"))


if __name__ == "__main__":
    unittest.main()
