"""#1069 — every seeded two-party row pointed at ONE person.

`_seed_cell` derives an FK value from `(fk_table, row_index)` alone:

    m = max(1, int(counts.get(fk_table, 1)))
    idx = i % m

The COLUMN is not part of it. So when a table has two FK columns targeting the
SAME parent — the shape #77/#1059 call multi-principal — both get the same value
in every row. Generated straight from the current generator:

    follows :  {'follower_id': 1, 'followee_id': 1} ... 6 of 6 rows identical
    messages:  {'sender_id': 1, 'recipient_id': 1}  ... 6 of 6 rows identical

Which means every seeded follow is a self-follow and every seeded DM is a note to
self. The consequences are not cosmetic:

  * a DM inbox renders empty for every user except as messages they sent to
    themselves — and the delivery gate's own bar is "domain-REALISTIC populated
    screens";
  * the follows graph has nobody following anybody, so a followers list is empty
    by construction;
  * #1059's bug — the recipient of a DM 404s on their own message — could not be
    surfaced by ANY seeded row, because no seeded row ever had a recipient who
    was not the sender.

Fix: distinct FK columns to the same parent walk distinct parent rows. Row i takes
parent (i + ordinal) % m, where ordinal is the column's position among that
table's FK columns pointing at that parent. Deterministic, and byte-identical for
every single-FK table (ordinal 0).
"""
from __future__ import annotations

import ast
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime.backend_skeleton import render_seed_data  # noqa: E402


def _col(name, **kw):
    d = {"name": name, "type": kw.pop("type", "integer")}
    d.update(kw)
    return d


def _seed(tables):
    src = render_seed_data(tables)
    m = re.search(r"^_SEED = (\{.*\})$", src, re.M)
    assert m, "_SEED assignment not found"
    return ast.literal_eval(m.group(1))


_USERS = {"schema": {"columns": [_col("id", primary_key=True), _col("name", type="text")]}}


class TwoPartyRowsHaveTwoParties(unittest.TestCase):

    def test_a_dm_is_not_addressed_to_its_sender(self):
        seed = _seed({
            "users": _USERS,
            "messages": {"schema": {"columns": [
                _col("id", primary_key=True),
                _col("sender_id", references="users.id"),
                _col("recipient_id", references="users.id"),
                _col("body", type="text")]}},
        })
        rows = seed["messages"]
        self.assertTrue(rows)
        self_notes = [r for r in rows if r["sender_id"] == r["recipient_id"]]
        self.assertEqual(self_notes, [], "every seeded DM was a note to self")

    def test_a_follow_is_not_a_self_follow(self):
        seed = _seed({
            "users": _USERS,
            "follows": {"schema": {"columns": [
                _col("id", primary_key=True),
                _col("follower_id", references="users.id"),
                _col("followee_id", references="users.id")]}},
        })
        rows = seed["follows"]
        self.assertTrue(rows)
        self.assertEqual([r for r in rows if r["follower_id"] == r["followee_id"]], [],
                         "every seeded follow was a self-follow")

    def test_both_sides_still_reference_real_parents(self):
        """Distinctness must not be bought by inventing a parent that does not exist."""
        seed = _seed({
            "users": _USERS,
            "messages": {"schema": {"columns": [
                _col("id", primary_key=True),
                _col("sender_id", references="users.id"),
                _col("recipient_id", references="users.id")]}},
        })
        n_users = len(seed["users"])
        for r in seed["messages"]:
            for c in ("sender_id", "recipient_id"):
                self.assertIn(r[c], range(1, n_users + 1), f"{c}={r[c]!r}")

    def test_a_text_pk_parent_still_gets_its_string_keys(self):
        """#1069 must not regress the text-PK rule (test_fk_matches_text_pk_parent)."""
        seed = _seed({
            "workspaces": {"schema": {"columns": [
                _col("id", primary_key=True, type="text"), _col("name", type="text")]}},
            "shares": {"schema": {"columns": [
                _col("id", primary_key=True),
                _col("from_workspace_id", type="text", references="workspaces.id"),
                _col("to_workspace_id", type="text", references="workspaces.id")]}},
        })
        parents = {w["id"] for w in seed["workspaces"]}
        for r in seed["shares"]:
            self.assertIsInstance(r["from_workspace_id"], str)
            self.assertIn(r["from_workspace_id"], parents)
            self.assertIn(r["to_workspace_id"], parents)
        self.assertEqual(
            [r for r in seed["shares"]
             if r["from_workspace_id"] == r["to_workspace_id"]], [])


class SingleFkTablesAreUnchanged(unittest.TestCase):
    """The ordinal is 0 for the only FK to a parent, so nothing else moves."""

    def test_a_second_fk_to_another_parent_does_not_move_this_one(self):
        """#1202ue replaced the VALUES this used to pin, so it now pins the PROPERTY.

        The old assertion was `[(i % n_users) + 1 ...]` -- the parents cycled in lockstep, and
        #1202ue removed exactly that, because it gave every parent exactly one child (measured
        in the delivered r133 seed: comments.video_id = [1..8], likes.video_id = [1..8]). The
        cycle was never what #1069 owned; the docstring above says what is: the ordinal is 0
        for the only FK onto a parent, so nothing else moves it.

        That is asserted here directly. Adding a second FK onto a DIFFERENT parent must leave
        the first column's values untouched, because ordinals are counted per parent.
        """
        one = _seed({
            "users": _USERS,
            "posts": {"schema": {"columns": [
                _col("id", primary_key=True),
                _col("author_id", references="users.id"),
                _col("title", type="text")]}},
        })
        two = _seed({
            "users": _USERS,
            "topics": {"schema": {"columns": [
                _col("id", primary_key=True), _col("title", type="text")]}},
            "posts": {"schema": {"columns": [
                _col("id", primary_key=True),
                _col("author_id", references="users.id"),
                _col("topic_id", references="topics.id"),
                _col("title", type="text")]}},
        })
        self.assertEqual([r["author_id"] for r in one["posts"]],
                         [r["author_id"] for r in two["posts"]])

    def test_a_plain_child_still_references_real_parents(self):
        """The integrity half, which #1202ue must never cost."""
        seed = _seed({
            "users": _USERS,
            "posts": {"schema": {"columns": [
                _col("id", primary_key=True),
                _col("author_id", references="users.id"),
                _col("title", type="text")]}},
        })
        n_users = len(seed["users"])
        for row in seed["posts"]:
            self.assertIn(row["author_id"], range(1, n_users + 1))


if __name__ == "__main__":
    unittest.main()
