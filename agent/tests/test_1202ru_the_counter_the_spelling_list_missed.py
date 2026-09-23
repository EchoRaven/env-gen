r"""#1202ru: a counter column is filled by what it counts, not by how it is spelled.

`#483` maps a dataset's field names onto the ORM's column names through `_FIELD_SYNONYM_GROUPS`,
which enumerates spellings. Enumeration is what fails here, and it failed inside ONE schema:
tiktok-r131's models.py spells the video counter `like_count` and the user counter `likes_count`.
The group ("like_count", "likes") has no member that is a column on `users`, so the whole group
was skipped, `User.likes_count` kept its `Column(Integer, default=0)`, and the API served

    {"username": "...", "followers_count": 24126997, "likes_count": 0}

An unprimed M1 judge flagged exactly that while simply using the app: a creator with 74M
followers and zero total likes is not an account anyone would believe. No deterministic gate saw
it, because nothing in the source is wrong -- the seed has the number, the model has the column,
and the two never meet.

Measured over generated/: 23 of the 131 runs holding both a dataset and a lane seed drop at least
one counter this way; `users.likes_count <- likes` in 19 of them.

The fix matches structure instead of spelling, and the tests below are mostly about how NARROW
that is -- a structural matcher earns its generality by what it refuses.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime.material_prep import (
    _counter_stem_1202ru, align_dataset_field_names)


# --- what reads as a counter --------------------------------------------------------

@pytest.mark.parametrize("name,stem", [
    ("like_count", "like"), ("likes_count", "like"), ("likes_counts", "like"),
    ("num_likes", "like"), ("comment_count", "comment"), ("comments_count", "comment"),
    ("videos_count", "video"), ("view_num", "view"),
])
def test_every_spelling_of_the_same_counter_has_one_stem(name, stem):
    assert _counter_stem_1202ru(name) == stem


@pytest.mark.parametrize("name", [
    "comment", "comments", "likes", "title", "address", "", None, "count_",
])
def test_a_bare_noun_is_not_a_counter_target(name):
    """The marker is what keeps a text column named `comment` out of `comment_count`'s place."""
    assert _counter_stem_1202ru(name) is None


@pytest.mark.parametrize("name", ["order_total", "grand_total", "total_price", "account_number"])
def test_a_total_is_not_a_count(name):
    """`order_total` is money. `orders` must never fill it -- so `_total` is not a marker.

    Dropping it cost zero true positives across all 131 corpus runs, which is why it is out.
    """
    assert _counter_stem_1202ru(name) is None


# --- the r131 case ------------------------------------------------------------------

def test_the_user_counter_is_filled_from_the_datasets_bare_noun():
    ds = {"users": [{"username": "therock", "followers": 24126997, "likes": 98260819}]}
    cols = {"users": {"username", "followers_count", "likes_count"}}
    row = align_dataset_field_names(ds, cols)["users"][0]
    assert row["likes_count"] == 98260819, "the r131 contradiction is back"
    assert row["followers_count"] == 24126997, "#483's own group still works"


def test_one_schema_may_spell_two_counters_two_ways():
    """videos.like_count and users.likes_count in the same models.py -- the r131 shape."""
    ds = {"videos": [{"likes": 25500000}], "users": [{"likes": 98260819}]}
    cols = {"videos": {"like_count"}, "users": {"likes_count"}}
    out = align_dataset_field_names(ds, cols)
    assert out["videos"][0]["like_count"] == 25500000
    assert out["users"][0]["likes_count"] == 98260819


def test_it_works_in_the_other_direction_too():
    """gmrun-era shape: the dataset carries `video_count`, the model declares `videos_count`."""
    ds = {"sounds": [{"video_count": 8}]}
    cols = {"sounds": {"videos_count"}}
    assert align_dataset_field_names(ds, cols)["sounds"][0]["videos_count"] == 8


# --- and what it refuses ------------------------------------------------------------

def test_real_data_is_never_overwritten():
    ds = {"users": [{"likes": 5, "likes_count": 900}]}
    cols = {"users": {"likes_count"}}
    assert align_dataset_field_names(ds, cols)["users"][0]["likes_count"] == 900


def test_a_twin_column_is_mirrored_not_moved():
    """#1202rv: both are real columns for one fact. Copy, and leave the source intact.

    r115's models.py declares `likes = Column(Integer)` AND
    `like_count = Column(Integer, default=0)` on `videos`. The dataset fills `likes` with
    3,600,000; `like_count` stayed at 0, and which of the two the frontend happened to read
    decided whether the video showed 3.6M likes or none. 10 of 149 corpus runs declare such a
    pair, and in 8 exactly one side is seeded -- always the bare noun, never the `_count`.
    """
    ds = {"users": [{"likes": 5}]}
    cols = {"users": {"likes", "likes_count"}}
    row = align_dataset_field_names(ds, cols)["users"][0]
    assert row["likes"] == 5, "the source column lost its value"
    assert row["likes_count"] == 5, "the twin is still served as 0"


def test_a_twin_that_is_not_a_counter_is_left_alone():
    """`title` and `name` can be two different facts; `like_count` and `likes` cannot.

    This is why mirroring is restricted to counter targets rather than applied to every
    synonym group.
    """
    ds = {"sounds": [{"name": "Neon Pop Loop"}]}
    cols = {"sounds": {"name", "title"}}
    row = align_dataset_field_names(ds, cols)["sounds"][0]
    assert row["name"] == "Neon Pop Loop" and row.get("title") is None


def test_mirroring_still_never_overwrites():
    ds = {"videos": [{"likes": 5, "like_count": 900}]}
    cols = {"videos": {"likes", "like_count"}}
    assert align_dataset_field_names(ds, cols)["videos"][0]["like_count"] == 900


def test_money_does_not_fill_a_count_and_a_count_does_not_fill_money():
    ds = {"orders": [{"orders": 3, "items": 12.5}]}
    cols = {"orders": {"order_total", "item_count"}}
    row = align_dataset_field_names(ds, cols)["orders"][0]
    assert "order_total" not in row, "a count filled a monetary total"
    assert row.get("item_count") is None, "a float filled a count"


def test_text_never_reaches_a_counter():
    ds = {"posts": [{"comments": "great post"}]}
    cols = {"posts": {"comment_count"}}
    assert align_dataset_field_names(ds, cols)["posts"][0].get("comment_count") is None


def test_a_boolean_is_not_a_count():
    """bool is an int in Python; `verified: True` must not become `verified_count: 1`."""
    ds = {"users": [{"verifieds": True}]}
    cols = {"users": {"verified_count"}}
    assert align_dataset_field_names(ds, cols)["users"][0].get("verified_count") is None


def test_a_run_whose_names_already_match_is_untouched():
    """#483's safety claim, which this pass must not weaken: matching names -> identical."""
    import copy

    ds = {"videos": [{"like_count": 7, "comment_count": 2, "title": "x"}]}
    before = copy.deepcopy(ds)
    assert align_dataset_field_names(ds, {"videos": {"like_count", "comment_count", "title"}}) == before


def test_malformed_input_is_still_a_no_op():
    assert align_dataset_field_names(None, {}) is None
    assert align_dataset_field_names({"t": "notalist"}, {"t": {"a_count"}}) == {"t": "notalist"}
    assert align_dataset_field_names({"t": [None, 3]}, {"t": {"a_count"}}) == {"t": [None, 3]}
