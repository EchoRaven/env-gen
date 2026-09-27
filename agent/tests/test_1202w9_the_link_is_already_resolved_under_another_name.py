"""#1202w9: a declared FK nobody fills, whose link the rows already carry ALREADY RESOLVED.

#1202vz fills a declared FK from a natural key under the FK's own base name (`sound` for
`sound_id`). A dataset may instead carry the link already resolved under a DIFFERENT name.
MEASURED across the 136 corpus datasets: `videos.user_id` is a declared FK to `users` that
no dataset row fills while every row carries a populated `author_id` holding real user ids
-- 6 runs, including the two most recent (r136, r137). The owner column therefore loaded
NULL for all 35 real videos, so every owner-scoped read over it returns nothing.

The criterion is evidence in the data, not a synonym table: the candidate must be an
UNDECLARED `<x>_id` column, populated in every row, resolving entirely inside the target's
id set, and the ONLY such column. The same sweep produced exactly one candidate 6 times
and never two, so a tie is refused rather than guessed.
"""
import copy
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "env_generator", "llm_generator"))

from multi_agent.runtime.material_prep import resolve_dataset_fks_1202vz  # noqa: E402


def _schema(**cols):
    out = {}
    for name, fk in cols.items():
        out[name] = {"type": "integer", "nullable": True, "pk": name == "id", "fk": fk}
    return out


USERS = [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]
SOUNDS = [{"id": 7, "name": "one"}, {"id": 8, "name": "two"}]


def _videos(**extra):
    rows = []
    for i, (author, sound) in enumerate(((1, 7), (2, 8), (2, 7)), start=1):
        r = {"id": i, "caption": "c%d" % i, "author_id": author}
        for k, v in extra.items():
            r[k] = v[i - 1] if isinstance(v, list) else v
        rows.append(r)
        r.setdefault("_sound", sound)
        del r["_sound"]
    return rows


SCHEMA = {
    "users": _schema(id=None, name=None),
    "sounds": _schema(id=None, name=None),
    "videos": _schema(id=None, user_id="users.id", sound_id="sounds.id"),
}


def _run(videos):
    ds = {"users": copy.deepcopy(USERS), "sounds": copy.deepcopy(SOUNDS),
          "videos": copy.deepcopy(videos)}
    return resolve_dataset_fks_1202vz(ds, copy.deepcopy(SCHEMA))["videos"]


def test_the_resolved_link_under_another_name_fills_the_declared_fk():
    rows = _run(_videos())
    assert [r.get("user_id") for r in rows] == [1, 2, 2], (
        "author_id holds real user ids, so user_id must not load NULL: %r"
        % [r.get("user_id") for r in rows]
    )


def test_a_declared_column_is_never_copied_across_targets():
    """`sound_id` is the dataset's own business even when its ids also exist in `users`."""
    overlapping = [{"id": 1, "caption": "c1", "sound_id": 1},
                   {"id": 2, "caption": "c2", "sound_id": 2},
                   {"id": 3, "caption": "c3", "sound_id": 2}]
    # sound ids 1/2 do not exist in `sounds` here, but they DO exist in `users` -- a copy
    # would put a sound's id in the owner column.
    rows = _run(overlapping)
    assert all(r.get("user_id") in (None, "", 0) for r in rows), (
        "a declared column must never be harvested for another FK: %r"
        % [r.get("user_id") for r in rows]
    )


def test_two_candidates_are_refused_rather_than_guessed():
    rows = _run(_videos(uploader_id=[1, 2, 2]))
    assert all(r.get("user_id") in (None, "", 0) for r in rows), (
        "author_id and uploader_id both qualify; picking one would be a guess: %r"
        % [r.get("user_id") for r in rows]
    )


def test_a_gap_in_the_candidate_disqualifies_it():
    partial = [{"id": 1, "caption": "c1", "author_id": 1},
               {"id": 2, "caption": "c2", "author_id": None},
               {"id": 3, "caption": "c3", "author_id": 2}]
    rows = _run(partial)
    assert all(r.get("user_id") in (None, "", 0) for r in rows), (
        "a column that does not cover every row is not the link: %r"
        % [r.get("user_id") for r in rows]
    )


def test_a_value_outside_the_target_disqualifies_it():
    stray = [{"id": 1, "caption": "c1", "author_id": 1},
             {"id": 2, "caption": "c2", "author_id": 99},
             {"id": 3, "caption": "c3", "author_id": 2}]
    rows = _run(stray)
    assert all(r.get("user_id") in (None, "", 0) for r in rows), (
        "99 is not a user, so author_id is not a resolved users FK: %r"
        % [r.get("user_id") for r in rows]
    )


def test_the_fks_own_base_name_stays_authoritative():
    """When the rows carry `user`, the natural key decides -- not the sibling column."""
    named = [{"id": 1, "caption": "c1", "user": "b", "author_id": 1},
             {"id": 2, "caption": "c2", "user": "b", "author_id": 1},
             {"id": 3, "caption": "c3", "user": "b", "author_id": 1}]
    rows = _run(named)
    assert [r.get("user_id") for r in rows] == [2, 2, 2], (
        "`user` names user 2; the sibling author_id (1) must not win: %r"
        % [r.get("user_id") for r in rows]
    )


def test_an_already_populated_fk_is_left_alone():
    owned = [{"id": 1, "caption": "c1", "user_id": 2, "author_id": 1},
             {"id": 2, "caption": "c2", "user_id": 2, "author_id": 1},
             {"id": 3, "caption": "c3", "user_id": 2, "author_id": 1}]
    rows = _run(owned)
    assert [r.get("user_id") for r in rows] == [2, 2, 2]
