r"""#1203a9: `/api/feed` served a column-identical COPY of the content table, so the app
shipped 8 of 35 rows.

`_resource_model` resolves a path to a table by its LAST matching segment, and falls back to
the shape-derived `_primary_content_model` only when nothing matched. `/api/feed` usually names
no table, so the fallback does the right thing. When a lane ALSO creates a `feed` table the
literal match wins, the fallback never runs, and the two diverge: the content pipeline fills the
content table while the route reads the copy.

MEASURED against r140's still-running database: `videos` 35 rows, `feed` 8 — and those 8 are a
STALE PREFIX. The seed had `feed` as videos' first rows; the pipeline then grew `videos` to 35
real rows and left `feed` where it was. The delivered 1.0.0 served 8 of 35. `#1202zb` could only
REPORT this, because its predicate needs live row counts, which do not exist at projection time.

DECIDABLE HERE WITH NO COUNTS: identical column sets. Over 181 runs (160 with a parseable
backend) this fires on exactly 2 — r121 and r140 — the two the corpus sweep identified as true
positives, and on nothing else.

★ THE CORPUS SUPPLIES ITS OWN NEGATIVE CONTROL. r139 also has a `feed` table, and it is a real
ranking table:

    r139 feed:   id, user_id, video_id, rank, reason, is_active, created_at
    r139 videos: id, user_id, sound_id, video_url, thumbnail_url, caption, ... (14)

Different columns, so this leaves it alone and `/api/feed` still resolves to `feed` there.

SCOPE: only a PROJECTED handler moves. A lane that genuinely curates `/api/feed` writes its own
route and the projector yields to it, so a real curated feed is untouched. The override logs
itself, because a silent re-pointing of which table an API serves is the failure mode this area
keeps producing.

★ MY FIRST DRAFT NEVER FIRED. It read `meta["columns"]`; the ORM meta this function receives
uses `meta["cols"]` (a list of names). The branch was silently dead on the very run it was
measured against — caught only because I re-ran it against r140 instead of trusting the diff.
"""
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

from multi_agent.runtime.route_projector import _resource_model  # noqa: E402

_VID_COLS = ["id", "author_id", "sound_id", "video_url", "thumbnail_url", "caption",
             "category", "like_count", "comment_count", "share_count", "save_count",
             "created_at"]


def _types(cols):
    """`_primary_content_model` is a SHAPE heuristic — timestamp + owner FK + richness — so a
    fixture whose `created_at` is typed String resolves to nothing and every assertion below
    becomes vacuous. My first version did exactly that and only the real-tree tests passed."""
    out = {}
    for c in cols:
        if c.endswith("_at"):
            out[c] = "DateTime"
        elif c.endswith("_id") or c.endswith("_count") or c == "id":
            out[c] = "Integer"
        else:
            out[c] = "String"
    return out


def _m(**tables):
    return {name: {"cls": name.title(), "cols": list(cols),
                   "fks": {"author_id": "users"} if "author_id" in cols else {},
                   "required": [], "types": _types(cols)}
            for name, cols in tables.items()}


def test_a_feed_copy_is_not_served():
    """★ The defect: identical columns, so `feed` is a duplicate of `videos`."""
    models = _m(videos=_VID_COLS, feed=_VID_COLS, users=["id", "email"])
    got = _resource_model("/api/feed", models)
    assert got and got[0] == "videos", got


def test_a_real_feed_table_is_still_served():
    """★ The corpus's own negative control, r139's shape: a ranking table with its own
    columns is a concept of its own and must keep its route."""
    models = _m(videos=_VID_COLS,
                feed=["id", "user_id", "video_id", "rank", "reason", "is_active", "created_at"],
                users=["id", "email"])
    got = _resource_model("/api/feed", models)
    assert got and got[0] == "feed", got


def test_the_fallback_path_is_unchanged():
    """No `feed` table at all — the pre-existing #1202zn/.. fallback must still answer."""
    models = _m(videos=_VID_COLS, users=["id", "email"])
    got = _resource_model("/api/feed", models)
    assert got and got[0] == "videos", got


def test_a_non_feed_path_is_untouched():
    """The override is keyed on a feed-shaped SEGMENT; an ordinary resource must not move
    even when a column-identical twin exists."""
    models = _m(videos=_VID_COLS, archive=_VID_COLS, users=["id", "email"])
    got = _resource_model("/api/archive", models)
    assert got and got[0] == "archive", got


def test_the_primary_content_table_itself_is_not_redirected():
    """`/api/videos` resolves to `videos`, which IS the primary content model — the branch
    must not fire on it (the `!=` guard)."""
    models = _m(videos=_VID_COLS, feed=_VID_COLS, users=["id", "email"])
    got = _resource_model("/api/videos", models)
    assert got and got[0] == "videos", got


def test_a_narrow_twin_is_not_enough():
    """A >=6-column requirement, so two small lookup tables that happen to share a shape
    (the 48%-of-runs false-positive class this project already measured) cannot trigger it."""
    models = _m(videos=["id", "title"], feed=["id", "title"], users=["id", "email"])
    got = _resource_model("/api/feed", models)
    assert got and got[0] == "feed", got


def test_other_feed_shaped_words_are_covered():
    """`_FEED_SHAPED_TOKENS` is the existing vocabulary; the override uses the same one."""
    for word in ("explore", "timeline", "reels", "discover"):
        models = _m(videos=_VID_COLS, **{word: _VID_COLS})
        got = _resource_model("/api/" + word, models)
        assert got and got[0] == "videos", (word, got)


def test_two_feed_shaped_twins_separate_nothing():
    """★ FOUND BY MUTANT. If BOTH identical tables are feed-shaped, the name tie-break carries
    no information — picking one would be the arbitrary choice this branch exists to avoid.
    r35 is this shape on the corpus: `live_stream` and `live_streams`, 6 identical columns."""
    models = _m(feed=_VID_COLS, timeline=_VID_COLS, users=["id", "email"])
    got = _resource_model("/api/feed", models)
    assert got and got[0] == "feed", got


def test_a_feed_shaped_table_reached_by_a_non_token_segment_is_untouched():
    """★ FOUND BY MUTANT. The branch requires the PATH SEGMENT to be one of the literal
    feed-shaped words, not merely the table name to look feed-ish. r35's `/api/live_stream`
    resolves to a feed-shaped TABLE through a segment that is not a token, and its answer must
    not move — that redirect belongs to the pre-existing singular/plural match, not here."""
    cols = ["id", "user_id", "viewer_count", "category", "follower_goal", "is_active"]
    models = _m(live_stream=cols, broadcasts=cols, users=["id", "email"])
    got = _resource_model("/api/live_stream", models)
    assert got and got[0] == "live_stream", got


def test_the_override_announces_itself(caplog):
    """A silent re-pointing of which table an API serves is exactly the failure mode this
    area keeps producing, so the choice has to be auditable."""
    import logging
    models = _m(videos=_VID_COLS, feed=_VID_COLS, users=["id", "email"])
    with caplog.at_level(logging.WARNING):
        _resource_model("/api/feed", models)
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "#1203a9" in text, text
    assert "feed" in text and "videos" in text, text
    assert "curated" in text, "the note must say what to do if the copy was deliberate: " + text


def test_the_real_r140_and_r121_trees_now_serve_the_content_table():
    """★ Against the artifacts this was measured on. r140's delivered app served 8 of 35 rows."""
    from pathlib import Path
    from multi_agent.runtime.route_projector import _orm_models
    repo = os.path.dirname(_AGENT)
    checked = 0
    for run in ("tiktok-web-r140", "tiktok-web-r121"):
        be = Path(repo) / "generated" / run / "app" / "backend"
        if not be.is_dir():
            continue
        models = _orm_models(be) or {}
        if "feed" not in models or "videos" not in models:
            continue
        checked += 1
        got = _resource_model("/api/feed", models)
        assert got and got[0] == "videos", (run, got)
    if not checked:
        import pytest
        pytest.skip("neither r140 nor r121 is on this machine")


def test_the_real_r139_tree_keeps_its_ranking_feed():
    """★ The live negative control, same source."""
    from pathlib import Path
    from multi_agent.runtime.route_projector import _orm_models
    be = Path(os.path.dirname(_AGENT)) / "generated" / "tiktok-web-r139" / "app" / "backend"
    if not be.is_dir():
        import pytest
        pytest.skip("r139 not on this machine")
    models = _orm_models(be) or {}
    if "feed" not in models:
        import pytest
        pytest.skip("r139 has no feed table here")
    got = _resource_model("/api/feed", models)
    assert got and got[0] == "feed", got
