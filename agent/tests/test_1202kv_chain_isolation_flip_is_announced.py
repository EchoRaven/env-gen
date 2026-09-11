"""#1202kv: flipping owner_scoped_reads back over a lane's explicit False must SAY SO.

`register_verification_chain` marks a table owner_scoped_reads=True when a chain step asserts
a cross-user denial on it. That is the right call -- the probe is the verifier's judgment that
the rows are per-user, and outlook run-9/10 leaked because nobody made it. The defect is that
it happened SILENTLY, and its guard (`not ...get("owner_scoped_reads")`) fires PRECISELY when
a lane has just written an explicit False.

#1202io already diagnosed this flag's failure mode -- "r107: the lane cleared it SIX times and
it came back. Neither side can win a fight it has to keep re-winning" -- but #1202io lives in
`register_table` and could not see this second writer.

tiktok-r118 is r107 repeating through this one. The attribution is structural, not a guess:
`register_table` emits `table_registered` and this block does not, and they are the ONLY two
writers of the table store. r118 logged four `table_registered` for `video_likes` (17:19:31,
17:22:21, 17:33:05, 17:34:34), every one carrying `metadata={"owner_scoped_reads": false}` --
while the stored record reads True. Only a non-emitting writer can open that gap. The lane then
spent SIX remediations -- public regex, nested-resource removal, a middleware short-circuit,
startup route reordering, a BaseHTTPMiddleware at the front of user_middleware, and a wrapper
around _fw_contract_public_1202kh -- none of which touch the flag that decides. Executed against
r118's real ledger, `_FW_PUBLIC_API_1202KH` in its deployed main.py holds only live_streams/
videos/comments/sounds -- video_likes absent, so the blanket auth guard denies it by construction.

The flip is also ONE-WAY, which is what makes it unwinnable: r118 has ZERO cross-user denial
steps on video_likes in its chains as they now stand, and the table is scoped regardless.

WHAT IS VERIFIED: the flip still happens (safety preserved); an explicit False additionally
records provenance and logs a message naming the chain, the table, and BOTH repairs; a table
that never set the flag is flipped quietly as before; an already-True table is left alone; and
the block no longer swallows its exceptions with a bare `pass`.

WHAT IS NOT: that announcing it resolves the contradiction. It does not pick a side -- the flip
stands. It makes the cause attributable, which is what the six blind remediations lacked.
"""
from __future__ import annotations

import ast
import logging
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime.registryhub import RegistryHub  # noqa: E402

_DENIAL_CHAIN = [
    {"method": "POST", "path": "/auth/register",
     "body": {"email": "a@example.com", "password": "Pw123!x"},
     "save": {"token": "access_token"}, "expect": [200, 201]},
    {"method": "GET", "path": "/api/video_likes/1", "auth": "token",
     "expect": [403, 404]},
]


class TheFlipOverAnExplicitFalse(unittest.TestCase):

    def setUp(self):
        self.hub = Path(tempfile.mkdtemp(prefix="hub_1202kv_"))
        self.rh = RegistryHub(self.hub)

    def tearDown(self):
        shutil.rmtree(self.hub, ignore_errors=True)

    def _table(self, **md):
        self.rh.register_table(name="video_likes", schema={"columns": [
            {"name": "id", "type": "integer", "primary_key": True},
            {"name": "user_id", "type": "integer", "references": "users.id"}]},
            agent="backend", status="implemented", **md)

    def _chain(self):
        self.rh.register_verification_chain(
            name="video_likes_cross_user_denial", steps=_DENIAL_CHAIN, agent="backend")

    def _md(self):
        return (self.rh.list_tables().get("video_likes") or {}).get("metadata") or {}

    def test_the_flip_still_happens(self):
        """★ Safety first: the probe's judgment still wins."""
        self._table(owner_scoped_reads=False)
        self._chain()
        self.assertIs(self._md().get("owner_scoped_reads"), True)

    def test_an_explicit_false_records_which_chain_overrode_it(self):
        """★ The case: provenance the lane can actually act on."""
        self._table(owner_scoped_reads=False)
        self._chain()
        self.assertEqual(self._md().get("owner_scoped_reads_set_by_chain_1202kv"),
                         "video_likes_cross_user_denial")

    def test_an_explicit_false_is_announced_with_both_repairs(self):
        self._table(owner_scoped_reads=False)
        with self.assertLogs("multi_agent.runtime.registryhub", level="WARNING") as cm:
            self._chain()
        said = "\n".join(cm.output)
        self.assertIn("#1202kv", said)
        self.assertIn("video_likes", said)
        self.assertIn("video_likes_cross_user_denial", said)
        # both ways out must be named, not just the diagnosis
        self.assertIn("drop the cross-user denial step", said)
        self.assertIn("stop declaring the endpoint public", said)

    def test_a_table_that_never_set_the_flag_is_flipped_quietly(self):
        """#1202gd's rule: stay narrow. Silence was only wrong over a deliberate False."""
        self._table()
        self._chain()
        self.assertIs(self._md().get("owner_scoped_reads"), True)
        self.assertNotIn("owner_scoped_reads_set_by_chain_1202kv", self._md())

    def test_an_already_scoped_table_is_left_alone(self):
        self._table(owner_scoped_reads=True)
        self._chain()
        self.assertIs(self._md().get("owner_scoped_reads"), True)
        self.assertNotIn("owner_scoped_reads_set_by_chain_1202kv", self._md())

    def test_the_flip_is_one_way_and_a_revised_chain_does_not_clear_it(self):
        """★ The property that made it unwinnable, and the reason the announcement matters:
        re-registering the SAME chain without the denial step leaves the table scoped, so the
        lane cannot undo it by fixing the chain either. Documented, not fixed -- clearing it
        automatically would re-open the leak the probe exists to catch."""
        self._table(owner_scoped_reads=False)
        self._chain()
        self.assertIs(self._md().get("owner_scoped_reads"), True)
        self.rh.register_verification_chain(
            name="video_likes_cross_user_denial", agent="backend",
            steps=[{"method": "GET", "path": "/api/video_likes", "expect": [200]}])
        self.assertIs(self._md().get("owner_scoped_reads"), True)

    def test_a_chain_without_a_denial_step_scopes_nothing(self):
        self._table(owner_scoped_reads=False)
        self.rh.register_verification_chain(
            name="plain_read", agent="backend",
            steps=[{"method": "GET", "path": "/api/video_likes", "expect": [200]}])
        self.assertIs(self._md().get("owner_scoped_reads"), False)


class TheBlockNoLongerSwallowsSilently(unittest.TestCase):

    def test_the_isolation_block_does_not_end_in_a_bare_pass(self):
        """Counter-proof anchor, on the AST (#943) -- a bare `except: pass` here is how the
        signal could die whole without anyone learning it had."""
        import multi_agent.runtime.registryhub as _rh
        tree = ast.parse(Path(_rh.__file__).read_text(encoding="utf-8"))
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "register_verification_chain")
        # THE isolation-scoping try, identified by the local it builds -- not every handler in
        # the function, several of which guard unrelated work and are none of this fix's business.
        tries = [t for t in ast.walk(fn) if isinstance(t, ast.Try)
                 and any(isinstance(n, ast.Name) and n.id == "_to_scope" for n in ast.walk(t))]
        self.assertEqual(len(tries), 1, "could not locate the isolation-scoping try uniquely")
        bare = [h for h in tries[0].handlers
                if len(h.body) == 1 and isinstance(h.body[0], ast.Pass)]
        self.assertEqual(bare, [], "the isolation-scoping handler still swallows silently")

    def test_the_announcement_reads_the_previous_value(self):
        """The guard must test the PRIOR value for `is False`, not merely log unconditionally."""
        import multi_agent.runtime.registryhub as _rh
        tree = ast.parse(Path(_rh.__file__).read_text(encoding="utf-8"))
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "register_verification_chain")
        cmps = [n for n in ast.walk(fn) if isinstance(n, ast.Compare)
                and any(isinstance(o, ast.Is) for o in n.ops)
                and any(isinstance(c, ast.Constant) and c.value is False for c in n.comparators)]
        self.assertTrue(cmps, "nothing distinguishes an explicit False from an absent flag")


if __name__ == "__main__":
    unittest.main()
