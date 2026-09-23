r"""#1202rw: a declared time column that no seed row ever fills.

85 of the 129 corpus runs carrying a dataset declare a DateTime column that NOT ONE row
populates -- users.created_at in 74 of them, comments.created_at in 59, videos.created_at in
46 -- emitted as a bare `Column(DateTime)` with no default. 111 of the 170 generated frontends
render a timestamp field, so the NULL is not hidden; it surfaces three different ways, each
taken from the corpus:

  * r131 and r115 render `<span>{c.created_at}</span>` while the backend serialises
    `str(created)`, so the line beside every comment literally reads "None";
  * instagram-run77 renders `new Date(post.created_at).toLocaleDateString()`, and `new
    Date(null)` is the epoch -- the post is dated 1/1/1970;
  * that same frontend's HomeFeedPage then invents `Date.now() - 5h` client-side, which is
    the static-twin class `#1202rl` exists to catch.

Two constraints shaped the fix, and most of these tests exist to hold them:

DETERMINISM is not a preference. The emitted loader re-seeds on a changed fingerprint with
TRUNCATE ... RESTART IDENTITY, so a wall-clock anchor would wipe the database on every
staging -- including one mid-run, taking any data a test user had created with it.

FK AWARENESS is what stops the fix from being worse than the bug. Fill each table on its own
and comments land before the videos they reply to; that is a contradiction NULL never was.
"""
import copy
import json
import subprocess
import sys
from datetime import datetime

import pytest

from env_generator.llm_generator.multi_agent.runtime.material_prep import (
    enrich_seed_timestamps_1202rw, model_schema_from_models_py)


def _col(ctype, pk=False, fk=None):
    return {"type": ctype, "nullable": not pk, "pk": pk, "fk": fk}


_SCHEMA = {
    "users": {"id": _col("integer", pk=True), "created_at": _col("datetime")},
    "videos": {"id": _col("integer", pk=True), "user_id": _col("integer", fk="users.id"),
               "created_at": _col("datetime")},
    "comments": {"id": _col("integer", pk=True), "video_id": _col("integer", fk="videos.id"),
                 "parent_comment_id": _col("integer", fk="comments.id"),
                 "created_at": _col("datetime")},
}


def _data(users=3, videos=5, comments=9):
    return {
        "users": [{"id": i + 1} for i in range(users)],
        "videos": [{"id": i + 1, "user_id": 1} for i in range(videos)],
        "comments": [{"id": i + 1, "video_id": 1} for i in range(comments)],
    }


def _stamps(out, table):
    return [r["created_at"] for r in out[table]]


# --- it fills, and what it writes is what the loader accepts -------------------------

def test_every_row_gets_a_timestamp():
    out = enrich_seed_timestamps_1202rw(_data(), copy.deepcopy(_SCHEMA))
    for table in ("users", "videos", "comments"):
        assert all(isinstance(v, str) and v for v in _stamps(out, table))


def test_the_format_is_the_one_the_emitted_loader_coerces():
    """The generated seed_data.py does `datetime.fromisoformat(v.replace('Z','+00:00'))`."""
    out = enrich_seed_timestamps_1202rw(_data(), copy.deepcopy(_SCHEMA))
    for value in _stamps(out, "videos"):
        assert datetime.fromisoformat(value.replace("Z", "+00:00"))


# --- the ordering that keeps it from being a worse tell ------------------------------

def test_no_comment_predates_the_videos_it_replies_to():
    out = enrich_seed_timestamps_1202rw(_data(), copy.deepcopy(_SCHEMA))
    assert min(_stamps(out, "comments")) > max(_stamps(out, "videos"))


def test_no_video_predates_the_accounts_that_posted_them():
    out = enrich_seed_timestamps_1202rw(_data(), copy.deepcopy(_SCHEMA))
    assert min(_stamps(out, "videos")) > max(_stamps(out, "users"))


def test_within_a_table_the_ids_and_the_clock_agree():
    """In a real database the primary key grows with time -- the only ordering assumption
    the schema itself justifies."""
    out = enrich_seed_timestamps_1202rw(_data(videos=12), copy.deepcopy(_SCHEMA))
    assert _stamps(out, "videos") == sorted(_stamps(out, "videos"))


def test_a_self_referencing_fk_does_not_hang():
    """comments.parent_comment_id -> comments.id is a cycle in the FK graph."""
    schema = {"comments": {"id": _col("integer", pk=True),
                           "parent_comment_id": _col("integer", fk="comments.id"),
                           "created_at": _col("datetime")}}
    out = enrich_seed_timestamps_1202rw({"comments": [{"id": 1}, {"id": 2}]}, schema)
    assert all(r["created_at"] for r in out["comments"])


def test_two_tables_referencing_each_other_still_terminate():
    schema = {"a": {"id": _col("integer", pk=True), "b_id": _col("integer", fk="b.id"),
                    "created_at": _col("datetime")},
              "b": {"id": _col("integer", pk=True), "a_id": _col("integer", fk="a.id"),
                    "created_at": _col("datetime")}}
    out = enrich_seed_timestamps_1202rw({"a": [{"id": 1}], "b": [{"id": 1}]}, schema)
    assert out["a"][0]["created_at"] and out["b"][0]["created_at"]


# --- determinism, which the re-seed makes load-bearing -------------------------------

def test_the_same_input_gives_the_same_output():
    a = enrich_seed_timestamps_1202rw(_data(), copy.deepcopy(_SCHEMA))
    b = enrich_seed_timestamps_1202rw(_data(), copy.deepcopy(_SCHEMA))
    assert a == b


def test_running_it_twice_over_its_own_output_changes_nothing():
    """A second staging must not move the fingerprint -- that is a TRUNCATE."""
    once = enrich_seed_timestamps_1202rw(_data(), copy.deepcopy(_SCHEMA))
    before = copy.deepcopy(once)
    assert enrich_seed_timestamps_1202rw(once, copy.deepcopy(_SCHEMA)) == before


def test_it_does_not_depend_on_the_process_hash_seed():
    """`hash()` is randomised per process; a CRC is not. This is the counter-proof.

    If the spread ever goes back to hash(), two stagings of one run produce different seeds,
    the fingerprint moves, and the loader TRUNCATEs a database a test user was working in.
    """
    prog = (
        "import json,sys;"
        "sys.path.insert(0, %r);"
        "from env_generator.llm_generator.multi_agent.runtime.material_prep import"
        " enrich_seed_timestamps_1202rw as f;"
        "d=json.loads(sys.stdin.read());"
        "print(json.dumps(f(d['data'], d['schema']), sort_keys=True))"
    ) % str(__import__("pathlib").Path(__file__).resolve().parents[1])
    payload = json.dumps({"data": _data(), "schema": _SCHEMA})
    outs = []
    for seed in ("0", "1", "12345"):
        env = dict(__import__("os").environ, PYTHONHASHSEED=seed)
        outs.append(subprocess.run([sys.executable, "-c", prog], input=payload, env=env,
                                   capture_output=True, text=True, check=True).stdout)
    assert outs[0] == outs[1] == outs[2], "the spread moves with PYTHONHASHSEED"


def test_no_wall_clock_reaches_the_output():
    """Nothing here may read the clock -- see the TRUNCATE note above."""
    out = enrich_seed_timestamps_1202rw(_data(), copy.deepcopy(_SCHEMA))
    newest = max(_stamps(out, "comments"))
    assert datetime.fromisoformat(newest) <= datetime(2026, 9, 20, 12, 0, 0)


# --- and what it leaves alone --------------------------------------------------------

def test_an_author_supplied_timestamp_makes_it_byte_identical():
    data = _data()
    data["videos"][0]["created_at"] = "2020-01-01T00:00:00"
    before = copy.deepcopy(data["videos"])
    out = enrich_seed_timestamps_1202rw(data, copy.deepcopy(_SCHEMA))
    assert out["videos"] == before, "one author value must freeze the whole column"


def test_a_column_that_is_merely_named_like_a_date_is_not_touched():
    """Keyed off the declared TYPE, so a `created_at = Column(String)` holding '3d ago'
    keeps whatever the author put there."""
    schema = {"posts": {"id": _col("integer", pk=True), "created_at": _col("string")}}
    out = enrich_seed_timestamps_1202rw({"posts": [{"id": 1}]}, schema)
    assert out["posts"][0].get("created_at") is None


def test_a_datetime_primary_key_is_not_rewritten():
    """Named `recorded_at` on purpose -- it passes the name rule, so only the pk check can
    be what stops it."""
    schema = {"ticks": {"recorded_at": _col("datetime", pk=True), "note": _col("string")}}
    out = enrich_seed_timestamps_1202rw({"ticks": [{"note": "x"}]}, schema)
    assert out["ticks"][0].get("recorded_at") is None


def test_a_content_date_is_never_invented():
    """netflix-r12 and r5: `titles.release_date` is a null Date on a row that already says
    `year: 2026`. Banding titles at depth 0 dates those films to 2025 and contradicts the
    row's own year -- a sharper tell than the null. Only record timestamps (`_at`) are filled.
    """
    schema = {"titles": {"id": _col("integer", pk=True), "release_date": _col("date"),
                         "created_at": _col("datetime")}}
    out = enrich_seed_timestamps_1202rw({"titles": [{"id": 1, "year": "2026"}]}, schema)
    assert out["titles"][0].get("release_date") is None, "invented a release date"
    assert out["titles"][0]["created_at"], "the record timestamp is still filled"


@pytest.mark.parametrize("name", ["release_date", "birth_date", "due_date", "start_time",
                                  "air_date", "event_date"])
def test_no_content_date_spelling_is_filled(name):
    schema = {"t": {"id": _col("integer", pk=True), name: _col("datetime")}}
    assert enrich_seed_timestamps_1202rw({"t": [{"id": 1}]}, schema)["t"][0].get(name) is None


def test_a_table_with_no_time_column_is_untouched():
    schema = {"tags": {"id": _col("integer", pk=True), "name": _col("string")}}
    before = {"tags": [{"id": 1, "name": "a"}]}
    assert enrich_seed_timestamps_1202rw(copy.deepcopy(before), schema) == before


def test_the_data_supplies_the_anchor_when_it_has_one():
    """A run whose dataset already carries dates stays current for free."""
    data = _data()
    data["users"][0]["joined_at"] = "2030-06-01T00:00:00"
    schema = copy.deepcopy(_SCHEMA)
    schema["users"]["joined_at"] = _col("string")  # a string, so it is read but not rewritten
    out = enrich_seed_timestamps_1202rw(data, schema)
    assert max(_stamps(out, "comments")) > "2030-01-01"


def test_malformed_input_is_a_no_op():
    assert enrich_seed_timestamps_1202rw(None, {}) is None
    assert enrich_seed_timestamps_1202rw({"t": "notalist"}, {"t": {}}) == {"t": "notalist"}
    assert enrich_seed_timestamps_1202rw({"t": [None]}, {"t": {"a": _col("datetime")}}) == {"t": [None]}


# --- the schema extractor and the wiring ---------------------------------------------

def test_the_extractor_reports_the_foreign_key(tmp_path):
    """Read off a real models.py, not a hand-built dict -- the shape production passes."""
    models = tmp_path / "models.py"
    models.write_text(
        "from sqlalchemy import Column, Integer, DateTime, ForeignKey\n"
        "class Video(Base):\n"
        "    __tablename__ = 'videos'\n"
        "    id = Column(Integer, primary_key=True)\n"
        "    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)\n"
        "    created_at = Column(DateTime)\n")
    schema = model_schema_from_models_py(models)
    assert schema["videos"]["user_id"]["fk"] == "users.id"
    assert schema["videos"]["created_at"]["fk"] is None
    assert schema["videos"]["created_at"]["type"] == "datetime"


def test_the_staging_path_actually_calls_it():
    """#1202rt's lesson: a mechanism with no caller does nothing at all."""
    import inspect

    from env_generator.llm_generator.multi_agent.runtime import backend_skeleton

    src = inspect.getsource(backend_skeleton)
    assert "real = enrich_seed_timestamps_1202rw(real, _schema)" in src
    # and after the ranking fill, so both run on the same staged dataset
    assert (src.index("real = enrich_ranking_seed(real, _schema)")
            < src.index("real = enrich_seed_timestamps_1202rw(real, _schema)"))
