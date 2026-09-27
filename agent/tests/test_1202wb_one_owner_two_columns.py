"""#1202wb: one owner, two declared columns, one of them NULL for every row.

r136's contract declares BOTH `author_id` and `user_id` as FKs to `users` on `videos` AND
on `comments`, and the dataset fills exactly one of each -- in opposite directions: videos
carry `author_id` (35/35, user_id 0/35), comments carry `user_id` (295/295, author_id
0/295). The framework's own `_OWNER_COL` picked `user_id` for videos, i.e. the empty one,
so every owner-scoped read and write on r136's videos keyed on NULL; the lane's source
names videos.user_id 27 times and the projected code 42.

#1202w9 deliberately cannot fix this: it harvests only an UNDECLARED column, so that a
populated `sound_id` is never poured into `user_id`. When both names are declared the
question is whether they mean the same thing, and that must not be guessed from data --
`follows.follower_id`/`following_id` are two declared FKs to `users` meaning opposite ends
of one edge, and mirroring them would make everybody follow themselves. The test is
therefore the framework's OWN owner vocabulary (`_OWNER_FK_COL_NAMES`, what
`_table_has_owner_fk` keys ownership on), which contains `author_id` and `user_id` and does
NOT contain `follower_id`, `following_id`, `actor_id` or `recipient_id`.
"""
import copy
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "env_generator", "llm_generator"))

from multi_agent.runtime.kickoff.run_kickoff import _OWNER_FK_COL_NAMES  # noqa: E402
from multi_agent.runtime.material_prep import (  # noqa: E402
    mirror_redundant_owner_fks_1202wb,
)

USERS = [{"id": 1}, {"id": 2}, {"id": 3}]


def _cols(**fks):
    return {name: {"type": "integer", "nullable": True, "pk": name == "id", "fk": fk}
            for name, fk in fks.items()}


def _run(table, cols, rows, extra_tables=None):
    ds = {"users": copy.deepcopy(USERS), table: copy.deepcopy(rows)}
    ds.update(copy.deepcopy(extra_tables or {}))
    schema = {"users": _cols(id=None), table: cols}
    return mirror_redundant_owner_fks_1202wb(ds, schema)[table]


VIDEO_COLS = _cols(id=None, author_id="users.id", user_id="users.id", sound_id="sounds.id")


def test_the_empty_owner_column_takes_the_filled_ones_values():
    rows = _run("videos", VIDEO_COLS,
                [{"id": 1, "author_id": 1}, {"id": 2, "author_id": 2}, {"id": 3, "author_id": 2}])
    assert [r.get("user_id") for r in rows] == [1, 2, 2], (
        "the owner column the framework scopes on must not stay NULL: %r"
        % [r.get("user_id") for r in rows]
    )


def test_it_mirrors_in_whichever_direction_the_dataset_filled():
    """r136 filled videos.author_id but comments.user_id, so neither name is privileged."""
    cols = _cols(id=None, author_id="users.id", user_id="users.id")
    rows = _run("comments", cols,
                [{"id": 1, "user_id": 3}, {"id": 2, "user_id": 3}])
    assert [r.get("author_id") for r in rows] == [3, 3], (
        "%r" % [r.get("author_id") for r in rows]
    )


def test_the_two_ends_of_an_edge_are_never_mirrored():
    """follows.follower_id / following_id both point at users and mean opposite things."""
    assert "follower_id" not in _OWNER_FK_COL_NAMES
    assert "following_id" not in _OWNER_FK_COL_NAMES
    cols = _cols(id=None, follower_id="users.id", following_id="users.id")
    rows = _run("follows", cols,
                [{"id": 1, "follower_id": 1}, {"id": 2, "follower_id": 2}])
    assert all(r.get("following_id") in (None, "", 0) for r in rows), (
        "mirroring an edge's ends would make everybody follow themselves: %r"
        % [r.get("following_id") for r in rows]
    )


def test_a_notification_actor_is_not_its_recipient():
    assert "actor_id" not in _OWNER_FK_COL_NAMES
    cols = _cols(id=None, user_id="users.id", actor_id="users.id")
    rows = _run("notifications", cols,
                [{"id": 1, "user_id": 1}, {"id": 2, "user_id": 2}])
    assert all(r.get("actor_id") in (None, "", 0) for r in rows), (
        "%r" % [r.get("actor_id") for r in rows]
    )


def test_a_partially_filled_sibling_is_left_alone():
    """Some rows saying something is the dataset's own statement, not an omission."""
    cols = _cols(id=None, author_id="users.id", user_id="users.id")
    rows = _run("videos", cols,
                [{"id": 1, "author_id": 1, "user_id": 3},
                 {"id": 2, "author_id": 2, "user_id": None},
                 {"id": 3, "author_id": 2, "user_id": None}])
    assert [r.get("user_id") for r in rows] == [3, None, None], (
        "%r" % [r.get("user_id") for r in rows]
    )


def test_a_third_partially_filled_sibling_freezes_the_whole_group():
    """With one filled, one empty and one PARTIAL column, the group is not understood.

    Two columns can never reach this: a partial sibling is neither `filled` nor `empty`, so
    a pair exits earlier for want of an empty column. It takes a third owner column to ask
    whether a group containing a per-row statement may still be mirrored. It may not --
    mirroring would assert the empty column means the same as the filled one while the
    dataset is visibly saying something else about individual rows.
    """
    assert "creator_id" in _OWNER_FK_COL_NAMES
    cols = _cols(id=None, author_id="users.id", user_id="users.id", creator_id="users.id")
    rows = _run("videos", cols,
                [{"id": 1, "author_id": 1, "creator_id": 3},
                 {"id": 2, "author_id": 2, "creator_id": None},
                 {"id": 3, "author_id": 2, "creator_id": None}])
    assert all(r.get("user_id") in (None, "", 0) for r in rows), (
        "a group holding a partially-filled column must be left whole: %r"
        % [r.get("user_id") for r in rows]
    )


def test_two_filled_owner_columns_are_refused_rather_than_ranked():
    """Which of two populated owner columns is THE owner is not ours to decide."""
    cols = _cols(id=None, author_id="users.id", user_id="users.id", creator_id="users.id")
    rows = _run("videos", cols,
                [{"id": 1, "author_id": 1, "user_id": 3},
                 {"id": 2, "author_id": 2, "user_id": 3}])
    assert all(r.get("creator_id") in (None, "", 0) for r in rows), (
        "author_id and user_id disagree; copying either into creator_id is a guess: %r"
        % [r.get("creator_id") for r in rows]
    )


def test_a_lone_owner_fk_is_not_a_group():
    """`sounds.author_id` is the only FK to users there; nothing to mirror from."""
    cols = _cols(id=None, author_id="users.id")
    rows = _run("sounds", cols, [{"id": 1}, {"id": 2}])
    assert all(r.get("author_id") in (None, "", 0) for r in rows)


def test_two_targets_are_two_groups():
    """A filled FK to another table must never reach an owner column."""
    ds = {"users": copy.deepcopy(USERS), "sounds": [{"id": 1}, {"id": 2}],
          "videos": [{"id": 1, "sound_id": 1}, {"id": 2, "sound_id": 2}]}
    schema = {"users": _cols(id=None), "sounds": _cols(id=None), "videos": VIDEO_COLS}
    rows = mirror_redundant_owner_fks_1202wb(ds, schema)["videos"]
    assert all(r.get("user_id") in (None, "", 0) for r in rows), (
        "a sound's id must never land in an owner column: %r"
        % [r.get("user_id") for r in rows]
    )
    assert all(r.get("author_id") in (None, "", 0) for r in rows)
