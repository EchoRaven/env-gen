"""#1202lf: `unscoped owner read` declined delivery with nobody dispatched.

`_deliverability_check_token` maps blocker prose onto a named token; anything unmapped falls
into a catch-all that embeds the prose: `f"deliverability_other:{blocker[:80]}"`. The
dispatcher looks its owner up with `_GATE_OWNER.get(name)`, an exact-key lookup, so a name with
prose in it can never match -- the check blocks delivery and dispatches nobody.

This file's own history says the shape is a known one. #1042: "Replaying every historical 'NO
remediation owner' list against the owner tables left 8 mentions, all of them this one blocker
falling into `deliverability_other`". And elsewhere: "was in neither `_GATE_OWNER` nor
`_COVERED_ELSEWHERE` ... 26 runs logged 'NO remediation owner' and NOTHING was ever dispatched."

Measured the same way, `unscoped owner read` is now what is left: ~348 occurrences over 21 days
against 4 of everything else, in 20 runs that declined delivery on it.

The truncation makes it worse than merely unowned. At 80 characters the same finding arrives
under a DIFFERENT name depending on path length -- "...to ANY calle" / "...to ANY caller" /
"...to ANY" / "...to AN" are one defect wearing four names. Replayed over the corpus, 23
distinct prose strings produced 23 distinct check names; they now produce one. The dispatcher's
re-fire guard is keyed on the name (`guard.get(name) == milestone`), so a drifting name defeats
de-duplication and storm control too.

The advice deliberately does NOT say "add a filter". Measured across the corpus most of these
findings are a PUBLIC table wrongly carrying `owner_scoped_reads` (netflix's `titles`, tiktok's
`sounds`/`users`), where filtering would wall the catalogue -- #1202gt exists for that exact
wording hazard. Both repairs are named and neither is assumed, and appending to the framework's
public list from custom_routes.py is named as not a third one (tiktok-r117 did exactly that).

WHAT IS VERIFIED: every one of the 23 real prose strings in the corpus maps to the one token;
the token has an owner in the dispatcher's table; unrelated blockers still reach their own
tokens and the catch-all still exists for genuinely new prose.

WHAT IS NOT: that the finding is real when it fires. #1202le removes the largest false-positive
source (a chain flip scoping a materials-public table); this gives whatever remains an owner
instead of a dead end.
"""
from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "env_generator" / "llm_generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime.delivery_gate import _deliverability_check_token as tok  # noqa: E402

_RD = (_ROOT / "env_generator/llm_generator/multi_agent/runtime"
       / "remediation_dispatcher.py")

# Verbatim shapes taken from real run logs, including the truncations.
_REAL = [
    "unscoped owner read: GET /api/videos returns every row of `videos` to ANY caller",
    "unscoped owner read: GET /api/explore/videos returns every row of `videos` to ANY calle",
    "unscoped owner read: GET /api/feed returns every row of `videos` to ANY",
    "unscoped owner read: GET /api/video_likes returns every row of `video_likes` to AN",
    "unscoped owner read: GET /api/my-list returns every row of `my_list` to any authenticated",
]


class TheTokenIsNamed(unittest.TestCase):

    def test_every_real_shape_maps_to_one_token(self):
        """★ 23 distinct prose strings in the corpus produced 23 distinct check names."""
        got = {tok(b) for b in _REAL}
        self.assertEqual(got, {"deliverability_unscoped_owner_read"},
                         "the truncated variants still split into separate names: %s" % got)

    def test_it_no_longer_falls_into_the_catch_all(self):
        for b in _REAL:
            self.assertFalse(tok(b).startswith("deliverability_other"), b)

    def test_the_catch_all_still_exists_for_genuinely_new_prose(self):
        """Naming this one must not swallow the next unmapped blocker silently."""
        t = tok("some brand new blocker nobody has mapped yet")
        self.assertTrue(t.startswith("deliverability_other:"), t)

    def test_unrelated_blockers_keep_their_own_tokens(self):
        self.assertEqual(tok("dead control: resolves to no App.jsx route"),
                         "deliverability_dead_nav_link")
        self.assertEqual(tok("a parameterised route with an empty parameter"),
                         "deliverability_empty_param_nav_link")


def _owner_entry():
    """The `_GATE_OWNER` value for our token, read from the AST.

    Not a byte window (#943): these entries carry long comments and a window sized in bytes
    breaks the moment one of them grows — which is exactly what my first version of this file
    did, pushing that ratchet from 57 to 59.
    """
    tree = ast.parse(_RD.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for k, v in zip(node.keys, node.values):
            if (isinstance(k, ast.Constant)
                    and k.value == "deliverability_unscoped_owner_read"):
                return [c.value for c in ast.walk(v)
                        if isinstance(c, ast.Constant) and isinstance(c.value, str)]
    return None


class ItHasAnOwner(unittest.TestCase):
    """A named token with no owner entry is the same dead end under a tidier name."""

    def test_the_dispatcher_table_carries_the_token(self):
        self.assertIsNotNone(_owner_entry(),
                             "the token is named but still has no remediation owner")

    def test_the_advice_names_both_repairs_and_rejects_custom_routes(self):
        entry = " ".join(_owner_entry() or [])
        self.assertIn("really are per-user", entry)
        self.assertIn("visibility: public", entry)
        self.assertIn("custom_routes.py", entry)

    def test_the_owner_is_the_backend(self):
        self.assertEqual((_owner_entry() or [""])[0], "backend")


if __name__ == "__main__":
    unittest.main()
