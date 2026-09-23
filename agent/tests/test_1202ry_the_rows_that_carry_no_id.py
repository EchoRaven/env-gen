r"""#1202ry: a dataset table whose rows carry no id at all is not a foreign id space.

From tiktok-r126's own backend log, on a stack still running today:

  [seed] #807b REFUSED the dataset swap for comments: it would orphan 2 of 2 dependent
  row(s) -- the two sources do not share an id space (lane ids look like 1, dataset ids
  like None). Keeping the lane rows.

Its database holds 26 comments. The dataset staged into that same image holds 295 real ones.
283 authentic comments were discarded to keep 2 comment_likes rows resolvable. r122 and r120,
also still running, print the same line.

`#807b` is right about the case it was written for: r145's lane keyed titles on TEXT slugs
while the dataset supplied integers 1..60 -- two REAL and incompatible id spaces, and swapping
wholesale orphaned 93 dependent rows across 5 tables. This is not that. Design-prep's comments
carry no id field because scraped comments have no natural one, the model's PK is
autoincrement, and the database assigns it on insert. `_new_ids` collapses to `{None}`, every
dependent row counts as orphaned, and the majority test fires every time.

So the repair sits upstream of the test rather than loosening it. Measured over generated/:
the refusal drops from 74 (run, table) pairs to 28 and from 55 runs to 20, recovering 12,501
real rows. The 28 that remain are videos and users -- datasets that DO carry ids, where the
two sources genuinely disagree, and where #807b should still refuse.
"""
import copy

import pytest

from env_generator.llm_generator.multi_agent.runtime.material_prep import (
    assign_dataset_ids_1202ry)


_SCHEMA = {"comments": {"id": {"type": "integer", "pk": True, "nullable": False},
                        "text": {"type": "text", "pk": False, "nullable": True}}}


def _rows(n):
    return {"comments": [{"text": "c%d" % i} for i in range(n)]}


# --- what it numbers ------------------------------------------------------------------

def test_rows_with_no_key_are_numbered_from_one():
    out = assign_dataset_ids_1202ry(_rows(3), copy.deepcopy(_SCHEMA))
    assert [r["id"] for r in out["comments"]] == [1, 2, 3]


def test_the_row_order_is_preserved():
    out = assign_dataset_ids_1202ry(_rows(4), copy.deepcopy(_SCHEMA))
    assert [r["text"] for r in out["comments"]] == ["c0", "c1", "c2", "c3"]


def test_it_is_deterministic_and_idempotent():
    a = assign_dataset_ids_1202ry(_rows(5), copy.deepcopy(_SCHEMA))
    b = assign_dataset_ids_1202ry(_rows(5), copy.deepcopy(_SCHEMA))
    assert a == b
    assert assign_dataset_ids_1202ry(copy.deepcopy(a), copy.deepcopy(_SCHEMA)) == a


# --- and what it refuses to touch -----------------------------------------------------

def test_one_author_id_anywhere_freezes_the_whole_table():
    """A single id means the author had an id space in mind; filling the rest invents
    collisions inside it."""
    data = {"comments": [{"text": "a"}, {"id": 7, "text": "b"}, {"text": "c"}]}
    before = copy.deepcopy(data)
    assert assign_dataset_ids_1202ry(data, copy.deepcopy(_SCHEMA)) == before


def test_a_text_key_is_left_alone():
    """A TEXT primary key is a slug, and a slug is content -- r145's 'movie-hollowfield'.
    Numbering it 1, 2, 3 would invent the very id-space conflict #807b exists to catch."""
    schema = {"titles": {"id": {"type": "string", "pk": True}, "name": {"type": "text"}}}
    data = {"titles": [{"name": "x"}]}
    assert assign_dataset_ids_1202ry(data, schema)["titles"][0].get("id") is None


def test_a_table_with_no_primary_key_is_left_alone():
    schema = {"t": {"a": {"type": "text", "pk": False}}}
    assert assign_dataset_ids_1202ry({"t": [{"a": "x"}]}, schema)["t"][0] == {"a": "x"}


def test_a_composite_primary_key_is_left_alone():
    """Two PK columns are not a row number."""
    schema = {"follows": {"follower_id": {"type": "integer", "pk": True},
                          "followee_id": {"type": "integer", "pk": True}}}
    data = {"follows": [{}]}
    assert assign_dataset_ids_1202ry(data, schema)["follows"][0] == {}


def test_malformed_input_is_a_no_op():
    assert assign_dataset_ids_1202ry(None, {}) is None
    assert assign_dataset_ids_1202ry({"t": "notalist"}, {"t": {}}) == {"t": "notalist"}
    assert assign_dataset_ids_1202ry({"t": [None]}, _SCHEMA) == {"t": [None]}


# --- the guard it exists to satisfy ---------------------------------------------------

def _would_807b_refuse(real, base):
    """#807b's guard, LIFTED OUT OF THE EMITTED MODULE and executed -- not re-implemented.

    This was a hand-written mirror of the loader's logic, and `#1202sc` proved why that is not
    good enough: it changed one line of the real guard and the mirror went on asserting the old
    behaviour, caught only by a separate test pinning two exact source lines. A mirror is a
    second copy of the fact, and second copies drift. Now there is one.
    """
    from test_1202sc_the_same_id_written_two_ways import refuses

    return sorted(refuses(real, base))


_LANE = {"comment_likes": [{"comment_id": 1, "user_id": 1}, {"comment_id": 2, "user_id": 2}]}


def test_the_refusal_is_reproduced_then_removed():
    """The r126 case end to end: refused before, allowed after, same inputs."""
    real = {"comments": [{"text": "real comment %d" % i} for i in range(295)]}
    assert _would_807b_refuse(real, _LANE) == ["comments"], "the r126 refusal did not reproduce"

    real = assign_dataset_ids_1202ry(real, copy.deepcopy(_SCHEMA))
    assert _would_807b_refuse(real, _LANE) == [], "the swap is still refused"
    assert len(real["comments"]) == 295


def test_a_genuine_id_space_conflict_is_still_refused():
    """r145: the lane keyed on TEXT slugs, the dataset on integers. #1202ry must not reach
    this -- and must not make it reachable, since a TEXT pk is never numbered."""
    real = {"titles": [{"id": i, "name": "t%d" % i} for i in range(1, 61)]}
    base = {"episodes": [{"title_id": "movie-hollowfield"}, {"title_id": "movie-atlas"}]}
    assert _would_807b_refuse(real, base) == ["titles"]
    schema = {"titles": {"id": {"type": "string", "pk": True}}}
    assert _would_807b_refuse(assign_dataset_ids_1202ry(real, schema), base) == ["titles"]


def test_this_file_keeps_no_second_copy_of_the_guard():
    """The mirror that used to live here is gone; if one comes back it will drift again."""
    import pathlib

    src = pathlib.Path(__file__).read_text()
    # Built at runtime: a literal here would be found in this very file, the way a `pgrep`
    # pattern matches its own command line.
    for needle in ("_dep" + "_orphan", "_new" + "_ids = {"):
        assert needle not in src, "a re-implementation of #807b is back in this file: %s" % needle


# --- the wiring -----------------------------------------------------------------------

def test_the_staging_path_numbers_the_rows_before_anything_reads_them():
    import inspect

    from env_generator.llm_generator.multi_agent.runtime import backend_skeleton

    src = inspect.getsource(backend_skeleton)
    assert "real = assign_dataset_ids_1202ry(real, _schema)" in src
    for later in ("real = enrich_ranking_seed(real, _schema)",
                  "real = enrich_seed_timestamps_1202rw(real, _schema)",
                  "real = align_dataset_id_types(real, _schema)"):
        assert src.index("real = assign_dataset_ids_1202ry(real, _schema)") < src.index(later), \
            "ids must be assigned before %s reasons about them" % later
