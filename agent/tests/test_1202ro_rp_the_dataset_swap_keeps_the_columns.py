r"""#1202ro/#1202rp: a wholesale dataset swap that destroyed the columns it omits.

`seed_dataset.json` REPLACES a table, so any column the dataset does not carry ceases to exist.
The framework knew: #264 preserved the scope column and its own note says a column the dataset
omits is LOST. Only that one hole was plugged.

Measured across r129/r130/r131 — all three — the swap dropped 18 to 24 columns per run:

    users.email, users.password   a seeded login form answering 401
    videos.like_count et al       every engagement figure 0, beside real video_likes rows
    videos.created_at             every timestamp reading None
    videos.thumbnail_url          the thumbnails gone

An unprimed agent hit the far end of this and reported it (#1202rl); my own first check looked
at seed_data.json, which still had the values, and concluded the report was wrong. It was not —
I was reading the file that gets replaced.

#1202ro — the synonym table that was supposed to reconcile the names held eight groups, ALL of
them film vocabulary (poster_url, release_year, average_rating, runtime), because #483 was
written against a netflix clone. A short-video env shares none of them. The new groups are
deliberately domain-NEUTRAL suffix pairs — count/url/time — since adding this product's words
would repeat the original mistake one env later.

#1202rp — for columns the dataset genuinely lacks, carry the lane's values PER ROW, matched on
id and falling back to a natural key. Never broadcast: copying one row's email to every row
collides on a unique column, which is the trap #264's own note describes.

Real-corpus effect on r131: 21 columns lost -> 6, with users, videos and sounds fully
recovered and email still 4 distinct values across 4 rows. The remaining 6 are `comments`,
where the dataset carries no natural key at all — an honest ceiling, not something to force.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "env_generator" / "llm_generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime.material_prep import (  # noqa: E402
    _FIELD_SYNONYM_GROUPS, align_dataset_field_names)

RT = ROOT / "env_generator" / "llm_generator" / "multi_agent" / "runtime"


# --- #1202ro: the synonym table ----------------------------------------------------------

def test_engagement_counters_are_reconciled():
    """The dataset carries the bare noun, the model the _count column."""
    ds = {"videos": [{"likes": 3600000, "comments": 61300, "shares": 1}]}
    cols = {"videos": {"like_count", "comment_count", "share_count"}}
    out = align_dataset_field_names(ds, cols)["videos"][0]
    assert out["like_count"] == 3600000 and out["comment_count"] == 61300


def test_media_references_are_reconciled():
    ds = {"videos": [{"thumbnail": "/assets/a.jpg"}], "users": [{"avatar": "/assets/b.jpg"}]}
    cols = {"videos": {"thumbnail_url"}, "users": {"avatar_url"}}
    out = align_dataset_field_names(ds, cols)
    assert out["videos"][0]["thumbnail_url"] == "/assets/a.jpg"
    assert out["users"][0]["avatar_url"] == "/assets/b.jpg"


def test_a_real_column_is_never_cannibalised():
    """#483's safety rule: if the synonym IS its own column on this table, leave it alone."""
    ds = {"sounds": [{"cover": "/assets/c.jpg"}]}
    cols = {"sounds": {"cover", "cover_url"}}
    out = align_dataset_field_names(ds, cols)["sounds"][0]
    assert out["cover"] == "/assets/c.jpg"


def test_an_existing_target_is_never_overwritten():
    ds = {"videos": [{"like_count": 5, "likes": 999}]}
    cols = {"videos": {"like_count"}}
    assert align_dataset_field_names(ds, cols)["videos"][0]["like_count"] == 5


def test_the_groups_stay_domain_neutral():
    """Adding this product's vocabulary would repeat #483's own mistake one env later."""
    flat = {w for g in _FIELD_SYNONYM_GROUPS for w in g}
    for product_word in ("tiktok", "video_likes", "duet", "stitch", "sound_id", "fyp"):
        assert product_word not in flat


# --- #1202rp: the per-row carry, as emitted into the seed loader --------------------------

def _loader_src() -> str:
    s = (RT / "backend_skeleton.py").read_text(encoding="utf-8")
    i = s.index("#1202rp: CARRY THE COLUMNS THE DATASET DOES NOT HAVE")
    return s[i:s.index("#807: replacing a table WHOLESALE", i)]


def test_the_carry_is_matched_not_broadcast():
    """Broadcasting one row's email to every row collides on a unique column."""
    blk = _loader_src()
    assert "_by_id" in blk and "_NAT_KEYS" in blk
    assert "_src = None" in blk


def test_it_falls_back_to_a_natural_key():
    """r131: videos agree on id, users carry none on the lane side, comments none on the
    dataset side — an id-only match recovered nothing for either."""
    blk = _loader_src()
    m = re.search(r"_NAT_KEYS = \(([^)]*)\)", blk)
    assert m
    keys = [k.strip().strip("'\"") for k in m.group(1).split(",") if k.strip()]
    assert keys[0] == "id"
    assert "username" in keys and "email" in keys


def test_only_columns_the_dataset_lacks_are_carried():
    """Carrying a column the dataset DOES have would overwrite the real domain data — the
    whole point of preferring the dataset."""
    blk = _loader_src()
    assert "_k not in _ds_keys" in blk


def test_the_scope_column_is_still_carried():
    """#264's original guarantee must survive this widening."""
    blk = _loader_src()
    assert "_scope.items()" in blk
