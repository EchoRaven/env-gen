r"""#1202uu: FIX #74's demo-content clone mints a byte-identical copy of someone else's video.

FIX #74 tops the FIRST user (the demo identity every gate and first page-load uses) up to
`_DEMO_FLOOR = 8` owned rows, by CLONING donor rows -- fresh PK, owner set to the demo,
unique string columns de-duped, everything else copied verbatim. Its complaint was real:
"lanes routinely spread rows evenly across many users, so the demo owns only a few ->
inbox/feed/calendar look EMPTY on first load".

That reasoning holds where a row's identity is its TEXT. It breaks where the row IS an asset.
MEASURED on the delivered r135 database, started from its own compose file:

    videos in seed_dataset.json : 35, all distinct video_url
    videos in the shipped DB    : 39
    duplicated video_url        : 4, each exactly twice

    id 5 author_id 2 (charlidamelio)      created_at 2025-10-19 03:15:50
    id 36 author_id 1 (bts_official_bighit) created_at 2025-10-19 03:15:50   <- same second

and the logged-out landing page rendered a Charli D'Amelio clip bylined `bts_official_bighit`
with the caption copied across. That is the realism rubric's dimension 4 (cross-record
provenance) and dimension 5 (the same item twice) on the first screen a visitor sees.

ACROSS 146 GENERATED BACKENDS, 105 (71%) carry a media URL on an owner-scoped content table,
so this is the common shape rather than one app's quirk.

THE FIX IS THE FLOOR, NOT THE CLONE. #74's own complaint -- a screen that looks EMPTY -- is
answered by ONE row. Eight only matters where rows differ by their text, which is precisely
where `_MEDIA_COL` is empty. So a table whose rows carry a content-identity column keeps a
floor of 1 and a table of text rows keeps 8, and #74 is untouched for the inbox/calendar case
it was written for.

`_MEDIA_COL` is deliberately NOT `_IMAGE_COL`: a thumbnail, avatar or cover is decoration that
two rows may legitimately share, while `video_url` / `media_url` / `stream_url` is what makes
a row a distinct piece of content.

LOCAL-ONLY (gitignored)."""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime.backend_skeleton import (  # noqa: E402
    _is_image_col,
    _is_media_col_1202uu,
    render_seed_data,
)

MEDIA_TABLES = {
    "users": {"columns": [{"name": "id", "type": "integer", "primary_key": True},
                          {"name": "username", "type": "text"},
                          {"name": "avatar_url", "type": "text"}]},
    "videos": {"columns": [{"name": "id", "type": "integer", "primary_key": True},
                           {"name": "author_id", "type": "integer", "fk": "users.id"},
                           {"name": "video_url", "type": "text"},
                           {"name": "thumbnail_url", "type": "text"},
                           {"name": "caption", "type": "text"}]},
}

TEXT_TABLES = {
    "users": {"columns": [{"name": "id", "type": "integer", "primary_key": True},
                          {"name": "username", "type": "text"}]},
    "messages": {"columns": [{"name": "id", "type": "integer", "primary_key": True},
                             {"name": "user_id", "type": "integer", "fk": "users.id"},
                             {"name": "body", "type": "text"}]},
}


def _media_col(tables):
    src = render_seed_data(tables)
    m = re.search(r"^_MEDIA_COL = (\{.*\})$", src, re.M)
    assert m, "_MEDIA_COL assignment not found in the generated loader"
    return ast.literal_eval(m.group(1)), src


def test_a_content_asset_column_is_recognised():
    """★ The defect's discriminator: the column that makes a row a distinct item."""
    for col in ("video_url", "media_url", "stream_url", "audio_src", "url"):
        assert _is_media_col_1202uu(col), col


def test_decoration_is_not_mistaken_for_content():
    """★ The half that keeps #74 alive: two rows may legitimately share a thumbnail or an
    avatar, so those must NOT lower the floor."""
    for col in ("thumbnail_url", "avatar_url", "cover_url", "poster_url", "icon_url",
                "image_url", "banner_url"):
        assert not _is_media_col_1202uu(col), col
    assert _is_image_col("thumbnail_url") and _is_image_col("avatar_url")
    # ★ The names the decoration guard actually EXISTS for: a media word and a decoration
    # word in one column. My first version of this test only listed plain decoration, which
    # the media-word list already rejects -- disabling the guard left it green. These are the
    # cases that make it load-bearing, and they are ordinary schema names.
    for col in ("video_thumbnail_url", "movie_poster_url", "stream_cover_url",
                "audio_cover_url", "clip_thumb_url"):
        assert not _is_media_col_1202uu(col), col


def test_numeric_lookalikes_are_excluded():
    """Same trap `_is_image_col` documents: a count column must never be treated as a URL."""
    for col in ("video_count", "media_total", "video_id", "stream_width"):
        assert not _is_media_col_1202uu(col), col


def test_the_generated_loader_names_the_media_table():
    media, _src = _media_col(MEDIA_TABLES)
    assert media.get("videos") == ["video_url"], media
    assert "users" not in media, media          # avatar_url is decoration


def test_a_text_only_app_gets_no_media_columns():
    """★ #74's original case must be untouched: with no content-identity column the floor
    stays at 8 and the clone behaves exactly as before."""
    media, _src = _media_col(TEXT_TABLES)
    assert media == {}, media


def test_the_floor_is_one_for_media_and_eight_otherwise():
    """★ The rule itself, read out of the generated loader rather than trusted."""
    _media, src = _media_col(MEDIA_TABLES)
    assert "_floor = 1 if _MEDIA_COL.get(t) else _DEMO_FLOOR" in src, src[:200]
    assert "if have >= _floor:" in src
    assert "need = (1 if _MEDIA_COL.get(t) else _DEMO_FLOOR) - have" in src
    assert "_DEMO_FLOOR = 8" in src              # #74's value is unchanged


def test_r135s_case_produces_no_clone_at_all():
    """★ The delivered failure, restated as arithmetic: the demo owned 4 videos and the clone
    topped it to 8, minting 4 duplicate assets. With a floor of 1, `have >= _floor` is already
    true and nothing is cloned."""
    have, media_floor, text_floor = 4, 1, 8
    assert have >= media_floor                   # no clone -> no duplicated video_url
    assert text_floor - have == 4                # what it used to mint
