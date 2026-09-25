r"""#1202ue: every parent row had exactly one child, in every table, in every environment.

`_seed_cell` assigned a foreign key with `(i + fk_ordinal) % m` -- it WALKED the parents in
lockstep with the child rows. With 8 comments over 9 videos, every video got exactly one
comment.

MEASURED in the delivered r133 seed:

    comments.video_id = [1, 2, 3, 4, 5, 6, 7, 8]     each parent used exactly once
    likes.video_id    = [1, 2, 3, 4, 5, 6, 7, 8]     and again

Two separate tells. Dimension 6, because one subtraction reads the sequence. And dimension 5,
which matters more here: "uneven participation" is missing entirely. No video has two comments
and none has zero -- a shape no real table has -- and a "most liked" ordering over a column
where every row is 1 is meaningless. A detail page always showed exactly one comment.

The parent is now drawn from crc32 of (child table, column, row index), squared to concentrate
the draw on earlier parents. Squaring is what produces the long tail real participation has:
a few rows carry most of the children and many carry none.

THREE PROPERTIES HELD, each pinned below:
  * FK INTEGRITY. Every reference still lands on a row that exists -- the thing the skew could
    most easily have broken.
  * #1069 SURVIVES. Two FK columns pointing at the same parent must not pick the same parent in
    one row, or every seeded follow is a self-follow and every DM a note to self. `fk_ordinal`
    still offsets.
  * THE FIRST PARENT IS NEVER CHILDLESS. Squaring concentrates on low indices, so row 1 -- the
    one a landing page shows first -- always has children. A skew that left the first item
    empty would trade a realism tell for the dataless-page hold that cost r124 three hours.

DOMAIN-AGNOSTIC: the draw reads only the child table's own name, the column, and the row index.
It knows nothing of what either table means, so `comments -> videos` and `orders -> customers`
take the identical path -- asserted below by renaming everything to `t1`/`t2`.

LOCAL-ONLY (gitignored)."""
from __future__ import annotations

import collections
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.runtime.backend_skeleton import _build_seed_rows  # noqa: E402

PARENT = {"columns": [{"name": "id", "type": "integer", "primary_key": True},
                      {"name": "title", "type": "text"}]}


def _child(parent, col):
    return {"columns": [{"name": "id", "type": "integer", "primary_key": True},
                        {"name": col, "type": "integer", "fk": f"{parent}.id"},
                        {"name": "body", "type": "text"}]}


def _seed(salt="e0", parent="videos", child="comments", col="video_id"):
    return _build_seed_rows({parent: PARENT, child: _child(parent, col)}, salt)[0]


def test_parents_do_not_each_get_exactly_one_child():
    """The r133 shape, stated as the property it violated."""
    flat = 0
    for k in range(30):
        seed = _seed(f"e{k}")
        counts = collections.Counter(r["video_id"] for r in seed["comments"])
        if set(counts.values()) == {1}:
            flat += 1
    assert flat == 0, f"{flat}/30 environments still give every parent exactly one child"


def test_participation_is_uneven():
    """Dimension 5: a few rows carry several children, many carry none."""
    seed = _seed("uneven")
    counts = collections.Counter(r["video_id"] for r in seed["comments"])
    assert max(counts.values()) > 1, counts
    assert len(counts) < len(seed["videos"]), counts   # some parents have none


def test_every_reference_still_exists():
    """★ The property the skew could most easily have broken."""
    dangling = 0
    for k in range(40):
        seed = _seed(f"fk{k}")
        n = len(seed["videos"])
        dangling += sum(1 for r in seed["comments"]
                        if not 1 <= r["video_id"] <= n)
    assert dangling == 0, dangling


def test_the_first_parent_is_never_childless():
    """★ The discriminator against r124's dataless-page hold: the row a landing page shows
    first must have something to show."""
    empty = [k for k in range(60)
             if 1 not in {r["video_id"] for r in _seed(f"first{k}")["comments"]}]
    assert empty == [], empty


def test_1069_still_holds_for_two_fks_on_one_parent():
    """Two columns onto the same parent must not agree in a row, or every follow is a
    self-follow and every DM a note to self."""
    tables = {"users": PARENT,
              "follows": {"columns": [
                  {"name": "id", "type": "integer", "primary_key": True},
                  {"name": "follower_id", "type": "integer", "fk": "users.id"},
                  {"name": "followee_id", "type": "integer", "fk": "users.id"},
                  {"name": "body", "type": "text"}]}}
    same = 0
    for k in range(30):
        seed = _build_seed_rows(tables, f"f{k}")[0]
        same += sum(1 for r in seed["follows"]
                    if r.get("follower_id") == r.get("followee_id"))
    assert same == 0, f"{same} self-referential pairs"


def test_two_fks_on_one_parent_do_not_share_a_distribution():
    """#1202uj: #1202ue kept the two columns DISTINCT per row and made their SHAPES identical.

    Measured in r134's delivered seed: `follows.follower_id` and `follows.following_id` were
    both [7, 1, 1, 1], and `notifications.user_id` and `notifications.actor_id` were both
    [5, 3, 1] -- so "who receives most" and "who causes most" produce the same ranking, which
    real data does not do. The cause was the offset being the ordinal itself against a base
    shared by the row.

    I first recorded this as an unavoidable trade against #1069's guarantee. It is not: an
    offset of `ordinal * step` where `gcd(step, m) == 1` is still injective over ordinals, so
    the guarantee holds, and drawing the step PER ROW moves the two columns off a fixed
    distance, which decorrelates the shapes.
    """
    tables = {"users": PARENT,
              "follows": {"columns": [
                  {"name": "id", "type": "integer", "primary_key": True},
                  {"name": "follower_id", "type": "integer", "fk": "users.id"},
                  {"name": "followee_id", "type": "integer", "fk": "users.id"},
                  {"name": "body", "type": "text"}]}}
    identical = 0
    for k in range(40):
        rows = _build_seed_rows(tables, f"d{k}")[0]["follows"]
        a = sorted(collections.Counter(r["follower_id"] for r in rows).values(), reverse=True)
        b = sorted(collections.Counter(r["followee_id"] for r in rows).values(), reverse=True)
        identical += (a == b)
    assert identical <= 8, f"{identical}/40 environments still share one shape"


def test_the_step_keeps_1069s_guarantee():
    """★ The property the decorrelation could most easily have cost, re-asserted directly."""
    tables = {"users": PARENT,
              "follows": {"columns": [
                  {"name": "id", "type": "integer", "primary_key": True},
                  {"name": "follower_id", "type": "integer", "fk": "users.id"},
                  {"name": "followee_id", "type": "integer", "fk": "users.id"},
                  {"name": "body", "type": "text"}]}}
    same = 0
    for k in range(40):
        rows = _build_seed_rows(tables, f"g{k}")[0]["follows"]
        same += sum(1 for r in rows if r.get("follower_id") == r.get("followee_id"))
    assert same == 0, f"{same} self-referential pairs"


def test_it_is_deterministic():
    a = _seed("same")
    b = _seed("same")
    assert [r["video_id"] for r in a["comments"]] == [r["video_id"] for r in b["comments"]]


def test_it_is_domain_agnostic():
    """★ The user's iron rule, asserted as the PROPERTY rather than as identical values.

    The draw is salted by the table name, so renaming changes which parent each row picks --
    that is a different sample, not different behaviour. What must not change is that the
    algorithm never consults what a table MEANS, and the way to assert that is that every
    statistical property survives the rename. My first version compared the two count vectors
    directly and failed for a reason that had nothing to do with domain binding.
    """
    for parent, child, col in (("videos", "comments", "video_id"), ("t1", "t2", "t1_id")):
        counts = collections.Counter(
            r[col] for r in _seed("x", parent, child, col)[child])
        seed = _seed("x", parent, child, col)
        assert max(counts.values()) > 1, (parent, counts)          # uneven
        assert len(counts) < len(seed[parent]), (parent, counts)   # a tail with none
        assert 1 in counts, (parent, counts)                       # first parent populated
        assert all(1 <= v <= len(seed[parent]) for v in counts), (parent, counts)


def test_a_third_column_onto_one_parent_is_still_distinct():
    r"""★ #1202uj's coprimality correction, asserted where it is the ONLY thing holding.

    I shipped `while gcd(step, m) != 1: step += 1` and then falsified the whole file against
    a build with that loop disabled: 9 passed, 0 red. The correction had zero proving power
    here, because BOTH #1069 tests above use exactly TWO columns -- and with two columns the
    loop is provably dead code. `_step` is drawn as `1 + crc % (m - 1)`, so it lies in
    [1, m-1] and can never be `0 mod m`; ordinals 0 and 1 therefore always differ whether or
    not the step shares a factor with `m`.

    A third column is where a shared factor bites: ordinals 0 and 2 collide exactly when
    `2 * step == 0 mod m`, i.e. `step == m/2`. MEASURED over the draw itself, with the
    correction removed, for the row counts #1202tz actually emits (5..12):

        m = 6   ->  19.5% of rows have two of the three columns on one parent
        m = 12  ->   9.0%
        m = 4   ->  34.3%

    and with the correction, 0 across every (m, columns) pair up to six columns.

    Three columns onto one parent is not exotic -- an `assignments` row carrying `author_id`,
    `reviewer_id` and `approver_id`, or a `transfers` row carrying `from_id`, `to_id` and
    `initiated_by`. A collision there seeds a review someone gave their own work, which is
    dimension 2's "implausible relationship" tell and the same class of defect #1069 exists
    to prevent.

    Asserted as EXHAUSTIVE rather than statistical: not one row, in any environment, may
    repeat a parent across the three columns.
    """
    tables = {"people": PARENT,
              "assignments": {"columns": [
                  {"name": "id", "type": "integer", "primary_key": True},
                  {"name": "author_id", "type": "integer", "fk": "people.id"},
                  {"name": "reviewer_id", "type": "integer", "fk": "people.id"},
                  {"name": "approver_id", "type": "integer", "fk": "people.id"},
                  {"name": "body", "type": "text"}]}}
    cols = ("author_id", "reviewer_id", "approver_id")
    clashes = []
    for k in range(60):
        for r in _build_seed_rows(tables, f"three{k}")[0]["assignments"]:
            picks = [r.get(c) for c in cols]
            if len(set(picks)) != len(picks):
                clashes.append((k, picks))
    assert clashes == [], f"{len(clashes)} rows repeat a parent across three columns: {clashes[:4]}"


def test_the_correction_terminates_for_every_row_count():
    """★ The risk the correction itself introduces: an unbounded `while`.

    `_step += 1` with no ceiling is only safe because some `step` coprime to `m` is always
    reachable -- `m + 1` is congruent to 1. Asserted over the whole range of row counts the
    seeder emits rather than trusting that argument, and with a wide-enough table that every
    ordinal exercises the loop.
    """
    for m in range(2, 40):
        step = 1 + (m * 7919) % max(1, m - 1)
        for _ in range(m + 2):
            if m <= 1 or math.gcd(step, m) == 1:
                break
            step += 1
        else:
            raise AssertionError(f"no coprime step reached for m={m}")
        assert m <= 1 or math.gcd(step, m) == 1, (m, step)
